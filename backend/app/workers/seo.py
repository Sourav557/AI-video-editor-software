"""Worker: SEO / packaging / discovery engine (Slice 5).

Per the master prompt (§3.12) this is the ONE online-dependent module — and even
here the core is fully local:
- Keyword extraction from the transcript (frequency × early-position weight,
  bigrams/trigrams), ranked table with scores.
- Optional keyless enrichment: YouTube autocomplete suggestions (no API key).
  Offline-tolerant — failure just means fewer suggestions, never a failed job.
- Title variants per platform, descriptions with hashtags + chapters from clips,
  punchy thumbnail overlay texts.
Rule-based for now; the editing agent (Slice 6) will refine copy with the LLM.
Idempotent: re-running overwrites seo.json.
"""
from __future__ import annotations

import re
from collections import Counter

from ..projects import load_json, save_json

STOPWORDS = frozenset("""
a an the and or but if then else when while of at by for with about into through
during before after above below to from up down in out on off over under again
further once here there all any both each few more most other some such no nor
not only own same so than too very can will just don should now i me my myself
we our ours ourselves you your yours yourself he him his she her hers it its
they them their theirs this that these those am is are was were be been being
have has had having do does did doing would could ought im ive dont cant wont
isnt arent wasnt werent didnt doesnt dont youve theyre youre weve thats theres
heres lets what which who whom whose where why how as because until as
one two three four five six seven eight nine ten first second third
need needs want wants make makes get gets go goes going take takes come comes
know knows think thinks see sees look looks use uses used using find finds
give gives tell tells say says said""".split())

TITLE_PATTERNS = [
    "Why {kw} Matters More Than You Think",
    "I Fixed My {kw} With These 3 Changes",
    "{Kw} Mistakes Everyone Makes",
    "How to {kw} in 2026 (Step by Step)",
    "The Truth About {kw} Nobody Tells You",
    "3 {kw} Tips That Actually Work",
    "Stop Doing {kw} Like This",
    "{kw}: What I Wish I Knew Earlier",
]


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z']{3,}", text.lower())
            if w not in STOPWORDS]


def _keywords(segments: list[dict], top_n: int = 15) -> list[dict]:
    word_score: Counter = Counter()
    phrase_score: Counter = Counter()
    for si, seg in enumerate(segments):
        pos_w = 1.0 / (1.0 + 0.15 * si)  # early content weighs more
        toks = _tokens(seg["text"])
        for w in toks:
            word_score[w] += pos_w
        for n in (2, 3):
            for i in range(len(toks) - n + 1):
                phrase_score[" ".join(toks[i:i + n])] += pos_w
    # phrases need to repeat to count
    for p in [p for p, c in phrase_score.items() if c < 1.6]:
        del phrase_score[p]
    combined = Counter()
    combined.update(word_score)
    combined.update({p: s * 1.4 for p, s in phrase_score.items()})  # phrases win ties
    ranked = combined.most_common(top_n)
    if not ranked:
        return []
    top = ranked[0][1]
    return [{"keyword": k, "score": round(s / top, 3)} for k, s in ranked]


def _suggest(seed: str) -> list[str]:
    """Keyless YouTube autocomplete enrichment. Never raises."""
    try:
        import json as _json
        import requests
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "youtube", "ds": "yt", "q": seed},
            timeout=8)
        r.raise_for_status()
        body = r.text.strip()
        body = re.sub(r"^[\w.]+\(", "", body).rstrip(")")
        data = _json.loads(body)
        sugs = []
        for item in data[1]:
            if isinstance(item, str):
                sugs.append(item)
            elif isinstance(item, (list, tuple)) and item and isinstance(item[0], str):
                sugs.append(item[0])
        return sugs[:8]
    except Exception:  # offline or format change — degrade gracefully
        return []


def _singular(kw: str) -> str:
    """Naive singularization so title patterns read naturally ('videos'→'video')."""
    if kw.endswith("ies"):
        return kw[:-3] + "y"
    if kw.endswith(("ses", "xes", "ches", "shes")):
        return kw[:-2]
    if kw.endswith("s") and not kw.endswith(("ss", "us", "is")):
        return kw[:-1]
    return kw


def _titles(keywords: list[dict], hooks: list[str]) -> list[dict]:
    kws = [k["keyword"] for k in keywords[:6]]
    out: list[dict] = []
    seen = set()
    cands: list[str] = []
    for h in hooks[:3]:
        cands.append(h.strip().rstrip(".")[:60])
    for kw in kws:
        skw = _singular(kw)
        for pat in TITLE_PATTERNS:
            cands.append(pat.format(kw=skw, Kw=skw.title()))
    for t in cands:
        t = t.strip()
        if not t or t.lower() in seen or len(t) > 100:
            continue
        seen.add(t.lower())
        score = 0.0
        if any(kw in t.lower() for kw in kws[:3]):
            score += 0.4
        if 40 <= len(t) <= 60:
            score += 0.3
        elif len(t) <= 70:
            score += 0.15
        if re.search(r"\d|\?|!", t):
            score += 0.2
        if t.endswith("?"):
            score += 0.1
        out.append({"title": t, "score": round(score, 2),
                    "length": len(t)})
    out.sort(key=lambda x: -x["score"])
    return out[:10]


def _thumb_text(hook: str) -> list[str]:
    toks = _tokens(hook)
    variants = []
    if len(toks) >= 3:
        variants.append(" ".join(toks[:4]).upper())
    if len(toks) >= 5:
        variants.append(" ".join(toks[1:5]).upper())
    # question flip: "WHY VIDEOS FAIL"
    q = re.sub(r"^(why|how|what)\s+", "", hook, flags=re.I).strip(" ?!")
    qt = _tokens(q)
    if len(qt) >= 2:
        variants.append(" ".join(qt[:3]).upper())
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out[:3]


def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def run(job, report) -> dict:
    data = load_json(job.project_id, "transcript.json")
    if not data or not data.get("segments"):
        raise RuntimeError("no transcript found — run Analyze first")
    segments = data["segments"]
    clips = (load_json(job.project_id, "clips.json") or {}).get("clips", [])

    report(0.15)
    keywords = _keywords(segments)
    report(0.35)

    # Keyless enrichment: autocomplete for the top 3 keywords (offline-tolerant).
    suggestions: dict[str, list[str]] = {}
    for k in keywords[:3]:
        sugs = _suggest(k["keyword"])
        if sugs:
            suggestions[k["keyword"]] = sugs
    report(0.55)

    hooks = [c["hook_text"] for c in clips] or [s["text"] for s in segments[:3]]
    titles = _titles(keywords, hooks)

    # Descriptions
    summary = " ".join(s["text"] for s in segments[:2]).strip()
    hashtags = ["#" + re.sub(r"\s+", "", k["keyword"].title()) for k in keywords[:5]]
    chapters = [f"{_fmt_ts(c['start'])} {c['hook_text'][:50]}" for c in clips]
    kw_list = ", ".join(k["keyword"] for k in keywords[:10])

    long_desc = summary + "\n\n"
    if chapters:
        long_desc += "CHAPTERS\n" + "\n".join(chapters) + "\n\n"
    long_desc += " ".join(hashtags) + f"\n\nKeywords: {kw_list}"

    short_desc = (hooks[0][:90] if hooks else summary[:90]) + "\n" + " ".join(hashtags[:4])

    per_clip = []
    for c in clips:
        per_clip.append({
            "clip_index": c["index"],
            "titles": _titles(keywords, [c["hook_text"]])[:3],
            "thumbnail_texts": _thumb_text(c["hook_text"]),
        })

    result = {
        "keywords": keywords,
        "suggestions": suggestions,
        "enrichment_note": ("YouTube autocomplete suggestions (keyless)"
                            if suggestions else
                            "Offline — keyword table is from your transcript only"),
        "titles": {
            "youtube": titles,
            "shorts": [{"title": t["title"][:55], "score": t["score"]}
                       for t in titles[:6]],
        },
        "descriptions": {
            "youtube": long_desc,
            "shorts": short_desc,
        },
        "hashtags": hashtags,
        "per_clip": per_clip,
        "thumbnail_texts_long": _thumb_text(hooks[0]) if hooks else [],
    }
    save_json(job.project_id, "seo.json", result)
    report(1.0)
    return {"keywords": len(keywords), "titles": len(titles),
            "clips_packaged": len(per_clip)}
