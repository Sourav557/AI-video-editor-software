"""Model manager (Slice 1 skeleton): manifest + VRAM budgeting policy.

Full version (later slices): on-demand load/unload, quantization choice per tier,
download progress, disk-space estimator. The orchestrator consults vram_plan()
before co-scheduling workers.
"""

# size_gb = quantized download size; vram_gb = peak at chosen quantization
MANIFEST = {
    "whisper-base": {
        "size_gb": 0.15, "vram_gb": 1.0, "license": "MIT (code + weights)",
        "tier": "A", "worker": "transcribe",
    },
    # Future slices (placeholders — measured at build time, never guessed):
    # "qwen3-tts-0.6b": {"size_gb": 2.5, "vram_gb": 4.0, "license": "Apache-2.0", "tier": "A"},
    # "qwen3-llm-8b-q4": {"size_gb": 5.0, "vram_gb": 6.0, "license": "Apache-2.0", "tier": "A"},
}

VRAM_TIERS = {"lite": 8, "standard": 16, "full": 24}


def vram_plan(vram_gb: int) -> dict:
    """Which workers may co-run. Conservative: heavy models never co-reside."""
    if vram_gb >= 24:
        return {"max_heavy_workers": 2, "note": "two small workers may co-run"}
    return {"max_heavy_workers": 1, "note": "heavy models strictly serialized"}
