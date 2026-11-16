#!/usr/bin/env python3
"""WorkReceipt desktop shell: native window around the local engine. Local only."""
import atexit, os, shutil, subprocess, sys, threading
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


class Native:
    """Native actions served to the page over the local HTTP channel (/api/native/*), independent of the WebView's JS bridge.
    Holds the pywebview Window privately; every method returns plain JSON-able data and never raises into the HTTP layer."""

    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._ready = threading.Event()

    def attach(self, window):
        self._window = window
        def shown():
            self._ready.set()
            try:                                          # decisive diagnostic: ~/Library/Application Support/WorkReceipt/desktop-diag.json
                import json
                with open(os.path.join(core._home(), "desktop-diag.json"), "w") as f:
                    json.dump(self.status(), f, indent=1)
            except Exception:
                pass
        try:
            window.events.shown += shown
        except Exception:
            self._ready.set()

    def status(self):
        import platform
        try:
            import webview
            ver = getattr(webview, "__version__", "?")
        except Exception as e:
            return {"available": False, "reason": "pywebview could not be imported: " + type(e).__name__}
        return {"available": self._window is not None and self._ready.is_set(), "window": self._window is not None, "shown": self._ready.is_set(),
                "pywebview": ver, "platform": sys.platform, "python": platform.python_version(), "version": core.VERSION}

    def pick_folder(self, start=None):
        """-> {ok, path|None, cancelled} or {ok: False, error}. One dialog at a time."""
        if self._window is None or not self._ready.is_set():
            return {"ok": False, "error": "The window is still starting. Try again in a moment."}
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": "A folder dialog is already open."}
        try:
            import webview
            kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
            d = start if isinstance(start, str) and os.path.isdir(start) else ""
            r = self._window.create_file_dialog(kind, directory=d)
            return {"ok": True, "path": str(r[0]), "cancelled": False} if r else {"ok": True, "path": None, "cancelled": True}
        except Exception as e:
            return {"ok": False, "error": "The folder dialog could not be opened (" + type(e).__name__ + ")."}
        finally:
            self._lock.release()

    # The page sends only a report FILE NAME; core.resolve_report maps it to a path from the app's own history.
    def open(self, name, kind="html"):
        return self._launch(name, kind, [])

    def reveal(self, name, kind="html"):
        return self._launch(name, kind, ["-R"])

    def _launch(self, name, kind, flags):
        try:
            path = core.resolve_report(name, kind)
        except core.UserError as e:
            return {"ok": False, "error": str(e)}
        try:
            run_opener(flags + [path])
        except OpenError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}


class OpenError(RuntimeError):
    pass


def run_opener(args):
    """macOS `open` (default browser for .html, `-R` reveals in Finder). Raises OpenError with a user-readable message."""
    exe = "/usr/bin/open" if sys.platform == "darwin" else (shutil.which("xdg-open") or "")
    if not exe or (args and args[0] == "-R" and sys.platform != "darwin"):
        raise OpenError("Opening files is only supported in the macOS app")
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise OpenError("macOS could not open the file (the open command failed to run)")
    if r.returncode != 0:
        raise OpenError("macOS could not open the file. Try Show in Finder, or open it from your reports folder")


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
        return lambda: win.run_js(f"window.wrCommand({cmd!r})")
    return [m.Menu(title, [m.MenuSeparator() if i is None else m.MenuAction(i[0], act(i[1])) for i in items]) for title, items in MENU]


def _drop_handler(win):
    """Dropped folders: the path is only visible to Python (DOM drop event), so hand it to the page via run_js."""
    try:
        from webview.dom import DOMEventHandler
        def on_drop(e):
            files = (e.get("dataTransfer") or {}).get("files") or []
            p = files[0].get("pywebviewFullPath") if files else None
            if p:
                win.run_js(f"window.wrDropped({p!r})")
        win.events.loaded += lambda: win.dom.document.events.drop.__iadd__(DOMEventHandler(on_drop, True, True))
    except Exception:
        pass            # drag-and-drop is optional; Add project always works


def main():
    import webview
    if sys.platform == "darwin":
        from desktop import pdf_mac
        core.PDF_BACKEND = pdf_mac.render_pdf        # packaged PDF export: system WebKit, no Chrome required
        core.PDF_INSPECTOR = pdf_mac.extract_facts    # Client-Safe Mode: PDFKit reads the finished PDF back before it is shared
    srv, url = start_server()
    atexit.register(lambda: stop_server(srv))
    nat = Native()
    app.NATIVE = nat
    win = webview.create_window("WorkReceipt", url + "?shell=desktop", width=1180, height=760, min_size=MIN_SIZE)
    nat.attach(win)
    _drop_handler(win)
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
