"""Platform export presets — versioned, not hard-coded.

Slice 3 covers the big three. Per the master prompt, these live in a versioned
file the updater can refresh as platform specs change.
"""
from __future__ import annotations

PRESET_VERSION = 1

# width/height = output resolution; aspect = crop target; loudness in LUFS
PRESETS: dict[str, dict] = {
    "tiktok": {
        "label": "TikTok / Reels / Shorts",
        "width": 1080, "height": 1920, "aspect": (9, 16),
        "video_bitrate": "8M", "loudness_lufs": -14,
    },
    "youtube": {
        "label": "YouTube",
        "width": 1920, "height": 1080, "aspect": (16, 9),
        "video_bitrate": "12M", "loudness_lufs": -14,
    },
    "square": {
        "label": "Square (Feed posts)",
        "width": 1080, "height": 1080, "aspect": (1, 1),
        "video_bitrate": "8M", "loudness_lufs": -14,
    },
}


def get_preset(name: str) -> dict:
    try:
        return PRESETS[name]
    except KeyError:
        raise ValueError(f"unknown platform {name!r}; choose from {sorted(PRESETS)}")


def crop_box(src_w: int, src_h: int, aspect: tuple[int, int]) -> tuple[int, int, int, int]:
    """Largest centered crop of the source matching aspect (x, y, w, h)."""
    aw, ah = aspect
    target = aw / ah
    src = src_w / src_h
    if src > target:  # source wider → crop width
        w = int(src_h * target)
        h = src_h
    else:             # source taller → crop height
        w = src_w
        h = int(src_w / target)
    # ffmpeg crop needs even dimensions for yuv420p
    w -= w % 2
    h -= h % 2
    return (src_w - w) // 2, (src_h - h) // 2, w, h
