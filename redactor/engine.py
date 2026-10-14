"""Remove information from a PDF instead of only painting over it."""

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


def safe_filename(name: str) -> str:
    base = (name or "document.pdf").replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(character for character in base if character.isprintable() and character not in '<>:"|?*')
    cleaned = cleaned.strip().strip(".")
    if not cleaned:
        cleaned = "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned[:180]


def redacted_filename(name: str) -> str:
    safe = safe_filename(name)
    stem = safe[:-4]
    if stem.lower().endswith("-redacted"):
        return safe
    return f"{stem}-redacted.pdf"


def _finite(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DocumentError("That area is off the page.") from None
    if not math.isfinite(number):
        raise DocumentError("That area is off the page.")
    return number


class DocumentSession:
    """One open PDF plus the redactions that will be burned in on save.

    Word positions from the PDF are in unrotated page space. The image on
    screen is rotated for reading, so the app sends rectangles in that
    display space and they are converted here before anything is stored.
    """

    def __init__(self, data: bytes, name: str) -> None:
        if not data:
            raise DocumentError("This file is empty.")
        if len(data) > MAX_PDF_BYTES:
            raise DocumentError("This PDF is larger than 100 MB.")
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise DocumentError("This file couldn't be opened. Choose a PDF.") from exc
        if document.needs_pass and not document.authenticate(""):
            document.close()
            raise DocumentError("This PDF is password-protected.")
        if document.page_count < 1:
            document.close()
            raise DocumentError("This PDF has no pages.")
        self.doc = document
        self.data = data
        self.name = safe_filename(name)
        self.doc_id = uuid.uuid4().hex
        self.redactions: list[Redaction] = []
        self._words: dict[int, list[tuple[int, str, pymupdf.Rect]]] = {}

    def close(self) -> None:
        self.doc.close()

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def _page(self, index: int) -> pymupdf.Page:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= self.doc.page_count:
            raise DocumentError("That page is not in this PDF.")
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
            "redactions": self.public_redactions(),
        }

    def export_pdf(self) -> bytes:
        if not self.redactions:
            raise DocumentError("Redact something before saving a copy.")
        output = pymupdf.open(stream=self.data, filetype="pdf")
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
