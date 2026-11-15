#!/usr/bin/env python3
"""WorkReceipt desktop shell: native window around the local engine. Local only."""
import atexit, os, subprocess, sys, threading
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


    def open_report(self, path):
        known = {p for rec in core.history() for p in (rec.get("html"), rec.get("pdf")) if p}
        if path in known and os.path.exists(path) and sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
            return True
        return False


# (menu label, command understood by window.wrCommand in ui/app.js). Shortcuts are handled in the page (Cmd+key); the
# pywebview menu API has no accelerator column, so the shortcut is shown in the label.
MENU = [
    ("File", [("Add Project…  ⌘O", "add"), ("Refresh Projects  ⌘R", "refresh"), None, ("Preview Report  ⌘P", "preview"), ("Export Report…  ⌘E", "export")]),
    ("View", [("Overview  ⌘1", "go:overview"), ("Projects  ⌘2", "go:projects"), ("Report Studio  ⌘3", "go:studio"),
              ("Privacy Center  ⌘4", "go:privacy"), ("Reports  ⌘5", "go:reports"), ("Settings  ⌘,", "go:settings")]),
]


def build_menu(win):
    import webview.menu as m
    def act(cmd):
        return lambda: win.evaluate_js(f"window.wrCommand({cmd!r})")
    return [m.Menu(title, [m.MenuSeparator() if i is None else m.MenuAction(i[0], act(i[1])) for i in items]) for title, items in MENU]


def main():
    import webview
    if sys.platform == "darwin":
        from desktop import pdf_mac
        core.PDF_BACKEND = pdf_mac.render_pdf        # packaged PDF export: system WebKit, no Chrome required
    srv, url = start_server()
    atexit.register(lambda: stop_server(srv))
    api = Api()
    win = webview.create_window("WorkReceipt", url, js_api=api, width=1180, height=760, min_size=MIN_SIZE)
    api.window = win
    win.events.closed += lambda: stop_server(srv)
    try:
        webview.start(menu=build_menu(win))
    finally:
        try:
            stop_server(srv)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
