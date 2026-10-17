"""Network hygiene for model downloads.

Some environments (corporate proxies, sandboxes) export NO_PROXY lists containing
bracketed IPv6 literals like `[::1]`, which break urllib3's proxy-bypass parsing
("Invalid port: ':1]'") inside huggingface_hub/requests. This strips those entries
while keeping hostname/IP bypasses intact. Harmless when no proxy is configured.
"""
from __future__ import annotations

import os


def sanitize_proxy_env() -> None:
    for var in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if not val:
            continue
        parts = [p.strip() for p in val.split(",") if p.strip()]
        cleaned = [p for p in parts if not (p.startswith("[") and p.endswith("]"))]
        if len(cleaned) != len(parts):
            os.environ[var] = ",".join(cleaned)
