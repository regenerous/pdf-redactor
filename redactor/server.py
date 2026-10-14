"""Local-only HTTP server for the redaction window."""

from __future__ import annotations

import json
import threading
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from redactor import __version__
from redactor.engine import DocumentError, DocumentSession, redacted_filename

MAX_JSON_BYTES = 1024 * 1024


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.session: DocumentSession | None = None
        self.image_cache: OrderedDict[tuple, bytes] = OrderedDict()

    def replace(self, session: DocumentSession) -> None:
        previous = self.session
        self.session = session
        self.image_cache.clear()
        if previous is not None:
            previous.close()


def static_root() -> Path:
    candidates: list[Path] = []
    import sys

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        candidates.append(Path(meipass) / "redactor" / "static")
    candidates.append(Path(__file__).resolve().parent / "static")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[-1]


def save_to_path(session: DocumentSession, path: str) -> str:
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise DocumentError("Choose a folder for the copy.")
    if not target.name.lower().endswith(".pdf"):
        target = target.with_name(target.name + ".pdf")
    if not target.parent.is_dir():
        raise DocumentError("That folder doesn't exist.")
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise DocumentError("That file couldn't be replaced.") from exc
        if existing == session.data:
            raise DocumentError("That is the original file. Save the copy under a new name.")
    data = session.export_pdf()
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise DocumentError("The copy couldn't be saved there.") from exc
    return str(target)


class Handler(BaseHTTPRequestHandler):
    state: AppState
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def _route(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if parsed.path == "/favicon.ico":
                self._favicon()
                return
            if method == "GET" and parsed.path in ("/", "/index.html", "/app.css", "/app.js"):
                self._serve_static(parsed.path)
                return
            if parts[:1] == ["api"] and self._blocked():
                return
            query = parse_qs(parsed.query)
            if method == "GET" and parts == ["api", "health"]:
                self._json(200, {"ok": True, "version": __version__})
                return
            if method == "GET" and parts == ["api", "session"]:
                self._session()
                return
            if method == "POST" and parts == ["api", "open"]:
                self._open()
                return
            if method == "GET" and len(parts) == 4 and parts[:2] == ["api", "pages"] and parts[3] == "words":
                self._words(parts[2])
                return
            if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "pages"]:
                self._image(parts[2], query)
                return
            if method == "POST" and parts == ["api", "redactions"]:
                self._add_redaction()
                return
            if method == "POST" and parts == ["api", "redactions", "all"]:
                self._redact_all()
                return
            if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "redactions"]:
                self._remove(parts[2])
                return
            if method == "POST" and parts == ["api", "save"]:
                self._save()
                return
            self._json(404, {"error": "That page isn't part of PDF Redactor."})
        except DocumentError as exc:
            self._json(400, {"error": exc.message})
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "Something went wrong. Try that again."})

    def _blocked(self) -> bool:
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site and fetch_site not in ("same-origin", "none"):
            self._json(403, {"error": "Blocked."})
            return True
        origin = self.headers.get("Origin")
        if not origin:
            return False
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        allowed = {f"http://{host}", f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if origin not in allowed:
            self._json(403, {"error": "Blocked."})
            return True
        return False

    def _favicon(self) -> None:
        icon = static_root() / "icon.ico"
        if not icon.is_file():
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = icon.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/x-icon")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        file_path = static_root() / name
        if not file_path.is_file():
            self._json(404, {"error": "The app files are missing."})
            return
        content_type = {
            "index.html": "text/html; charset=utf-8",
            "app.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
        }[name]
        data = file_path.read_bytes()
        if name == "index.html":
            data = data.replace(b"__APP_VERSION__", __version__.encode("ascii"))
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _session(self) -> None:
        with self.state.lock:
            session = self.state.session
            payload = session.snapshot() if session is not None else {"open": False}
        self._json(200, payload)

    def _open(self) -> None:
        data = self._read_body(100 * 1024 * 1024, "This PDF is larger than 100 MB.")
        raw_name = self.headers.get("X-Filename", "")
        name = unquote(raw_name) if raw_name else "document.pdf"
        session = DocumentSession(data, name)
        with self.state.lock:
            self.state.replace(session)
            payload = session.snapshot()
        self._json(200, payload)

    def _words(self, page_text: str) -> None:
        page = self._page_index(page_text)
        with self.state.lock:
            payload = self._require().words_for_display(page)
        self._json(200, payload)

    def _image(self, page_text: str, query: dict[str, list[str]]) -> None:
        page = self._page_index(page_text)
        raw_scale = query.get("scale", ["2"])[0]
        try:
            scale = round(float(raw_scale), 2)
        except ValueError:
            scale = 2.0
        with self.state.lock:
            session = self._require()
            doc_id = query.get("doc", [session.doc_id])[0]
            if doc_id != session.doc_id:
                raise DocumentError("Open the PDF again.")
            key = (session.doc_id, page, scale)
            cached = self.state.image_cache.get(key)
            if cached is None:
                cached = session.render_png(page, scale)
                self.state.image_cache[key] = cached
                while len(self.state.image_cache) > 12:
                    self.state.image_cache.popitem(last=False)
            else:
                self.state.image_cache.move_to_end(key)
            image = cached
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(image)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(image)

    def _add_redaction(self) -> None:
        payload = self._json_body()
        with self.state.lock:
            session = self._require()
            _item, remaining = session.add_area(
                self._payload_page(payload),
                payload.get("x0"),
                payload.get("y0"),
                payload.get("x1"),
                payload.get("y1"),
                payload.get("text"),
                str(payload.get("color") or "#000000"),
            )
            response = {"remaining": remaining, **session.activity()}
        self._json(200, response)

    def _redact_all(self) -> None:
        payload = self._json_body()
        with self.state.lock:
            session = self._require()
            added = session.redact_all(str(payload.get("text") or ""), str(payload.get("color") or "#000000"))
            response = {"added": added, **session.activity()}
        self._json(200, response)

    def _remove(self, redaction_id: str) -> None:
        with self.state.lock:
            session = self._require()
            session.remove(redaction_id)
            response = session.activity()
        self._json(200, response)

    def _save(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self._read_body(MAX_JSON_BYTES, "That request was too large.") if length else b""
        with self.state.lock:
            session = self._require()
            if body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DocumentError("The copy couldn't be saved.") from exc
                if not isinstance(payload, dict):
                    raise DocumentError("The copy couldn't be saved.")
                path = payload.get("path")
                if path:
                    saved = save_to_path(session, str(path))
                    self._json(200, {"saved": saved})
                    return
            data = session.export_pdf()
            filename = redacted_filename(session.name)
        ascii_name = "".join(character if 32 <= ord(character) < 127 and character not in '"\\' else "_" for character in filename)
        disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", disposition)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _require(self) -> DocumentSession:
        if self.state.session is None:
            raise DocumentError("Open a PDF first.")
        return self.state.session

    def _page_index(self, page_text: str) -> int:
        try:
            page = int(page_text)
        except ValueError as exc:
            raise DocumentError("That page is not in this PDF.") from exc
        return page

    def _payload_page(self, payload: dict) -> int:
        try:
            page = payload["page"]
        except (KeyError, TypeError) as exc:
            raise DocumentError("That page is not in this PDF.") from exc
        if isinstance(page, bool) or not isinstance(page, int):
            raise DocumentError("That page is not in this PDF.")
        return page

    def _json_body(self) -> dict:
        body = self._read_body(MAX_JSON_BYTES, "That request was too large.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DocumentError("That redaction couldn't be read.") from exc
        if not isinstance(payload, dict):
            raise DocumentError("That redaction couldn't be read.")
        return payload

    def _read_body(self, limit: int, too_large: str) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise DocumentError("The upload was incomplete.")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise DocumentError("The upload was incomplete.") from exc
        if length < 0:
            raise DocumentError("The upload was incomplete.")
        if length > limit:
            raise DocumentError(too_large)
        data = self.rfile.read(length)
        if len(data) != length:
            raise DocumentError("The upload was incomplete.")
        return data

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def create_server(port: int = 0) -> tuple[ThreadingHTTPServer, AppState]:
    state = AppState()

    class BoundHandler(Handler):
        pass

    BoundHandler.state = state
    server = ThreadingHTTPServer(("127.0.0.1", port), BoundHandler)
    server.daemon_threads = True
    return server, state
