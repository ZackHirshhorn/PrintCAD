"""Shared scripts and utilities for the P0 QA suite (see docs/qa/qa-flows.md)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "src" / "printcad" / "examples"
QA_DOC = REPO_ROOT / "docs" / "qa" / "qa-flows.md"
EXAMPLE_NAMES = ("bracket", "enclosure", "gear")

CUBE20 = "result = cq.Workplane('XY').box(20, 20, 20, centered=False)"
BOX_PARAM = "w = param('w', 10.0, min=5, max=50)\nresult = cq.Workplane('XY').box(w, 20, 30, centered=False)"
# Wide top over a narrow base: side faces lean ~42 degrees from vertical, so they
# overhang at a 30 degree threshold but not at 45 or 50.
INVERTED_CONE = (
    "result = cq.Workplane('XY').add("
    "cq.Solid.makeCone(2, 20, 20, pnt=cq.Vector(0, 0, 0), dir=cq.Vector(0, 0, 1)))"
)
# A slab held up by a thin post: the slab underside is a flat ceiling (overhang at any angle).
MUSHROOM = (
    "post = cq.Workplane('XY').box(6, 6, 20, centered=(True, True, False))\n"
    "cap = cq.Workplane('XY').workplane(offset=20).box(40, 40, 4, centered=(True, True, False))\n"
    "result = post.union(cap)"
)

STL_DTYPE = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


def read_binary_stl(data: bytes) -> tuple[int, np.ndarray]:
    """Return (declared triangle count, structured triangle array) of a binary STL."""
    count = struct.unpack("<I", data[80:84])[0]
    return count, np.frombuffer(data, dtype=STL_DTYPE, count=count, offset=84)


def decode_png(data: bytes) -> np.ndarray:
    """Decode an 8-bit, non-interlaced RGB/RGBA PNG (as produced by Chromium screenshots) to (H, W, 3) uint8."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, header = 8, b"", None
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
    assert header is not None, "PNG has no IHDR"
    width, height, depth, color, _, _, interlace = header
    assert depth == 8 and interlace == 0 and color in (2, 6), f"unsupported PNG format {header}"
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw = zlib.decompress(idat)
    out = np.zeros((height, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(height):
        ftype = raw[y * (stride + 1)]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=y * (stride + 1) + 1).astype(np.int32)
        if ftype == 0:
            cur = line
        elif ftype == 2:
            cur = (line + prev) & 0xFF
        else:  # Sub (1), Average (3) and Paeth (4) depend on the left neighbour, decode per byte.
            cur = np.zeros(stride, dtype=np.int32)
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                if ftype == 1:
                    pred = a
                elif ftype == 3:
                    pred = (a + b) // 2
                elif ftype == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                else:
                    raise AssertionError(f"bad PNG filter {ftype}")
                cur[x] = (line[x] + pred) & 0xFF
        out[y] = cur
        prev = cur
    return out.reshape(height, width, bpp)[:, :, :3]


def pixel_counts(png: bytes) -> dict[str, int]:
    """Count viewer pixels by role: background, overhang red, build-volume blue, model grey."""
    img = decode_png(png).astype(int)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    background = (abs(r - 0x1B) <= 6) & (abs(g - 0x1E) <= 6) & (abs(b - 0x23) <= 6)
    # Overhang faces point down, so seen from below they are lit only by the dim hemisphere
    # ground light: a dark red around (100, 40, 40). Nothing else in the scene is red-dominant.
    red = (r > 70) & (r > 1.8 * g) & (r > 1.8 * b)
    blue = (b > 150) & (b > r + 80) & (g > 90) & (g < 170)
    grey_model = (r > 70) & (b > r) & (b - r < 60) & (g >= r - 10) & ~blue
    return {
        "total": int(img.shape[0] * img.shape[1]),
        "background": int(background.sum()),
        "red": int(red.sum()),
        "blue": int(blue.sum()),
        "model": int(grey_model.sum()),
    }
