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
    """Create the status item and refresh it every minute. `handle_action(action)` is called on the main thread. Returns a stop() function."""
    from AppKit import NSStatusBar
    from PyObjCTools import AppHelper
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
    item.button().setTitle_("WR")
    stop, prev = threading.Event(), {}

    def apply(snap, visible):
        item.setVisible_(visible)
        item.setMenu_(build_menu(menubar.menu_items(snap), handle_action))
        n = snap["new_commits"]
        item.button().setTitle_(f"WR {n}" if n else "WR")

    def tick():
        import app_core as core
        s = core.load_settings()
        snap = menubar.snapshot(s)
        AppHelper.callAfter(apply, snap, snap["enabled"])
        msg = menubar.notification(snap, prev, s)
        if msg:
            menubar.notify(msg)
        prev.update(snap)

    def loop():
        while not stop.is_set():
            try:
                tick()
            except Exception:
                pass
            stop.wait(REFRESH_SECONDS)
    threading.Thread(target=loop, daemon=True).start()
    return stop.set
