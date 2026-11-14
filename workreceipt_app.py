#!/usr/bin/env python3
"""WorkReceipt local app. Start with:  python3 workreceipt_app.py
Serves the UI on 127.0.0.1 only. Session data is read from disk and never leaves this computer."""
import argparse, json, mimetypes, os, secrets, sys, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app_core as core

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
TOKEN = secrets.token_urlsafe(24)
PORT = 8765


class H(BaseHTTPRequestHandler):
    server_version = "WorkReceipt"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _send(self, code, body, ctype="application/json", extra=None):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str))

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "bad host", "text/plain")
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            html = open(os.path.join(UI, "index.html"), encoding="utf-8").read().replace("__TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                          "frame-src 'self'; connect-src 'self'; font-src 'self'"})
        if path == "/api/state":
            return self._state()
        if path.startswith("/report/"):
            return self._report_file(path[len("/report/"):])
        f = os.path.normpath(os.path.join(UI, path.lstrip("/")))
        if f.startswith(UI + os.sep) and os.path.isfile(f):
            return self._send(200, open(f, "rb").read(), mimetypes.guess_type(f)[0] or "application/octet-stream")
        self._send(404, "not found", "text/plain")

    def _report_file(self, name):
        """Serve only files this app has exported (listed in history), sandboxed for inline preview."""
        for rec in core.history():
            for key in ("html", "pdf"):
                p = rec.get(key)
                if p and os.path.basename(p) == os.path.basename(name) and os.path.isfile(p):
                    ct = "application/pdf" if p.endswith(".pdf") else "text/html; charset=utf-8"
                    return self._send(200, open(p, "rb").read(), ct,
                                      {"Content-Security-Policy": "sandbox allow-same-origin; default-src 'none'; style-src 'unsafe-inline'"}
                                      if key == "html" else None)
        self._send(404, "not found", "text/plain")

    def _state(self):
        s = core.load_settings()
        projects = core.discover(s["claude_dir"])
        wk = core.weekly(projects)
        for p in projects:
            p.pop("mtimes", None)
        self._json(200, {"settings": s, "projects": projects, "weekly": wk, "history": core.history()[::-1],
                         "version": core.VERSION, "chrome": bool(core.chrome_path()), "claude_dir_ok": os.path.isdir(os.path.join(s["claude_dir"], "projects"))})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-WR-Token") != TOKEN:
            return self._send(403, "forbidden", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                return self._json(413, {"error": "request too large"})
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "invalid JSON"})
        try:
            if self.path == "/api/preview":
                return self._json(200, core.summary(core.build(data)))
            if self.path == "/api/render":
                return self._json(200, {"html": core.render_preview(data, data.get("titles"))})
            if self.path == "/api/export":
                r = core.export(data, data.get("approved"), data.get("titles"))
                r.pop("html", None)
                return self._json(200 if r.get("ok") else 409, r)
            if self.path == "/api/reveal":
                # Local-only, one value, only on an explicit confirmed request. Never cached, never logged.
                if data.get("confirm") is not True:
                    return self._json(400, {"error": "confirmation required"})
                r = core.reveal(data, data.get("id"))
                return self._send(200, json.dumps(r), "application/json")
            if self.path == "/api/settings":
                return self._json(200, core.save_settings(data))
        except core.NotFound:
            return self._json(404, {"error": "That detection no longer exists. The source may have changed or been removed; reload the project."})
        except core.UserError as ex:                  # messages written by this program only
            return self._json(400, {"error": str(ex)})
        except Exception:                             # never echo exception text: it can contain log content
            return self._json(500, {"error": "Something went wrong. Nothing was exported."})
        self._json(404, {"error": "unknown endpoint"})


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorkReceipt local app")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)
    srv = None
    for port in range(a.port, a.port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    if not srv:
        print("error: no free port", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"WorkReceipt running at {url}  (local only; press Ctrl+C to stop)")
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
