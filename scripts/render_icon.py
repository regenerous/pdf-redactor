"""Draw the PDF Redactor icon: three black bars on a warm tile.

Each small size is laid out by hand so the bars stay thick enough for a
taskbar. Larger sizes follow the same offsets. Pillow is only needed to
run this script; the committed .ico is what the app and the Windows build use.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "redactor" / "static" / "icon.ico"
OUT_PNG = ROOT / "redactor" / "static" / "icon.png"

TILE = (246, 244, 238, 255)
INK = (17, 17, 17, 255)

# (x, y, width, height) for the three bars, top to bottom.
# Widths differ, and each row starts at a different x.
HAND = {
    16: [(3, 4, 5, 2), (2, 7, 12, 2), (6, 10, 8, 2)],
    20: [(4, 5, 7, 2), (3, 9, 14, 2), (8, 13, 9, 2)],
    24: [(5, 6, 8, 3), (4, 11, 16, 3), (10, 16, 10, 3)],
    32: [(6, 8, 11, 4), (5, 14, 22, 4), (13, 20, 15, 4)],
    40: [(7, 10, 14, 5), (6, 18, 28, 5), (16, 26, 18, 5)],
    48: [(9, 12, 16, 6), (8, 21, 32, 6), (18, 30, 22, 6)],
}


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


def render(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = max(2, round(size * 0.22))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=TILE)
    for x, y, width, height in bars_for(size):
        bar_radius = 0 if height <= 2 else max(1, height // 5)
        draw.rounded_rectangle(
            (x, y, x + width - 1, y + height - 1),
            radius=bar_radius,
            fill=INK,
        )
    return image


def _png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_ico(images: list[Image.Image], path: Path) -> None:
    """Pack pre-rendered PNGs into one .ico so small sizes are not resampled."""
    blobs = [_png_bytes(image) for image in images]
    count = len(blobs)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    offset = 6 + 16 * count
    for image, blob in zip(images, blobs):
        width = 0 if image.width >= 256 else image.width
        height = 0 if image.height >= 256 else image.height
        entries += struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = [render(size) for size in sizes]
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    write_ico(images, OUT_ICO)
    images[-1].save(OUT_PNG)
    preview = Path("/tmp/redactor-shots")
    preview.mkdir(parents=True, exist_ok=True)
    pad = 16
    blow = [render(size).resize((size * 8, size * 8), Image.Resampling.NEAREST) for size in (16, 24, 32, 48)]
    blow.append(render(256))
    blow_w = sum(image.width for image in blow) + pad * (len(blow) + 1)
    blow_h = max(image.height for image in blow) + pad * 2
    blown = Image.new("RGB", (blow_w, blow_h), (210, 208, 202))
    x = pad
    for image in blow:
        y = (blow_h - image.height) // 2
        if image.mode == "RGBA":
            blown.paste(image, (x, y), image)
        else:
            blown.paste(image, (x, y))
        x += image.width + pad
    blown.save(preview / "icon-taskbar.png")
    print(f"wrote {OUT_ICO} ({OUT_ICO.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
