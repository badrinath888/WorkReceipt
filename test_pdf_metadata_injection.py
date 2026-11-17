"""Regression tests for the macOS finding "native: private text in PDF metadata is detected - the product validator accepted a private PDF title (got [])".
SYNTHETIC data only. Every test writes a private title/field into the information dictionary of a REAL printed client report (so the injection is
certain to be in the file, whatever the print engine does with <title>) and then requires BOTH the product validator (client_safe.validate_pdf) and
the independent checker (scripts/pdfkit_check.verify) to refuse it, with the poppler extractor and with the pypdf extractor (the Mac without poppler).
Also pinned here: the footer-token tolerance that made the Mac browser test time out without poppler (pypdf reads the page number glued to the footer name)."""
import os, shutil, sys, tempfile, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "scripts"))
os.environ.setdefault("WRV_SELFTEST", "1")      # pdfkit_check reads this at import: off macOS it falls back to pypdf/poppler (same as test_validation_scripts)
import app_core as core, client_safe as cs, pdfkit_check as pk
from test_client_safe import Base, draft, item, CANARIES, HAS_CHROME
try:
    import pypdf  # noqa: F401
except ImportError:
    pypdf = None

POPPLER = ("pdftotext", "pdfinfo", "pdftoppm")
_REAL_WHICH = shutil.which


def hide_poppler():
    """What a Mac without Homebrew poppler looks like to client_safe.pdf_facts_cli (falls back to pypdf)."""
    return mock.patch("shutil.which", lambda n, *a, **k: None if os.path.basename(str(n)) in POPPLER else _REAL_WHICH(n, *a, **k))


def extractors():
    out = [("pypdf", hide_poppler)]
    if all(_REAL_WHICH(t) for t in ("pdftotext", "pdfinfo")):
        out.append(("poppler", mock.MagicMock))                 # a no-op context manager: leave PATH alone
    return out


@unittest.skipUnless(HAS_CHROME and pypdf, "needs Chrome and pypdf")
class InjectedPdfMetadata(unittest.TestCase):
    TERMS, LOCAL = ["zelda-quill", "oracle-fin-01"], ["zelda-quill"]

    def setUp(self):
        self.r, iss, _ = cs.build_report(draft(), {"commits": set(), "checks_total": 0, "checks_ok": 0}, "2026-11-01 to 2026-11-30", [], [])
        self.html = cs.render_client(self.r)
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        h = os.path.join(self.tmp, "r.html"); open(h, "w", encoding="utf-8").write(self.html)
        self.base = core.to_pdf(h); self.assertTrue(self.base, "chrome could not print")
        self.title = cs.title_of(self.r)
        patcher = mock.patch.object(pk, "SELFTEST", True); patcher.start(); self.addCleanup(patcher.stop)   # pypdf stands in for PDFKit off macOS

    def inject(self, name="inj", **fields):
        out = os.path.join(self.tmp, name + ".pdf")
        back = pk.inject_info(self.base, out, fields)
        for k, v in fields.items():
            self.assertEqual(back.get(k), v, f"test bug: the injected {k} is not in the PDF the checkers will read")     # the injection LANDED
        return out

    def product(self, path, facts=None):
        return cs.validate_pdf(path, self.r, self.html, facts if facts is not None else cs.pdf_facts_cli(path), self.TERMS, self.LOCAL)

    def independent(self, path):
        return pk.verify(path, self.html, title=self.title)[0]

    # ---- the confirmed failure ----
    def test_private_pdf_title_is_rejected_by_both_checkers_with_every_extractor(self):
        for private in ("oracle-fin-01 internal", "Quarterly payroll notes", "Untitled"):          # a canary, an ordinary private-looking title, a generic one
            for label, ctx in extractors():
                with self.subTest(title=private, extractor=label), ctx():
                    path = self.inject("t", Title=private)
                    got = self.product(path)
                    self.assertIn("metadata", got); self.assertIn("metadata_title", got)
                    ind = self.independent(path)
                    self.assertIn("metadata_title", ind)
                    if private == "oracle-fin-01 internal":
                        self.assertIn("canary_in_metadata", ind)

    def test_title_the_extractor_dropped_is_still_caught_from_the_file_itself(self):
        """The macOS run got [] from the product validator. If PDFKit (or any extractor) returns no Title, the file's own information dictionary is still read."""
        for private in ("oracle-fin-01 internal", "Quarterly payroll notes"):
            path = self.inject("drop", Title=private)
            facts = cs.pdf_facts_cli(path)
            for blind in ({}, {"Title": ""}, {"Author": "", "Subject": ""}):
                with self.subTest(title=private, extractor_reports=blind):
                    got = self.product(path, dict(facts, meta=blind))
                    self.assertIn("metadata", got); self.assertIn("metadata_title", got)

    def test_other_information_fields_are_rejected(self):
        for field, val in (("Author", "Zed Author"), ("Subject", "internal"), ("Keywords", "billing, payroll"), ("Company", "Globex"), ("Department", "Finance")):
            for label, ctx in extractors():
                with self.subTest(field=field, extractor=label), ctx():
                    path = self.inject("f", **{field: val})
                    got = self.product(path)
                    self.assertIn("metadata", got); self.assertIn("metadata_" + field.lower(), got)
                    if field in ("Author", "Subject", "Keywords"):
                        self.assertTrue(self.independent(path))

    def test_the_refusal_never_contains_the_private_value(self):
        path = self.inject("v", Title="oracle-fin-01 internal")
        resp = core._blocked("validation", self.product(path))
        self.assertNotIn("oracle", str(resp).lower()); self.assertIn("a PDF title that is not the report title", resp["message"])

    # ---- the checks must not turn into over-blocking ----
    def test_clean_pdf_and_allowed_titles_are_still_accepted(self):
        for label, ctx in extractors():
            with self.subTest(extractor=label), ctx():
                self.assertEqual(self.product(self.base), [])
                self.assertEqual(self.independent(self.base), [])
                self.assertEqual(self.product(self.inject("ok", Title=self.title)), [])             # exactly the approved report title
                self.assertEqual(self.product(self.inject("empty", Title="")), [])                  # an empty field carries nothing

    # ---- footer text read without poppler (the Mac browser-test timeout) ----
    def test_glued_footer_text_is_footer_but_other_extra_text_is_not(self):
        facts = cs.pdf_facts_cli(self.base)
        for ok in ("1WorkReceipt", "Page 2 of 3 WorkReceipt", "WorkReceipt1", "12workreceiptpage3"):
            with self.subTest(ok):
                self.assertNotIn("pdf_text", self.product(self.base, dict(facts, text=facts["text"] + "\n" + ok)))
        for bad in ("1WorkReceipt leaked", "1workreceiptsecret", "workreceiptq", "reportx"):
            with self.subTest(bad):
                self.assertIn("pdf_text", self.product(self.base, dict(facts, text=facts["text"] + "\n" + bad)))

    def test_real_chrome_pdf_passes_with_the_pypdf_extractor(self):
        with hide_poppler():
            facts = cs.pdf_facts_cli(self.base)
            self.assertIn("pypdf", repr(type(facts)) + "pypdf")              # (extractor chosen by pdf_facts_cli; text must come back)
            self.assertTrue(facts["text"].strip())
            self.assertEqual(self.product(self.base, facts), [])


class RawInfoParser(unittest.TestCase):
    """Pure parsing of the information dictionary from file bytes; no Chrome needed."""
    def pdf(self, info_body, trailer="/Info 5 0 R"):
        return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n5 0 obj\n<<" + info_body + b">>\nendobj\ntrailer\n<< /Root 1 0 R " + trailer.encode() + b" >>\n%%EOF\n")

    def test_literal_hex_utf16_and_escapes(self):
        got = cs.raw_info_fields(self.pdf(b"/Title (Quarterly \\(draft\\) \\101\\n) /Author <FEFF005A006500640020>/Producer (Skia/PDF m153) /CreationDate (D:20261117)"))
        self.assertEqual(got["Title"], "Quarterly (draft) A\n"); self.assertEqual(got["Author"], "Zed "); self.assertEqual(got["Producer"], "Skia/PDF m153")

    def test_nested_parentheses_and_a_value_containing_dict_end(self):
        got = cs.raw_info_fields(self.pdf(b"/Title (a (b) >> c) /Subject (after)"))
        self.assertEqual(got["Title"], "a (b) >> c"); self.assertEqual(got["Subject"], "after")        # a '>>' inside a string must not hide later fields

    def test_no_info_or_missing_object_gives_nothing(self):
        self.assertEqual(cs.raw_info_fields(self.pdf(b"/Title (x)", trailer="")), {})
        self.assertEqual(cs.raw_info_fields(self.pdf(b"/Title (x)", trailer="/Info 9 0 R")), {})

    def test_last_information_dictionary_wins(self):
        data = self.pdf(b"/Title (old)") + b"5 0 obj\n<</Title (new)>>\nendobj\ntrailer\n<< /Info 5 0 R >>\n"
        self.assertEqual(cs.raw_info_fields(data)["Title"], "new")


@unittest.skipUnless(HAS_CHROME, "needs Chrome")
class ExportWithoutPoppler(Base):
    """The Mac run had no poppler: the whole client export (the browser test's 90 s timeout) went through the pypdf extractor and was refused with pdf_text."""
    def test_client_pdf_export_succeeds_and_is_clean_with_the_pypdf_extractor(self):
        d = draft([item("Rebuilt the invoice screen so customers can pay online", status="delivered", commits=self.f.commits[:1])], verification={"mode": "auto"})
        with hide_poppler():
            r = self.f.export(d, pdf=True)
        self.assertTrue(r["ok"] and r["pdf_path"] and not r["pdf_failed"], r)
        raw = open(r["pdf_path"], "rb").read().lower()
        for k, v in CANARIES.items():
            self.assertNotIn(v.lower().encode(), raw, k)

    def test_client_export_refuses_a_pdf_whose_title_was_changed_after_printing(self):
        if pypdf is None:
            self.skipTest("needs pypdf")
        d = draft(); t = self.f.approve(d)["token"]
        real = core.to_pdf

        def tampered(p):
            out = real(p)
            pk.inject_info(out, out + ".t", {"Title": "oracle-fin-01 internal"}); os.replace(out + ".t", out)
            return out
        core.to_pdf = tampered
        try:
            with hide_poppler():
                r = core.client_export(self.f.o, d, self.f.ap, t, True)
        finally:
            core.to_pdf = real
        self.assertFalse(r["ok"]); self.assertEqual(r["reason"], "validation"); self.assertEqual(self.out_files(), [])
        self.assertNotIn("oracle", str(r).lower())


if __name__ == "__main__":
    unittest.main()
