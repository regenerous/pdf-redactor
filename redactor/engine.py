"""Remove information from a PDF or an image instead of only painting over it."""

from __future__ import annotations

import io
import math
import uuid
from dataclasses import dataclass

import pymupdf

MAX_PDF_BYTES = 100 * 1024 * 1024


class DocumentError(Exception):
    """A problem the person using the app can fix."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Redaction:
    id: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str | None
    color: str

    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(self.x0, self.y0, self.x1, self.y1)


def normalize_color(color: str) -> str:
    if not isinstance(color, str):
        raise DocumentError("Choose a block color.")
    raw = color.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(character * 2 for character in raw)
    if len(raw) != 6 or any(character not in "0123456789abcdefABCDEF" for character in raw):
        raise DocumentError("Choose a color like #111111.")
    return "#" + raw.lower()


def color_to_rgb(color: str) -> tuple[float, float, float]:
    value = normalize_color(color)[1:]
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


# Source kinds the app can open. gif, bmp, and tiff are saved as PNG,
# because those pixels can be kept without a lossy encode. JPEG stays JPEG.
_SOURCE_KIND = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
}
_KNOWN_SUFFIXES = (".jpeg", ".tiff", ".png", ".jpg", ".gif", ".bmp", ".tif", ".pdf")
MAX_IMAGE_PIXELS = 80_000_000


def _suffix(name: str) -> str:
    lower = name.lower()
    for ext in _KNOWN_SUFFIXES:
        if lower.endswith(ext):
            return ext
    return ""


def _display_extension(kind: str, suffix: str) -> str:
    if kind == "jpeg":
        return ".jpeg" if suffix == ".jpeg" else ".jpg"
    if kind == "tiff":
        return ".tiff" if suffix == ".tiff" else ".tif"
    return {"pdf": ".pdf", "png": ".png", "gif": ".gif", "bmp": ".bmp"}.get(kind, ".pdf")


def _output_extension(output_format: str, suffix: str) -> str:
    if output_format == "jpeg":
        return ".jpeg" if suffix == ".jpeg" else ".jpg"
    if output_format == "png":
        return ".png"
    return ".pdf"


def safe_filename(name: str, kind: str | None = None) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(character for character in base if character.isprintable() and character not in '<>:"|?*')
    cleaned = cleaned.strip().strip(".")
    suffix = _suffix(cleaned)
    if kind is None:
        kind = _SOURCE_KIND.get(suffix, "pdf")
    stem = cleaned[: -len(suffix)].strip().strip(".") if suffix else cleaned
    ext = _display_extension(kind, suffix)
    if not stem:
        stem = "document" if ext == ".pdf" else "image"
    return stem[: 180 - len(ext)] + ext


def redacted_filename(name: str, output_format: str | None = None) -> str:
    suffix = _suffix(name)
    source_kind = _SOURCE_KIND.get(suffix, "pdf")
    safe = safe_filename(name, source_kind)
    ext = _suffix(safe)
    stem = safe[: -len(ext)]
    if output_format is None:
        output_format = "png" if source_kind in ("gif", "bmp", "tiff") else source_kind
    out_ext = _output_extension(output_format, ext)
    if stem.lower().endswith("-redacted"):
        return stem + out_ext
    return f"{stem}-redacted{out_ext}"


def sniff_kind(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def _skip_gif_subblocks(data: bytes, index: int) -> int:
    limit = len(data)
    while index < limit:
        size = data[index]
        index += 1 + size
        if size == 0:
            return index
    return index


def _gif_is_animated(data: bytes) -> bool:
    """True when a GIF has more than one frame.

    MuPDF only decodes one frame, and it is not the first. Redacting that
    frame would cover the wrong picture, so animated GIFs are refused.
    """
    if len(data) < 13 or not data.startswith((b"GIF87a", b"GIF89a")):
        return False
    index = 13
    if data[10] & 0x80:
        index += 3 * (1 << ((data[10] & 0x07) + 1))
    frames = 0
    limit = len(data)
    while index < limit:
        marker = data[index]
        if marker == 0x3B:
            return False
        if marker == 0x21:
            if index + 2 > limit:
                return False
            index += 2
            index = _skip_gif_subblocks(data, index)
            continue
        if marker != 0x2C:
            return False
        frames += 1
        if frames > 1:
            return True
        if index + 10 > limit:
            return False
        packed = data[index + 9]
        index += 10
        if packed & 0x80:
            index += 3 * (1 << ((packed & 0x07) + 1))
        if index >= limit:
            return False
        index += 1
        index = _skip_gif_subblocks(data, index)
    return False


def _is_upright(transform: object) -> bool:
    if not isinstance(transform, (list, tuple)) or len(transform) < 6:
        return False
    try:
        a, b, c, d, e, f = (float(value) for value in transform[:6])
    except (TypeError, ValueError):
        return False
    return abs(b) < 0.01 and abs(c) < 0.01 and a > 0 and d > 0 and abs(e) < 0.01 and abs(f) < 0.01


def _image_block(page: pymupdf.Page) -> dict | None:
    for block in page.get_text("dict").get("blocks") or []:
        if block.get("type") == 1 and block.get("width") and block.get("height"):
            return block
    info = page.get_image_info() or []
    if info and info[0].get("width") and info[0].get("height"):
        return info[0]
    return None


def _pixmap_from_encoded(block: dict) -> pymupdf.Pixmap | None:
    image = block.get("image")
    if not image or not _is_upright(block.get("transform")):
        return None
    try:
        pix = pymupdf.Pixmap(image)
    except Exception:
        return None
    if pix.width < 1 or pix.height < 1:
        return None
    if int(block.get("width") or 0) not in (0, pix.width) or int(block.get("height") or 0) not in (0, pix.height):
        return None
    return pix


def _render_image_page(page: pymupdf.Page, block: dict | None) -> pymupdf.Pixmap:
    if page.rect.width <= 0 or page.rect.height <= 0:
        raise DocumentError("This image has no pages.")
    alpha = True
    if block and block.get("width") and block.get("height"):
        if _is_upright(block.get("transform")):
            width = int(block["width"])
            height = int(block["height"])
        else:
            xres = float(block.get("xres") or 72) or 72
            yres = float(block.get("yres") or xres) or xres
            width = max(1, int(round(float(page.rect.width) * xres / 72)))
            height = max(1, int(round(float(page.rect.height) * yres / 72)))
        if block.get("ext") in ("jpeg", "jpg"):
            alpha = False
    else:
        width = max(1, int(round(float(page.rect.width))))
        height = max(1, int(round(float(page.rect.height))))
        alpha = False
    matrix = pymupdf.Matrix(width / float(page.rect.width), height / float(page.rect.height))
    return page.get_pixmap(matrix=matrix, alpha=alpha, colorspace=pymupdf.csRGB)


def _copy_pixmap(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    # Pixmap(src) adds an alpha channel. Pass the flag to keep the original.
    return pymupdf.Pixmap(pix, int(bool(pix.alpha)))


def _drop_unused_alpha(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    if not pix.alpha:
        return pix
    samples = pix.samples
    step = pix.n
    for index in range(step - 1, len(samples), step):
        if samples[index] != 255:
            return pix
    return pymupdf.Pixmap(pix, 0)


def _normalize_pixmap(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    if pix.colorspace is not None and not pix.alpha and pix.n == 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    pix = _drop_unused_alpha(pix)
    if pix.width < 1 or pix.height < 1:
        raise DocumentError("This image has no pages.")
    if pix.width * pix.height > MAX_IMAGE_PIXELS:
        raise DocumentError("This image is too large to open.")
    return pix


def _document_from_pixmaps(pixmaps: list[pymupdf.Pixmap]) -> pymupdf.Document:
    document = pymupdf.open()
    try:
        for pix in pixmaps:
            page = document.new_page(width=float(pix.width), height=float(pix.height))
            page.insert_image(page.rect, pixmap=pix)
        return document
    except Exception:
        document.close()
        raise


def _pixel_color(pix: pymupdf.Pixmap, color: str) -> tuple[int, ...]:
    red, green, blue = (int(round(channel * 255)) for channel in color_to_rgb(color))
    if pix.n == 1:
        tone = int(round(0.2126 * red + 0.7152 * green + 0.0722 * blue))
        return (tone,)
    if pix.n == 2:
        tone = int(round(0.2126 * red + 0.7152 * green + 0.0722 * blue))
        return (tone, 255)
    if pix.alpha:
        return (red, green, blue, 255)
    return (red, green, blue)


def _finite(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DocumentError("That area is off the page.") from None
    if not math.isfinite(number):
        raise DocumentError("That area is off the page.")
    return number


class DocumentSession:
    """One open PDF or image, plus the redactions that will be burned in on save.

    Word positions are in unrotated page space. The picture on screen is
    rotated for reading, so the app sends rectangles in that display space
    and they are converted here before anything is stored.

    A still image is shown as one page in its own pixels, including the
    rotation stored in the file. JPEG is saved as JPEG. PNG, GIF, BMP, and
    a one-page TIFF are saved as PNG. A TIFF with more than one page is
    saved as a PDF so every page is kept.
    """

    def __init__(self, data: bytes, name: str) -> None:
        if not data:
            raise DocumentError("This file is empty.")
        if len(data) > MAX_PDF_BYTES:
            raise DocumentError("This file is larger than 100 MB.")
        if _is_webp(data):
            raise DocumentError("WebP images aren't supported. Save the picture as a PNG or JPEG first.")
        kind = sniff_kind(data)
        self.data = data
        self.doc_id = uuid.uuid4().hex
        self.redactions: list[Redaction] = []
        self._words: dict[int, list[tuple[int, str, pymupdf.Rect]]] = {}
        self._image: pymupdf.Pixmap | None = None
        if kind in ("png", "jpeg", "gif", "bmp", "tiff"):
            self.kind = kind
            self._open_image(data, name)
            return
        self.kind = "pdf"
        self.output_format = "pdf"
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise DocumentError("This file couldn't be opened. Choose a PDF or an image.") from exc
        if document.needs_pass and not document.authenticate(""):
            document.close()
            raise DocumentError("This PDF is password-protected.")
        if document.page_count < 1:
            document.close()
            raise DocumentError("This PDF has no pages.")
        self.doc = document
        self.name = safe_filename(name, "pdf")

    def _open_image(self, data: bytes, name: str) -> None:
        if self.kind == "gif" and _gif_is_animated(data):
            raise DocumentError("Animated GIFs aren't supported. Open a still image.")
        try:
            source = pymupdf.open(stream=data)
        except Exception as exc:
            raise DocumentError("This file couldn't be opened. Choose a PDF or an image.") from exc
        try:
            if source.page_count < 1:
                raise DocumentError("This image has no pages.")
            pixmaps = []
            for index in range(source.page_count):
                page = source[index]
                block = _image_block(page)
                pix = _pixmap_from_encoded(block) if block else None
                if pix is None:
                    pix = _render_image_page(page, block)
                pixmaps.append(_normalize_pixmap(pix))
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("This file couldn't be opened. Choose a PDF or an image.") from exc
        finally:
            source.close()
        try:
            self.doc = _document_from_pixmaps(pixmaps)
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("This file couldn't be opened. Choose a PDF or an image.") from exc
        if len(pixmaps) == 1:
            self._image = pixmaps[0]
            self.output_format = "jpeg" if self.kind == "jpeg" else "png"
        else:
            self.output_format = "pdf"
        self.name = safe_filename(name, self.kind)

    def save_suffixes(self) -> tuple[str, ...]:
        if self.output_format == "jpeg":
            return (".jpg", ".jpeg")
        if self.output_format == "png":
            return (".png",)
        return (".pdf",)

    def preferred_suffix(self) -> str:
        return _output_extension(self.output_format, _suffix(self.name))

    def close(self) -> None:
        self.doc.close()

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def _page(self, index: int) -> pymupdf.Page:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= self.doc.page_count:
            raise DocumentError("That page is not in this file.")
        return self.doc[index]

    def page_size(self, index: int) -> tuple[float, float]:
        rect = self._page(index).rect
        return float(rect.width), float(rect.height)

    def _pdf_words(self, index: int) -> list[tuple[int, str, pymupdf.Rect]]:
        cached = self._words.get(index)
        if cached is not None:
            return cached
        words: list[tuple[int, str, pymupdf.Rect]] = []
        for position, word in enumerate(self._page(index).get_text("words")):
            text = str(word[4])
            if not text.strip():
                continue
            words.append((position, text, pymupdf.Rect(word[0], word[1], word[2], word[3])))
        self._words[index] = words
        return words

    def words_for_display(self, index: int) -> dict:
        page = self._page(index)
        width, height = self.page_size(index)
        words = []
        for position, text, rect in self._pdf_words(index):
            shown = rect * page.rotation_matrix
            words.append(
                {
                    "i": position,
                    "text": text,
                    "x0": round(shown.x0, 3),
                    "y0": round(shown.y0, 3),
                    "x1": round(shown.x1, 3),
                    "y1": round(shown.y1, 3),
                }
            )
        return {"width": round(width, 3), "height": round(height, 3), "words": words}

    def render_png(self, index: int, scale: float) -> bytes:
        page = self._page(index)
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            scale = 2.0
        if not math.isfinite(scale):
            scale = 2.0
        scale = max(0.5, min(scale, 3.0))
        area = float(page.rect.width) * float(page.rect.height)
        if area > 0 and area * scale * scale > 12_000_000:
            scale = math.sqrt(12_000_000 / area)
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            alpha=False,
            colorspace=pymupdf.csRGB,
        )
        return pixmap.tobytes("png")

    def _to_pdf_rect(self, index: int, x0: float, y0: float, x1: float, y1: float) -> pymupdf.Rect:
        page = self._page(index)
        display = pymupdf.Rect(x0, y0, x1, y1) & page.rect
        if display.is_empty or display.width < 0.4 or display.height < 0.4:
            raise DocumentError("That area is too small to redact.")
        pdf_rect = display * page.derotation_matrix
        if pdf_rect.is_empty or pdf_rect.width < 0.2 or pdf_rect.height < 0.2:
            raise DocumentError("That area is outside the page.")
        return pdf_rect

    def _covered(self, index: int, rect: pymupdf.Rect) -> bool:
        area = rect.get_area()
        if area <= 0:
            return False
        for item in self.redactions:
            if item.page != index:
                continue
            overlap = rect & item.rect()
            if overlap.is_empty:
                continue
            if overlap.get_area() >= area * 0.6:
                return True
        return False

    def _nearly_same(self, index: int, rect: pymupdf.Rect) -> Redaction | None:
        for item in self.redactions:
            if item.page != index:
                continue
            if (
                abs(item.x0 - rect.x0) < 0.6
                and abs(item.y0 - rect.y0) < 0.6
                and abs(item.x1 - rect.x1) < 0.6
                and abs(item.y1 - rect.y1) < 0.6
            ):
                return item
        return None

    def _label(self, text: str | None) -> str | None:
        if not isinstance(text, str):
            return None
        label = text.strip()
        if not label:
            return None
        return label[:200]

    def add_area(
        self,
        page: int,
        x0: object,
        y0: object,
        x1: object,
        y1: object,
        text: str | None,
        color: str,
    ) -> tuple[Redaction, int]:
        rect = self._to_pdf_rect(page, _finite(x0), _finite(y0), _finite(x1), _finite(y1))
        label = self._label(text)
        existing = self._nearly_same(page, rect)
        if existing is not None:
            return existing, self.remaining_matches(label)
        item = Redaction(
            id=uuid.uuid4().hex[:12],
            page=page,
            x0=float(rect.x0),
            y0=float(rect.y0),
            x1=float(rect.x1),
            y1=float(rect.y1),
            text=label,
            color=normalize_color(color),
        )
        self.redactions.append(item)
        return item, self.remaining_matches(label)

    def remaining_matches(self, text: str | None) -> int:
        if not text:
            return 0
        return sum(1 for _ in self._uncovered_matches(text))

    def _uncovered_matches(self, text: str):
        for index in range(self.doc.page_count):
            for _position, word, rect in self._pdf_words(index):
                if word != text or self._covered(index, rect):
                    continue
                yield index, rect

    def redact_all(self, text: str, color: str) -> int:
        label = self._label(text)
        if not label:
            raise DocumentError("There is no text to redact.")
        fill = normalize_color(color)
        matches = list(self._uncovered_matches(label))
        for index, rect in matches:
            self.redactions.append(
                Redaction(
                    id=uuid.uuid4().hex[:12],
                    page=index,
                    x0=float(rect.x0),
                    y0=float(rect.y0),
                    x1=float(rect.x1),
                    y1=float(rect.y1),
                    text=label,
                    color=fill,
                )
            )
        return len(matches)

    def remove(self, redaction_id: str) -> None:
        before = len(self.redactions)
        self.redactions = [item for item in self.redactions if item.id != redaction_id]
        if len(self.redactions) == before:
            raise DocumentError("That redaction is already gone.")

    def remove_text(self, text: str) -> None:
        label = self._label(text)
        if not label:
            raise DocumentError("That redaction is already gone.")
        before = len(self.redactions)
        self.redactions = [item for item in self.redactions if item.text != label]
        if len(self.redactions) == before:
            raise DocumentError("That redaction is already gone.")

    def string_summary(self) -> list[dict]:
        """Unique redacted strings, newest first, with copies still left in the file."""
        order: list[str] = []
        counts: dict[str, int] = {}
        colors: dict[str, str] = {}
        for item in self.redactions:
            if not item.text:
                continue
            counts[item.text] = counts.get(item.text, 0) + 1
            colors[item.text] = item.color
            if item.text in order:
                order.remove(item.text)
            order.append(item.text)
        summary = []
        for text in reversed(order):
            summary.append(
                {
                    "text": text,
                    "count": counts[text],
                    "remaining": self.remaining_matches(text),
                    "color": colors[text],
                }
            )
        return summary

    def activity(self) -> dict:
        return {"redactions": self.public_redactions(), "strings": self.string_summary()}

    def public_redactions(self) -> list[dict]:
        published = []
        for item in self.redactions:
            shown = item.rect() * self._page(item.page).rotation_matrix
            published.append(
                {
                    "id": item.id,
                    "page": item.page,
                    "x0": round(shown.x0, 3),
                    "y0": round(shown.y0, 3),
                    "x1": round(shown.x1, 3),
                    "y1": round(shown.y1, 3),
                    "text": item.text,
                    "color": item.color,
                }
            )
        return published

    def snapshot(self) -> dict:
        return {
            "open": True,
            "docId": self.doc_id,
            "name": self.name,
            "pageCount": self.page_count,
            "format": self.output_format,
            "saveName": redacted_filename(self.name, self.output_format),
            **self.activity(),
        }

    def export_copy(self) -> tuple[bytes, str]:
        if self.output_format == "png":
            return self.export_image(), "image/png"
        if self.output_format == "jpeg":
            return self.export_image(), "image/jpeg"
        return self.export_pdf(), "application/pdf"

    def export_image(self) -> bytes:
        if self._image is None:
            raise DocumentError("The copy couldn't be saved.")
        if not self.redactions:
            raise DocumentError("Redact something before saving a copy.")
        pix = _copy_pixmap(self._image)
        bounds = pymupdf.Rect(0, 0, pix.width, pix.height)
        for item in self.redactions:
            if item.page != 0:
                continue
            rect = item.rect() & bounds
            if rect.is_empty or rect.width < 0.4 or rect.height < 0.4:
                continue
            area = pymupdf.IRect(math.floor(rect.x0), math.floor(rect.y0), math.ceil(rect.x1), math.ceil(rect.y1))
            pix.set_rect(area, _pixel_color(pix, item.color))
        try:
            if self.output_format == "jpeg":
                if pix.alpha:
                    pix = pymupdf.Pixmap(pix, 0)
                if pix.n not in (1, 3):
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                return pix.tobytes("jpeg", jpg_quality=95)
            return pix.tobytes("png")
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("The copy couldn't be saved.") from exc

    def _reopen(self) -> pymupdf.Document:
        if self.kind == "pdf":
            return pymupdf.open(stream=self.data, filetype="pdf")
        return pymupdf.open(stream=self.doc.tobytes(), filetype="pdf")

    def export_pdf(self) -> bytes:
        if not self.redactions:
            raise DocumentError("Redact something before saving a copy.")
        output = self._reopen()
        try:
            grouped: dict[int, list[Redaction]] = {}
            for item in self.redactions:
                grouped.setdefault(item.page, []).append(item)
            for index, items in grouped.items():
                page = output[index]
                for item in items:
                    rect = item.rect() & page.mediabox
                    if rect.is_empty:
                        continue
                    page.add_redact_annot(rect, fill=color_to_rgb(item.color))
                # A box erases text inside it and the picture pixels it covers.
                # Line art is removed only when the box covers that shape completely,
                # so a form rule that crosses the box can remain on the rest of the page.
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                    text=pymupdf.PDF_REDACT_TEXT_REMOVE,
                )
            self._scrub(output)
            buffer = io.BytesIO()
            output.save(buffer, garbage=4, deflate=True, clean=True)
            return buffer.getvalue()
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("The copy couldn't be saved.") from exc
        finally:
            output.close()

    def _scrub(self, document: pymupdf.Document) -> None:
        needles = [item.text for item in self.redactions if item.text and len(item.text) >= 4]
        if not needles:
            return
        try:
            metadata = {}
            for key, value in dict(document.metadata or {}).items():
                metadata[key] = "" if value is None else str(value)
            changed = False
            for key, value in list(metadata.items()):
                if value and any(needle in value for needle in needles):
                    metadata[key] = ""
                    changed = True
            if changed:
                document.set_metadata(metadata)
        except Exception:
            pass
        try:
            xml = document.get_xml_metadata() or ""
            if any(needle in xml for needle in needles):
                document.del_xml_metadata()
        except Exception:
            pass
        try:
            toc = document.get_toc()
            changed = False
            for item in toc:
                if len(item) >= 2 and any(needle in str(item[1]) for needle in needles):
                    item[1] = "Redacted"
                    changed = True
            if changed:
                document.set_toc(toc)
        except Exception:
            pass
