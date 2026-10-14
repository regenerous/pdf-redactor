"""Open PDF Redactor in its own window."""

from __future__ import annotations

import argparse
import threading
import webbrowser

from redactor.server import create_server


class SaveDialog:
    """Native save dialog used by the portable Windows app."""

    def choose_save_path(self, suggested: str) -> str:
        import webview

        if not webview.windows:
            return ""
        chosen = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested or "redacted.pdf",
            file_types=("PDF files (*.pdf)",),
        )
        if not chosen:
            return ""
        if isinstance(chosen, (list, tuple)):
            return str(chosen[0]) if chosen else ""
        return str(chosen)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Redact text and regions in a PDF.")
    parser.add_argument("--port", type=int, default=47321)
    parser.add_argument("--no-window", action="store_true", help="Serve the app without opening a window.")
    parser.add_argument("--browser", action="store_true", help="Open the app in a browser instead of a window.")
    args = parser.parse_args(argv)

    server = None
    port = args.port
    for candidate in range(args.port, args.port + 20):
        try:
            server, _state = create_server(candidate)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("PDF Redactor could not start. Another copy may already be open.")

    thread = threading.Thread(target=server.serve_forever, name="pdf-redactor", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    print(f"PDF Redactor is running at {url}", flush=True)
    try:
        if args.no_window:
            threading.Event().wait()
        elif args.browser:
            webbrowser.open(url)
            threading.Event().wait()
        else:
            _open_window(url)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _open_window(url: str) -> None:
    try:
        import webview
    except Exception:
        webbrowser.open(url)
        threading.Event().wait()
        return
    webview.create_window(
        "PDF Redactor",
        url,
        width=1280,
        height=840,
        min_size=(960, 680),
        js_api=SaveDialog(),
    )
    webview.start()


if __name__ == "__main__":
    main()
