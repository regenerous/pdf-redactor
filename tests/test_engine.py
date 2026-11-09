import io

import pymupdf
import pytest

from redactor.engine import DocumentError, DocumentSession, normalize_color, redacted_filename, safe_filename


TOKEN = "472-19-8831"


def form_pdf() -> bytes:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 80), f"SSN {TOKEN} remains", fontsize=14)
    first.insert_text((72, 120), f"{TOKEN} again and KeepMe", fontsize=14)
    second = document.new_page()
    second.insert_text((72, 80), f"Page two {TOKEN}", fontsize=14)
    document.set_metadata({"title": TOKEN, "author": "Ada"})
    document.set_toc([[1, TOKEN, 1]])
    return document.tobytes()


def open_form() -> DocumentSession:
    return DocumentSession(form_pdf(), "intake.pdf")


def word_box(session: DocumentSession, page: int, text: str) -> dict:
    words = session.words_for_display(page)["words"]
    return next(word for word in words if word["text"] == text)


def extracted(data: bytes) -> str:
    document = pymupdf.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text() for page in document)


def test_clicking_a_word_removes_only_that_word():
    session = open_form()
    original = session.data
    target = word_box(session, 0, TOKEN)
    _item, remaining = session.add_area(0, target["x0"], target["y0"], target["x1"], target["y1"], TOKEN, "#000000")
    assert remaining == 2
    saved = session.export_pdf()
    assert session.data == original
    reopened = pymupdf.open(stream=saved, filetype="pdf")
    first_page = reopened[0].get_text()
    assert first_page.count(TOKEN) == 1
    assert "remains" in first_page
    assert "KeepMe" in first_page
    assert TOKEN in reopened[1].get_text()


def test_string_list_keeps_earlier_text_after_another_redaction():
    session = open_form()
    token = word_box(session, 0, TOKEN)
    other = word_box(session, 0, "KeepMe")
    session.add_area(0, token["x0"], token["y0"], token["x1"], token["y1"], TOKEN, "#111111")
    session.add_area(0, other["x0"], other["y0"], other["x1"], other["y1"], "KeepMe", "#c4453c")
    summary = {row["text"]: row for row in session.string_summary()}
    assert list(summary)[0] == "KeepMe"
    assert summary[TOKEN]["count"] == 1
    assert summary[TOKEN]["remaining"] == 2
    assert summary["KeepMe"]["remaining"] == 0
    session.redact_all(TOKEN, "#111111")
    finished = {row["text"]: row for row in session.string_summary()}
    assert finished[TOKEN]["remaining"] == 0
    assert finished[TOKEN]["count"] == 3
    token_item = next(item for item in session.redactions if item.text == TOKEN)
    session.remove(token_item.id)
    after_undo = {row["text"]: row for row in session.string_summary()}
    assert after_undo[TOKEN]["remaining"] == 1
    assert after_undo[TOKEN]["count"] == 2


def test_redact_all_removes_every_match_and_hidden_copies():
    session = open_form()
    added = session.redact_all(TOKEN, "#c4453c")
    assert added == 3
    saved = session.export_pdf()
    text = extracted(saved)
    assert TOKEN not in text
    assert "KeepMe" in text
    assert "remains" in text
    assert TOKEN.encode() not in saved
    reopened = pymupdf.open(stream=saved, filetype="pdf")
    assert reopened.metadata["title"] == ""
    assert reopened.metadata["author"] == "Ada"
    assert reopened.get_toc()[0][1] == "Redacted"


def test_box_removes_text_under_it():
    session = open_form()
    target = word_box(session, 0, "KeepMe")
    session.add_area(0, target["x0"] + 1, target["y0"] + 1, target["x1"] - 1, target["y1"] - 1, None, "#111111")
    text = extracted(session.export_pdf())
    assert "KeepMe" not in text
    assert "remains" in text


def test_rotated_page_uses_the_word_you_see():
    document = pymupdf.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((72, 100), "RotateMe stays", fontsize=20)
    page.set_rotation(90)
    session = DocumentSession(document.tobytes(), "rotated.pdf")
    target = word_box(session, 0, "RotateMe")
    session.add_area(0, target["x0"], target["y0"], target["x1"], target["y1"], "RotateMe", "#000000")
    text = extracted(session.export_pdf())
    assert "RotateMe" not in text
    assert "stays" in text


def test_box_erases_picture_pixels_and_leaves_a_crossing_line():
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 80), 0)
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    page.insert_image(pymupdf.Rect(40, 40, 140, 140), pixmap=pixmap)
    page.draw_line((20, 100), (180, 100), color=(0, 1, 0), width=4)
    session = DocumentSession(document.tobytes(), "scan.pdf")
    session.add_area(0, 40, 40, 90, 140, None, "#0000ff")
    saved = session.export_pdf()
    opened = pymupdf.open(stream=saved, filetype="pdf")
    shot = opened[0].get_pixmap(alpha=False, colorspace=pymupdf.csRGB)

    def sample(x, y):
        index = (y * shot.width + x) * shot.n
        return tuple(shot.samples[index : index + 3])

    assert sample(55, 70) == (0, 0, 255)
    assert sample(120, 70) == (255, 0, 0)
    assert sample(30, 100)[1] > 200


def test_duplicate_click_does_not_stack():
    session = open_form()
    target = word_box(session, 0, "remains")
    session.add_area(0, target["x0"], target["y0"], target["x1"], target["y1"], "remains", "#000")
    session.add_area(0, target["x0"], target["y0"], target["x1"], target["y1"], "remains", "#000")
    assert len(session.redactions) == 1


def test_undo_string_removes_every_copy_and_leaves_the_others():
    session = open_form()
    session.redact_all(TOKEN, "#111111")
    other = word_box(session, 0, "KeepMe")
    session.add_area(0, other["x0"], other["y0"], other["x1"], other["y1"], "KeepMe", "#c4453c")
    session.remove_text(TOKEN)
    assert TOKEN not in {item.text for item in session.redactions}
    assert any(item.text == "KeepMe" for item in session.redactions)
    assert TOKEN not in {row["text"] for row in session.string_summary()}


def test_undo_brings_a_redaction_back_off_the_list():
    session = open_form()
    target = word_box(session, 0, "remains")
    item, _remaining = session.add_area(0, target["x0"], target["y0"], target["x1"], target["y1"], "remains", "#fff")
    session.remove(item.id)
    assert session.redactions == []
    with pytest.raises(DocumentError):
        session.export_pdf()


def test_rejects_password_empty_and_non_pdf():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Secret")
    buffer = io.BytesIO()
    document.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pass", user_pw="user-pass")
    with pytest.raises(DocumentError, match="password-protected"):
        DocumentSession(buffer.getvalue(), "locked.pdf")
    with pytest.raises(DocumentError, match="Choose a PDF or an image"):
        DocumentSession(b"not a pdf", "notes.txt")
    with pytest.raises(DocumentError, match="empty"):
        DocumentSession(b"", "empty.pdf")
    with pytest.raises(DocumentError, match="WebP"):
        DocumentSession(b"RIFF\x00\x00\x00\x00WEBP", "shot.webp")


def test_names_and_colors():
    assert safe_filename("../../secret.pdf") == "secret.pdf"
    assert safe_filename("photo.JPEG") == "photo.jpeg"
    assert safe_filename("anim.gif") == "anim.gif"
    assert redacted_filename("secret.pdf") == "secret-redacted.pdf"
    assert redacted_filename("secret-redacted.pdf") == "secret-redacted.pdf"
    assert redacted_filename("photo.jpeg") == "photo-redacted.jpeg"
    assert redacted_filename("anim.gif") == "anim-redacted.png"
    assert redacted_filename("scan.tiff", "pdf") == "scan-redacted.pdf"
    assert normalize_color("#abc") == "#aabbcc"
    with pytest.raises(DocumentError):
        normalize_color("blue")


def _sample(pix: pymupdf.Pixmap, x: int, y: int) -> tuple:
    index = (y * pix.width + x) * pix.n
    return tuple(pix.samples[index : index + pix.n])


def _solid_png(width: int, height: int, color: tuple[int, ...], alpha: bool = False) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), int(alpha))
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


def test_png_redaction_changes_only_the_marked_pixels():
    original = _solid_png(80, 60, (240, 10, 10))
    marked = pymupdf.Pixmap(original)
    marked.set_rect(pymupdf.IRect(0, 0, 10, 10), (10, 220, 30))
    original = marked.tobytes("png")
    session = DocumentSession(original, "id-card.png")
    assert session.output_format == "png"
    assert session.name == "id-card.png"
    assert session.page_count == 1
    assert session.words_for_display(0)["words"] == []
    assert session.snapshot()["saveName"] == "id-card-redacted.png"
    session.add_area(0, 20, 15, 50, 45, None, "#0000ff")
    saved, media = session.export_copy()
    assert media == "image/png"
    assert session.data == original
    opened = pymupdf.Pixmap(saved)
    assert opened.width == 80 and opened.height == 60
    assert _sample(opened, 30, 25)[:3] == (0, 0, 255)
    assert _sample(opened, 2, 2)[:3] == (10, 220, 30)
    assert _sample(opened, 70, 50)[:3] == (240, 10, 10)
    before = pymupdf.Pixmap(original)
    for x, y in ((2, 2), (70, 50), (19, 15), (50, 44)):
        assert _sample(opened, x, y) == _sample(before, x, y)


def test_alpha_png_keeps_untouched_pixels():
    original = _solid_png(40, 30, (10, 20, 30, 128), alpha=True)
    session = DocumentSession(original, "overlay.png")
    session.add_area(0, 0, 0, 8, 8, None, "#00ff00")
    saved, _media = session.export_copy()
    opened = pymupdf.Pixmap(saved)
    before = pymupdf.Pixmap(original)
    assert _sample(opened, 2, 2) == (0, 255, 0, 255)
    assert _sample(opened, 20, 15) == _sample(before, 20, 15)


def test_jpeg_redaction_saves_a_jpeg():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 60), 0)
    pix.set_rect(pix.irect, (240, 10, 10))
    original = pix.tobytes("jpeg", jpg_quality=95)
    session = DocumentSession(original, "badge.JPEG")
    assert session.kind == "jpeg"
    assert session.name == "badge.jpeg"
    assert session.output_format == "jpeg"
    assert session.snapshot()["saveName"] == "badge-redacted.jpeg"
    session.add_area(0, 18, 16, 52, 46, None, "#0000ff")
    saved, media = session.export_copy()
    assert media == "image/jpeg"
    assert saved.startswith(b"\xff\xd8\xff")
    assert session.data == original
    opened = pymupdf.Pixmap(saved)
    red, green, blue = _sample(opened, 32, 28)
    assert blue > 200 and red < 40 and green < 40
    red, green, blue = _sample(opened, 4, 4)
    assert red > 200 and green < 40 and blue < 40


def test_oriented_jpeg_is_saved_as_the_picture_you_see():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 40), 0)
    pix.set_rect(pix.irect, (200, 0, 0))
    pix.set_rect(pymupdf.IRect(0, 0, 8, 8), (0, 255, 0))
    oriented = _with_orientation(pix.tobytes("jpeg", jpg_quality=95), 6)
    session = DocumentSession(oriented, "turn.jpg")
    width, height = session.page_size(0)
    assert (round(width), round(height)) == (40, 60)
    session.add_area(0, 0, 0, 12, 12, None, "#0000ff")
    saved, media = session.export_copy()
    assert media == "image/jpeg"
    opened = pymupdf.Pixmap(saved)
    assert (opened.width, opened.height) == (40, 60)
    red, green, blue = _sample(opened, 2, 2)
    assert blue > 200 and red < 40
    assert any(
        _sample(opened, x, y)[1] > 180 and _sample(opened, x, y)[0] < 80
        for y in range(opened.height)
        for x in range(opened.width)
    )


def test_still_gif_and_bmp_save_as_png_and_animated_gif_is_refused():
    session = DocumentSession(STILL_GIF, "mark.gif")
    assert session.name == "mark.gif"
    assert session.output_format == "png"
    assert session.snapshot()["saveName"] == "mark-redacted.png"
    session.add_area(0, 0, 0, 4, 4, None, "#0000ff")
    saved, media = session.export_copy()
    assert media == "image/png"
    assert saved.startswith(b"\x89PNG")
    with pytest.raises(DocumentError, match="Animated GIFs"):
        DocumentSession(ANIMATED_GIF, "move.gif")

    session = DocumentSession(_bmp(20, 16, (255, 0, 0)), "scan.bmp")
    assert session.output_format == "png"
    session.add_area(0, 2, 2, 10, 10, None, "#00ff00")
    saved, _media = session.export_copy()
    opened = pymupdf.Pixmap(saved)
    assert _sample(opened, 4, 4)[:3] == (0, 255, 0)
    assert _sample(opened, 16, 12)[:3] == (255, 0, 0)


def test_tiff_saves_png_for_one_page_and_pdf_for_several():
    single = DocumentSession(_tiff([(255, 0, 0)], 30, 20), "page.tiff")
    assert single.output_format == "png"
    assert single.name == "page.tiff"
    assert single.snapshot()["saveName"] == "page-redacted.png"
    single.add_area(0, 4, 4, 16, 14, None, "#0000ff")
    saved, media = single.export_copy()
    assert media == "image/png"
    assert _sample(pymupdf.Pixmap(saved), 8, 8)[:3] == (0, 0, 255)

    session = DocumentSession(_tiff([(255, 0, 0), (0, 255, 0)], 30, 20), "pages.tif")
    assert session.page_count == 2
    assert session.output_format == "pdf"
    assert session.snapshot()["saveName"] == "pages-redacted.pdf"
    session.add_area(0, 4, 4, 18, 16, None, "#0000ff")
    session.add_area(1, 4, 4, 18, 16, None, "#0000ff")
    saved = session.export_pdf()
    opened = pymupdf.open(stream=saved, filetype="pdf")
    assert opened.page_count == 2

    def sample_page(page, x, y):
        shot = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
        index = (y * shot.width + x) * shot.n
        return tuple(shot.samples[index : index + 3])

    assert sample_page(opened[0], 8, 8) == (0, 0, 255)
    assert sample_page(opened[0], 26, 16) == (255, 0, 0)
    assert sample_page(opened[1], 8, 8) == (0, 0, 255)
    assert sample_page(opened[1], 26, 16) == (0, 255, 0)


def _with_orientation(jpeg: bytes, orientation: int) -> bytes:
    import struct

    entry = struct.pack("<HHII", 0x0112, 3, 1, orientation)
    tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + entry + struct.pack("<I", 0)
    payload = b"Exif\x00\x00" + tiff
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return jpeg[:2] + segment + jpeg[2:]


def _bmp(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    import struct

    row = bytes((color[2], color[1], color[0])) * width
    pad = (4 - (len(row) % 4)) % 4
    pixels = (row + b"\x00" * pad) * height
    offset = 54
    header = struct.pack("<2sIHHI", b"BM", offset + len(pixels), 0, 0, offset)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return header + dib + pixels


def _tiff(colors: list[tuple[int, int, int]], width: int, height: int) -> bytes:
    import struct

    count = len(colors)
    ifd_size = 2 + 10 * 12 + 4
    ifd_start = 8
    bits_start = ifd_start + count * ifd_size
    strip_start = bits_start + count * 6
    strip_bytes = width * height * 3
    blob = bytearray(strip_start + count * strip_bytes)
    blob[0:8] = b"II*\x00" + struct.pack("<I", ifd_start)
    strip_off = strip_start
    pixel_count = width * height
    for index, color in enumerate(colors):
        ifd = ifd_start + index * ifd_size
        bits_off = bits_start + index * 6
        blob[bits_off : bits_off + 6] = struct.pack("<HHH", 8, 8, 8)
        blob[strip_off : strip_off + strip_bytes] = bytes(color) * pixel_count
        next_ifd = ifd_start + (index + 1) * ifd_size if index + 1 < count else 0
        blob[ifd : ifd + 2] = struct.pack("<H", 10)
        entries = (
            (256, 3, 1, width),
            (257, 3, 1, height),
            (258, 3, 3, bits_off),
            (259, 3, 1, 1),
            (262, 3, 1, 2),
            (273, 4, 1, strip_off),
            (277, 3, 1, 3),
            (278, 3, 1, height),
            (279, 4, 1, strip_bytes),
            (284, 3, 1, 1),
        )
        position = ifd + 2
        for tag, kind, number, value in entries:
            blob[position : position + 12] = struct.pack("<HHII", tag, kind, number, value)
            position += 12
        blob[position : position + 4] = struct.pack("<I", next_ifd)
        strip_off += strip_bytes
    return bytes(blob)


STILL_GIF = (
    b"GIF87a\x04\x00\x04\x00\x81\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x04\x00\x04\x00\x00\x08\t\x00\x01\x08\x1cH\xb0 \x80\x80\x00;"
)
ANIMATED_GIF = (
    b"GIF89a\x04\x00\x04\x00\x81\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00!\xff\x0b"
    b"NETSCAPE2.0\x03\x01\x00\x00\x00!\xf9\x04\x08\n\x00\x00\x00,\x00\x00\x00\x00\x04\x00\x04\x00\x00"
    b"\x08\t\x00\x01\x08\x1cH\xb0 \x80\x80\x00!\xf9\x04\x08\n\x00\x00\x00,\x00\x00\x00\x00\x04\x00"
    b"\x04\x00\x81\x00\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\t\x00\x01\x08\x1cH\xb0 \x80\x80\x00;"
)
