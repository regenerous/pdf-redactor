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
    with pytest.raises(DocumentError, match="Choose a PDF"):
        DocumentSession(b"not a pdf", "notes.txt")
    with pytest.raises(DocumentError, match="empty"):
        DocumentSession(b"", "empty.pdf")


def test_names_and_colors():
    assert safe_filename("../../secret.pdf") == "secret.pdf"
    assert redacted_filename("secret.pdf") == "secret-redacted.pdf"
    assert redacted_filename("secret-redacted.pdf") == "secret-redacted.pdf"
    assert normalize_color("#abc") == "#aabbcc"
    with pytest.raises(DocumentError):
        normalize_color("blue")
