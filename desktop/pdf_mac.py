"""PDF export for the packaged macOS app, using the system WKWebView (no Chrome needed). macOS only.

STATUS: written against the PyObjC/WebKit APIs but NOT yet run on a Mac (the development environment is Linux).
See docs/MAC_VALIDATION.md. Input is the already-redacted exported HTML; JavaScript is disabled and no file or network
access is granted to the page, and nothing is written except the final PDF."""
import os, threading

TIMEOUT = 60


def render_pdf(html, out_path, timeout=TIMEOUT):
    """Callable from any thread. Raises on failure (core.to_pdf then reports 'PDF could not be created'; the HTML is kept)."""
    from PyObjCTools import AppHelper
    done, box = threading.Event(), {}
    AppHelper.callAfter(_start, html, out_path, done, box)
    if not done.wait(timeout):
        raise TimeoutError("PDF rendering timed out")
    if box.get("error") or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("PDF rendering failed")


def _start(html, out_path, done, box):                    # main thread
    import objc
    from AppKit import (NSObject, NSWindow, NSMakeRect, NSBackingStoreBuffered, NSPrintInfo, NSPrintSaveJob, NSPrintJobDisposition,
                        NSPrintJobSavingURL, NSPrintInfo as PI)
    from Foundation import NSURL
    from WebKit import WKWebView, WKWebViewConfiguration, WKWebpagePreferences

    def finish(err=None):
        box["error"] = err
        keep.clear()
        done.set()

    keep = []

    class Nav(NSObject):
        def webView_didFinishNavigation_(self, wv, nav):
            try:
                _print(wv, out_path, finish)
            except Exception as e:                       # noqa: BLE001
                finish(e)

        def webView_didFailNavigation_withError_(self, wv, nav, err):
            finish(err)

    try:
        cfg = WKWebViewConfiguration.alloc().init()
        prefs = WKWebpagePreferences.alloc().init()
        prefs.setAllowsContentJavaScript_(False)
        cfg.setDefaultWebpagePreferences_(prefs)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(-20000, -20000, 816, 1056), 0, NSBackingStoreBuffered, False)
        wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 816, 1056), cfg)
        nav = Nav.alloc().init()
        wv.setNavigationDelegate_(nav)
        win.setContentView_(wv)
        keep.extend([win, wv, nav])
        wv.loadHTMLString_baseURL_(html, None)           # no baseURL: the page cannot reach local files
    except Exception as e:                               # noqa: BLE001
        finish(e)


def _print(wv, out_path, finish):
    """Paginated PDF through a save-to-file print job; falls back to a single-page PDF if the print job cannot run."""
    import objc
    from AppKit import NSObject, NSPrintInfo, NSPrintSaveJob, NSPrintJobDisposition, NSPrintJobSavingURL
    from Foundation import NSURL
    info = NSPrintInfo.sharedPrintInfo().copy()
    info.setJobDisposition_(NSPrintSaveJob)
    info.dictionary()[NSPrintJobSavingURL] = NSURL.fileURLWithPath_(out_path)
    for side in ("Top", "Bottom", "Left", "Right"):
        getattr(info, f"set{side}Margin_")(36)
    op = wv.printOperationWithPrintInfo_(info)
    op.setShowsPrintPanel_(False)
    op.setShowsProgressPanel_(False)

    class Done(NSObject):
        @objc.typedSelector(b"v@:@Bn^v")
        def printOperationDidRun_success_contextInfo_(self, o, ok, ctx):
            if ok and os.path.exists(out_path):
                finish(None)
            else:
                _single_page(wv, out_path, finish)

    d = Done.alloc().init()
    wv._wr_done = d
    op.runOperationModalForWindow_delegate_didRunSelector_contextInfo_(wv.window(), d, b"printOperationDidRun:success:contextInfo:", None)


def _single_page(wv, out_path, finish):
    from WebKit import WKPDFConfiguration

    def handler(data, error):
        if error is not None or data is None:
            return finish(error or RuntimeError("no data"))
        try:
            data.writeToFile_atomically_(out_path, True)
            finish(None)
        except Exception as e:                           # noqa: BLE001
            finish(e)
    wv.createPDFWithConfiguration_completionHandler_(WKPDFConfiguration.alloc().init(), handler)
