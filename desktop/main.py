#!/usr/bin/env python3
"""WorkReceipt desktop shell: native window around the local engine. Local only."""
import os, subprocess, sys, threading, webbrowser
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import workreceipt_app as app  # noqa: E402
import app_core as core  # noqa: E402

MIN_SIZE = (960, 640)


def start_server():
    """Bind to a free loopback port; return (server, url)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def stop_server(srv):
    srv.shutdown()
    srv.server_close()


class Api:
    """Exposed to the page as window.pywebview.api. Paths only; never file contents."""
    window = None

    def pick_folder(self):
        import webview
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None

    def reveal(self, path):
        # Only reveal files this app exported.
        known = {p for rec in core.history() for p in (rec.get("html"), rec.get("pdf")) if p}
        if path in known and os.path.exists(path) and sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
            return True
        return False


def main():
    import webview
    srv, url = start_server()
    api = Api()
    win = webview.create_window("WorkReceipt", url, js_api=api, width=1180, height=760, min_size=MIN_SIZE)
    api.window = win
    win.events.closed += lambda: stop_server(srv)
    try:
        webview.start()
    finally:
        try:
            stop_server(srv)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
