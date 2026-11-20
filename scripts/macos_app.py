"""Launch the REAL WorkReceipt desktop app (source checkout, and the packaged .app when it exists) against the temp sandbox, then drive the same
client workflow through its live HTTP routes, so the PDF is produced by the app's own WKWebView and read back by PDFKit. macOS only.
SYNTHETIC data only. The app's window contents are not inspected (that would need Screen Recording permission); see docs/MAC_VALIDATION.md."""
import json, os, re, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wrv
from wrv import check, need, record, Failure
import buildinfo

ROOT = os.environ["WRV_ROOT"]
os.environ["WORKRECEIPT_HOME"] = os.path.join(ROOT, "home")
os.environ["WORKRECEIPT_CLAUDE_DIR"] = os.path.join(ROOT, "claude")
PACKAGED = os.environ.get("WR_APP_BIN") or os.path.join(wrv.REPO, "dist", "WorkReceipt.app", "Contents", "MacOS", "WorkReceipt")


def listeners(pid):
    r = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN", "-Fn"], capture_output=True, text=True, timeout=20)
    return [ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n")]


def window_of(pid):
    from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID
    best = None
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID) or []:
        if int(w.get("kCGWindowOwnerPID", -1)) == pid and int(w.get("kCGWindowLayer", 9)) == 0:
            b = w.get("kCGWindowBounds") or {}
            if best is None or b.get("Width", 0) * b.get("Height", 0) > best[0] * best[1]:
                best = (b.get("Width", 0), b.get("Height", 0), bool(w.get("kCGWindowIsOnscreen")))
    return best


def run_app(label, cmd, ctx, required):
    import app_core as core, pdfkit_check as pk
    log = os.path.join(ROOT, "logs"); os.makedirs(log, exist_ok=True)
    out = open(os.path.join(log, label.replace(" ", "_") + ".log"), "w")
    diag = os.path.join(ctx.home, "desktop-diag.json")
    if os.path.exists(diag):
        os.remove(diag)
    p = subprocess.Popen(cmd, cwd=wrv.REPO, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    L = label + ": "
    state = {}

    def launched():
        t0 = time.time()
        while time.time() - t0 < 90:
            if p.poll() is not None:
                tail = open(out.name, errors="replace").read()[-300:].replace("\n", " | ")
                raise Failure(f"the app exited during start-up (code {p.returncode}); log tail: {tail}")
            try:
                d = json.load(open(diag))
                if d.get("available") and d.get("shown"):
                    state["diag"] = d
                    return f"native window shown (pywebview {d.get('pywebview')}, app {d.get('version')})"
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        raise Failure("no native window within 90s. This needs a logged-in desktop session (not SSH) with the screen unlocked")
    ok = check(L + "app launches and the native window is shown", launched, required)
    try:
        if not ok:
            return

        def socket_ok():
            ls = listeners(p.pid)
            need(ls, "the app is not listening on any TCP port")
            need(all(a.startswith("127.0.0.1:") or a.startswith("[::1]:") for a in ls), f"the app listens on a non-loopback address: {ls}")
            state["port"] = int(ls[0].rsplit(":", 1)[1])
            return f"loopback only ({', '.join(ls)})"
        if not check(L + "app serves on loopback only", socket_ok, required):
            return
        base = f"http://127.0.0.1:{state['port']}"
        api = wrv.Api(base)

        def window():
            w = window_of(p.pid)
            for _ in range(30):  # the window server can report 0x0 for a moment after "shown"; poll, same strict assertion
                if w and w[0] >= 940 and w[1] >= 620:
                    break
                time.sleep(0.5); w = window_of(p.pid)
            need(w is not None, "no window owned by the app process")
            need(w[0] >= 940 and w[1] >= 620, f"window is {w[0]:.0f}x{w[1]:.0f}, smaller than the app minimum")
            return f"{w[0]:.0f}x{w[1]:.0f} window, on screen: {w[2]}"
        check(L + "a real macOS window exists at the expected size", window, required)

        def st():
            c, raw = api.get("/api/state"); s = json.loads(raw)
            need(s["version"] == core.VERSION, f"app reports version {s['version']}, expected {core.VERSION}")
            same, why = buildinfo.compare(s.get("build"), buildinfo.source_fingerprint(wrv.REPO))
            need(same, "the RUNNING app is not built from this checkout's source: " + why + ". " + buildinfo.STALE_HELP)
            need(os.path.realpath(s["home"]) == os.path.realpath(ctx.home), "the app is NOT using the sandbox data folder")
            need(os.path.realpath(s["settings"]["out_dir"]).startswith(os.path.realpath(ROOT) + os.sep), "the app's reports folder is outside the sandbox")
            c, r = api.post("/api/native/status", {})
            need(r.get("available") is True and r.get("shown") is True, f"native bridge status: {r}")
            return f"v{s['version']}, {why}; sandbox data folder, native bridge available"
        check(L + "app uses the sandbox and reports native status", st, required)

        def csp():
            import urllib.request
            h = urllib.request.urlopen(base + "/").headers
            need("default-src 'self'" in (h.get("Content-Security-Policy") or ""), "no restrictive Content-Security-Policy on the app page")
        check(L + "app page is served with a restrictive CSP", csp, required)
        wrv.workflow(api, ctx, label, pk.inspect, producer_re=r"quartz|macos|webkit")
    finally:
        def shutdown():
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(40):
                if p.poll() is not None:
                    break
                time.sleep(0.25)
            else:
                os.killpg(p.pid, signal.SIGKILL)
                raise Failure("the app did not exit after SIGTERM (had to be killed)")
            time.sleep(0.5)
            need(subprocess.run(["pgrep", "-g", str(p.pid)], capture_output=True).returncode != 0, "processes from the app are still running")
            if "port" in state:
                import socket
                s = socket.socket(); s.settimeout(1)
                try:
                    need(s.connect_ex(("127.0.0.1", state["port"])) != 0, "the app's port is still open after exit")
                finally:
                    s.close()
            return "exited on SIGTERM; no process or listening port left"
        if p.poll() is None or ok:
            check(L + "app shuts down cleanly (no leftover process or port)", shutdown, required)
        out.close()


def main():
    if sys.platform != "darwin":
        record("live app: launch, window, PDF export", "BLOCKED", "requires macOS (the desktop shell needs WKWebView)")
        return 0
    check("sandbox before launching the app: app data and Claude folder inside the sandbox", lambda: wrv.assert_isolated(ROOT, reports=False))
    ws = wrv.make_workspace(ROOT)
    ctx = wrv.Ctx(ws)
    check("live app: workspace and reports folder are inside the sandbox", lambda: wrv.assert_isolated(ROOT))
    run_app("source app", [sys.executable, os.path.join(wrv.REPO, "desktop", "main.py")], ctx, True)
    if os.path.isfile(PACKAGED) and os.access(PACKAGED, os.X_OK):
        def packaged_is_current():
            ok, msg, _ = buildinfo.check_app(PACKAGED, wrv.REPO, timeout=20)
            need(ok, "STALE packaged app, not a release candidate: " + msg + ". " + buildinfo.STALE_HELP)
            return msg
        if check("packaged app: built from this checkout's current source (not a stale build)", packaged_is_current, True):
            run_app("packaged app", [PACKAGED], ctx, True)               # a stale app is not launched: its refusals would only mislead
    else:
        record("packaged app: launch and PDF export", "SKIP", "dist/WorkReceipt.app not built here (run desktop/build_macos.sh, or set WR_APP_BIN)", required=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                                       # noqa: BLE001
        record("live app harness ran to completion", "FAIL", f"{type(e).__name__}: {e}")
        sys.exit(0)
