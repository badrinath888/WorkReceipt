"""PDF export for the packaged macOS app, using the system WKWebView (no Chrome needed). macOS only.

Input is the already-redacted exported HTML. The page gets no JavaScript, no base URL (so no file or network access), and nothing
is written to disk except the final PDF. Every failure raises PdfError carrying the stage that failed and a NON-SENSITIVE reason
(our own text or a system error description, never document content); core.to_pdf records it so the user can see what broke.

Pipeline (each step is checked; the next is tried only if the previous cannot produce a valid PDF):
  load -> 1. paginated print job (NSPrintOperation, proper Letter pages)
       -> 2. fallback: whole-page createPDF sliced into Letter-proportioned pages with PDFKit.
Bugs fixed vs the first version, found by review (the Linux dev environment cannot run WebKit; confirm on a Mac):
  * the navigation delegate and window were only referenced from a local closure; WKWebView holds its delegate weakly, so they could
    be garbage-collected and didFinishNavigation never fired (timeout). Jobs are now held in a module-level set until finished;
  * imports sat outside the try block, so an import error on the main thread left the caller waiting for the full timeout;
  * the print operation's view had a zero frame, and the offscreen window was never ordered in, which can make the job fail;
  * the print-callback selector signature was malformed and the delegate was stored as an attribute of a PyObjC proxy.
"""
import math, os, threading

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
    finally:
        job.abort()
        _JOBS.discard(job)


def valid_pdf(path):
    try:
        with open(path, "rb") as f:
            return os.path.getsize(path) > 100 and f.read(5) == b"%PDF-"
    except OSError:
        return False


def _describe(e):
    """Short, non-sensitive text for an exception or NSError."""
    d = getattr(e, "localizedDescription", None)
    try:
        return str(d() if callable(d) else e)[:200] or type(e).__name__
    except Exception:                                                # noqa: BLE001
        return type(e).__name__


class _Job:
    W, H = 816, 1056                                                 # Letter at 96 dpi

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
        except Exception:                                            # noqa: BLE001
            self._slice_fallback()

    def _print_job(self):
        from AppKit import NSPrintInfo, NSPrintSaveJob, NSPrintJobDisposition, NSPrintJobSavingURL
        from Foundation import NSURL, NSMakeRect
        _rm(self.out)
        info = NSPrintInfo.sharedPrintInfo().copy()
        info.setJobDisposition_(NSPrintSaveJob)
        info.dictionary()[NSPrintJobSavingURL] = NSURL.fileURLWithPath_(self.out)
        for side in ("Top", "Bottom", "Left", "Right"):
            getattr(info, f"set{side}Margin_")(36)
        try:
            from AppKit import NSAutoPagination
            info.setHorizontalPagination_(NSAutoPagination)
            info.setVerticalPagination_(NSAutoPagination)
        except Exception:                                            # noqa: BLE001
            pass
        op = self.wv.printOperationWithPrintInfo_(info)
        op.view().setFrame_(NSMakeRect(0, 0, self.W, self.H))        # a zero-sized print view yields no output
        op.setShowsPrintPanel_(False)
        op.setShowsProgressPanel_(False)
        self.pdone = _classes()["PrintDone"].alloc().init()
        self.pdone.job = self
        op.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(self.win, self.pdone, b"printOperationDidRun:success:contextInfo:", None)

    def printed(self, ok):
        if ok and valid_pdf(self.out):
            return self.finish()
        self._slice_fallback()

    def _slice_fallback(self):
        try:
            self.stage = "render"
            _rm(self.out)
            from WebKit import WKPDFConfiguration

            def handler(data, error):
                try:
                    if error is not None or data is None:
                        return self.fail(error or "WebKit returned no data", "render")
                    self.stage = "paginate"
                    self._write_sliced(data)
                    self.finish()
                except Exception as e:                               # noqa: BLE001
                    self.fail(e, "paginate")
            self.wv.createPDFWithConfiguration_completionHandler_(WKPDFConfiguration.alloc().init(), handler)
        except Exception as e:                                       # noqa: BLE001
            self.fail(e, "render")

    def _write_sliced(self, data):
        from Foundation import NSMakeRect
        from Quartz import PDFDocument, kPDFDisplayBoxCropBox, kPDFDisplayBoxMediaBox
        src = PDFDocument.alloc().initWithData_(data)
        if src is None or src.pageCount() < 1:
            raise RuntimeError("WebKit produced an unreadable PDF")
        page = src.pageAtIndex_(0)
        r = page.boundsForBox_(kPDFDisplayBoxMediaBox)
        w, h = r.size.width, r.size.height
        ph = w * 11.0 / 8.5
        n = max(1, int(math.ceil(h / ph - 1e-6)))
        out = PDFDocument.alloc().init()
        for k in range(n):
            p = page.copy()
            box = NSMakeRect(r.origin.x, r.origin.y + h - (k + 1) * ph, w, ph)    # slices run top to bottom
            p.setBounds_forBox_(box, kPDFDisplayBoxMediaBox)
            p.setBounds_forBox_(box, kPDFDisplayBoxCropBox)
            out.insertPage_atIndex_(p, k)
        if not out.writeToFile_(self.out):
            raise RuntimeError("could not write the PDF file")


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
