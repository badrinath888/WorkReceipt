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


_PCLS = []


def _pop_target_class():
    if not _PCLS:
        import objc
        from Foundation import NSObject

        class WRPopTarget(NSObject):
            @objc.typedSelector(b"v@:@")
            def toggle_(self, sender):
                self.owner.toggle()

            @objc.typedSelector(b"v@:@")
            def act_(self, sender):
                self.owner.click(str(sender.identifier()))
        _PCLS.append(WRPopTarget)
    return _PCLS[0]


class Popover:
    """Native NSPopover card anchored to the status item. Content comes only from menubar.popover_model (counts and generic labels).
    Every call here runs on the AppKit main thread; the action callback returns immediately (see desktop.main.make_menu_action)."""
    WIDTH = 288

    def __init__(self, item, on_action):
        from AppKit import NSPopover, NSViewController, NSStackView, NSUserInterfaceLayoutOrientationVertical
        self.item, self.on_action = item, on_action
        self.stack = NSStackView.alloc().init()
        self.stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        self.stack.setSpacing_(10); self.stack.setEdgeInsets_((14, 16, 14, 16)); self.stack.setAlignment_(1)   # 1 = leading
        self.stack.setFrameSize_((self.WIDTH, 120))
        vc = NSViewController.alloc().init(); vc.setView_(self.stack)
        self.pop = NSPopover.alloc().init()
        self.pop.setContentViewController_(vc); self.pop.setBehavior_(1)                                       # 1 = transient: click-away and Esc close it
        self.target = _pop_target_class().alloc().init(); self.target.owner = self
        btn = item.button(); btn.setTarget_(self.target); btn.setAction_("toggle:")
        self.buttons = {}

    def _label(self, text, size=12, bold=False, secondary=False):
        from AppKit import NSTextField, NSFont, NSColor
        t = NSTextField.labelWithString_(text)
        t.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if secondary:
            t.setTextColor_(NSColor.secondaryLabelColor())
        return t

    def update(self, model):
        from AppKit import NSStackView, NSButton
        for v in list(self.stack.arrangedSubviews()):
            self.stack.removeArrangedSubview_(v); v.removeFromSuperview()
        self.buttons = {}
        add = self.stack.addArrangedSubview_
        add(self._label("WorkReceipt", 15, True))
        if not model["enabled"]:
            add(self._label("The widget is off. Turn it on in Settings.", secondary=True))
        else:
            row = NSStackView.alloc().init(); row.setSpacing_(18)
            for st in model["stats"]:
                col = NSStackView.alloc().init(); col.setOrientation_(1); col.setSpacing_(0); col.setAlignment_(1)
                col.addArrangedSubview_(self._label(str(st["value"]), 22, True)); col.addArrangedSubview_(self._label(st["label"], 11, secondary=True))
                row.addArrangedSubview_(col)
            add(row)
            add(self._label("Selected projects · last 7 days", 11, True, True))
            for p in model["projects"] or [{"label": "No projects selected", "new_commits": None}]:
                n = p["new_commits"]
                add(self._label(p["label"] if n is None else f"{p['label']}   {n} new commit{'' if n == 1 else 's'} · {p['sessions']} session{'' if p['sessions'] == 1 else 's'}"))
            add(self._label(f"Last report: {model['last_report']}" if model["last_report"] else "No reports exported yet", 11, secondary=True))
        for a in model["actions"]:
            b = NSButton.buttonWithTitle_target_action_(a["title"], self.target, "act:")
            b.setIdentifier_(a["id"]); b.setBezelStyle_(1)
            if a["id"] == "open":
                b.setKeyEquivalent_("\r")                                                                         # default button: Return activates it
            self.buttons[a["id"]] = b; add(b)
        self.stack.layoutSubtreeIfNeeded()
        self.pop.setContentSize_(self.stack.fittingSize())

    def toggle(self):
        if self.pop.isShown():
            self.pop.close()
        else:
            from AppKit import NSApp
            NSApp.activateIgnoringOtherApps_(True)
            self.pop.showRelativeToRect_ofView_preferredEdge_(self.item.button().bounds(), self.item.button(), 1)   # 1 = minY: opens below the menu bar

    def is_shown(self):
        return bool(self.pop.isShown())

    def click(self, action_id):
        if action_id in ("open", "report"):
            self.pop.close()
        self.on_action(action_id)

    def texts(self):
        out = []
        def walk(v):
            for attr in ("stringValue", "title"):
                f = getattr(v, attr, None)
                if f and isinstance(f(), str) and f():
                    out.append(f()); break
            for c in v.subviews():
                walk(c)
        walk(self.stack)
        return out


def install(handle_action):
    """Create the (initially hidden) status item and refresh it every minute and whenever Settings are saved. Returns a stop() function."""
    from AppKit import NSStatusBar
    from PyObjCTools import AppHelper
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
    item.setVisible_(False)                               # install() runs on the main thread: hidden before the first draw
    stop, wake = threading.Event(), threading.Event()
    try:
        pop = Popover(item, handle_action)
        on_model = pop.update
    except Exception:
        on_model = None                                    # unsupported configuration: fall back to the plain NSMenu
    ctl = menubar.StatusController(item, build_menu, handle_action, call_after=AppHelper.callAfter, wake=wake.set, on_model=on_model)
    item.button().setTitle_("WR")
    menubar.ON_CHANGED = ctl.settings_changed

    def loop():
        while not stop.is_set():
            ctl.refresh()
            wake.wait(REFRESH_SECONDS); wake.clear()
    threading.Thread(target=loop, daemon=True).start()
    return stop.set
