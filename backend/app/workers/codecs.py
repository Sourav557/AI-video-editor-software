"""Slice 18: export codec library.

Transcodes the EDL mezzanine (edit.mp4, h264) into the final downloadable
file. Each codec entry describes its ffmpeg output-side arguments, default
quality, and container. Encoder availability is checked against the actual
ffmpeg binary AT RUNTIME (cached per process), never at import time: the
API layer converts a missing encoder into a clean 400, and the worker
raises RuntimeError so the job fails honestly instead of silently skipping.
"""
from __future__ import annotations

import shutil
import subprocess

# ffmpeg -preset names, shared by the x264/x265-style encoders. For
# libaom-av1 / libvpx-vp9 they map to -cpu-used (see _CPU_USED_MAP).
PRESET_NAMES = ("ultrafast", "superfast", "veryfast", "faster", "fast",
                "medium", "slow", "slower", "veryslow")

_CPU_USED_MAP = {
    # libaom-av1: 0 (best) .. 8 (fastest)
    "av1": {"ultrafast": 8, "superfast": 7, "veryfast": 6, "faster": 5,
            "fast": 4, "medium": 3, "slow": 2, "slower": 1, "veryslow": 0},
    # libvpx-vp9 (-deadline good): 0 (best) .. 5 (fastest)
    "vp9": {"ultrafast": 5, "superfast": 5, "veryfast": 4, "faster": 4,
            "fast": 3, "medium": 2, "slow": 1, "slower": 0, "veryslow": 0},
}

CODECS: dict[str, dict] = {
    "h264": {
        "label": "H.264 (MP4)", "ext": ".mp4", "encoder": "libx264",
        "crf_range": (0, 51), "crf_default": 18,
        "preset_default": "veryfast", "preset_kind": "preset",
        "missing_msg": "H.264 encoder not available in this ffmpeg build",
        "file": "edit_h264.mp4",
    },
    "hevc": {
        "label": "H.265 / HEVC (MP4)", "ext": ".mp4", "encoder": "libx265",
        "crf_range": (0, 51), "crf_default": 23,
        "preset_default": "veryfast", "preset_kind": "preset",
        "missing_msg": "HEVC encoder not available in this ffmpeg build",
        "file": "edit_hevc.mp4",
    },
    "av1": {
        "label": "AV1 (MP4)", "ext": ".mp4", "encoder": "libaom-av1",
        "crf_range": (0, 63), "crf_default": 28,
        "preset_default": "medium", "preset_kind": "cpu-used",
        "missing_msg": "AV1 encoder not available in this ffmpeg build",
        "file": "edit_av1.mp4",
    },
    "prores": {
        "label": "ProRes LT (MOV)", "ext": ".mov", "encoder": "prores_ks",
        "crf_range": None, "crf_default": None,
        "preset_default": None, "preset_kind": "profile",
        "missing_msg": "ProRes encoder not available in this ffmpeg build",
        "file": "edit_prores.mov",
    },
    "vp9": {
        "label": "VP9 (WebM)", "ext": ".webm", "encoder": "libvpx-vp9",
        "crf_range": (0, 63), "crf_default": 30,
        "preset_default": "medium", "preset_kind": "cpu-used",
        "missing_msg": "VP9 encoder not available in this ffmpeg build",
        "file": "edit.webm",
    },
    "gif": {
        "label": "GIF (animated)", "ext": ".gif", "encoder": None,
        "crf_range": None, "crf_default": None,
        "preset_default": None, "preset_kind": None,
        "needs_filters": ("palettegen", "paletteuse"),
        "missing_msg": "GIF palette filters not available in this ffmpeg build",
        "file": "edit.gif",
    },
    "mp3": {
        "label": "MP3 (audio only)", "ext": ".mp3", "encoder": "libmp3lame",
        "crf_range": None, "crf_default": None,
        "preset_default": None, "preset_kind": None,
        "missing_msg": "MP3 encoder not available in this ffmpeg build",
        "file": "edit.mp3",
    },
    "wav": {
        "label": "WAV (audio only, PCM)", "ext": ".wav", "encoder": "pcm_s16le",
        "crf_range": None, "crf_default": None,
        "preset_default": None, "preset_kind": None,
        "missing_msg": "WAV encoder not available in this ffmpeg build",
        "file": "edit.wav",
    },
}

_AUDIO_ONLY = {"mp3", "wav"}
_GIF_MAX_W, _GIF_FPS = 480, 15


def describe() -> dict:
    """JSON-safe codec catalog for the UI (defaults + ranges + choices)."""
    out = {}
    for name, m in CODECS.items():
        out[name] = {
            "label": m["label"], "ext": m["ext"],
            "crf_range": list(m["crf_range"]) if m["crf_range"] else None,
            "crf_default": m["crf_default"],
            "presets": list(PRESET_NAMES) if m["preset_kind"] in ("preset", "cpu-used") else None,
            "preset_default": m["preset_default"],
            "profiles": [0, 1, 2, 3] if m["preset_kind"] == "profile" else None,
            "profile_default": 2 if m["preset_kind"] == "profile" else None,
            "audio_only": name in _AUDIO_ONLY,
            "file": m["file"],
        }
    return out


def clean_export_spec(codec: str = "h264", crf=None, preset=None,
                      profile=None) -> dict:
    """Sanitize user export options -> spec dict. Raises ValueError on bad input."""
    if codec not in CODECS:
        raise ValueError(f"unknown codec {codec!r}; choose from {sorted(CODECS)}")
    m = CODECS[codec]
    spec: dict = {"codec": codec, "file": m["file"], "ext": m["ext"]}
    if m["crf_range"]:
        lo, hi = m["crf_range"]
        try:
            c = float(crf) if crf is not None else m["crf_default"]
        except (TypeError, ValueError):
            c = m["crf_default"]
        spec["crf"] = int(min(hi, max(lo, round(c))))
    else:
        spec["crf"] = None
    if m["preset_kind"] in ("preset", "cpu-used"):
        spec["preset"] = preset if preset in PRESET_NAMES else m["preset_default"]
    else:
        spec["preset"] = None
    if m["preset_kind"] == "profile":
        try:
            spec["profile"] = int(min(3, max(0, int(profile if profile is not None else 2))))
        except (TypeError, ValueError):
            spec["profile"] = 2
    else:
        spec["profile"] = None
    return spec


def spec_from_params(params: dict) -> dict | None:
    """Export spec from a render/batch params dict, or None when no codec
    option was passed (the default path stays EXACTLY as before)."""
    if not any(k in (params or {}) for k in ("codec", "crf", "preset", "profile")):
        return None
    return clean_export_spec((params or {}).get("codec", "h264"),
                             (params or {}).get("crf"),
                             (params or {}).get("preset"),
                             (params or {}).get("profile"))


_enc_cache: dict[str, set[str]] = {}
_filter_cache: dict[str, set[str]] = {}


def _encoders(ffmpeg: str) -> set[str]:
    """Encoder names from `ffmpeg -encoders`, checked once per binary path."""
    if ffmpeg not in _enc_cache:
        pr = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                            capture_output=True, text=True)
        names = set()
        for line in pr.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0][0] in "VAS." and len(parts[0]) >= 6:
                names.add(parts[1])
        _enc_cache[ffmpeg] = names
    return _enc_cache[ffmpeg]


def _filters(ffmpeg: str) -> set[str]:
    """Filter names from `ffmpeg -filters`, checked once per binary path."""
    if ffmpeg not in _filter_cache:
        import re
        pr = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                            capture_output=True, text=True)
        # anchor on the I/O marker ("V->V", "AA->A" …): the token before it
        # is the filter name; header lines have no marker.
        pat = re.compile(r"^\s*\S+\s+([a-z0-9_]+)\s+\S*->\S*")
        names = set()
        for line in pr.stdout.splitlines():
            m = pat.match(line)
            if m:
                names.add(m.group(1))
        _filter_cache[ffmpeg] = names
    return _filter_cache[ffmpeg]


def availability(ffmpeg: str, codec: str) -> tuple[bool, str | None]:
    """(ok, clean_error_message_or_None) for one codec on this binary."""
    m = CODECS[codec]
    if m.get("needs_filters"):
        missing = [f for f in m["needs_filters"] if f not in _filters(ffmpeg)]
        if missing:
            return False, m["missing_msg"]
        return True, None
    enc = m["encoder"]
    if enc in _encoders(ffmpeg):
        return True, None
    return False, m["missing_msg"]


def assert_available(ffmpeg: str, codec: str) -> None:
    """Fail fast with the clean message when the codec can't be encoded."""
    ok, msg = availability(ffmpeg, codec)
    if not ok:
        raise RuntimeError(msg)


def _output_args(ffmpeg: str, spec: dict) -> list[str]:
    """ffmpeg output-side args (everything after -i, before the path)."""
    codec, crf, preset = spec["codec"], spec["crf"], spec["preset"]
    if codec == "h264":
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"]
    if codec == "hevc":
        return ["-c:v", "libx265", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-c:a", "aac", "-movflags", "+faststart"]
    if codec == "av1":
        cpu = _CPU_USED_MAP["av1"][preset]
        return ["-c:v", "libaom-av1", "-crf", str(crf), "-b:v", "0",
                "-cpu-used", str(cpu), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart"]
    if codec == "prores":
        return ["-c:v", "prores_ks", "-profile:v", str(spec["profile"]),
                "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le",
                "-movflags", "+faststart"]
    if codec == "vp9":
        cpu = _CPU_USED_MAP["vp9"][preset]
        acodec = "libopus" if "libopus" in _encoders(ffmpeg) else "aac"
        return ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
                "-deadline", "good", "-cpu-used", str(cpu),
                "-pix_fmt", "yuv420p", "-c:a", acodec]
    if codec == "mp3":
        return ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
    if codec == "wav":
        return ["-vn", "-c:a", "pcm_s16le", "-ar", "48000"]
    raise ValueError(f"no args for codec {codec!r}")


def _transcode_gif(ffmpeg: str, src, dst) -> None:
    """Two-pass palette GIF, capped at 480px wide / 15fps (sanity)."""
    import tempfile
    pal = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    pal.close()
    try:
        vf = f"fps={_GIF_FPS},scale={_GIF_MAX_W}:-2:flags=lanczos"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(src), "-vf", f"{vf},palettegen",
                        pal.name], check=True)
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-i", str(src), "-i", pal.name, "-lavfi",
                        f"{vf}[x];[x][1:v]paletteuse", str(dst)], check=True)
    finally:
        import os
        try:
            os.unlink(pal.name)
        except OSError:
            pass


def transcode(ffmpeg: str | None, src, dst, spec: dict) -> None:
    """Transcode the mezzanine into the spec's codec/file. Raises
    RuntimeError with a clean message when the encoder is unavailable."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    codec = spec["codec"]
    assert_available(ffmpeg, codec)
    if codec == "gif":
        _transcode_gif(ffmpeg, src, dst)
        return
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(src), *_output_args(ffmpeg, spec),
                    str(dst)], check=True)
