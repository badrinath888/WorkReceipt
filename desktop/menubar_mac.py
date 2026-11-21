"""AppKit status-bar item for the WorkReceipt menu-bar widget (v0.8.0). All content comes from menubar.menu_items (counts and generic labels only).
Everything here is best-effort: a failure never affects the main window."""
import threading

import menubar

TITLE = "WorkReceipt"
REFRESH_SECONDS = 60
_KEEP = []


_CLS = []


def _target_class():
    """ObjC classes can be registered only once per process, so build it lazily and reuse it on every refresh."""
    if not _CLS:
        import objc
        from Foundation import NSObject

        class WRMenuTarget(NSObject):
            @objc.typedSelector(b"v@:@")
            def fire_(self, sender):
                self.callback(sender.representedObject())
        _CLS.append(WRMenuTarget)
    return _CLS[0]


def build_menu(items, on_action):
    from AppKit import NSMenu, NSMenuItem
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    tgt = _target_class().alloc().init()
    tgt.callback = on_action
    _KEEP[:] = [tgt]                                        # NSMenuItem targets are weak references; hold the latest one
    for it in items:
        if it is None:
            menu.addItem_(NSMenuItem.separatorItem()); continue
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(it["title"], "fire:" if it.get("action") else None, "")
        if it.get("action"):
            mi.setTarget_(tgt); mi.setRepresentedObject_(it["action"])
        mi.setEnabled_(bool(it.get("action")))
        menu.addItem_(mi)
    return menu


def install(handle_action):
    """Create the (initially hidden) status item and refresh it every minute and whenever Settings are saved. Returns a stop() function."""
    from AppKit import NSStatusBar
    from PyObjCTools import AppHelper
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
    item.setVisible_(False)                               # install() runs on the main thread: hidden before the first draw
    stop, wake = threading.Event(), threading.Event()
    ctl = menubar.StatusController(item, build_menu, handle_action, call_after=AppHelper.callAfter, wake=wake.set)
    item.button().setTitle_("WR")
    menubar.ON_CHANGED = ctl.settings_changed

    def loop():
        while not stop.is_set():
            ctl.refresh()
            wake.wait(REFRESH_SECONDS); wake.clear()
    threading.Thread(target=loop, daemon=True).start()
    return stop.set
