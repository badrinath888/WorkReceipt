"""v0.8.0 macOS menu-bar widget (TDD). Logic lives in menubar.py (pure, testable); the AppKit shell is desktop/menubar_mac.py.
SYNTHETIC data only. The widget is opt-in, local, and must never put names, paths, commit text, prompts or secrets in the menu bar."""
import json, os, subprocess, sys, unittest

import app_core as core, workreceipt as w
from test_phase1 import WS

AKIA = "AKIAQWERTYUIOPASDFGH"
NAME, MSG, PROMPT = "zq-confidential-app", "Wire zq-secret-db token", "Connect zq-secret-db with key " + AKIA


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, "-c", "user.email=a@b.c", "-c", "user.name=A", "-c", "commit.gpgsign=false", *a], check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        import menubar
        self.m = menubar
        self.ws = WS(name=NAME, commits=[("a.py", MSG, "03")]); self.addCleanup(self.ws.done)
        self.ws.log([self.ws.user(PROMPT, "2026-11-04T10:00:00Z")])
        self.repo = self.ws.repo
        self.head1 = git(self.repo, "rev-parse", "HEAD")

    def enable(self, **kw):
        return core.save_settings({"menubar": dict({"enabled": True, "projects": [self.repo]}, **kw)})

    def commit(self, msg="More work"):
        open(os.path.join(self.repo, "b.py"), "a").write("x\n"); git(self.repo, "add", "."); git(self.repo, "commit", "-qm", msg)

    def everything(self, s, snap):
        return json.dumps(snap) + json.dumps(self.m.menu_items(snap)) + json.dumps(self.m.notification(snap, {"new_commits": 0}, s) or "")


class Settings(Base):
    def test_off_by_default_and_sanitised(self):
        self.assertEqual(core.DEFAULTS["menubar"], {"enabled": False, "projects": [], "names": False, "notify": False, "seen": {}})
        s = core.save_settings({"menubar": {"enabled": "yes", "projects": [1, "", self.repo, None], "names": 1, "notify": "x", "seen": {"a": 5, "b": "abc123"}, "evil": 1}})
        self.assertEqual(s["menubar"], {"enabled": False, "projects": [self.repo], "names": False, "notify": False, "seen": {"b": "abc123"}})
        self.assertEqual(core.save_settings({"menubar": "junk"})["menubar"], core.DEFAULTS["menubar"])


class Snapshot(Base):
    def test_disabled_reads_nothing(self):
        seen = []; orig = w.git; w.git = lambda *a: seen.append(a)
        try:
            snap = self.m.snapshot(core.save_settings({"menubar": {"enabled": False, "projects": [self.repo]}}))
        finally:
            w.git = orig
        self.assertEqual((snap["enabled"], snap["projects"], seen), (False, [], []))

    def test_only_explicitly_selected_projects_are_read(self):
        other = os.path.join(self.ws.root, "other"); os.makedirs(other); git(other, "init", "-q")
        touched = []; orig = w.git; w.git = lambda repo, *a: (touched.append(repo), orig(repo, *a))[1]
        try:
            self.m.snapshot(self.enable())
        finally:
            w.git = orig
        self.assertEqual(set(touched), {self.repo})

    def test_new_commits_since_last_seen_with_baseline_first(self):
        s = self.enable(); self.assertEqual(self.m.snapshot(s)["new_commits"], 0)            # nothing seen yet: baseline, no flood
        s = self.enable(seen={self.repo: self.head1}); self.commit(); self.commit("again")
        self.assertEqual(self.m.snapshot(s)["new_commits"], 2)
        s = self.m.mark_seen(s); self.assertEqual(self.m.snapshot(s)["new_commits"], 0)
        self.assertEqual(s["menubar"]["seen"], {self.repo: git(self.repo, "rev-parse", "HEAD")})

    def test_activity_and_review_status(self):
        snap = self.m.snapshot(self.enable(), window_days=3650)
        self.assertGreaterEqual(snap["sessions"], 1)
        self.assertGreaterEqual(snap["review"]["pending"], 1)                               # the fake key in the session log needs review before any export
        self.assertIsNone(snap["review"]["last_report"])

    def test_missing_or_non_git_selected_project_is_harmless(self):
        s = core.save_settings({"menubar": {"enabled": True, "projects": ["/nonexistent/zz", self.ws.root]}})
        self.assertEqual(self.m.snapshot(s)["new_commits"], 0)


class Privacy(Base):
    def leaks(self, text, names):
        bad = [self.repo, MSG, "zq-secret-db", "AKIA", "Connect", self.ws.root] + ([] if names else [NAME])
        for b in bad:
            self.assertNotIn(b, text, b)

    def test_default_menu_and_notification_have_no_identifying_content(self):
        s = self.enable(seen={self.repo: self.head1}); self.commit(MSG)
        snap = self.m.snapshot(s, window_days=3650)
        self.leaks(self.everything(s, snap), names=False)
        self.assertIn("Project 1", json.dumps(snap))

    def test_names_are_opt_in_and_still_exclude_paths_messages_prompts_secrets(self):
        s = self.enable(names=True, notify=True, seen={self.repo: self.head1}); self.commit(MSG)
        snap = self.m.snapshot(s, window_days=3650)
        text = self.everything(s, snap); self.leaks(text, names=True)
        self.assertIn(NAME, text)


class MenuAndNotify(Base):
    def test_quick_actions_open_app_and_report_studio_without_bypassing_review(self):
        snap = self.m.snapshot(self.enable())
        acts = [i["action"] for i in self.m.menu_items(snap) if i and i.get("action")]
        for a in ("open", "report", "refresh", "mark_seen"):
            self.assertIn(a, acts)
        self.assertEqual(self.m.ACTION_CMD["report"], "go:studio")                          # Studio, where privacy review + approval still apply
        self.assertNotIn("export", " ".join(self.m.ACTION_CMD.values()))

    def test_notification_only_on_new_commits_and_only_when_enabled(self):
        s = self.enable(notify=True, seen={self.repo: self.head1}); self.commit()
        snap = self.m.snapshot(s)
        self.assertEqual(self.m.notification(snap, {"new_commits": 0}, s), "1 new commit in your selected projects")
        self.assertIsNone(self.m.notification(snap, {"new_commits": 1}, s))                 # nothing new since last notice
        self.assertIsNone(self.m.notification(snap, {"new_commits": 0}, self.enable(notify=False)))

    def test_notify_uses_escaped_osascript(self):
        calls = []; self.m.notify('He said "hi" \\ there', runner=lambda a: calls.append(a))
        (argv,) = calls; self.assertEqual(argv[:2], ["osascript", "-e"])
        self.assertIn('He said \\"hi\\" \\\\ there', argv[2]); self.assertEqual(len(argv), 3)

class FakeItem:
    def __init__(self):
        self.vis, self.menu, self.title = [], None, None
        self.btn = type("B", (), {"setTitle_": lambda s, x: setattr(self_outer, "title", x)})()
        self_outer = self
    setVisible_ = lambda self, v: self.vis.append(bool(v))
    setMenu_ = lambda self, m: setattr(self, "menu", m)
    button = lambda self: self.btn


class Lifecycle(Base):
    """Status-item lifecycle (v0.8.0 review fixes): hidden on creation, hidden if the first refresh fails, immediate update after a Settings save."""
    def ctl(self, **kw):
        self.item = FakeItem()
        return self.m.StatusController(self.item, lambda items, cb: [i["title"] for i in items if i], lambda a: None, call_after=lambda f, *a: f(*a), **kw)

    def test_hidden_immediately_on_creation_even_before_any_refresh(self):
        self.ctl(); self.assertEqual(self.item.vis, [False])

    def test_disabled_stays_hidden_and_builds_no_menu(self):
        c = self.ctl(); core.save_settings({"menubar": {"enabled": False, "projects": [self.repo]}}); c.refresh()
        self.assertNotIn(True, self.item.vis); self.assertIsNone(self.item.menu)

    def test_failed_first_refresh_keeps_the_icon_hidden(self):
        def boom(*a, **k): raise RuntimeError("scan failed")
        c = self.ctl(snapshot=boom); self.enable(); c.refresh()
        self.assertNotIn(True, self.item.vis); self.assertFalse(self.item.vis[-1])

    def test_enabled_refresh_shows_icon_and_counts_only_menu(self):
        c = self.ctl(); self.enable(seen={self.repo: self.head1}); self.commit(MSG); c.refresh()
        self.assertTrue(self.item.vis[-1]); self.assertEqual(self.item.title, "WR 1")
        self.leaks_in(json.dumps(self.item.menu))

    def leaks_in(self, text):
        for b in (self.repo, MSG, "zq-secret-db", "AKIA", NAME):
            self.assertNotIn(b, text, b)

    def test_settings_saved_toggles_visibility_immediately(self):
        c = self.ctl(); self.m.ON_CHANGED = c.settings_changed; self.addCleanup(setattr, self.m, "ON_CHANGED", None)
        core.save_settings({"menubar": {"enabled": True, "projects": [self.repo]}}); self.m.changed()
        self.assertTrue(self.item.vis[-1])
        core.save_settings({"menubar": {"enabled": False, "projects": [self.repo]}}); self.m.changed()
        self.assertFalse(self.item.vis[-1])

    def test_changed_never_raises_into_the_save_path(self):
        self.m.ON_CHANGED = lambda: 1 / 0; self.addCleanup(setattr, self.m, "ON_CHANGED", None)
        self.m.changed()                                                               # no exception
        self.m.ON_CHANGED = None; self.m.changed()


class SaveRoute(Base):
    @classmethod
    def setUpClass(cls):
        import threading, urllib.request
        from http.server import ThreadingHTTPServer
        import workreceipt_app as srv
        cls.srv = srv
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.H)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def post(self, body):
        import urllib.error, urllib.request
        req = urllib.request.Request(self.base + "/api/settings", json.dumps(body).encode(), {"Content-Type": "application/json", "X-WR-Token": self.srv.TOKEN})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_successful_save_notifies_the_widget_once_and_a_failed_save_does_not(self):
        calls = []; self.m.ON_CHANGED = lambda: calls.append(1); self.addCleanup(setattr, self.m, "ON_CHANGED", None)
        self.assertEqual(self.post({"menubar": {"enabled": True, "projects": [self.repo]}}), 200); self.assertEqual(calls, [1])
        orig = core.save_settings; core.save_settings = lambda d: 1 / 0
        try:
            self.assertEqual(self.post({"menubar": {"enabled": False}}), 500)
        finally:
            core.save_settings = orig
        self.assertEqual(calls, [1])


NATIVE_SCRIPT = """
import sys, json; sys.path.insert(0, %r)
import menubar
from desktop import menubar_mac
items = json.loads(sys.argv[1])
m1 = menubar_mac.build_menu(items, lambda a: None)
got = []; m2 = menubar_mac.build_menu(items, got.append)            # rebuilt on every refresh: must not re-register the ObjC class
act = next(m for m in m2.itemArray() if m.representedObject() == "open"); act.target().fire_(act)
print(json.dumps({"titles": [m.title() for m in m1.itemArray() if not m.isSeparatorItem()], "got": got, "t": menubar_mac.TITLE}))
"""


@unittest.skipUnless(sys.platform == "darwin", "AppKit shell is macOS-only")
class Native(Base):
    def test_status_menu_mirrors_the_privacy_safe_items(self):
        # Subprocess on purpose: importing AppKit here would change process-wide state that other suites (PDF setup tests) rely on.
        items = self.m.menu_items(self.m.snapshot(self.enable()))
        root = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, "-c", NATIVE_SCRIPT % root, json.dumps(items)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["titles"], [i["title"] for i in items if i]); self.assertEqual((out["got"], out["t"]), (["open"], "WorkReceipt"))


class Ui(unittest.TestCase):
    def test_settings_card_and_save_payload(self):
        js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "app.js"), encoding="utf-8").read()
        self.assertIn("Menu bar", js); self.assertIn("menubar:", js)


if __name__ == "__main__":
    unittest.main()
