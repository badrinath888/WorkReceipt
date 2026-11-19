"""In-process native validation. On macOS this runs the real AppKit event loop on the main thread and drives the SAME wiring the app uses
(desktop.main.install_native_backends: WKWebView PDF export + PDFKit read-back) through the real HTTP routes. SYNTHETIC data only.
WRV_SELFTEST=1 (Linux dry run) swaps in Chrome/poppler so the scenario logic can be exercised; those runs are labelled and are not macOS evidence."""
import os, sys, tempfile, threading, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wrv
from wrv import check, need, record, Failure

ROOT = os.environ["WRV_ROOT"]
os.environ["WORKRECEIPT_HOME"] = os.path.join(ROOT, "home")                      # set before app_core is imported: the first check is then meaningful
os.environ["WORKRECEIPT_CLAUDE_DIR"] = os.path.join(ROOT, "claude")


def render_native(html, out):
    """Render HTML to PDF through the engine the app uses (WKWebView on macOS; Chrome only in the Linux selftest)."""
    import app_core as core
    if core.PDF_BACKEND is not None:
        core.PDF_BACKEND(html, out)
        return
    p = os.path.join(tempfile.gettempdir(), "wrv-tamper.html")
    open(p, "w", encoding="utf-8").write(html)
    got = core.to_pdf(p)
    need(got, "no PDF engine available")
    os.replace(got, out)


def _raw_title(path):
    """The /Title in the file's own information dictionary (read without PDFKit), '' if none."""
    import client_safe as cs, re
    data = open(path, "rb").read()
    return cs.raw_info_fields(re.sub(rb"stream\r?\n.*?\r?\nendstream", b"", data, flags=re.S)).get("Title", "")


def inject(html, frag):
    """The report HTML is minified and has no closing body tag, so append the fragment (browsers place it in the body)."""
    return html.replace("</body>", frag + "</body>") if "</body>" in html else html + frag


def run():
    import app_core as core, client_safe as cs, workreceipt_app as app
    from http.server import ThreadingHTTPServer
    import pdfkit_check as pk
    from desktop import main as dmain
    mac = sys.platform == "darwin"
    check("sandbox: app data and Claude folder resolve inside the temp sandbox before anything runs", lambda: wrv.assert_isolated(ROOT, reports=False))

    def env():
        import platform
        v = ""
        try:
            import objc
            v = " pyobjc " + objc.__version__
        except Exception:                                        # noqa: BLE001
            pass
        return f"{platform.platform()} python {platform.python_version()}{v}"
    check("environment", env, required=False)

    if mac:
        check("native backends installed (WKWebView PDF writer + PDFKit reader)", lambda: (
            need(dmain.install_native_backends() is True, "install_native_backends did nothing"),
            need(core.PDF_BACKEND is not None and core.PDF_INSPECTOR is not None, "backends not set"),
            need(core.PDF_BACKEND.__module__.endswith("pdf_mac") and core.PDF_INSPECTOR.__module__.endswith("pdf_mac"), "backends are not the pdf_mac ones"))[-1] or "same wiring as desktop/main.py")
    else:
        record("native backends installed (WKWebView PDF writer + PDFKit reader)", "BLOCKED", "not macOS (selftest uses Chrome/poppler instead)" if wrv.SELFTEST else "requires macOS", required=not wrv.SELFTEST)
    def meta_probe():
        """Which information-dictionary fields does THIS engine write? Synthetic page only; allowed values are shown, others only by length."""
        pdf = os.path.join(ROOT, "probe.pdf")
        render_native("<html><head><meta charset=utf-8><title>Work report for Initech</title></head><body><p>Synthetic probe page for the metadata diagnostic, with enough text to be selectable.</p></body></html>", pdf)
        info = pk.inspect(pdf)
        return f"{info['backend']}: " + cs.describe_metadata_diagnostics(cs.metadata_diagnostics(info["meta"], "Work report for Initech", (), [])) + f"; annotations={info['annotations']}"
    check("native: PDF information fields written by this engine (diagnostic)", meta_probe, required=False)
    ws = wrv.make_workspace(ROOT)
    ctx = wrv.Ctx(ws)
    check("synthetic workspace created; app data, Claude folder and reports folder are inside the sandbox", lambda: wrv.assert_isolated(ROOT))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = wrv.Api("http://127.0.0.1:%d" % srv.server_address[1])
    art = wrv.workflow(api, ctx, "native", pk.inspect, producer_re=r"quartz|macos|webkit" if mac else None)
    if not art:
        return
    d = wrv.base_draft(ctx)
    st = core._client_state(ctx.o, d, ctx.ap, core.load_settings())
    report, terms, ch = st["report"], st["terms"], art["pv"]["content_hash"]
    real_html = art["html"]
    out0 = ctx.files()

    def expired():
        old = cs.approval_token(ch, now=time.time() - 5 * 3600)
        c, r = api.post("/api/client/export", wrv.body(ctx, d, token=old, pdf=True))
        need(c == 409 and r.get("reason") == "approval", f"an expired approval was accepted (HTTP {c})")
        need(ctx.files() == out0, "files were written for an expired approval")
        return "a correctly signed token older than the 4h limit is refused"
    check("native: expired approval is refused", expired)

    def fail_closed():
        keep = core.PDF_INSPECTOR
        try:
            for label, fn in (("returns nothing", lambda p: None), ("raises", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))):
                core.PDF_INSPECTOR = fn
                try:
                    c, r = api.post("/api/client/export", wrv.body(ctx, d, token=art["ap"]["token"], pdf=True))
                except Exception as e:                           # noqa: BLE001
                    raise Failure(f"an inspector that {label} crashed the app instead of blocking: {type(e).__name__}")
                need(c in ((409,) if label == "returns nothing" else (409, 500)) and not r.get("ok"), f"an inspector that {label} did not block the export (HTTP {c})")
                need(ctx.files() == out0, f"files written although the PDF inspector {label}")
        finally:
            core.PDF_INSPECTOR = keep
        return "PDF read-back that returns nothing or raises blocks the export and writes nothing"
    check("native: an unverifiable PDF is never shared (fail closed)", fail_closed)

    tdir = os.path.join(ROOT, "tamper"); os.makedirs(tdir, exist_ok=True)
    inspect_native = core.PDF_INSPECTOR or cs.pdf_facts_cli

    def tamper(name, fn, expect_codes, must_flag=True):
        html = fn(real_html)
        need(html != real_html, "the tamper step changed nothing (test bug)")
        pdf = os.path.join(tdir, name + ".pdf")
        render_native(html, pdf)
        facts = inspect_native(pdf)
        app_fails = cs.validate_pdf(pdf, report, real_html, facts, terms)
        ind_fails, info = pk.verify(pdf, real_html, title="Billing Revamp")
        return app_fails, ind_fails, info

    def hidden():
        app_fails, ind, info = tamper("hidden", lambda h: inject(h, '<div style="color:#fff;font-size:1px;position:absolute">oracle-fin-01 envoy-edge-mesh Sup3rS3cret99</div>'), None)
        need(app_fails, "the product's PDF validator missed white 1px text containing private strings")
        need(ind, "the independent checker missed white 1px text containing private strings")
        return f"app validator: {','.join(app_fails)}; independent: {','.join(ind)[:90]}"
    check("native: hidden text in a real WKWebView PDF is detected", hidden)

    def title_propagation():
        """Diagnostic only: does this engine copy the HTML <title> into the PDF at all? (The first Mac run assumed it did; the product validator then saw no private title.)"""
        app_fails, ind, info = tamper("meta-html", lambda h: __import__("re").sub(r"<title>.*?</title>", "<title>oracle-fin-01 internal</title>", h, flags=16), None)
        written = _raw_title(os.path.join(tdir, "meta-html.pdf"))
        read = info["meta"].get("Title", "")
        return (f"HTML <title> written into the PDF: {'yes' if written else 'NO'}; read by {info['backend']}: {'yes' if read else 'no'}; "
                f"product validator: {','.join(app_fails) or 'clean'}; independent: {','.join(ind)[:80] or 'clean'}")
    check("native: does WKWebView copy the HTML <title> into the PDF (diagnostic)", title_propagation, required=False)

    def meta():
        """Inject private metadata INTO the real WKWebView PDF (the engine's own handling of <title> is irrelevant), then follow it through every stage:
        written to the file -> read by PDFKit -> product validator -> independent checker. Failure messages say which stage lost it (booleans only)."""
        import pdfkit_check
        base = os.path.join(tdir, "meta-base.pdf")
        render_native(real_html, base)
        facts_ok = inspect_native(base)
        need(cs.validate_pdf(base, report, real_html, facts_ok, terms) == [], "the untouched WKWebView PDF was refused by the product validator; cannot judge metadata checks")
        summary = []
        for field, value, want_ind in (("Title", "oracle-fin-01 internal", ("canary_in_metadata", "metadata_title")), ("Title", "Quarterly payroll notes", ("metadata_title",)),
                                       ("Creator", "/Users/zelda-quill/billing-core", ("metadata_creator",)), ("Creator", "Zelda's MacBook Pro", ("metadata_creator",)),
                                       ("Creator", "WorkReceipt Internal Billing", ("metadata_creator",)), ("Author", "Zed Author", ("metadata_extra",)), ("Subject", "internal", ("metadata_extra",)), ("Keywords", "billing, payroll", ("metadata_extra",))):
            out = os.path.join(tdir, f"meta-{field.lower()}.pdf")
            back = pdfkit_check.inject_info(base, out, {field: value})
            written = back.get(field) == value
            need(written, f"test bug: the injected {field} did not land in the PDF file")
            facts = inspect_native(out)
            read = bool((facts or {}).get("meta", {}).get(field))
            app_fails = cs.validate_pdf(out, report, real_html, facts, terms)
            ind, _info = pk.verify(out, real_html, title="Billing Revamp")
            stages = f"{field}: written=yes, read_by_extractor={'yes' if read else 'NO'}, product={','.join(app_fails) or 'ACCEPTED'}, independent={','.join(ind)[:60] or 'ACCEPTED'}"
            need("metadata" in app_fails and "metadata_" + field.lower() in app_fails, f"the product validator accepted a private PDF {field.lower()} ({stages})")
            need(any(c in ind for c in want_ind), f"the independent checker accepted a private PDF {field.lower()} ({stages})")
            summary.append(f"{field}: extractor read={'yes' if read else 'no'}")
        okp = os.path.join(tdir, "meta-creator-ok.pdf")                      # the one accepted non-engine Creator: the product's exact name
        pdfkit_check.inject_info(base, okp, {"Creator": "WorkReceipt"})
        okf = inspect_native(okp)
        need(cs.validate_pdf(okp, report, real_html, okf, terms) == [] and "metadata_creator" not in pk.verify(okp, real_html, title="Billing Revamp")[0],
             "Creator = the exact product name was refused")
        return "private Title/Creator/Author/Subject/Keywords injected into a real WKWebView PDF were refused by both checks (" + "; ".join(summary) + ")"
    check("native: private text in PDF metadata is detected", meta)

    def link():
        app_fails, ind, info = tamper("link", lambda h: inject(h, '<p><a href="https://tracker.example/x">Rebuilt the invoice screen</a></p>'), None)
        if not info["annotations"] and not info["skeleton_hits"]:
            return "this engine emitted no link annotation for an injected link (nothing to detect); the HTML validator also forbids links outright"
        need("annotation" in app_fails, f"link annotations present but the product validator did not flag them ({app_fails})")
        need(ind, "link annotations present but the independent checker did not flag them")
        return f"{info['annotations']} annotation(s) flagged by both checks"
    check("native: PDF links and annotations are detected", link)

    def tampered_html():
        bad = inject(real_html, "<!-- internal: oracle-fin-01 -->")
        need(cs.validate_html(bad, report, terms), "an HTML comment with a private string passed the HTML validator")
        bad2 = real_html.replace("Initech", "Initech</p><script>1</script><p>")
        need(cs.validate_html(bad2, report, terms), "an injected script passed the HTML validator")
        bad3 = real_html.replace("Billing Revamp", "Billing Revamp Globex", 1)
        need(cs.validate_html(bad3, report, terms), "a changed name passed the HTML validator")
        return "comment, script and altered text are all rejected"
    check("native: tampered HTML artifacts are rejected", tampered_html)

    def dev_export():
        ex = core.export(dict(ctx.o), ctx.ap, {})
        need(ex.get("ok"), "developer export failed")
        h = open(ex["html_path"], encoding="utf-8").read()
        need("PRIVATE" in h and "not for clients" in h, "developer report is not marked PRIVATE")
        return "developer report is marked PRIVATE"
    check("native: developer reports stay marked private", dev_export)

    def untouched():
        left = sorted(set(ctx.files()) - set(out0))
        need(all(f.startswith("client-report-") or f.startswith("billing") for f in left), "unexpected files in the reports folder")
    check("native: only expected files exist in the sandbox reports folder", untouched)


def main():
    done = threading.Event()

    def work():
        try:
            run()
        except BaseException:                                    # noqa: BLE001
            record("native harness ran to completion", "FAIL", traceback.format_exc().strip().splitlines()[-1])
            traceback.print_exc(file=sys.stderr)
        else:
            record("native harness ran to completion", "PASS", "")
        finally:
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(0)                                           # the AppKit loop never returns on its own

    def watchdog():
        time.sleep(int(os.environ.get("WRV_NATIVE_TIMEOUT", "900")))
        record("native harness ran to completion", "FAIL", "timed out")
        os._exit(3)
    threading.Thread(target=watchdog, daemon=True).start()
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyRegular
        except ImportError as e:
            record("native harness ran to completion", "FAIL", "PyObjC is not installed (%s)" % type(e).__name__)
            return 1
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)    # like the real app: a full window-server citizen (a Python icon appears in the Dock for a few seconds)
        threading.Thread(target=work, daemon=True).start()
        app.run()
    else:
        work()


if __name__ == "__main__":
    sys.exit(main())
