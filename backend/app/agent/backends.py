"""Chat backends for the co-editor agent.

- RuleBackend: pattern-based intents. Zero downloads, deterministic — the
  default, and what Slice 6 verifies. Honest about what it is.
- OllamaBackend: a real local LLM via Ollama (http://127.0.0.1:11434).
  Select with AGENT_BACKEND=ollama (and AGENT_MODEL, default qwen3:8b).
  Any failure falls back to the rule backend with a one-line notice.
"""
from __future__ import annotations

import os
import re


def _clip_n(message: str) -> int:
    m = re.search(r"clip\s*(\d+)", message, re.I)
    return max(0, int(m.group(1)) - 1) if m else 0


def _platform(message: str) -> str:
    m = message.lower()
    if "youtube" in m:
        return "youtube"
    if "square" in m or "1:1" in m or "feed" in m:
        return "square"
    return "tiktok"


def _montage_indices(message: str) -> list[int] | None:
    nums = [int(n) - 1 for n in re.findall(r"clip\s*(\d+)", message, re.I)]
    nums = [n for n in nums if n >= 0]
    return nums or None


def _voice_text(message: str) -> str | None:
    m = re.search(r"(?:say|speak|narrate|voiceover)[:\s]+[\"']?(.+?)[\"']?$",
                  message, re.I | re.S)
    if m:
        return m.group(1).strip()
    m = re.search(r"[\"'](.{5,300})[\"']", message, re.S)
    return m.group(1).strip() if m else None


class RuleBackend:
    name = "rule"

    PATTERNS = [
        (re.compile(r"\bmontage\b|\bhighlight reel\b|\bhighlight\b.*\breel\b|\bcombin\w+\b|\bstitch\b|\bmashup\b", re.I),
         lambda m: [("make_montage", {"clip_indices": _montage_indices(m),
                                      "platform": _platform(m)})]),
        (re.compile(r"\banaly[sz]e\b", re.I),
         lambda m: [("analyze", {})]),
        (re.compile(r"\bpackag\w*\b|\bseo\b|\bkeyword\b|\btitle\b|\bthumbnail\b", re.I),
         lambda m: [("packaging", {})]),
        (re.compile(r"\bautopilot\b|\bclean\s*up\b|\bself[\s-]?edit\b", re.I),
         lambda m: [("autopilot", {"remove_silence": True,
                                   "remove_fillers": bool(re.search(r"filler", m, re.I)),
                                   "captions": True})]),
        (re.compile(r"\bvoiceover\b|\bnarrat\w+\b|\bsay\b|\bspeak\b", re.I),
         lambda m: [("voiceover", {"text": _voice_text(m) or ""})]),
        (re.compile(r"\brender\b", re.I),
         lambda m: [("render_clip", {"clip_index": _clip_n(m)})]),
        (re.compile(r"\bexport\b", re.I),
         lambda m: [("export_clip", {"clip_index": _clip_n(m),
                                     "platform": _platform(m)})]),
        (re.compile(r"\bclips?\b", re.I),
         lambda m: [("find_clips", {})]),
        (re.compile(r"\bstatus\b|\bprogress\b|\bwhere\b.*\b(at|we)\b|\bwhat\b.*\bdone\b", re.I),
         lambda m: [("project_status", {})]),
    ]

    def plan(self, message: str, ctx: dict) -> dict:
        steps: list[tuple[str, dict]] = []
        seen = set()
        for rx, build in self.PATTERNS:
            if rx.search(message):
                for tool, args in build(message):
                    if tool not in seen:
                        seen.add(tool)
                        steps.append((tool, args))
        return {"steps": steps}

    def compose(self, steps_results: list[dict], ctx: dict) -> str:
        if not steps_results:
            return ("I can analyze videos, find clips, render and export them, "
                    "stitch a highlight montage, generate voiceovers, and prepare "
                    "publishing packages. Try: “analyze this video”, “find clips”, "
                    "or “make a highlight montage”.")
        parts = []
        for s in steps_results:
            tool, res = s["tool"], s["result"]
            if res.get("error"):
                parts.append(f"{tool}: {res['error']}")
            elif tool == "analyze":
                parts.append(f"Analyzed — {res['segments']} segments, "
                             f"{res['words']} words ({res['language']}).")
            elif tool == "find_clips":
                parts.append(res["message"] or f"Found {res['clips']} clips.")
            elif tool == "render_clip":
                parts.append(f"Rendered clip {res['clip_index'] + 1} → {res['file']}.")
            elif tool == "export_clip":
                parts.append(f"Exported for {res['platform']} → {res['file']}.")
            elif tool == "make_montage":
                parts.append(f"Montage ready — {len(res['clips'])} clips, "
                             f"{res['duration']}s, {res['platform']} → {res['file']}.")
            elif tool == "voiceover":
                parts.append(f"Voiceover generated → {res['file']} "
                             f"({res.get('duration_sec', '?')}s).")
            elif tool == "packaging":
                parts.append(f"Packaging done — {res['keywords']} keywords, "
                             f"{res['titles']} titles.")
            elif tool == "autopilot":
                parts.append(f"Autopilot edit done — kept {res['kept']}s, "
                             f"cut {res['removed']}s in {res['cuts']} cuts → {res['file']}.")
            elif tool == "project_status":
                bits = []
                bits.append("transcribed ✓" if res["transcribed"]
                            else "not analyzed yet")
                if res["transcribed"]:
                    bits.append(f"{res['segments']} segments")
                bits.append(f"{res['clips_found']} clips")
                bits.append("packaged ✓" if res["packaged"] else "not packaged")
                parts.append("Status: " + ", ".join(bits) + ".")
        return " ".join(parts)


class OllamaBackend:
    """Real local LLM. Requires `ollama serve` + a pulled model on the PC."""
    name = "ollama"

    def __init__(self):
        self.base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.model = os.environ.get("AGENT_MODEL", "qwen3:8b")

    def _tools_spec(self) -> str:
        from .tools import TOOLS
        return "\n".join(
            f"- {t.name}{t.args_hint}: {t.description}"
            for t in TOOLS.values())

    def plan(self, message: str, ctx: dict) -> dict:
        import json as _json
        import requests
        system = (
            "You are LocalCut's co-editor, a local AI video editing assistant. "
            "You have these tools (call by exact name):\n" + self._tools_spec() +
            "\nProject state: " + _json.dumps(ctx) +
            "\nReply with JSON ONLY: {\"steps\": [{\"tool\": name, \"args\": {}}], "
            "\"reply\": \"one-line summary\"}. Use project_status first when unsure."
        )
        r = requests.post(self.base + "/api/chat", json={
            "model": self.model, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": message}],
        }, timeout=180)
        r.raise_for_status()
        data = _json.loads(r.json()["message"]["content"])
        steps = [(s["tool"], s.get("args", {})) for s in data.get("steps", [])]
        return {"steps": steps, "_reply": data.get("reply", "")}

    def compose(self, steps_results: list[dict], ctx: dict) -> str:
        # The LLM already wrote its reply during planning; kept for symmetry.
        return ""


def select_backend():
    if os.environ.get("AGENT_BACKEND") == "ollama":
        try:
            b = OllamaBackend()
            import requests
            requests.get(b.base + "/api/tags", timeout=5).raise_for_status()
            return b, ""
        except Exception:
            return RuleBackend(), ("Ollama not reachable — using the built-in "
                                   "assistant instead. Set AGENT_BACKEND=ollama once "
                                   "`ollama serve` is running.")
    return RuleBackend(), ""
