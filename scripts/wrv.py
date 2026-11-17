"""Shared helpers for the automated macOS validation (scripts/validate_macos.sh). SYNTHETIC data only.

Nothing here reads a real ~/.claude, repository, report or credential. Every "secret" is a made-up pattern. The harness refuses to run
unless app data, the Claude folder and the reports folder all resolve inside the validation sandbox (assert_isolated).
Python >= 3.9 syntax only (the macOS system python is old)."""
import hashlib, json, os, re, sys, tempfile, time, traceback, urllib.error, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

RESULTS = os.environ.get("WRV_RESULTS")
SELFTEST = os.environ.get("WRV_SELFTEST") == "1"          # Linux dry run of the logic: Chrome/poppler stand in for WebKit/PDFKit. NOT macOS evidence.
TAG = " [linux selftest: not macOS evidence]" if SELFTEST else ""


class Failure(AssertionError):
    pass


def need(cond, msg):
    if not cond:
        raise Failure(msg)


def record(name, status, detail="", required=True):
    row = {"name": name + (TAG if SELFTEST and status == "PASS" else ""), "status": status, "detail": str(detail)[:500], "required": bool(required)}
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    print(f"{status:7} {'[req] ' if required else '[opt] '}{row['name']}" + (f" - {row['detail']}" if row["detail"] else ""), flush=True)


def check(name, fn, required=True):
    """Run fn; PASS unless it raises. A string return value becomes the detail line."""
    try:
        r = fn()
    except Failure as e:
        record(name, "FAIL", str(e), required)
        return False
    except Exception as e:                                       # noqa: BLE001
        record(name, "FAIL", f"{type(e).__name__}: {e}", required)
        traceback.print_exc(file=sys.stderr)
        return False
    record(name, "PASS", r if isinstance(r, str) else "", required)
    return True


def snapshot(paths):
    """Hash of (relative name, size, mtime) for every file under each path. Used to prove real user data was not touched."""
    h = hashlib.sha256()
    for base in paths:
        for dp, dn, fn in os.walk(base):
            dn.sort()
            for f in sorted(fn):
                p = os.path.join(dp, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                h.update(f"{p}\0{st.st_size}\0{int(st.st_mtime)}\n".encode())
        h.update(f"[{base}]\n".encode())
    return h.hexdigest()


def real_dirs():
    """Where the REAL app keeps data and reports (computed with the sandbox variables removed)."""
    saved = {k: os.environ.pop(k, None) for k in ("WORKRECEIPT_HOME", "WORKRECEIPT_CLAUDE_DIR")}
    try:
        import app_core as core
        return [core.HOME_DIR, core.DEFAULT_OUT]
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ---------------------------------------------------------------- sandbox + synthetic workspace
def assert_isolated(root, reports=True):
    import app_core as core
    s = core.load_settings()
    base = os.path.realpath(root) + os.sep
    for label, p in (("app data folder", core._home()), ("Claude folder", s["claude_dir"])) + ((("reports folder", s["out_dir"]),) if reports else ()):
        need(os.path.realpath(p).startswith(base), f"{label} is outside the validation sandbox")
    return "app data, Claude folder and reports folder are all inside the sandbox"


def make_workspace(root):
    """Hostile synthetic workspace (private terms, fake credentials, internal hosts) from the Client-Safe test suite, built inside root."""
    os.makedirs(os.path.join(root, "tmp"), exist_ok=True)
    tempfile.tempdir = os.path.join(root, "tmp")
    from test_client_safe import hostile_ws
    ws = hostile_ws()
    import app_core as core
    core.save_settings({"onboarded": True})
    return ws


class Ctx:
    def __init__(self, ws):
        import app_core as core
        from test_client_safe import PERIOD
        from test_phase1 import disp
        self.ws, self.core = ws, core
        self.o = dict({"repo": ws.repo}, **PERIOD)
        b = core.build(self.o)
        self.ap = disp(b["findings"])
        self.commits = [c[0] for c in b["ctx"]["commits"]]
        self.out = core.load_settings()["out_dir"]
        self.home = core._home()

    def files(self):
        return sorted(os.listdir(self.out)) if os.path.isdir(self.out) else []


class Api:
    """The real HTTP routes, with the page token the UI would use."""
    def __init__(self, base):
        self.base = base.rstrip("/")
        html = urllib.request.urlopen(self.base + "/", timeout=30).read().decode()
        m = re.search(r'name="wr-token" content="([^"]+)"', html)
        need(m is not None, "the app page carries no session token")
        self.token = m.group(1)

    def _go(self, req, timeout):
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def get(self, path):
        code, body = self._go(urllib.request.Request(self.base + path), 60)
        return code, body

    def post(self, path, body, token="auto", host=None, timeout=240):
        h = {"Content-Type": "application/json"}
        if token == "auto":
            h["X-WR-Token"] = self.token
        elif token:
            h["X-WR-Token"] = token
        if host:
            h["Host"] = host
        code, raw = self._go(urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=h, method="POST"), timeout)
        try:
            return code, json.loads(raw or b"{}")
        except ValueError:
            return code, {"_raw": raw.decode("utf-8", "replace")[:200]}


def review_via_api(api, ctx):
    """Privacy-Center review of every high-severity finding, using the finding ids of the app UNDER TEST. Ids are salted per process
    (app_core._SALT) so an approval computed in the harness process can never apply to a separately launched app; the live apps
    therefore get their ids from their own /api/preview, exactly as the UI does."""
    c, r = api.post("/api/preview", dict(ctx.o))
    need(c == 200 and isinstance(r.get("findings"), list), f"the app's preview refused (HTTP {c})")
    ctx.ap = {d["id"]: "unsure" for f in r["findings"] if f.get("severity") == "high" for d in f.get("detections", []) if not d.get("suppressed")}
    need(ctx.ap, "the synthetic workspace produced no high-severity findings to review (test setup problem)")
    return len(ctx.ap)


def body(ctx, draft, **extra):
    return dict(ctx.o, draft=draft, approved=extra.pop("approved", ctx.ap), **extra)


def leaks(text):
    from test_client_safe import CANARIES
    low = text.lower()
    sq = re.sub(r"[^a-z0-9]+", "", low)
    return [k for k, v in CANARIES.items() if v.lower() in low or re.sub(r"[^a-z0-9]+", "", v.lower()) in sq]


def flat(x):
    return json.dumps(x, default=str)


# ---------------------------------------------------------------- the complete client workflow (shared by the in-process and live-app runs)
TYPED = "Rebuilt the invoice screen so customers can pay online"


def base_draft(ctx):
    from test_client_safe import item
    return {"project_name": "Billing Revamp", "client_name": "Initech", "include_prepared_by": True, "prepared_by": "Zed Author",
            "items": [item(TYPED, status="delivered", commits=[ctx.commits[0]]), item("Started the reporting dashboard")],
            "verification": {"mode": "auto"}}


def workflow(api, ctx, label, inspect_pdf, producer_re=None):
    """preview -> approve -> export HTML+PDF, then every negative path. Records PASS/FAIL per behaviour. Returns the exported artifacts."""
    import pdfkit_check as pk
    art = {}
    d = base_draft(ctx)
    L = label + ": "

    def happy():
        n = review_via_api(api, ctx)
        c, pv = api.post("/api/client/preview", body(ctx, d)); need(c == 200 and pv.get("ok") and pv.get("html"), "preview was refused")
        need(pv.get("pending_findings") == 0, f"preview still lists {pv.get('pending_findings')} unreviewed findings after the review")
        c, ap = api.post("/api/client/approve", body(ctx, d, confirm={"privacy_review": True, "content_hash": pv["content_hash"]}))
        need(c == 200 and ap.get("token"), f"approval was refused: HTTP {c} reason={ap.get('reason')} failed={ap.get('failed')} missing={len(ap.get('missing') or [])}")
        c, ex = api.post("/api/client/export", body(ctx, d, token=ap["token"], pdf=True))
        need(c == 200 and ex.get("ok"), f"export refused: {ex.get('reason')} {ex.get('failed')}")
        need(not ex.get("pdf_failed"), f"PDF was not produced: {ex.get('pdf_error')}")
        for k in ("html_path", "pdf_path"):
            need(ex.get(k) and os.path.isfile(ex[k]), f"{k} missing")
            need(os.path.realpath(ex[k]).startswith(os.path.realpath(ctx.out) + os.sep), f"{k} is outside the sandbox reports folder")
        need(all(os.path.basename(ex[k]).startswith("client-report-Billing-Revamp-") for k in ("html_path", "pdf_path")), "unexpected file names")
        art.update(pv=pv, ap=ap, ex=ex, html=open(ex["html_path"], encoding="utf-8").read(), pdf=ex["pdf_path"])
        need(art["html"] == pv["html"], "the exported HTML is not byte-identical to the preview")
        return f"{n} findings reviewed through the app's own API; HTML + PDF written; export HTML identical to the preview"
    if not check(L + "approve and export HTML + PDF", happy):
        return art

    def hist():
        rec = [r for r in ctx.core.history() if r.get("html") == art["ex"]["html_path"]]
        need(len(rec) == 1 and rec[0].get("mode") == "client", "history record missing or not marked client")
    check(L + "export recorded as a client report", hist)

    facts = {}

    def native_pdf():
        info = inspect_pdf(art["pdf"])
        facts.update(info)
        if producer_re:
            need(re.search(producer_re, info["meta"].get("Producer", ""), re.I), f"PDF producer is {info['meta'].get('Producer')!r}, not the expected native writer")
        return f"{info['backend']}: {info['pages']} page(s), producer {info['meta'].get('Producer')!r}"
    check(L + "PDF was written by the expected engine", native_pdf)

    def pdfcheck():
        fails, info = pk.verify(art["pdf"], art["html"], expect=[TYPED, "Billing Revamp", "Initech", "Zed Author", "Supported by Git history (1 commit)"], title="Billing Revamp")
        need(not fails, "independent PDF check failed: " + ", ".join(fails))
        return f"{info['backend']}: text, metadata, annotations, hidden-content checks clean ({info['pages']} page(s), {info['annotations']} annotations)"
    check(L + "PDF text, metadata, annotations and hidden content (independent check)", pdfcheck)

    def conf():
        bad = {}
        bad["html"] = leaks(art["html"])
        bad["pdf text"] = leaks(facts.get("text", ""))
        bad["pdf metadata"] = leaks(flat(facts.get("meta")))
        bad["file names"] = leaks(" ".join(ctx.files()))
        bad["api responses"] = leaks(flat([art["pv"], art["ap"], art["ex"]]).replace(ctx.ws.root, ""))
        hp = os.path.join(ctx.home, "history.json")
        bad["history"] = leaks(open(hp, encoding="utf-8").read()) if os.path.exists(hp) else []
        bad = {k: v for k, v in bad.items() if v}
        need(not bad, "confidential strings reached: " + "; ".join(f"{k}: {v}" for k, v in bad.items()))
        return "no private canary (credential, internal host/service, private repo, path, user, unapproved client, file or commit text) in any artifact"
    check(L + "confidential technical details are excluded", conf)

    token, ch = art["ap"]["token"], art["pv"]["content_hash"]
    after_ok = ctx.files()

    def refused(c, r, reasons=("approval", "findings", "issues", "validation"), what=""):
        need(c == 409 and r.get("ok") is False and r.get("reason") in reasons, f"{what}: expected a refusal, got HTTP {c} {r.get('reason')}")
        need(ctx.files() == after_ok, "a refused export still wrote files")
        need(not leaks(flat(r)), "the refusal echoed private content")

    def edits():
        import copy
        muts = {}
        def m(name):
            def deco(fn):
                muts[name] = fn
            return deco
        @m("item wording")
        def _(x): x["items"][1]["text"] = "Started the reporting dashboard and email digests"
        @m("project name")
        def _(x): x["project_name"] = "Billing Revamp 2"
        @m("client name")
        def _(x): x["client_name"] = "Initech Ltd"
        @m("added item")
        def _(x): x["items"].append(dict(x["items"][1], text="Added a new approved item"))
        @m("removed item")
        def _(x): x["items"].pop()
        @m("status change")
        def _(x): x["items"][0]["status"] = "in_progress"
        @m("verification wording")
        def _(x): x["verification"] = {"mode": "none"}
        @m("prepared by")
        def _(x): x["prepared_by"] = "Someone Else"
        for name, fn in muts.items():
            x = copy.deepcopy(d); fn(x)
            c, r = api.post("/api/client/export", body(ctx, x, token=token, pdf=False)); refused(c, r, ("approval",), name)
        c, r = api.post("/api/client/export", dict(body(ctx, d, token=token, pdf=False), since="2026-11-02")); refused(c, r, ("approval",), "period change")
        weaker = dict(ctx.ap); weaker.pop(next(iter(weaker)))
        c, r = api.post("/api/client/export", body(ctx, d, token=token, pdf=False, approved=weaker)); refused(c, r, ("findings", "approval"), "weakened review")
        c, r = api.post("/api/client/export", body(ctx, d, token=token, pdf=False)); need(c == 200 and r.get("ok"), "the unchanged approved content should still export")
        return f"{len(muts)} content edits, a period change and a weakened review each invalidated the approval"
    if check(L + "editing after approval invalidates it (server-side)", edits):
        after_ok[:] = ctx.files()                                # the final control export above is the only expected new file

    def forged():
        flips = {"empty": "", "garbage": "forged", "wrong type": {"a": 1}, "number": 12345, "missing signature": f"{int(time.time())}.",
                 "tampered signature": token[:-1] + ("0" if token[-1] != "0" else "1"), "future timestamp": f"{int(time.time()) + 9999}.{token.split('.', 1)[1]}",
                 "other content's token": None}
        for name, t in flips.items():
            if t is None:
                x = dict(d, project_name="Another Report")
                c, pv2 = api.post("/api/client/preview", body(ctx, x)); c, ap2 = api.post("/api/client/approve", body(ctx, x, confirm={"privacy_review": True, "content_hash": pv2["content_hash"]}))
                t = ap2["token"]
            c, r = api.post("/api/client/export", body(ctx, d, token=t, pdf=False)); refused(c, r, ("approval",))
        c, r = api.post("/api/client/export", {k: v for k, v in body(ctx, d, pdf=False).items()}); refused(c, r, ("approval",))
        c, r = api.post("/api/client/approve", body(ctx, d, confirm={"privacy_review": True, "content_hash": "0" * 64})); refused(c, r, ("approval",))
        c, r = api.post("/api/client/approve", body(ctx, d, confirm={"privacy_review": False, "content_hash": ch})); need(c == 409 and not r.get("token"), "approval without the confirmation was accepted")
        c, r = api.post("/api/client/approve", body(ctx, d)); need(c == 409 and not r.get("token"), "approval without any confirmation object was accepted")
        return f"{len(flips) + 4} forged / replayed / malformed approvals refused; nothing written"
    check(L + "forged, replayed and malformed approval tokens are refused", forged)

    def blocked():
        from test_client_safe import AKIA, item
        cases = {
            "credential in item text": [item(f"Finished the upload (key {AKIA}) and the dashboard")],
            "internal URL": [item("See https://github.com/acme-private/billing-core for details")],
            "file path": [item("Edited src/ledger_oracle_sync.py today")],
            "absolute path": [item("Fixed /Users/zelda-quill/work/billing-core/src/ledger.py")],
            "private term": [item("Payroll export for Globex Corporation")],
            "markup": [item("<script>alert(1)</script> invoice screen")],
            "shell command": [item("Ran `pytest -q tests/test_ledger_oracle.py`")],
            "commit hash": [item("Landed change a1b2c3d4e5f60718293a4b5c6d7e8f9012345678")],
            "unapproved item only": [item(approved=False)],
            "no items": [],
            "delivered without evidence": [item(status="delivered")],
            "delivered with forged commit": [item(status="delivered", commits=["deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"])],
        }
        for name, items in cases.items():
            x = dict(d, items=items)
            c, pv = api.post("/api/client/preview", body(ctx, x))
            need(not pv.get("ok") and not pv.get("html"), f"{name}: the preview was not blocked")
            need(not leaks(flat(pv)), f"{name}: the preview response echoed private content")
            c, r = api.post("/api/client/approve", body(ctx, x, confirm={"privacy_review": True, "content_hash": ch})); refused(c, r)
            c, r = api.post("/api/client/export", body(ctx, x, token=token, pdf=True)); refused(c, r)
        c, r = api.post("/api/client/export", body(ctx, d, token=token, pdf=False, approved={})); refused(c, r, ("findings",))
        return f"{len(cases) + 1} unsafe drafts blocked at preview, approval and export; nothing written"
    check(L + "unsafe content and unreviewed findings block the export", blocked)

    def auth():
        for name, kw in (("no page token", {"token": None}), ("wrong page token", {"token": "wrong-token"}), ("foreign Host header", {"host": "evil.example"})):
            c, r = api.post("/api/client/export", body(ctx, d, token=ctx_token(art), pdf=False), **kw)
            need(c == 403, f"{name}: expected 403, got {c}")
        need(ctx.files() == after_ok, "a rejected request wrote files")
        return "requests without the page token, with a wrong one, or from a foreign host get 403"

    def ctx_token(a):
        return a["ap"]["token"]
    check(L + "the local API rejects unauthenticated requests", auth)

    def tmp_clean():
        left = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith("wr-client-") or n.startswith("wr-chrome-")]
        need(not left, f"temporary staging folders left behind: {len(left)}")
    check(L + "no staging files left behind", tmp_clean)
    return art
