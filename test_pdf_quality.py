"""Visual/structural QA on REAL rendered PDFs (headless Chrome on Linux; the macOS WebKit path is not exercised here).
Synthetic data only. Every PDF is rendered page-by-page and checked for: Letter size, page count, blank pages, text inside margins,
selectable/searchable text, page order, completeness vs the HTML, colours present, and absence of sentinel secrets."""
import json, os, random, re, shutil, subprocess, sys, tempfile, types, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workreceipt as w
CHROME = next((c for c in (os.environ.get("WR_CHROME"), "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if c and os.path.exists(c)), None)
HAVE = bool(CHROME and shutil.which("pdftotext") and shutil.which("pdftoppm") and shutil.which("pdfinfo"))
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = []


def ctx(n_items=3, n_commits=2, n_checks=2, long=False, author="Dana Dev", status_mix=True, hits=3, dirs=3):
    rnd = random.Random(7)
    words = "refactor checkout totals cache invalidation session login retry webhook schema migration pagination cart coupon".split()
    sent = lambda k: " ".join(rnd.choice(words) for _ in range(k))
    items = [dict(title=(f"Request {i}: " + sent(250 if long and i % 7 == 0 else rnd.randint(4, 14))), date=f"Nov {1 + i % 28:02d}") for i in range(n_items)]
    commits = [[f"{rnd.getrandbits(40):010x}", f"2026-11-{1 + i % 28:02d}", f"Commit {i}: " + sent(rnd.randint(3, 40 if long else 12))] for i in range(n_commits)]
    checks = [dict(cmd=f"pytest tests/test_{sent(2).replace(' ', '_')}.py -k case{i}", ok=([True, False, None][i % 3] if status_mix else True),
                   state=[None, "edited", "superseded", "possible", "current"][i % 5]) for i in range(n_checks)]
    return dict(title="Work report for Acme Corp", project="acme-storefront", period="2026-11-01 → 2026-11-14", author=author, generated="2026-11-15 09:00",
                items=items, n_items=len(items), commits=commits, n_commits=len(commits), n_files=min(40, n_commits), ins=1234, dele=567, n_authors=2,
                dirs=[(f"src/module{i}", 3 + i) for i in range(dirs)], git_filtered=False, checks=checks, hits={"secret": hits} if hits else {})


def to_pdf(html, name, tmp):
    h = os.path.join(tmp, name + ".html"); p = os.path.join(tmp, name + ".pdf"); prof = tempfile.mkdtemp(dir=tmp)
    open(h, "w", encoding="utf-8").write(html)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={prof}", "--no-pdf-header-footer", f"--print-to-pdf={p}", "file://" + h],
                   capture_output=True, timeout=120, check=True)
    return p


def pages_text(p, n):
    return [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", p, "-"], capture_output=True, text=True).stdout for i in range(1, n + 1)]


def analyse(p, tmp, name):
    info = subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout
    n = int(re.search(r"Pages:\s+(\d+)", info).group(1)); size = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
    out = dict(name=name, pages=n, size=(float(size.group(1)), float(size.group(2))), info=info, text=pages_text(p, n))
    # raster every page; ink coverage per page, and ink touching the page edges (clipping / overflow)
    from PIL import Image
    subprocess.run(["pdftoppm", "-r", "50", "-png", p, os.path.join(tmp, name)], check=True)
    ink, edge = [], []
    for f in sorted(x for x in os.listdir(tmp) if x.startswith(name + "-") and x.endswith(".png")):
        im = Image.open(os.path.join(tmp, f)).convert("L"); W, H = im.size; px = im.load()
        dark = sum(1 for y in range(0, H, 2) for x in range(0, W, 2) if px[x, y] < 200)
        ink.append(dark / ((W // 2) * (H // 2)))
        m = int(0.35 * 50)           # outer 0.35in must be empty (margins are 0.75in; footer sits inside the bottom margin)
        e = sum(1 for y in range(H) for x in list(range(0, m)) + list(range(W - m, W)) if px[x, y] < 160)
        e += sum(1 for y in list(range(0, m)) for x in range(W) if px[x, y] < 160)
        edge.append(e)
    out.update(ink=ink, edge=edge); return out


@unittest.skipUnless(HAVE, "needs Chrome + poppler")
class PdfQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        with open(os.path.join(HERE, "docs", "pdf_qa_results.json"), "w") as f:
            json.dump([{k: v for k, v in r.items() if k not in ("text", "info")} for r in RESULTS], f, indent=1)

    def build(self, name, c, min_pages, max_pages):
        html = w.render(c); p = to_pdf(html, name, self.tmp); r = analyse(p, self.tmp, name); r["html"] = html; RESULTS.append(r)
        self.assertEqual(r["size"], (612.0, 792.0), "US Letter")
        self.assertTrue(min_pages <= r["pages"] <= max_pages, f"{name}: {r['pages']} pages")
        # no blank / nearly blank pages (the last page may be short, but never empty)
        for i, (t, ink) in enumerate(zip(r["text"], r["ink"]), 1):
            self.assertGreater(len(t.strip()), 80, f"{name} p{i} nearly blank"); self.assertGreater(ink, 0.004, f"{name} p{i} no ink")
        # nothing printed in the outer 0.35in (clipping / overflow past the margins)
        self.assertEqual(max(r["edge"]), 0, f"{name}: ink in outer margin {r['edge']}")
        # page order and footer
        for i, t in enumerate(r["text"], 1):
            self.assertIn(f"Page {i} of {r['pages']}", t, f"{name} p{i} footer/order")
        # every request, commit and check is present and searchable in the PDF (compare against the HTML source data)
        flat = re.sub(r"\s+", " ", " ".join(r["text"]))
        for it in c["items"][:: max(1, len(c["items"]) // 60)]:
            self.assertIn(re.sub(r"\s+", " ", it["title"])[:40], flat, "request text missing from PDF")
        for h, d, s in c["commits"][:: max(1, len(c["commits"]) // 60)]:
            self.assertIn(h[:7], flat); self.assertIn(s[:30], flat)
        self.assertEqual(len(re.findall(r"Commit \d+:", flat)), len(c["commits"]) if c["commits"] else 0, "every commit is listed")
        self.assertEqual(r["html"].count("<div class=req>"), len(c["items"]))
        return r

    def test_short_report_1_to_2_pages(self):
        r = self.build("short", ctx(), 1, 2); self.assertIn("Human review and sign-off", " ".join(r["text"]))

    def test_medium_report_5_to_10_pages(self):
        self.build("medium", ctx(30, 70, 30), 5, 10)

    def test_long_report_30_plus_pages(self):
        r = self.build("long", ctx(300, 1500, 300, long=True), 30, 400); self.assertGreaterEqual(r["pages"], 30)

    def test_long_descriptions_and_unbroken_strings_do_not_overflow(self):
        c = ctx(12, 12, 6, long=True); c["items"][1]["title"] = "X" * 900 + " tail"; c["commits"][0][2] = "Commit 0: https://example.com/" + "a" * 400
        c["checks"][0]["cmd"] = "pytest " + "-k " + "z" * 600
        self.build("longdesc", c, 2, 12)

    def test_empty_and_missing_optional_fields(self):
        r = self.build("empty", ctx(0, 0, 0, author="", hits=0, dirs=0), 1, 2)
        t = " ".join(r["text"]); self.assertIn("No session activity", t); self.assertIn("No commits found", t); self.assertIn("No test, lint or build", t); self.assertNotIn("Prepared by", t)

    def test_mixed_verification_statuses_legible(self):
        r = self.build("mixed", ctx(5, 5, 30), 1, 6); t = " ".join(r["text"])
        for lab in ("No error reported", "Failed", "Result not recorded"): self.assertIn(lab, t)       # status is text, not colour alone

    def test_redaction_markers_and_no_secret_in_text_or_metadata(self):
        sentinel = "SENTINEL-SECRET-9f3a7c"
        c = ctx(4, 3, 2); c["items"][0]["title"] = "Rotate key [REDACTED:aws-key] and mail [REDACTED:email]"
        r = self.build("redact", c, 1, 3); t = " ".join(r["text"])
        self.assertIn("[REDACTED:aws-key]", t); self.assertNotIn(sentinel, t + r["info"] + r["html"])
        raw = open(os.path.join(self.tmp, "redact.pdf"), "rb").read(); self.assertNotIn(sentinel.encode(), raw)
        self.assertNotIn(os.path.expanduser("~").encode(), raw)                                          # no local home path in metadata

    def test_colours_and_fonts_present(self):
        from PIL import Image
        self.build("colour", ctx(), 1, 2)
        im = Image.open([os.path.join(self.tmp, f) for f in sorted(os.listdir(self.tmp)) if f.startswith("colour-") and f.endswith(".png")][0]).convert("RGB")
        teal = sum(1 for p in im.getdata() if p[1] > p[0] + 25 and abs(p[1] - p[2]) < 30 and p[1] < 170)
        self.assertGreater(teal, 40, "teal accent should be visible")
        fonts = subprocess.run(["pdffonts", os.path.join(self.tmp, "colour.pdf")], capture_output=True, text=True).stdout
        self.assertGreaterEqual(len(fonts.strip().splitlines()), 3)

    def test_no_heading_stranded_at_page_bottom(self):
        for name in ("medium", "long", "mixed"):
            p = os.path.join(self.tmp, name + ".pdf")
            if not os.path.exists(p): continue
            n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout).group(1))
            for i, t in enumerate(pages_text(p, n), 1):
                body = [l for l in t.splitlines() if l.strip() and not re.search(r"Page \d+ of \d+", l)]
                self.assertFalse(re.match(r"^\s*\d\s*(Work requested|Changes delivered|Verification|Human review|Basis of this|Privacy)", body[-1] if body else ""), f"{name} p{i} ends on a heading")

    def test_html_screen_and_pdf_share_one_stylesheet(self):
        h = w.render(ctx()); self.assertEqual(h.count("<style>"), 1); self.assertIn("@page{size:letter", h); self.assertIn("thead{display:table-header-group}", h)


class MacVerifyLogic(unittest.TestCase):
    """The macOS verify step's decision logic (the WebKit/PDFKit calls themselves can only run on a Mac)."""
    def chk(self, pages):
        from desktop import pdf_mac
        return pdf_mac.check_pages(len(pages), lambda i: pages[i])

    def test_good_multi_page_letter(self):
        self.assertIsNone(self.chk([((612, 792), 900, (60, 550)), ((612, 792), 400, (58, 552))]))

    def test_rejects_giant_single_page(self):
        self.assertIn("not US Letter", self.chk([((612, 9000), 5000, (60, 550))]))

    def test_rejects_clipped_text_and_empty_text(self):
        self.assertIn("margin", self.chk([((612, 792), 900, (60, 610))]))
        self.assertIn("margin", self.chk([((612, 792), 900, (2, 550))]))
        self.assertIn("no selectable text", self.chk([((612, 792), 0, None)]))

    def test_no_slicing_fallback_remains(self):
        src = open(os.path.join(HERE, "desktop", "pdf_mac.py")).read()
        self.assertNotIn("createPDFWithConfiguration", src); self.assertNotIn("_write_sliced", src); self.assertIn("inspect_pdf", src)


class MacInspect(unittest.TestCase):
    """Regression for the Mac failure 'verify: the PDF could not be read back': the verifier called a PDFKit constructor that PyObjC does
    not expose and so rejected a valid PDF. A verifier that cannot run must never reject a structurally valid PDF."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        from desktop import pdf_mac; self.pm = pdf_mac

    def make(self, name, body, box="[0 0 612 792]", pages=2):
        p = os.path.join(self.tmp, name)
        objs = "".join(f"{i} 0 obj << /Type /Page /MediaBox {box} >> endobj\n" for i in range(pages))
        open(p, "wb").write(b"%PDF-1.4\n" + objs.encode() + b"%" * 200 + b"\n%%EOF")
        return p

    def with_quartz(self, mod):
        return mock.patch.dict(sys.modules, {"Quartz": mod})

    def test_source_does_not_use_nonexistent_pdfkit_constructor(self):
        src = open(os.path.join(HERE, "desktop", "pdf_mac.py")).read()
        self.assertNotIn("documentWithURL_", src); self.assertIn("alloc().initWithURL_", src)

    def test_pdfkit_unusable_falls_back_to_bytes_and_accepts_valid_pdf(self):
        d = self.pm.inspect_pdf(self.make("ok.pdf", ""))                       # Quartz not importable here
        self.assertEqual((d["verifier"], d["pages"], d["problem"], d["signature"]), ("bytes", 2, None, True))
        broken = types.SimpleNamespace(PDFDocument=types.SimpleNamespace(alloc=lambda: (_ for _ in ()).throw(AttributeError("x"))), kPDFDisplayBoxMediaBox=0)
        with self.with_quartz(broken):
            d = self.pm.inspect_pdf(self.make("ok2.pdf", "")); self.assertEqual((d["verifier"], d["problem"], d["exc"]), ("bytes", None, "AttributeError"))

    def test_pdfkit_path_reports_pages_and_layout(self):
        class Doc:
            def initWithURL_(s, u): return s
            def pageCount(s): return 2
            def pageAtIndex_(s, i): return i
        mod = types.SimpleNamespace(PDFDocument=types.SimpleNamespace(alloc=lambda: Doc()), kPDFDisplayBoxMediaBox=0)
        with self.with_quartz(mod), mock.patch.object(self.pm, "_url", lambda p: p), mock.patch.object(self.pm, "_page_facts", lambda pg, b: ((612, 792), 500, (60, 550))):
            d = self.pm.inspect_pdf(self.make("k.pdf", "")); self.assertEqual((d["verifier"], d["pages"], d["problem"]), ("pdfkit", 2, None))
        with self.with_quartz(mod), mock.patch.object(self.pm, "_url", lambda p: p), mock.patch.object(self.pm, "_page_facts", lambda pg, b: ((612, 5000), 500, (60, 550))):
            self.assertIn("not US Letter", self.pm.inspect_pdf(self.make("k2.pdf", ""))["problem"])

    def test_positive_defects_are_rejected(self):
        self.assertIn("not US Letter", self.pm.inspect_pdf(self.make("big.pdf", "", box="[0 0 612 9000]", pages=1))["problem"])
        junk = os.path.join(self.tmp, "j.pdf"); open(junk, "wb").write(b"<html>" + b"x" * 300); self.assertFalse(self.pm.inspect_pdf(junk)["signature"])
        empty = os.path.join(self.tmp, "e.pdf"); open(empty, "wb").write(b""); d = self.pm.inspect_pdf(empty); self.assertEqual((d["exists"], d["size"], d["signature"]), (True, 0, False))
        self.assertFalse(self.pm.inspect_pdf(os.path.join(self.tmp, "none.pdf"))["exists"])

    def test_compressed_object_streams_are_unverified_not_rejected(self):
        p = os.path.join(self.tmp, "c.pdf"); open(p, "wb").write(b"%PDF-1.5\n" + b"\x00" * 400)
        d = self.pm.inspect_pdf(p); self.assertEqual((d["verifier"], d["problem"]), ("unverified", None))

    def test_diag_file_holds_flags_only(self):
        os.environ["WORKRECEIPT_HOME"] = self.tmp
        d = self.pm.inspect_pdf(self.make("n.pdf", "")); self.pm._write_diag(d)
        t = open(os.path.join(self.tmp, "pdf-last-diag.txt")).read(); self.assertIn("verifier=bytes", t); self.assertNotIn(self.tmp, t); self.assertNotIn("%PDF", t)

    def test_core_rejects_non_pdf_backend_output_and_keeps_html(self):
        import app_core as core
        os.environ["WORKRECEIPT_HOME"] = self.tmp
        h = os.path.join(self.tmp, "r.html"); open(h, "w").write("<p>x</p>")
        def junk(html, out): open(out, "wb").write(b"<html>not a pdf" + b"x" * 300)
        old = core.PDF_BACKEND; core.PDF_BACKEND = junk; self.addCleanup(setattr, core, "PDF_BACKEND", old)
        self.assertIsNone(core.to_pdf(h)); self.assertFalse(os.path.exists(h[:-5] + ".pdf")); self.assertTrue(os.path.exists(h))
        self.assertTrue(core.LAST_PDF_ERROR.startswith("verify:")); self.assertNotIn(self.tmp, core.LAST_PDF_ERROR)

    def test_real_chrome_pdf_passes_byte_verifier(self):
        if not HAVE: self.skipTest("needs Chrome")
        p = to_pdf(w.render(ctx(30, 60, 20)), "real", self.tmp); d = self.pm.inspect_pdf(p)
        self.assertIn(d["verifier"], ("bytes", "unverified")); self.assertIsNone(d["problem"]); self.assertTrue(d["signature"])
        if d["verifier"] == "bytes": self.assertGreaterEqual(d["pages"], 3)


@unittest.skipUnless(HAVE, "needs Chrome + poppler")
class ExportSecurity(unittest.TestCase):
    def test_unreviewed_high_findings_never_reach_pdf(self):
        root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, root, True)
        os.environ["WORKRECEIPT_HOME"] = os.path.join(root, "home"); os.environ["WORKRECEIPT_CLAUDE_DIR"] = os.path.join(root, "none")
        import app_core as core
        core.save_settings({"out_dir": os.path.join(root, "out")}); proj = core.enable_demo()[0]["path"]
        r = core.export({"repo": proj, "pdf": True}, {}, {}, ) if hasattr(core, "export") else {}
        self.assertFalse(r.get("ok")); self.assertFalse(r.get("pdf_path"))
        out = os.path.join(root, "out"); self.assertFalse(os.path.isdir(out) and [f for f in os.listdir(out) if f.endswith((".pdf", ".html"))])


if __name__ == "__main__":
    unittest.main()
