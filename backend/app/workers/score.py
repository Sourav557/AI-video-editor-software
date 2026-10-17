"""Worker: clip quality engine, Slice 2 (rule-based, fully local, no LLM yet).

Pipeline:
  1. Candidate generation: sliding windows over transcript segments snapped to
     sentence/silence boundaries, 15–60 s each.
  2. Scoring: hook strength + completeness + pacing + length fit − filler penalty.
  3. Quality gate: reject weak clips instead of padding ("found 4 strong clips").
Every clip carries a score breakdown and a one-line reason — explainable by design.
Idempotent: re-running overwrites clips.json.
"""
from __future__ import annotations

import re

from ..projects import load_json, save_json

TARGET_MIN, TARGET_MAX = 15.0, 60.0
MAX_CLIPS = 5
QUALITY_FLOOR = 0.50

HOOK_WORDS = {
    "how", "what", "why", "when", "secret", "mistake", "free", "new",
    "best", "worst", "never", "always", "stop", "truth", "hack",
}
FILLERS = {
    "um", "uh", "uhm", "erm", "like", "basically", "actually",
    "literally", "stuff", "things",
}


def _feats(text: str) -> dict:
    t = text.lower()
    words = re.findall(r"[a-z']+", t)
    stripped = text.strip()
    return {
        "question": stripped.endswith("?"),
        "exclaim": "!" in text,
        "number": bool(re.search(r"\d", text)),
        "hook_word": any(w in HOOK_WORDS for w in words),
        "fillers": sum(1 for w in words if w in FILLERS) + t.count("you know"),
        "ends_terminal": stripped.endswith((".", "?", "!")),
        "words": len(words),
    }


def _score(segs: list[dict]) -> tuple[float, dict, str]:
    first, last = _feats(segs[0]["text"]), _feats(segs[-1]["text"])
    total_words = sum(_feats(s["text"])["words"] for s in segs)
    total_fillers = sum(_feats(s["text"])["fillers"] for s in segs)
    duration = segs[-1]["end"] - segs[0]["start"]
    wps = total_words / max(duration, 0.1)

    hook = min(1.0, 0.10 + 0.30 * first["question"] + 0.15 * first["exclaim"]
               + 0.20 * first["number"] + 0.25 * first["hook_word"])
    completeness = 0.60 + 0.40 * last["ends_terminal"]
    pacing = max(0.0, 1.0 - abs(wps - 2.6) / 2.6)
    length_fit = min(1.0, duration / 30.0)
    filler_pen = min(0.45, 0.07 * total_fillers)

    score = max(0.0, 0.45 * hook + 0.25 * completeness
                + 0.20 * pacing + 0.10 * length_fit - filler_pen)
    breakdown = {
        "hook": round(hook, 2),
        "completeness": round(completeness, 2),
        "pacing": round(pacing, 2),
        "length_fit": round(length_fit, 2),
        "filler_penalty": round(filler_pen, 2),
    }
    # One-line reason from the strongest positive signal.
    if first["question"]:
        reason = "Opens with a question — strong hook."
    elif first["number"]:
        reason = "Opens with a concrete number — strong hook."
    elif first["hook_word"]:
        reason = "Opens with a curiosity trigger word."
    elif pacing > 0.8:
        reason = "Tight, energetic pacing throughout."
    elif last["ends_terminal"]:
        reason = "Clean, resolved ending on a complete thought."
    else:
        reason = "Solid all-round moment."
    return round(score, 3), breakdown, reason


def _candidates(segments: list[dict]) -> list[tuple[int, int]]:
    n = len(segments)
    out: set[tuple[int, int]] = set()
    for i in range(n):
        for k in range(i, n):
            d = segments[k]["end"] - segments[i]["start"]
            if d > TARGET_MAX:
                break
            if d >= TARGET_MIN:
                out.add((i, k))
    return sorted(out)


def run(job, report) -> dict:
    data = load_json(job.project_id, "transcript.json")
    if not data or not data.get("segments"):
        raise RuntimeError("no transcript found — run Analyze first")
    segments = data["segments"]

    report(0.1)
    scored = []
    cands = _candidates(segments)
    for n, (i, k) in enumerate(cands):
        score, breakdown, reason = _score(segments[i:k + 1])
        scored.append({
            "index": len(scored),
            "start": segments[i]["start"],
            "end": segments[k]["end"],
            "duration": round(segments[k]["end"] - segments[i]["start"], 2),
            "hook_text": segments[i]["text"],
            "score": score,
            "breakdown": breakdown,
            "reason": reason,
        })
        report(0.1 + 0.5 * (n + 1) / max(1, len(cands)))

    # Quality gate + greedy de-overlap, best first.
    scored.sort(key=lambda c: -c["score"])
    picked, taken = [], []
    for c in scored:
        if c["score"] < QUALITY_FLOOR or len(picked) >= MAX_CLIPS:
            continue
        if any(not (c["end"] <= s or c["start"] >= e) for s, e in taken):
            continue
        picked.append(c)
        taken.append((c["start"], c["end"]))
    picked.sort(key=lambda c: -c["score"])
    for i, c in enumerate(picked):
        c["index"] = i

    result = {
        "clips": picked,
        "candidates_considered": len(scored),
        "message": (f"Found {len(picked)} strong clip(s)."
                    if picked else
                    "No clips passed the quality bar — try a longer or livelier video."),
    }
    save_json(job.project_id, "clips.json", result)
    report(1.0)
    return result
