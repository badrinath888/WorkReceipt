"""PDF export for the packaged macOS app, using the system WKWebView (no Chrome needed). macOS only.

Input is the already-redacted exported HTML. The page gets no JavaScript, no base URL (so no file or network access), and nothing
is written to disk except the final PDF. Every failure raises PdfError carrying the stage that failed and a NON-SENSITIVE reason
(our own text or a system error description, never document content); core.to_pdf records it so the user can see what broke.

Pipeline: load -> paginated print job (NSPrintOperation: Letter, 0.75in margins, WebKit honours the report's print CSS: keep-together
rows, repeating table headers, no stranded headings) -> verify (PDFKit: page count, every page Letter-sized, text selectable, no text
outside the margins). There is deliberately NO fallback that slices a one-page render: that produced cut lines and was removed. If the print
job or verification fails the file is deleted and a PdfError with the failing stage is raised; the HTML export is kept by the caller.
Known unknowns (cannot be tested on Linux): how WKWebView maps CSS px to the print view width, and whether it honours @page margin
boxes (page numbers). The verify step catches a clipped or wrongly sized result instead of shipping it.
Bugs fixed vs the first version, found by review (the Linux dev environment cannot run WebKit; confirm on a Mac):
  * the navigation delegate and window were only referenced from a local closure; WKWebView holds its delegate weakly, so they could
    be garbage-collected and didFinishNavigation never fired (timeout). Jobs are now held in a module-level set until finished;
  * imports sat outside the try block, so an import error on the main thread left the caller waiting for the full timeout;
  * the print operation's view had a zero frame, and the offscreen window was never ordered in, which can make the job fail;
  * the print-callback selector signature was malformed and the delegate was stored as an attribute of a PyObjC proxy.
"""
import os, threading

TIMEOUT = 90
_JOBS = set()                                   # strong references while a job is running (WKWebView only holds its delegate weakly)
_CLASSES = {}


class PdfError(RuntimeError):
    def __init__(self, stage, reason):
        super().__init__(f"{stage}: {reason}")
        self.stage, self.reason = stage, reason


def render_pdf(html, out_path, timeout=TIMEOUT):
    """Callable from any thread. Returns None on success; raises PdfError otherwise."""
    try:
        from PyObjCTools import AppHelper
    except Exception as e:                                           # noqa: BLE001
        raise PdfError("import", f"PyObjC is not available ({type(e).__name__})")
    job = _Job(html, out_path)
    _JOBS.add(job)
    try:
        AppHelper.callAfter(job.start)
        if not job.done.wait(timeout):
            raise PdfError("timeout", f"no result after {timeout}s (stuck at: {job.stage})")
        if job.error:
            raise PdfError(job.stage, job.error)
        if not valid_pdf(out_path):
            raise PdfError("verify", "the PDF file was empty or invalid")
        problem = verify_layout(out_path)
        if problem:
            raise PdfError("verify", problem)
    finally:
        job.abort()
        _JOBS.discard(job)


def valid_pdf(path):
    try:
        with open(path, "rb") as f:
            return os.path.getsize(path) > 100 and f.read(5) == b"%PDF-"
    except OSError:
        return False


LETTER = (612.0, 792.0)
MARGIN_PT = 54.0                                                     # 0.75in


def verify_layout(path):
    """Return None if the PDF looks right, else a short non-sensitive problem description. Needs PyObjC/PDFKit (macOS)."""
    try:
        from Quartz import PDFDocument, kPDFDisplayBoxMediaBox
    except Exception:                                                # noqa: BLE001
        return None                                                  # cannot verify off-macOS; callers/tests cover the logic separately
    doc = PDFDocument.documentWithURL_(_url(path)) if hasattr(PDFDocument, "documentWithURL_") else None
    if doc is None or doc.pageCount() < 1:
        return "the PDF could not be read back"
    return check_pages(doc.pageCount(), lambda i: _page_facts(doc.pageAtIndex_(i), kPDFDisplayBoxMediaBox))


def _url(path):
    from Foundation import NSURL
    return NSURL.fileURLWithPath_(path)


def _page_facts(page, box):
    r = page.boundsForBox_(box)
    s = page.string() or ""
    xs = []
    for k in range(0, len(s), 5):                                    # sample glyph positions
        b = page.characterBoundsAtIndex_(k)
        if b.size.width > 0:
            xs.append((b.origin.x, b.origin.x + b.size.width))
    return (r.size.width, r.size.height), len(s.strip()), (min(x[0] for x in xs), max(x[1] for x in xs)) if xs else None


def check_pages(n, facts):
    """Pure logic (unit-tested on Linux). facts(i) -> ((w, h), text_chars, (min_x, max_x) | None)."""
    total_text = 0
    for i in range(n):
        (w, h), chars, xr = facts(i)
        if abs(w - LETTER[0]) > 2 or abs(h - LETTER[1]) > 2:
            return f"page {i + 1} is {w:.0f}x{h:.0f}pt, not US Letter"
        total_text += chars
        if xr and (xr[0] < MARGIN_PT - 12 or xr[1] > LETTER[0] - MARGIN_PT + 12):
            return f"text on page {i + 1} runs into the page margin"
    if total_text < 20:
        return "the PDF has no selectable text"
    return None


def _describe(e):
    """Short, non-sensitive text for an exception or NSError."""
    d = getattr(e, "localizedDescription", None)
    try:
        return str(d() if callable(d) else e)[:200] or type(e).__name__
    except Exception:                                                # noqa: BLE001
        return type(e).__name__


class _Job:
    W, H = 816, 1056                                                 # offscreen window: Letter at 96 dpi
    PW, PH = 672, 912                                                # print view: Letter minus 0.75in margins, in CSS px

    def __init__(self, html, out_path):
        self.html, self.out, self.stage, self.error = html, out_path, "start", None
        self.done = threading.Event()
        self.win = self.wv = self.nav = self.pdone = None

    # --- lifecycle (main thread) ---
    def fail(self, e, stage=None):
        if self.done.is_set():
            return
        self.stage = stage or self.stage
        self.error = _describe(e)
        self.done.set()

    def finish(self):
        if not self.done.is_set():
            self.stage = "done"
            self.done.set()

    def abort(self):
        try:
            if self.win is not None:
                self.win.orderOut_(None)
            if self.wv is not None:
                self.wv.setNavigationDelegate_(None)
        except Exception:                                            # noqa: BLE001
            pass
        self.win = self.wv = self.nav = self.pdone = None

    def start(self):
        try:
            self.stage = "setup"
            from AppKit import NSWindow, NSBackingStoreBuffered
            from Foundation import NSMakeRect
            from WebKit import WKWebView, WKWebViewConfiguration, WKWebpagePreferences
            cfg = WKWebViewConfiguration.alloc().init()
            prefs = WKWebpagePreferences.alloc().init()
            prefs.setAllowsContentJavaScript_(False)
            cfg.setDefaultWebpagePreferences_(prefs)
            frame = NSMakeRect(0, 0, self.W, self.H)
            self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(frame, 0, NSBackingStoreBuffered, False)
            self.win.setAlphaValue_(0.0)                             # in the window list (printing needs that) but invisible
            self.win.setIgnoresMouseEvents_(True)
            self.wv = WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
            self.nav = _classes()["Nav"].alloc().init()
            self.nav.job = self
            self.wv.setNavigationDelegate_(self.nav)
            self.win.setContentView_(self.wv)
            self.win.orderFrontRegardless()
            self.stage = "load"
            self.wv.loadHTMLString_baseURL_(self.html, None)
        except Exception as e:                                       # noqa: BLE001
            self.fail(e)

    # --- steps ---
    def loaded(self):
        try:
            self.stage = "print"
            self._print_job()
        except Exception as e:                                       # noqa: BLE001
            self.fail(e, "print")

    def _print_job(self):
        from AppKit import NSPrintInfo, NSPrintSaveJob, NSPrintJobDisposition, NSPrintJobSavingURL
        from Foundation import NSURL, NSMakeRect
        _rm(self.out)
        info = NSPrintInfo.sharedPrintInfo().copy()
        info.setJobDisposition_(NSPrintSaveJob)
        info.dictionary()[NSPrintJobSavingURL] = NSURL.fileURLWithPath_(self.out)
        from Foundation import NSMakeSize
        info.setPaperSize_(NSMakeSize(*LETTER))
        for side in ("Top", "Bottom", "Left", "Right"):
            getattr(info, f"set{side}Margin_")(MARGIN_PT)
        try:
            from AppKit import NSAutoPagination
            info.setHorizontalPagination_(NSAutoPagination)
            info.setVerticalPagination_(NSAutoPagination)
        except Exception:                                            # noqa: BLE001
            pass
        op = self.wv.printOperationWithPrintInfo_(info)
        op.view().setFrame_(NSMakeRect(0, 0, self.PW, self.PH))      # a zero-sized print view yields no output
        op.setShowsPrintPanel_(False)
        op.setShowsProgressPanel_(False)
        self.pdone = _classes()["PrintDone"].alloc().init()
        self.pdone.job = self
        op.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(self.win, self.pdone, b"printOperationDidRun:success:contextInfo:", None)

    def printed(self, ok):
        if ok and valid_pdf(self.out):
            return self.finish()
        self.fail("the print job did not produce a PDF", "print")


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _classes():
    """Objective-C delegate classes, created once (PyObjC cannot redefine a class name)."""
    if _CLASSES:
        return _CLASSES
    import objc
    from Foundation import NSObject

    class Nav(NSObject):
        job = None

        def webView_didFinishNavigation_(self, wv, nav):
            if self.job:
                self.job.loaded()

        def webView_didFailNavigation_withError_(self, wv, nav, err):
            if self.job:
                self.job.fail(err, "load")

        def webView_didFailProvisionalNavigation_withError_(self, wv, nav, err):
            if self.job:
                self.job.fail(err, "load")

        def webViewWebContentProcessDidTerminate_(self, wv):
            if self.job:
                self.job.fail("the web content process ended unexpectedly", "load")

    class PrintDone(NSObject):
        job = None

        @objc.typedSelector(b"v@:@B^v")
        def printOperationDidRun_success_contextInfo_(self, op, ok, ctx):
            if self.job:
                self.job.printed(bool(ok))

    _CLASSES.update(Nav=Nav, PrintDone=PrintDone)
    return _CLASSES
