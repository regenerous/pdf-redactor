"""Draw the PDF Redactor icon: three black bars on a warm tile.

Small sizes are hard pixels, stored as classic BMP images inside the .ico.
Windows blurs an icon when it has to scale a PNG, so every taskbar size is
drawn on its own and stored uncompressed.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "redactor" / "static" / "icon.ico"
OUT_PNG = ROOT / "redactor" / "static" / "icon.png"

TILE = (246, 244, 238, 255)
INK = (17, 17, 17, 255)

# (x, y, width, height) for the three bars, top to bottom.
HAND = {
    16: [(3, 4, 5, 2), (2, 7, 12, 2), (6, 10, 8, 2)],
    20: [(4, 5, 7, 2), (3, 9, 14, 2), (8, 13, 9, 2)],
    24: [(5, 6, 8, 3), (4, 11, 16, 3), (10, 16, 10, 3)],
    28: [(6, 7, 9, 3), (4, 12, 19, 3), (11, 17, 12, 3)],
    30: [(6, 7, 10, 4), (5, 13, 20, 4), (12, 19, 13, 4)],
    32: [(6, 8, 11, 4), (5, 14, 22, 4), (13, 20, 15, 4)],
    36: [(7, 9, 12, 4), (5, 16, 25, 4), (14, 23, 16, 4)],
    40: [(7, 10, 14, 5), (6, 18, 28, 5), (16, 26, 18, 5)],
    48: [(9, 12, 16, 6), (8, 21, 32, 6), (18, 30, 22, 6)],
}

SIZES = [16, 20, 24, 28, 30, 32, 36, 40, 48, 60, 64, 72, 96, 128, 256]


def bars_for(size: int) -> list[tuple[int, int, int, int]]:
    if size in HAND:
        return HAND[size]
    height = max(4, round(size * 0.125))
    gap = max(3, round(size * 0.0625))
    stack = height * 3 + gap * 2
    top = (size - stack) // 2
    layout = (
        (0.18, 0.34),
        (0.15, 0.70),
        (0.42, 0.46),
    )
    bars = []
    for index, (x_frac, w_frac) in enumerate(layout):
        width = round(size * w_frac)
        x = round(size * x_frac)
        margin = round(size * 0.12)
        x = max(margin, min(x, size - margin - width))
        bars.append((x, top + index * (height + gap), width, height))
    return bars


def _covers_tile(x: int, y: int, size: int, radius: int) -> bool:
    px = x + 0.5
    py = y + 0.5
    if radius <= px <= size - radius and 0 <= py <= size:
        return True
    if radius <= py <= size - radius and 0 <= px <= size:
        return True
    cx = radius if px < size / 2 else size - radius
    cy = radius if py < size / 2 else size - radius
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= radius * radius


def _covers_bar(x: int, y: int, box: tuple[int, int, int, int], radius: int) -> bool:
    left, top, width, height = box
    if radius <= 0:
        return left <= x < left + width and top <= y < top + height
    px = x + 0.5
    py = y + 0.5
    right = left + width
    bottom = top + height
    if left + radius <= px <= right - radius and top <= py <= bottom:
        return True
    if top + radius <= py <= bottom - radius and left <= px <= right:
        return True
    cx = left + radius if px < left + width / 2 else right - radius
    cy = top + radius if py < top + height / 2 else bottom - radius
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= radius * radius


def render(size: int) -> Image.Image:
    """Binary pixels only. Gray edges are what makes a taskbar icon look soft."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    radius = max(2, round(size * 0.22))
    bars = bars_for(size)
    for y in range(size):
        for x in range(size):
            if _covers_tile(x, y, size, radius):
                pixels[x, y] = TILE
    for box in bars:
        bar_radius = 0 if box[3] <= 4 else max(1, box[3] // 5)
        for y in range(box[1], min(size, box[1] + box[3])):
            for x in range(box[0], min(size, box[0] + box[2])):
                if _covers_bar(x, y, box, bar_radius):
                    pixels[x, y] = INK
    return image


def _bmp_dib(image: Image.Image) -> bytes:
    image = image.convert("RGBA")
    width, height = image.size
    raw = image.tobytes("raw", "BGRA")
    stride = width * 4
    xor = b"".join(raw[y * stride : (y + 1) * stride] for y in range(height - 1, -1, -1))
    mask_stride = ((width + 31) // 32) * 4
    mask = bytes(mask_stride * height)
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(xor), 0, 0, 0, 0)
    return header + xor + mask


def write_ico(images: list[Image.Image], path: Path) -> None:
    blobs = [_bmp_dib(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    entries = b""
    offset = 6 + 16 * len(blobs)
    for image, blob in zip(images, blobs):
        width = 0 if image.width >= 256 else image.width
        height = 0 if image.height >= 256 else image.height
        entries += struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    images = [render(size) for size in SIZES]
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    write_ico(images, OUT_ICO)
    images[-1].save(OUT_PNG)
    print(f"wrote {OUT_ICO} ({OUT_ICO.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
