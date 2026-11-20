"""Independent verification of an exported client PDF. On macOS this reads the file with PDFKit (Quartz) plus a raw look at the page
content; it deliberately does NOT reuse client_safe.validate_pdf, so a bug there cannot hide a leak here.

Usage:  python scripts/pdfkit_check.py report.pdf [--html report.html] [--title "Project name"]
Exit 0 = clean, 1 = problems found (codes printed), 2 = could not be checked.
Python >= 3.9 syntax only. SYNTHETIC canaries come from test_client_safe; for a real report pass --canary TEXT (repeatable)."""
import os, re, sys, unicodedata
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELFTEST = os.environ.get("WRV_SELFTEST") == "1"
FORBID = (b"/URI", b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/FileAttachment", b"/OpenAction", b"/GoToR", b"/SubmitForm", b"/RichMedia", b"/XFA", b"/AcroForm", b"/Names", b"/Annots")
LETTER = (612.0, 792.0)
# Strict, anchored: a Creator/Producer may only name a rendering engine (or, for Creator, exactly the product name). Written separately from client_safe on purpose.
ENGINE_RX = re.compile(r"(?i)^(skia/pdf m?\d+|chrome(ium)?(/[\d.]+)?|quartz pdfcontext|macos version [\d.]+ \(build \w+\)( quartz pdfcontext)?|webkit|"
                       r"mozilla/5\.0 \([\w .;:,_-]{1,60}\) applewebkit/[\d.]+ \(khtml, like gecko\)[\w ./-]{0,60})$")
FOOTER_TOKEN = re.compile(r"^(?:\d+|workreceipt|report|work|page|of)+$")      # footer text some extractors glue together ("1workreceipt"); written separately from the product on purpose


def inject_info(src, dst, fields):
    """Test tool: copy `src` to `dst` with extra PDF information-dictionary fields (e.g. {"Title": "..."}). Producer/Creator of the original are
    kept (pypdf would otherwise stamp its own), so the only difference is what the caller injects. Needs pypdf. Returns the fields as read back."""
    import pypdf
    rd = pypdf.PdfReader(src)
    keep = {k: v for k, v in (rd.metadata or {}).items() if k in ("/Producer", "/Creator")}
    w = pypdf.PdfWriter(clone_from=src)
    w.add_metadata({**keep, **{"/" + k.lstrip("/"): v for k, v in fields.items()}})
    with open(dst, "wb") as f:
        w.write(f)
    back = pypdf.PdfReader(dst).metadata or {}
    return {k.lstrip("/"): str(v) for k, v in back.items()}


def squeeze(s):
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", s or "").lower())


class _Vis(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "title", "head"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html):
    p = _Vis()
    p.feed(html)
    return " ".join(p.parts)


def html_title(html):
    m = re.search(r"<title>(.*?)</title>", html or "", re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def tokens(s):
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", s or "").lower())


def inspect(path):
    """-> {backend, pages, sizes, text, meta, annotations, notes[list], skeleton_hits[list], invisible_text(int), streams_ok}."""
    info = {"backend": None, "pages": 0, "sizes": [], "text": "", "meta": {}, "annotations": 0, "skeleton_hits": [], "invisible_text": 0, "streams_ok": True}
    raw = open(path, "rb").read()
    skeleton = re.sub(rb"stream\r?\n.*?\r?\nendstream", b"", raw, flags=re.S)
    info["skeleton_hits"] = [t.decode() for t in FORBID if t in skeleton]
    try:
        from Quartz import PDFDocument, kPDFDisplayBoxMediaBox
        from Foundation import NSURL
        doc = PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(path))
        if doc is None:
            raise RuntimeError("PDFKit could not open the file")
        info["backend"] = "PDFKit"
        n = int(doc.pageCount())
        info["pages"] = n
        info["text"] = str(doc.string() or "")
        attrs = doc.documentAttributes() or {}
        info["meta"] = {k: str(attrs.get(k) or "") for k in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer")}
        for i in range(n):
            pg = doc.pageAtIndex_(i)
            b = pg.boundsForBox_(kPDFDisplayBoxMediaBox)
            info["sizes"].append((float(b.size.width), float(b.size.height)))
            info["annotations"] += len(pg.annotations() or [])
    except ImportError:
        if not SELFTEST:
            raise RuntimeError("PDFKit (pyobjc-framework-Quartz) is not available; this check must run on macOS")
        from pypdf import PdfReader
        rd = PdfReader(path)
        info["backend"] = "pypdf (selftest fallback)"
        info["pages"] = len(rd.pages)
        info["text"] = "\n".join((p.extract_text() or "") for p in rd.pages)
        import shutil, subprocess
        if shutil.which("pdftotext"):                            # more faithful than pypdf when poppler is installed
            r = subprocess.run(["pdftotext", "-q", "-layout", path, "-"], capture_output=True, timeout=60)
            if r.returncode == 0:
                info["text"] = r.stdout.decode("utf-8", "replace")
        md = rd.metadata or {}
        info["meta"] = {k: str(md.get("/" + k) or "") for k in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer")}
        for p in rd.pages:
            info["sizes"].append((float(p.mediabox.width), float(p.mediabox.height)))
            info["annotations"] += len(p.get("/Annots") or [])
    try:                                                         # content streams: invisible-text render mode (3 Tr) is how text is hidden but kept extractable
        from pypdf import PdfReader
        for p in PdfReader(path).pages:
            c = p.get_contents()
            data = c.get_data() if c is not None else b""
            info["invisible_text"] += len(re.findall(rb"(?<![\d.])3\s+Tr\b", data))
    except Exception:                                            # noqa: BLE001
        info["streams_ok"] = False
    return info


def verify(path, html, expect=(), canaries=None, title=None):
    """-> (failure codes, info). Empty codes = clean. Canaries default to the synthetic set used by the test workspace."""
    if canaries is None:
        from test_client_safe import CANARIES
        canaries = list(CANARIES.values())
    info = inspect(path)
    bad = []
    if info["pages"] < 1:
        bad.append("unreadable")
    if not info["text"].strip():
        bad.append("no_text")
    if not info["streams_ok"]:
        bad.append("content_streams_unreadable")
    if info["invisible_text"]:
        bad.append("hidden_text_render_mode")
    if info["annotations"]:
        bad.append("annotations")
    if info["skeleton_hits"]:
        bad.append("forbidden_objects:" + ",".join(sorted(set(info["skeleton_hits"]))))
    if any(abs(w - LETTER[0]) > 2 or abs(h - LETTER[1]) > 2 for w, h in info["sizes"]):
        bad.append("page_size")
    m = info["meta"]
    if m.get("Title", "") not in ("", html_title(html), title):
        bad.append("metadata_title")
    if any(m.get(k) for k in ("Author", "Subject", "Keywords")):
        bad.append("metadata_extra")
    if m.get("Producer", "").strip() and not ENGINE_RX.match(m["Producer"].strip()):
        bad.append("metadata_producer")
    if m.get("Creator", "").strip() and not ENGINE_RX.match(m["Creator"].strip()) and m["Creator"] != "WorkReceipt":
        bad.append("metadata_creator")
    sq_text, sq_meta = squeeze(info["text"]), squeeze(" ".join(m.values()))
    for c in canaries:
        s = squeeze(c)
        if s and s in sq_text:
            bad.append("canary_in_text")
            break
    for c in canaries:
        s = squeeze(c)
        if s and s in sq_meta:
            bad.append("canary_in_metadata")
            break
    for c in canaries:
        if c.encode().lower() in open(path, "rb").read().lower():
            bad.append("canary_in_raw_bytes")
            break
    vis = html_text(html)
    sq_html = squeeze(vis + " " + (title or ""))
    extra = [t for t in tokens(info["text"]) if t not in sq_html and not FOOTER_TOKEN.match(t)]
    if extra:
        bad.append("text_not_in_html(%d)" % len(extra))
    html_tokens = tokens(vis)
    if html_tokens:
        missing = [t for t in html_tokens if t not in sq_text]
        if len(missing) > max(2, 0.02 * len(html_tokens)):
            bad.append("html_text_missing_from_pdf(%d)" % len(missing))
    for e in expect:
        if squeeze(e) not in sq_text:
            bad.append("expected_text_missing")
            break
    return bad, info


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("--html"); ap.add_argument("--title"); ap.add_argument("--canary", action="append", default=[])
    a = ap.parse_args(argv)
    html = open(a.html, encoding="utf-8").read() if a.html else None
    try:
        if html is None:
            info = inspect(a.pdf)
            bad = [c for c, v in (("annotations", info["annotations"]), ("hidden_text_render_mode", info["invisible_text"]), ("forbidden_objects", info["skeleton_hits"])) if v]
            bad += ["canary_in_text" for c in a.canary if squeeze(c) in squeeze(info["text"])]
        else:
            bad, info = verify(a.pdf, html, canaries=a.canary or None, title=a.title)
    except Exception as e:                                       # noqa: BLE001
        print("could not check:", type(e).__name__, e)
        return 2
    print(f"{info['backend']}: {info['pages']} page(s), {info['annotations']} annotation(s), producer {info['meta'].get('Producer')!r}")
    print("CLEAN" if not bad else "PROBLEMS: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
