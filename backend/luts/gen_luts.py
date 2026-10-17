"""Generate the shipped 16x16x16 .cube LUTs for Slice 13 (color panel).

Run:  python gen_luts.py   (writes teal_orange.cube, warm_film.cube next to this file)

.cube layout: 4096 lines, red channel varies fastest, then green, then blue.
"""
from __future__ import annotations

import os

SIZE = 16


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _lum(r: float, g: float, b: float) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def teal_orange(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Shadows drift toward teal (red pulled down, green/blue lifted),
    highlights toward orange (red lifted, blue pulled down)."""
    l = _lum(r, g, b)
    ws = max(0.0, min(1.0, (0.35 - l) / 0.35))  # shadow weight
    wh = max(0.0, min(1.0, (l - 0.60) / 0.40))  # highlight weight
    r2 = r - 0.14 * ws + 0.12 * wh
    g2 = g + 0.06 * ws + 0.03 * wh
    b2 = b + 0.14 * ws - 0.12 * wh
    return _clamp(r2), _clamp(g2), _clamp(b2)


def warm_film(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Warm lift in the shadows plus a gentle overall warm cast."""
    l = _lum(r, g, b)
    lift = 1.0 - l  # strongest in darks
    r2 = r + 0.075 * lift + 0.030
    g2 = g + 0.022 * lift + 0.008
    b2 = b - 0.055 * lift - 0.028
    return _clamp(r2), _clamp(g2), _clamp(b2)


def write_lut(path: str, title: str, fn) -> None:
    lines = [
        f'TITLE "{title}"',
        f"LUT_3D_SIZE {SIZE}",
        "DOMAIN_MIN 0.0 0.0 0.0",
        "DOMAIN_MAX 1.0 1.0 1.0",
        "",
    ]
    for bi in range(SIZE):
        for gi in range(SIZE):
            for ri in range(SIZE):
                r, g, b = ri / (SIZE - 1), gi / (SIZE - 1), bi / (SIZE - 1)
                r2, g2, b2 = fn(r, g, b)
                lines.append(f"{r2:.6f} {g2:.6f} {b2:.6f}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {path} ({len(lines) - 5} entries)")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    write_lut(os.path.join(here, "teal_orange.cube"), "LocalCut teal-orange", teal_orange)
    write_lut(os.path.join(here, "warm_film.cube"), "LocalCut warm film", warm_film)
