"""Slice 18: project settings (canvas + fps).

settings.json lives in the project dir (via save_json/load_json):
  {"aspect": "16:9", "width": 1920, "height": 1080, "fps": 30}
Absent settings.json means "follow the source" — render_edl uses the
source video's WxH and 30 fps, exactly the pre-Slice-18 behavior.
"""
from __future__ import annotations

from .projects import load_json, save_json

ASPECTS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
}

DEFAULTS = {"aspect": "16:9", "width": 1920, "height": 1080, "fps": 30}


def clean(raw: dict | None) -> dict:
    """Sanitize a settings dict; always returns full, valid settings."""
    raw = raw if isinstance(raw, dict) else {}
    aspect = raw.get("aspect")
    preset_wh = ASPECTS.get(aspect) if isinstance(aspect, str) else None

    def dim(v, fallback):
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            n = fallback
        n -= n % 2  # ffmpeg needs even dims for yuv420p
        return min(8192, max(16, n))

    width = dim(raw.get("width"), preset_wh[0] if preset_wh else DEFAULTS["width"])
    height = dim(raw.get("height"), preset_wh[1] if preset_wh else DEFAULTS["height"])
    try:
        fps = int(float(raw.get("fps", DEFAULTS["fps"])))
    except (TypeError, ValueError):
        fps = DEFAULTS["fps"]
    fps = min(120, max(1, fps))
    return {"aspect": aspect if preset_wh else "custom",
            "width": width, "height": height, "fps": fps}


def save_settings(pid: str, raw: dict | None) -> dict:
    s = clean(raw)
    save_json(pid, "settings.json", s)
    return s


def get_settings(pid: str) -> dict | None:
    """The saved settings, or None when the user never opened Project settings
    (the render then follows the source, as before Slice 18)."""
    s = load_json(pid, "settings.json")
    return clean(s) if s else None


def get_settings_or_defaults(pid: str) -> dict:
    """For the UI: defaults when nothing was saved yet."""
    return get_settings(pid) or dict(DEFAULTS)
