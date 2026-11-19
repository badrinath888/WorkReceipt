"""CI diagnostic: which Creator does a script-run WKWebView print job stamp, who supplies it, and does setProcessName change it?
Synthetic page only; prints metadata field values of that synthetic PDF (nothing private exists in it)."""
import os, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "desktop"))
from PyObjCTools import AppHelper
from Foundation import NSProcessInfo, NSBundle, NSURL
from Quartz import PDFDocument
import pdf_mac


def creator(tag):
    out = os.path.join(tempfile.mkdtemp(), tag + ".pdf")
    try: pdf_mac.render_pdf("<html><body><p>probe text</p></body></html>", out)
    except Exception as e: print(f"[{tag}] render note: {e}")
    d = (PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(out)).documentAttributes() or {}) if os.path.exists(out) else {}
    print(f"[{tag}] Creator={d.get('Creator')!r} Producer={d.get('Producer')!r}", flush=True)


def work():
    pi = NSProcessInfo.processInfo()
    print(f"exe={sys.executable} processName={pi.processName()!r} bundleName={NSBundle.mainBundle().infoDictionary().get('CFBundleName')!r}", flush=True)
    creator("before")
    pi.setProcessName_("WorkReceipt")
    creator("after-setProcessName")
    os._exit(0)


threading.Thread(target=work, daemon=True).start()
AppHelper.runConsoleEventLoop(installInterrupt=False)
