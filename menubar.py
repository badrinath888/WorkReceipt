"""macOS menu-bar widget logic (v0.8.0). Pure and local: reads only the projects the user explicitly selected, returns counts and generic labels.
Never emits paths, commit text, prompts, code or secrets. Project names appear only if the user opts in (`names`). The AppKit shell is desktop/menubar_mac.py."""
import subprocess
from datetime import datetime, timedelta

import app_core as core
import workreceipt as w

DEFAULT = {"enabled": False, "projects": [], "names": False, "notify": False, "seen": {}}
# Quick actions map to existing page commands. "report" opens Report Studio: privacy review and approval still gate every export.
ACTION_CMD = {"open": "go:overview", "report": "go:studio", "refresh": "refresh"}


def clean(raw):
    r = raw if isinstance(raw, dict) else {}
    seen = r.get("seen") if isinstance(r.get("seen"), dict) else {}
    return {"enabled": r.get("enabled") is True, "projects": [p for p in (r.get("projects") if isinstance(r.get("projects"), list) else []) if isinstance(p, str) and p][:50],
            "names": r.get("names") is True, "notify": r.get("notify") is True, "seen": {k: v for k, v in seen.items() if isinstance(k, str) and isinstance(v, str)}}


def _head(path):
    h = w.git(path, "rev-parse", "HEAD")
    return h.strip() if h else None


def _new_commits(path, seen):
    if not seen:                                   # first run is a baseline, not a flood of "new" commits
        return 0
    n = w.git(path, "rev-list", "--count", f"{seen}..HEAD")
    return int(n) if n and n.strip().isdigit() else 0


def _pending(s, path, since):
    """High-severity findings that must be reviewed before an export. Counts only; values are never returned."""
    try:
        b = core.build({"repo": path, "since": since}, s)
    except Exception:
        return 0
    return sum(1 for f in b["findings"] if f["severity"] == "high" for d in f["detections"] if not d.get("suppressed"))


def snapshot(s=None, window_days=7):
    s = s or core.load_settings()
    mb = clean(s.get("menubar"))
    out = {"enabled": mb["enabled"], "projects": [], "new_commits": 0, "sessions": 0, "review": {"pending": 0, "last_report": None}}
    if not mb["enabled"]:
        return out
    since = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=window_days)).timestamp()
    known = {core._norm(p["path"]): p for p in core.all_projects(s)}
    for i, path in enumerate(mb["projects"]):
        new = _new_commits(path, mb["seen"].get(path))
        sess = sum(1 for t in (known.get(core._norm(path)) or {}).get("mtimes", []) if t >= cutoff)
        out["projects"].append({"label": (path.rstrip("/\\").rsplit("/", 1)[-1] or f"Project {i + 1}") if mb["names"] else f"Project {i + 1}", "new_commits": new, "sessions": sess})
        out["new_commits"] += new
        out["sessions"] += sess
        out["review"]["pending"] += _pending(s, path, since)
    h = core.history()
    out["review"]["last_report"] = h[-1].get("at") if h else None
    return out


def mark_seen(s=None):
    s = s or core.load_settings()
    mb = clean(s.get("menubar"))
    seen = {p: h for p in mb["projects"] if (h := _head(p))}
    return core.save_settings({"menubar": dict(mb, seen=seen)})


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def menu_items(snap):
    """[{title, action?}] with None as a separator. Titles come only from counts and generic labels."""
    items = [{"title": "WorkReceipt"}, None]
    if not snap["enabled"]:
        items.append({"title": "Widget is off (turn it on in Settings)"})
    else:
        items += [{"title": f"{p['label']}: {_plural(p['new_commits'], 'new commit')} · {_plural(p['sessions'], 'session')}"} for p in snap["projects"]] or [{"title": "No projects selected"}]
        r = snap["review"]
        items.append({"title": f"Review: {_plural(r['pending'], 'finding')} to review" if r["pending"] else "Review: nothing pending"})
        items.append({"title": f"Last report: {r['last_report']}" if r["last_report"] else "No reports exported yet"})
    return items + [None, {"title": "Open WorkReceipt", "action": "open"}, {"title": "Generate Report…", "action": "report"},
                    {"title": "Mark commits as seen", "action": "mark_seen"}, {"title": "Refresh", "action": "refresh"}]


def popover_model(snap):
    """Data for the native popover card. Same privacy rules as menu_items: counts, generic labels and the last report date only."""
    r = snap["review"]
    return {"enabled": snap["enabled"], "projects": [dict(p) for p in snap["projects"]], "last_report": r["last_report"],
            "stats": [{"label": "New commits", "value": snap["new_commits"]}, {"label": "AI sessions", "value": snap["sessions"]}, {"label": "To review", "value": r["pending"]}],
            "actions": [{"id": "open", "title": "Open WorkReceipt"}, {"id": "report", "title": "Generate Report"}, {"id": "refresh", "title": "Refresh"}, {"id": "mark_seen", "title": "Mark commits as seen"}]}


def notification(snap, prev, s):
    if not clean(s.get("menubar"))["notify"]:
        return None
    n = snap["new_commits"]
    return f"{_plural(n, 'new commit')} in your selected projects" if n > (prev or {}).get("new_commits", 0) else None


def notify(text, runner=None):
    esc = str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    argv = ["osascript", "-e", f'display notification "{esc}" with title "WorkReceipt"']
    try:
        (runner or (lambda a: subprocess.run(a, capture_output=True, timeout=5)))(argv)
    except Exception:
        pass


ON_CHANGED = None          # set by the desktop shell: called after Settings are saved so the status item updates at once


def changed():
    """Called by the settings route after a SUCCESSFUL save. Never raises into the save path."""
    try:
        if ON_CHANGED:
            ON_CHANGED()
    except Exception:
        pass


class StatusController:
    """Drives a status-bar item (duck-typed: setVisible_, setMenu_, button().setTitle_) with no AppKit dependency, so it is testable anywhere.
    The item is hidden on creation and stays hidden until a refresh succeeds AND the widget is enabled."""

    def __init__(self, item, build_menu, handle_action, call_after=None, snapshot=None, settings=None, wake=None, on_model=None):
        self.item, self.build_menu, self.handle_action = item, build_menu, handle_action
        self.call_after = call_after or (lambda f, *a: f(*a))
        self.on_model = on_model                      # popover mode: push the model to the native card instead of installing an NSMenu
        self.snapshot, self.settings, self.wake, self.prev = snapshot or globals()["snapshot"], settings or core.load_settings, wake, {}
        self.call_after(item.setVisible_, False)

    def _apply(self, snap):
        self.item.setVisible_(snap["enabled"])
        if self.on_model:
            self.on_model(popover_model(snap))
        elif snap["enabled"]:
            self.item.setMenu_(self.build_menu(menu_items(snap), self.handle_action))
        if snap["enabled"]:
            n = snap["new_commits"]
            self.item.button().setTitle_(f"WR {n}" if n else "WR")

    def refresh(self):
        try:
            s = self.settings()
            snap = self.snapshot(s)
        except Exception:
            self.call_after(self.item.setVisible_, False)      # a failed scan never leaves a stray icon
            return
        self.call_after(self._apply, snap)
        msg = notification(snap, self.prev, s)
        if msg:
            notify(msg)
        self.prev = snap

    def settings_changed(self):
        """Cheap and immediate: visibility depends only on the saved setting. The slower counts refresh follows in the background."""
        try:
            self.call_after(self.item.setVisible_, clean(self.settings().get("menubar"))["enabled"])
        except Exception:
            self.call_after(self.item.setVisible_, False)
        if self.wake:
            self.wake()
