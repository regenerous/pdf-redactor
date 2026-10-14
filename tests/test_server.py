import json
import struct
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pymupdf

from redactor import __version__
from redactor.server import create_server
from tests.test_engine import TOKEN, form_pdf


def start_server():
    server, state = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state


def call(server, method, path, body=None, headers=None):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request) as response:
            return response.status, response.read(), dict(response.headers)
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_page_describes_the_two_ways_to_redact(tmp_path):
    server, _state = start_server()
    try:
        status, body, _headers = call(server, "GET", "/")
        page = body.decode()
        assert status == 200
        assert "Click a word" in page
        assert "Drag a box" in page
        assert "Save a copy" in page
        assert "The original file stays untouched." in page
        assert f"Version {__version__}" in page
        assert __version__ == "1.0.2"
        assert "f6f4ee" in page
    finally:
        server.shutdown()


def test_open_redact_save_and_keep_the_original(tmp_path: Path):
    source = tmp_path / "intake.pdf"
    source.write_bytes(form_pdf())
    original = source.read_bytes()
    server, _state = start_server()
    try:
        status, body, _headers = call(
            server,
            "POST",
            "/api/open",
            original,
            {"Content-Type": "application/pdf", "X-Filename": "intake.pdf"},
        )
        assert status == 200
        opened = json.loads(body)
        assert opened["pageCount"] == 2

        status, body, _headers = call(server, "GET", "/api/pages/0/words")
        words = json.loads(body)["words"]
        target = next(word for word in words if word["text"] == TOKEN)
        status, body, _headers = call(
            server,
            "POST",
            "/api/redactions",
            json.dumps(
                {
                    "page": 0,
                    "x0": target["x0"],
                    "y0": target["y0"],
                    "x1": target["x1"],
                    "y1": target["y1"],
                    "text": TOKEN,
                    "color": "#111111",
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )
        added = json.loads(body)
        assert status == 200
        assert added["remaining"] == 2
        assert added["strings"][0]["text"] == TOKEN
        assert added["strings"][0]["remaining"] == 2

        status, body, _headers = call(
            server,
            "POST",
            "/api/redactions/all",
            json.dumps({"text": TOKEN, "color": "#111111"}).encode(),
            {"Content-Type": "application/json"},
        )
        assert json.loads(body)["added"] == 2

        copy_path = tmp_path / "intake-redacted.pdf"
        status, body, _headers = call(
            server,
            "POST",
            "/api/save",
            json.dumps({"path": str(copy_path)}).encode(),
            {"Content-Type": "application/json"},
        )
        assert status == 200
        assert source.read_bytes() == original
        saved = pymupdf.open(copy_path)
        assert TOKEN not in "".join(page.get_text() for page in saved)
        assert "KeepMe" in saved[0].get_text()

        status, body, _headers = call(
            server,
            "POST",
            "/api/save",
            json.dumps({"path": str(source)}).encode(),
            {"Content-Type": "application/json"},
        )
        assert status == 400
        assert source.read_bytes() == original
        assert b"original file" in body

        status, body, headers = call(server, "POST", "/api/save")
        assert status == 200
        assert headers["Content-Type"] == "application/pdf"
        assert "intake-redacted.pdf" in headers["Content-Disposition"]
        downloaded = pymupdf.open(stream=body, filetype="pdf")
        assert TOKEN not in "".join(page.get_text() for page in downloaded)
    finally:
        server.shutdown()


def test_favicon_is_the_three_bar_icon():
    icon = (Path(__file__).resolve().parents[1] / "redactor" / "static" / "icon.ico").read_bytes()
    _reserved, kind, count = struct.unpack_from("<HHH", icon, 0)
    assert kind == 1
    assert count >= 4
    widths = []
    offset = 6
    for _ in range(count):
        width, _height, *_rest = struct.unpack_from("<BBBBHHII", icon, offset)
        widths.append(256 if width == 0 else width)
        offset += 16
    assert {16, 24, 32, 256} <= set(widths)

    server, _state = start_server()
    try:
        status, body, headers = call(server, "GET", "/favicon.ico")
        assert status == 200
        assert headers["Content-Type"] == "image/x-icon"
        assert body[:4] == b"\x00\x00\x01\x00"
        assert body == icon
    finally:
        server.shutdown()


def test_other_websites_cannot_call_the_app():
    server, _state = start_server()
    try:
        status, _body, _headers = call(
            server,
            "POST",
            "/api/open",
            b"%PDF",
            {"Content-Type": "application/pdf", "Origin": "https://evil.example"},
        )
        assert status == 403
    finally:
        server.shutdown()
