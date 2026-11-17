"""Client-Safe Mode: allowlist model, adversarial synthetic data, approval integrity, final HTML/PDF artifact checks.
SYNTHETIC data only. Nothing here reads a real ~/.claude, repository, prompt or credential; every "secret" is a made-up pattern match."""
import dataclasses, json, os, shutil, socket, subprocess, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, client_safe as cs, workreceipt as w, workreceipt_app as srv
from test_phase1 import WS, disp

AKIA = "AKIAQWERTYUIOPASDFGH"
CANARIES = {                                   # private strings that must NEVER reach a client artifact
    "aws key": AKIA, "internal db": "oracle-fin-01", "internal service": "envoy-edge-mesh", "private repo": "acme-private/billing-core",
    "local user": "zelda-quill", "abs path": "/work/billing-core/src/ledger.py", "db creds": "Sup3rS3cret99", "db host": "db.acme-internal.net",
    "unapproved client": "Globex", "client email": "cfo@globex.example", "internal file": "ledger_oracle_sync", "internal file 2": "hr_payroll_export",
    "commit text": "Wire oracle-fin-01 sync", "test file": "test_ledger_oracle", "machine": "mbp-zelda-7",
}
PERIOD = {"since": "2026-11-01", "until": "2026-11-30"}
HAS_CHROME = core.chrome_path() is not None
HAS_PDFTEXT = bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))


def hostile_ws():
    ws = WS("billing-core-internal", commits=[("src/ledger_oracle_sync.py", "Wire oracle-fin-01 sync through envoy-edge-mesh", "03"),
                                              ("internal/hr_payroll_export.py", "Add payroll export for Globex Corporation", "05")])
    ws.log([ws.user(f"Connect billing to oracle-fin-01 behind envoy-edge-mesh. Use {AKIA} for the upload", "2026-11-04T10:00:00Z"),
            ws.user("Clone https://github.com/acme-private/billing-core and edit /Users/zelda-quill/work/billing-core/src/ledger.py; "
                    "DB is postgres://admin:Sup3rS3cret99@db.acme-internal.net:5432/billing on mbp-zelda-7", "2026-11-05T10:00:00Z"),
            ws.user("Payroll export for Globex Corporation, contact cfo@globex.example", "2026-11-06T10:00:00Z")]
           + ws.bash("c1", "pytest -q tests/test_ledger_oracle.py", "2026-11-06T11:00:00Z", result="ok", err=False))
    core.save_settings({"redact_terms": ["Globex", "oracle-fin-01"]})
    return ws


def item(text="Rebuilt the invoice screen so customers can pay online", status="in_progress", commits=None, attested=False, approved=True, **extra):
    return dict({"text": text, "status": status, "commits": commits or [], "attested": attested, "approved": approved}, **extra)


def draft(items=None, **kw):
    return dict({"project_name": "Billing Revamp", "client_name": "Initech", "items": items if items is not None else [item()], "verification": {"mode": "none"}}, **kw)


class Flow:
    """preview -> approve -> export through the same core functions the HTTP routes call."""
    def __init__(self, ws):
        self.ws, self.o = ws, dict({"repo": ws.repo}, **PERIOD)
        self.b = core.build(self.o)
        self.ap = disp(self.b["findings"])
        self.commits = [c[0] for c in self.b["ctx"]["commits"]]

    def preview(self, d):
        return core.client_preview(self.o, d, self.ap)

    def approve(self, d, pv=None):
        pv = pv or self.preview(d)
        return core.client_approve(self.o, d, self.ap, {"privacy_review": True, "content_hash": pv["content_hash"]})

    def export(self, d, pdf=False, token=None):
        t = token or self.approve(d)["token"]
        return core.client_export(self.o, d, self.ap, t, pdf)


def texts_of(path):
    return open(path, encoding="utf-8").read()


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = hostile_ws(); self.addCleanup(self.ws.done)
        self.f = Flow(self.ws)
        self.out = os.path.join(self.ws.root, "out")

    def out_files(self):
        return sorted(os.listdir(self.out)) if os.path.isdir(self.out) else []

    def no_canaries(self, text, label=""):
        for k, v in CANARIES.items():
            self.assertNotIn(v.lower(), text.lower(), f"{k} leaked {label}")


class PdfMetadataPolicy(unittest.TestCase):
    """Root cause of the macOS 'validation [metadata]' export refusal: WKWebView/Quartz PDFs carry a Producer but NO Creator, PDFKit reports the
    missing field as an empty string, and the old rule treated an empty Creator/Producer as 'not an engine string'. An absent field is
    harmless; everything that could carry information stays refused. Refusals now name the FIELD (never the value)."""
    TITLE = "Work report for Initech"
    WEBKIT = {"Title": "", "Author": "", "Subject": "", "Keywords": "", "Creator": "", "Producer": "macOS Version 27.2 (Build 27C44) Quartz PDFContext",
              "CreationDate": "D:20261117090000Z", "ModDate": "D:20261117090000Z"}

    def problems(self, **over):
        return cs.pdf_metadata_problems(dict(self.WEBKIT, **over), self.TITLE, ("Globex", "oracle-fin-01"), ["zelda-quill", "mbp-zelda-7"])

    def test_webkit_shape_with_no_creator_is_allowed(self):
        self.assertEqual(self.problems(), {})
        self.assertEqual(self.problems(Creator="", Producer=""), {})                       # a PDF with neither is fine: nothing to leak
        for p in ("macOS Version 15.1 (Build 24B83) Quartz PDFContext", "macOS Version 27.2 (Build 27C5039g) Quartz PDFContext", "Quartz PDFContext", "Skia/PDF m153"):
            self.assertEqual(self.problems(Producer=p), {}, p)
        self.assertEqual(self.problems(Title=self.TITLE), {})

    def test_everything_that_can_carry_information_is_still_refused(self):
        cases = {
            "Author": ("Badri Tiruveedula", "must_be_empty"), "Subject": ("quarterly numbers", "must_be_empty"), "Keywords": ("billing, internal", "must_be_empty"),
            "Title": ("Untitled", "title_differs"), "Creator": ("/Users/zelda-quill/work/billing-core", "mentions_private_or_local_name"),
            "Producer": ("WorkReceipt build by zelda", "not_an_engine_string"), "Company": ("Globex", "mentions_private_or_local_name"), "Department": ("Finance", "must_be_empty"),
        }
        for field, (val, why) in cases.items():
            self.assertEqual(self.problems(**{field: val}).get(field), why, field)
        self.assertEqual(self.problems(Creator="/Users/someone/project").get("Creator"), "not_an_engine_string")
        self.assertEqual(self.problems(Producer="Quartz PDFContext oracle-fin-01").get("Producer"), "mentions_private_or_local_name")
        self.assertEqual(self.problems(Title="zelda-quill").get("Title"), "mentions_private_or_local_name")
        self.assertEqual(self.problems(Creator="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/150.0.0.0 Safari/537.36"), {})
        self.assertTrue(self.problems(Creator="Mozilla/5.0 (X11; mbp-zelda-7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/1.0"))

    def test_validation_names_the_field_but_never_the_value(self):
        f = Flow(self._ws())
        d = draft(); pv = f.preview(d); st = core._client_state(f.o, d, f.ap, core.load_settings())
        pdf = os.path.join(self.ws.root, "x.pdf"); open(pdf, "wb").write(b"%PDF-1.4\n" + b"0" * 200)
        base = {"text": "Work report for Initech Rebuilt the invoice screen so customers can pay online", "annotations": 0, "attachments": 0}
        ok = cs.validate_pdf(pdf, st["report"], pv["html"], dict(base, meta=self.WEBKIT), st["terms"], [])
        self.assertEqual(ok, [])
        bad = cs.validate_pdf(pdf, st["report"], pv["html"], dict(base, meta=dict(self.WEBKIT, Author="Badri Tiruveedula")), st["terms"], [])
        self.assertIn("metadata", bad); self.assertIn("metadata_author", bad)
        resp = core._blocked("validation", bad)
        self.assertIn("a PDF author field", resp["message"]); self.assertNotIn("Badri", json.dumps(resp))
        shown = cs.describe_pdf_metadata(dict(self.WEBKIT, Author="Badri Tiruveedula"), self.TITLE, st["terms"], [])
        self.assertNotIn("Badri", shown); self.assertIn("rejected", shown); self.assertIn("Quartz PDFContext", shown)

    def _ws(self):
        self.ws = hostile_ws(); self.addCleanup(self.ws.done)
        return self.ws


class ModelAllowlist(Base):
    def test_only_allowlisted_fields_serialise_and_unknown_fields_are_dropped(self):
        d = draft(raw_prompts=["Connect billing to oracle-fin-01"], repo_url="https://github.com/acme-private/billing-core", absolute_path="/Users/zelda-quill",
                  commits=["x"], env={"STRIPE_KEY": AKIA}, internal_notes="debug oracle-fin-01")
        d["items"][0]["source_path"] = "src/ledger_oracle_sync.py"
        d["items"][0]["raw_prompt"] = "Use AKIA..."
        d["verification"]["raw_log"] = "pytest output envoy-edge-mesh"
        r, issues, ignored = cs.build_report(d, {"commits": set(), "checks_total": 0, "checks_ok": 0}, "p", [], [])
        self.assertEqual(issues, []); self.assertGreaterEqual(ignored, 8)
        blob = json.dumps(cs.public(r)); self.no_canaries(blob)
        self.assertEqual(set(cs.public(r)), set(cs.PUBLIC_FIELDS))
        self.assertEqual(set(cs.public(r)["items"][0]), set(cs.ITEM_FIELDS))

    def test_unexpected_field_on_internal_model_is_refused_not_exported(self):        # hostile case 18
        @dataclasses.dataclass(frozen=True)
        class Leaky(cs.ClientReport):
            debug_note: str = "oracle-fin-01 / " + AKIA
        r, _, _ = cs.build_report(draft(), {"commits": set()}, "p", [], [])
        leaky = Leaky(**dataclasses.asdict(r) | {"items": r.items, "verification": r.verification})
        with self.assertRaises(cs.SchemaError):
            cs.public(leaky)
        with self.assertRaises(cs.SchemaError):
            cs.render_client(leaky)

    def test_extra_keys_in_private_build_never_reach_the_client_report(self):         # hostile case 18 (engine side)
        real = core.build
        def noisy(opts, settings=None):
            b = real(opts, settings); b["ctx"]["debug_dump"] = AKIA; b["ctx"]["items"][0]["raw_prompt"] = "oracle-fin-01"; b["extra"] = {"token": AKIA}
            return b
        core.build = noisy
        try:
            r = self.f.export(draft())
        finally:
            core.build = real
        self.assertTrue(r["ok"]); self.no_canaries(texts_of(r["html_path"]))

    def test_unapproved_items_and_raw_prompts_are_never_in_the_report(self):
        d = draft([item("Rebuilt the invoice screen"), item("Connect billing to oracle-fin-01 behind envoy-edge-mesh", approved=False)])
        r = self.f.export(d)
        self.assertTrue(r["ok"]); h = texts_of(r["html_path"])
        self.assertIn("Rebuilt the invoice screen", h); self.no_canaries(h)

    def test_empty_report_does_not_populate_itself_from_prompts(self):
        pv = self.f.preview(draft([]))
        self.assertFalse(pv["ok"]); self.assertIsNone(pv["html"])
        self.assertIn("no_items", [i["code"] for i in pv["issues"]])
        pv = self.f.preview(draft([item(approved=False)]))
        self.assertFalse(pv["ok"]); self.assertIsNone(pv["html"])

    def test_project_name_is_never_taken_from_the_folder(self):
        pv = self.f.preview(draft(project_name=""))
        self.assertFalse(pv["ok"]); self.assertIn("required", [i["code"] for i in pv["issues"]])
        h = self.f.export(draft())["html_path"]
        self.assertNotIn("billing-core-internal", texts_of(h)); self.assertNotIn("billing-core-internal", os.path.basename(h))

    def test_prepared_by_only_when_enabled(self):
        self.assertNotIn("Prepared by", self.f.preview(draft(prepared_by="Zed Author"))["html"])
        pv = self.f.preview(draft(prepared_by="Zed Author", include_prepared_by=True))
        self.assertIn("Prepared by", pv["html"]); self.assertIn("Zed Author", pv["html"])


class CompletionWording(Base):
    def test_delivered_needs_evidence_or_attestation(self):
        pv = self.f.preview(draft([item(status="delivered")]))
        self.assertIn("evidence_missing", [i["code"] for i in pv["issues"]])
        self.assertTrue(self.f.preview(draft([item(status="delivered", attested=True)]))["ok"])
        pv = self.f.preview(draft([item(status="delivered", commits=self.f.commits[:1])]))
        self.assertTrue(pv["ok"]); self.assertIn("Supported by Git history (1 commit)", pv["html"])
        self.assertNotIn(self.f.commits[0][:7], pv["html"])                                  # commit ids are never printed

    def test_in_progress_never_claims_delivery(self):
        h = self.f.preview(draft([item(status="in_progress", attested=True, commits=self.f.commits)]))["html"]
        self.assertIn("In progress", h); self.assertNotIn("chip ok", h); self.assertNotIn("Supported by", h); self.assertNotIn("Confirmed by", h)

    def test_unknown_missing_or_forged_commit_evidence_is_refused(self):                  # hostile case 15
        for bad in (["f" * 40], [self.f.commits[0], "0" * 40], [123], "notalist"):
            pv = self.f.preview(draft([item(status="delivered", commits=bad, attested=True)]))
            self.assertFalse(pv["ok"], bad)
            self.assertTrue({"evidence_unknown", "evidence_missing"} & {i["code"] for i in pv["issues"]})
        self.assertIsNone(pv["html"])

    def test_evidence_that_vanished_after_the_period_changes(self):
        d = draft([item(status="delivered", commits=self.f.commits[:1])])
        t = self.f.approve(d)["token"]
        o = dict(self.f.o, since="2026-11-04", until="2026-11-30")               # first commit (Nov 3) is no longer in the period
        r = core.client_export(o, d, self.f.ap, t, False)
        self.assertFalse(r["ok"]); self.assertEqual(self.out_files(), [])

    def test_verification_counts_come_from_the_server_not_the_payload(self):
        d = draft(verification={"mode": "auto", "checks_total": 999, "checks_ok": 999})
        h = self.f.preview(d)["html"]
        self.assertIn("1 automated check recorded", h); self.assertNotIn("999", h)
        self.assertNotIn("pytest", h); self.assertNotIn("test_ledger_oracle", h)

    def test_auto_verification_without_checks_is_refused(self):
        ws = WS("quiet", commits=[("a.py", "x", "03")]); self.addCleanup(ws.done); ws.log([ws.user("hi", "2026-11-04T10:00:00Z")])
        pv = core.client_preview(dict({"repo": ws.repo}, **PERIOD), draft(verification={"mode": "auto"}), {})
        self.assertIn("no_checks", [i["code"] for i in pv["issues"]])


class Screening(Base):
    def codes(self, text, **kw):
        return {i["code"] for i in cs.screen(text, "x", kw.get("terms", []), kw.get("ids", []))}

    def test_hostile_text_is_blocked(self):
        cases = [("api key", f"Uploaded using {AKIA}", "secret"), ("db credentials", "Connected to postgres://admin:Sup3rS3cret99@db.acme-internal.net/x", "secret"),
                 ("private repo", "Cloned https://github.com/acme-private/billing-core", "url"), ("ssh repo", "Pushed to git@github.com:acme/x.git", "url"),
                 ("abs path", "Edited /Users/zelda-quill/work/billing-core/src/ledger.py", "path"), ("windows path", r"Saved to C:\Users\zelda\work", "path"),
                 ("internal file", "Rewrote src/ledger_oracle_sync.py", "filename"), ("bare file", "Updated hr_payroll_export.py", "filename"),
                 ("host", "Deployed to billing.acme-internal.net", "url"), ("email", "Ask cfo@globex.example", "secret"), ("commit id", "Reverted a1b2c3d4e5", "hash"),
                 ("command", "Ran npm run build && docker compose up", "command"), ("backticks", "Fixed `ledger.sync()`", "command"),
                 ("env", "Set STRIPE_KEY=abc in the shell", "env"), ("markup", "<script>alert(1)</script>", "markup"), ("img onerror", "<img src=x onerror=alert(1)>", "markup"),
                 ("js url", "javascript:alert(1)", "markup"), ("secret in prose", f"Finished the export (key {AKIA}) and the dashboard", "secret"),
                 ("ip", "Server at 10.20.30.40", "secret"), ("assignment", "password = 'hunter2hunter2'", "secret")]
        for name, text, code in cases:
            with self.subTest(name):
                self.assertIn(code, self.codes(text), text)

    def test_private_terms_and_local_identifiers_block_including_obfuscation(self):
        t = ["Globex", "oracle-fin-01"]
        for text in ("Payroll for Globex Corporation", "payroll for GLOBEX", "for G l o b e x", "ＧＬＯＢＥＸ export", "Globex\u200bCorp", "g-l-o-b-e-x", "oracle fin 01 sync", "ORACLE-FIN-01"):
            with self.subTest(text):
                self.assertIn("private_term", self.codes(text, terms=t))
        self.assertIn("local_id", self.codes("Built on mbp-zelda-7", ids=["mbp-zelda-7"]))
        self.assertIn("local_id", self.codes("Worked as Zelda-Quill", ids=["zelda-quill"]))

    def test_ordinary_prose_is_not_blocked(self):
        for text in ("Built the checkout page and connected online payments", "Fixed the Q4 invoice rounding issue (2026/11/16)", "Updated Node.js and Next.js pages",
                     "Make sure signup works on mobile", "Sample data: migrated 1,200 customer records", "Redesigned the dashboard; and/or reports", "Added role-based access for admins"):
            with self.subTest(text):
                self.assertEqual(self.codes(text), set())

    def test_limit_is_unambiguous_architecture_prose_is_the_human_s_job(self):
        # Honest limit: text with no secret shape and no listed term passes the checks. It only reaches a report if the developer typed it,
        # and then only after the exact preview is approved. Nothing here pretends otherwise.
        self.assertEqual(self.codes("Our billing database runs on the finance cluster"), set())

    def test_hidden_and_formatting_characters(self):
        d = draft([item("Fixed\u202e the\u200b invoice\u0000 screen\u2028now\ufeff")])
        h = self.f.preview(d)["html"]
        self.assertIn("Fixed the invoice screen now", h)
        for ch in ("\u202e", "\u200b", "\u0000", "\ufeff", "\u2028"):
            self.assertNotIn(ch, h)

    def test_long_unicode_and_odd_formatting(self):
        long_ok = ("Zażółć gęślą jaźń 日本語 😀 " * 30)[:399] + "x"
        self.assertEqual(len(long_ok), 400)
        pv = self.f.preview(draft([item(long_ok)]))
        self.assertTrue(pv["ok"], pv["issues"]); self.assertEqual(self.f.preview(draft([item(long_ok + "x")]))["ok"], False)
        self.assertIn("too_long", [i["code"] for i in self.f.preview(draft([item("a" * 401)]))["issues"]])
        weird = "  multiple   spaces\n\nand\tlines  "
        self.assertIn("multiple spaces and lines", self.f.preview(draft([item(weird)]))["html"])
        self.assertFalse(self.f.preview(draft([item("lone \ud800 surrogate")]))["ok"])
        self.assertFalse(self.f.preview(draft([item(12345)]))["ok"])

    def test_every_template_string_passes_the_same_screening(self):
        r, _, _ = cs.build_report(draft(prepared_by="Zed Author", include_prepared_by=True, verification={"mode": "auto"}, items=[item(status="delivered", attested=True)]),
                                   {"commits": set(), "checks_total": 3, "checks_ok": 2}, "2026-11-01 to 2026-11-30", [], [])
        self.assertEqual(cs.validate_html(cs.render_client(r), r, [], []), [])

    def test_css_has_no_hiding_or_loading_constructs(self):
        for bad in ("display:none", "visibility:hidden", "url(", "@import", "expression(", "contenteditable", "javascript:"):
            self.assertNotIn(bad, (cs.CLIENT_CSS + cs.CLIENT_FOOTER).lower())


class HtmlArtifact(Base):
    def report(self, **kw):
        r, issues, _ = cs.build_report(draft(**kw), {"commits": set(), "checks_total": 0, "checks_ok": 0}, "p", [], [])
        self.assertEqual(issues, []); return r

    def test_injection_is_escaped_if_it_ever_reached_the_template(self):             # hostile case 9, defence in depth
        r = dataclasses.replace(self.report(), project_name="<script>alert(1)</script>", items=(cs.ClientItem("<img src=x onerror=alert(1)>", "in_progress", "none", 0),))
        h = cs.render_client(r)
        self.assertNotIn("<script>", h); self.assertNotIn("<img", h); self.assertIn("&lt;script&gt;", h)
        self.assertIn("secret", cs.validate_html(h, r, [], []))                       # and the final-file check refuses it anyway

    def test_tampered_artifacts_are_rejected(self):
        r = self.report(); good = cs.render_client(r)
        tampers = {"hidden attr": good.replace("<div class=brand>", f"<div class=brand title='{AKIA}'>", 1), "data attr": good.replace("<h1>", "<h1 data-x='oracle-fin-01'>", 1),
                   "style attr": good.replace("<h1>", "<h1 style='color:#fff'>", 1), "script": good.replace("<h1>", "<script>x=1</script><h1>", 1),
                   "comment": good.replace("<h1>", "<!-- oracle-fin-01 --><h1>", 1), "link": good.replace("<h1>", "<a href='https://x.example'>x</a><h1>", 1),
                   "img": good.replace("<h1>", "<img src='data:image/png;base64,AAAA'><h1>", 1), "extra text": good.replace("<h1>", "<p>zelda-quill</p><h1>", 1),
                   "css": good.replace("<style>", "<style>.x{background:url(https://x.example/t.png)}", 1), "iframe": good + "<iframe src=about:blank></iframe>",
                   "meta": good.replace("<title>", "<meta name=author content='zelda-quill'><title>", 1), "class": good.replace("class=brand", "class=brand hidden-secret", 1)}
        for name, bad in tampers.items():
            with self.subTest(name):
                self.assertNotEqual(cs.validate_html(bad, r, ["zelda-quill", "oracle-fin-01"], ["zelda-quill"]), [], name)
        self.assertEqual(cs.validate_html(good, r, [], []), [])

    def test_failed_final_validation_blocks_export_and_writes_nothing(self):          # hostile case 16
        d = draft(); t = self.f.approve(d)["token"]
        real = cs.render_client
        cs.render_client = lambda r: real(r).replace("<div class=foot>", f"<div class=foot data-leak='{AKIA}'>")
        try:
            res = core.client_export(self.f.o, d, self.f.ap, t, False)
        finally:
            cs.render_client = real
        self.assertFalse(res["ok"]); self.assertEqual(res["reason"], "validation")
        self.assertEqual(self.out_files(), []); self.no_canaries(json.dumps(res), "in error")

    def test_validator_that_cannot_run_blocks_export(self):
        d = draft(); t = self.f.approve(d)["token"]
        real = cs.validate_html
        def boom(*a, **k): raise RuntimeError("zelda-quill " + AKIA)
        cs.validate_html = boom
        try:
            with self.assertRaises(RuntimeError):
                core.client_export(self.f.o, d, self.f.ap, t, False)
        finally:
            cs.validate_html = real
        self.assertEqual(self.out_files(), [])
        # over HTTP an unexpected exception is reduced to a fixed message (see ApiTests.test_errors_never_echo_content)


@unittest.skipUnless(HAS_CHROME and HAS_PDFTEXT, "needs Chrome and poppler")
class PdfArtifact(Base):
    """validate_pdf against PDFs built from doctored HTML (hidden text, links, metadata) plus unreadable and unverifiable inputs."""
    def setUp(self):
        super().setUp()
        self.r, iss, _ = cs.build_report(draft(), {"commits": set(), "checks_total": 0, "checks_ok": 0}, "2026-11-01 to 2026-11-30", [], [])
        self.good = cs.render_client(self.r); self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)

    def pdf(self, html, name="r"):
        p = os.path.join(self.tmp, name + ".html"); open(p, "w", encoding="utf-8").write(html)
        out = core.to_pdf(p); self.assertTrue(out, "chrome could not print"); return out

    def check(self, path, **k):
        return cs.validate_pdf(path, self.r, self.good, k.get("facts", cs.pdf_facts_cli(path)), ["zelda-quill", "oracle-fin-01"], ["zelda-quill"])

    def test_clean_pdf_passes(self):
        self.assertEqual(self.check(self.pdf(self.good)), [])

    def test_hidden_text_is_detected(self):                                          # hostile case 17
        for name, extra in (("white", "<p style='color:#fff;font-size:2pt'>canaryqwertyzzzz</p>"), ("tiny", "<p style='font-size:1px'>hiddenmarkerabc</p>")):
            with self.subTest(name):
                self.assertIn("pdf_text", self.check(self.pdf(self.good.replace("<div class=foot>", extra + "<div class=foot>"), name)))

    def test_secret_in_pdf_text_is_detected(self):
        html = self.good.replace("<div class=foot>", f"<p>{AKIA}</p><div class=foot>")
        bad = self.check(self.pdf(html))
        self.assertIn("secret", bad); self.assertIn("pdf_text", bad)

    def test_links_and_annotations_are_detected(self):
        bad = self.check(self.pdf(self.good.replace("<div class=foot>", "<a href='https://x.example/track'>Generated</a><div class=foot>")))
        self.assertIn("annotation", bad)

    def test_metadata_is_checked(self):
        bad = self.check(self.pdf(self.good.replace("<title>Work report for Initech</title>", "<title>Billing oracle-fin-01 notes</title>")))
        self.assertIn("metadata", bad)
        try:
            import pypdf
        except ImportError:
            return
        base = self.pdf(self.good, "m")
        for k, v in (("/Author", "zelda-quill"), ("/Subject", "internal"), ("/Keywords", "k"), ("/Creator", "/Users/zelda-quill/bin/tool")):
            w_ = pypdf.PdfWriter(clone_from=base); w_.add_metadata({k: v})
            out = os.path.join(self.tmp, "meta.pdf"); w_.write(out)
            with self.subTest(k):
                self.assertIn("metadata", self.check(out))

    def test_unverifiable_unreadable_and_empty_pdfs_fail(self):
        good = self.pdf(self.good)
        self.assertIn("pdf_unverified", self.check(good, facts=None))
        junk = os.path.join(self.tmp, "j.pdf"); open(junk, "wb").write(b"not a pdf at all" * 20)
        self.assertEqual(cs.validate_pdf(junk, self.r, self.good, None), ["pdf_unreadable"])
        self.assertEqual(cs.validate_pdf(os.path.join(self.tmp, "missing.pdf"), self.r, self.good, None), ["pdf_unreadable"])
        self.assertIn("empty", self.check(good, facts={"text": "  ", "meta": {}, "annotations": 0, "attachments": 0}))
        self.assertIn("pdf_unverified", self.check(good, facts={"text": None, "meta": {}, "annotations": 0, "attachments": 0}))
        self.assertIn("annotation", self.check(good, facts={"text": "Billing Revamp", "meta": {}, "annotations": 1, "attachments": 0}))

    def test_raw_structure_scan_ignores_compressed_stream_bytes(self):
        good = self.pdf(self.good)
        raw = open(good, "rb").read()
        noisy = raw.replace(b"endstream", b"endstream", 1)
        self.assertEqual(self.check(good), [])
        evil = raw + b"\n1 0 obj\n<< /S /JavaScript /JS (app.alert(1)) >>\nendobj\n"
        p = os.path.join(self.tmp, "evil.pdf"); open(p, "wb").write(evil)
        self.assertIn("annotation", self.check(p, facts={"text": "Billing Revamp Initech", "meta": {}, "annotations": 0, "attachments": 0}))


class Approval(Base):
    def test_export_requires_a_matching_server_issued_token(self):                   # hostile case 14
        d = draft()
        for forged in (None, "", "123.abc", "x", "9999999999." + "0" * 64, {"a": 1}):
            r = core.client_export(self.f.o, d, self.f.ap, forged, False)
            self.assertFalse(r["ok"]); self.assertEqual(r["reason"], "approval")
        self.assertEqual(self.out_files(), [])

    def test_approval_needs_explicit_scoped_confirmation(self):
        pv = self.f.preview(draft())
        for c in (None, {}, {"privacy_review": False, "content_hash": pv["content_hash"]}, {"privacy_review": "yes", "content_hash": pv["content_hash"]}, {"privacy_review": True}):
            self.assertFalse(core.client_approve(self.f.o, draft(), self.f.ap, c)["ok"])
        r = core.client_approve(self.f.o, draft(), self.f.ap, {"privacy_review": True, "content_hash": "0" * 64})
        self.assertFalse(r["ok"]); self.assertEqual(r["reason"], "approval")

    def test_any_edit_invalidates_the_approval(self):                                # hostile case 13
        d = draft(); t = self.f.approve(d)["token"]
        self.assertTrue(core.client_export(self.f.o, d, self.f.ap, t, False)["ok"])
        edits = [lambda x: x["items"][0].update(text="Rebuilt the invoice screen!"), lambda x: x.update(project_name="Billing Revamp 2"), lambda x: x.update(client_name="Other"),
                 lambda x: x["items"][0].update(status="delivered", attested=True), lambda x: x["items"].append(item("Another item")), lambda x: x["items"].reverse() or x["items"].append(item("b")),
                 lambda x: x.update(include_prepared_by=True, prepared_by="Zed"), lambda x: x["verification"].update(mode="custom", text="Tested manually")]
        for n, edit in enumerate(edits):
            e = json.loads(json.dumps(d)); edit(e)
            r = core.client_export(self.f.o, e, self.f.ap, t, False)
            self.assertFalse(r["ok"], n); self.assertEqual(r["reason"], "approval", n)

    def test_token_is_bound_to_project_period_and_findings(self):
        d = draft(); t = self.f.approve(d)["token"]
        r = core.client_export(dict(self.f.o, until="2026-11-29"), d, self.f.ap, t, False)
        self.assertEqual(r["reason"], "approval")
        changed = dict(self.f.ap); k = next(iter(changed)); changed[k] = "credential"           # a different review decision
        self.assertEqual(core.client_export(self.f.o, d, changed, t, False)["reason"], "approval")

    def test_token_expires_and_is_per_process(self):
        h = "ab" * 32
        self.assertTrue(cs.token_valid(cs.approval_token(h, now=1000), h, now=1000 + cs.APPROVAL_TTL))
        self.assertFalse(cs.token_valid(cs.approval_token(h, now=1000), h, now=1001 + cs.APPROVAL_TTL))
        self.assertFalse(cs.token_valid(cs.approval_token(h, now=2000), h, now=1000))
        sig = cs.approval_token(h, now=1000).split(".")[1]
        self.assertFalse(cs.token_valid(f"1001.{sig}", h, now=1001))                         # timestamp is part of the signature

    def test_secret_finding_review_alone_does_not_authorise_anything(self):          # two independent safeguards
        r = core.client_export(self.f.o, draft(), self.f.ap, None, False)
        self.assertEqual(r["reason"], "approval")
        r = core.client_approve(self.f.o, draft(), {}, {"privacy_review": True, "content_hash": self.f.preview(draft())["content_hash"]})
        self.assertEqual(r["reason"], "findings"); self.assertTrue(r["missing"])
        t = self.f.approve(draft())["token"]
        r = core.client_export(self.f.o, draft(), {}, t, False)                         # token ok, findings unreviewed: still blocked server-side
        self.assertEqual(r["reason"], "findings"); self.assertEqual(self.out_files(), [])
        for bad in ("looks fine", True, 1):
            self.assertEqual(core.client_export(self.f.o, draft(), {k: bad for k in self.f.ap}, t, False)["reason"], "findings")

    def test_text_issues_block_even_with_a_valid_token(self):
        t = self.f.approve(draft())["token"]
        bad = draft([item(f"Used {AKIA}")])
        r = core.client_export(self.f.o, bad, self.f.ap, t, False)
        self.assertFalse(r["ok"]); self.assertEqual(r["reason"], "issues"); self.no_canaries(json.dumps(r), "in issues")


class EndToEnd(Base):
    def test_html_export_contains_only_approved_content(self):
        d = draft([item("Rebuilt the invoice screen so customers can pay online", status="delivered", commits=self.f.commits[:2]), item("Started the reporting dashboard")],
                  verification={"mode": "auto"}, prepared_by="Zed Author", include_prepared_by=True)
        r = self.f.export(d)
        self.assertTrue(r["ok"], r); h = texts_of(r["html_path"])
        for want in ("Billing Revamp", "Initech", "2026-11-01 to 2026-11-30", "Zed Author", "Rebuilt the invoice screen", "Started the reporting dashboard", "Supported by Git history (2 commits)", "1 automated check recorded"):
            self.assertIn(want, h)
        self.no_canaries(h, "in html"); self.assertNotIn("billing-core-internal", h)
        rep, iss, _ = cs.build_report(d, {"commits": set(self.f.commits), "checks_total": 1, "checks_ok": 1}, "2026-11-01 to 2026-11-30", [], [])
        self.assertEqual(iss, []); self.assertEqual(cs.validate_html(h, rep, [], []), [])
        self.assertEqual(self.out_files(), [os.path.basename(r["html_path"])])
        self.assertTrue(os.path.basename(r["html_path"]).startswith("client-report-Billing-Revamp-"))
        rec = core.history()[-1]; self.assertEqual(rec["mode"], "client"); self.assertEqual(rec["project"], "Billing Revamp")
        self.assertNotIn("zelda", json.dumps(core.history()).lower().replace("billing-core-internal", ""))

    def test_preview_is_byte_identical_to_the_exported_html(self):
        d = draft([item("Rebuilt the invoice screen", status="delivered", attested=True)], verification={"mode": "custom", "text": "Tested on desktop and mobile"})
        pv = self.f.preview(d); r = self.f.export(d)
        self.assertEqual(pv["html"], texts_of(r["html_path"]))

    @unittest.skipUnless(HAS_CHROME and HAS_PDFTEXT, "needs Chrome and poppler")
    def test_pdf_export_is_checked_and_clean(self):
        d = draft([item("Rebuilt the invoice screen so customers can pay online", status="delivered", commits=self.f.commits[:1])], verification={"mode": "auto"})
        r = self.f.export(d, pdf=True)
        self.assertTrue(r["ok"] and r["pdf_path"] and not r["pdf_failed"], r)
        text = subprocess.run(["pdftotext", "-layout", r["pdf_path"], "-"], capture_output=True, text=True).stdout
        info = subprocess.run(["pdfinfo", r["pdf_path"]], capture_output=True, text=True).stdout
        self.assertIn("Rebuilt the invoice screen", text); self.no_canaries(text, "in pdf text"); self.no_canaries(info, "in pdf metadata")
        self.assertNotIn("zelda", info.lower())
        for k in ("Author", "Subject", "Keywords"):
            self.assertEqual("".join(l.split(":", 1)[1].strip() for l in info.splitlines() if l.startswith(k + ":")), "", k)
        for name in os.listdir(self.out):
            self.no_canaries(name, "in file name")
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in os.listdir(self.out)), ["html", "pdf"])
        raw = open(r["pdf_path"], "rb").read()
        for tok in (b"/URI", b"/JavaScript", b"/EmbeddedFile", b"/Annots"):
            self.assertNotIn(tok, raw)

    @unittest.skipUnless(HAS_CHROME, "needs Chrome")
    def test_pdf_generation_failure_keeps_validated_html_only(self):
        d = draft(); t = self.f.approve(d)["token"]
        real = core.to_pdf; core.to_pdf = lambda p: None
        try:
            r = core.client_export(self.f.o, d, self.f.ap, t, True)
        finally:
            core.to_pdf = real
        self.assertTrue(r["ok"]); self.assertTrue(r["pdf_failed"]); self.assertEqual([n.rsplit(".", 1)[1] for n in self.out_files()], ["html"])

    def test_pdf_that_cannot_be_verified_blocks_the_whole_export(self):
        if not HAS_CHROME:
            self.skipTest("needs Chrome")
        d = draft(); t = self.f.approve(d)["token"]
        real = core.PDF_INSPECTOR; core.PDF_INSPECTOR = lambda p: None
        try:
            r = core.client_export(self.f.o, d, self.f.ap, t, True)
        finally:
            core.PDF_INSPECTOR = real
        self.assertFalse(r["ok"]); self.assertIn("pdf_unverified", r["failed"]); self.assertEqual(self.out_files(), [])

    def test_failures_leak_nothing_into_responses_or_the_data_folder(self):
        for d in (draft([item(f"Used {AKIA} for oracle-fin-01")]), draft([])):
            r = self.f.preview(d); self.no_canaries(json.dumps(r), "in preview response")
            r = core.client_export(self.f.o, d, self.f.ap, "1.x", False); self.no_canaries(json.dumps(r), "in export response")
        home = core._home()
        for root, _, files in os.walk(home):
            for n in files:
                with open(os.path.join(root, n), encoding="utf-8", errors="replace") as fh:
                    blob = fh.read()
                for k in ("aws key", "db creds", "local user", "client email"):
                    self.assertNotIn(CANARIES[k], blob, f"{k} in {n}")

    def test_no_network_is_used(self):
        real = socket.socket.connect
        def deny(*a, **k): raise AssertionError("network access attempted")
        socket.socket.connect = deny
        try:
            self.assertTrue(self.f.export(draft())["ok"])
        finally:
            socket.socket.connect = real

    def test_missing_project_folder_is_a_safe_error(self):
        with self.assertRaises(core.UserError):
            core.client_preview({"repo": os.path.join(self.ws.root, "gone")}, draft(), {})

    def test_developer_report_still_works_and_is_marked_private(self):
        r = core.export(dict(self.f.o), self.f.ap, {})
        self.assertTrue(r["ok"]); self.assertIn("PRIVATE", r["html"]); self.assertIn("Developer report", r["html"])
        self.assertEqual(core.history()[-1]["mode"], "developer")

    def test_safe_file_names(self):
        for name in ("Acme/../../etc/passwd", "a" * 300, "名前", "", "..", "Billing Revamp", "zelda-quill x"):
            b = cs.safe_basename(name, ["oracle-fin-01"], ["zelda-quill"])
            self.assertRegex(b, r"^client-report(-[A-Za-z0-9-]{1,40})?$"); self.assertNotIn("..", b)
        self.assertEqual(cs.safe_basename("zelda-quill x", [], ["zelda-quill"]), "client-report")


class Migration(unittest.TestCase):
    def test_legacy_settings_and_history_are_safe(self):
        root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, root, True)
        os.environ["WORKRECEIPT_HOME"] = root
        os.makedirs(os.path.join(root, "x"), exist_ok=True)
        html = os.path.join(root, "old.html"); open(html, "w").write("<p>old</p>")
        json.dump({"author": "A", "client": "C", "theme": "dark", "future_key": 1}, open(os.path.join(root, "settings.json"), "w"))
        legacy = [{"project": "old", "repo": "/x", "period": "a → b", "html": html, "pdf": None, "client": "C", "at": "2026-01-01 10:00", "requests": 3, "commits": 2, "checks": 1, "high_reviewed": 0}]
        json.dump(legacy, open(os.path.join(root, "history.json"), "w"))
        s = core.load_settings()
        self.assertEqual((s["author"], s["theme"], s["settings_version"]), ("A", "dark", 2)); self.assertNotIn("future_key", s)
        h = core.history()
        self.assertEqual(h[0]["mode"], "developer"); self.assertNotEqual(h[0].get("mode"), "client"); self.assertNotIn("content_hash", h[0])
        self.assertEqual(json.load(open(os.path.join(root, "history.json"))), legacy)       # read-only normalisation
        self.assertEqual(core.resolve_report("old.html"), html)                             # still readable
        json.dump(["junk", 5, None, {"mode": "client", "html": "z"}], open(os.path.join(root, "history.json"), "w"))
        self.assertEqual(len(core.history()), 1)


class ApiTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def post(self, path, body, token=True):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json", **({"X-WR-Token": srv.TOKEN} if token else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, (json.loads(e.read() or b"{}") if e.code != 403 else {})

    def test_routes_need_the_page_token(self):
        for p in ("/api/client/preview", "/api/client/approve", "/api/client/export"):
            self.assertEqual(self.post(p, {}, token=False)[0], 403)

    def test_full_http_flow_and_forged_requests(self):
        body = dict(self.f.o, draft=draft(), approved=self.f.ap)
        code, pv = self.post("/api/client/preview", body); self.assertEqual(code, 200); self.assertTrue(pv["ok"])
        code, r = self.post("/api/client/export", dict(body, token="1.forged", pdf=False)); self.assertEqual((code, r["reason"]), (409, "approval"))
        code, r = self.post("/api/client/export", dict(body, approved=True, ok=True, token=None)); self.assertEqual(code, 409)
        code, r = self.post("/api/client/approve", dict(body, confirm={"privacy_review": True, "content_hash": pv["content_hash"]})); self.assertEqual(code, 200)
        code, ex = self.post("/api/client/export", dict(body, token=r["token"], pdf=False)); self.assertEqual(code, 200); self.assertTrue(ex["ok"])
        self.assertEqual(texts_of(ex["html_path"]), pv["html"])

    def test_errors_never_echo_content(self):
        real = core.client_preview
        def boom(*a, **k): raise RuntimeError(f"{AKIA} oracle-fin-01 /Users/zelda-quill")
        core.client_preview = boom
        try:
            code, r = self.post("/api/client/preview", dict(self.f.o, draft=draft(), approved={}))
        finally:
            core.client_preview = real
        self.assertEqual(code, 500); self.no_canaries(json.dumps(r), "in 500 body")


if __name__ == "__main__":
    unittest.main()
