"""Menu bar Settings card: switch rows + 'Projects to monitor'. Real Chrome via playwright (skipped where unavailable); SYNTHETIC data only."""
import os, subprocess, tempfile, unittest
import test_e2e_desktop as t
import app_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
SW = ("mb_on", "mb_names", "mb_notify")


def mkrepo(root, name):
    p = os.path.join(root, name); os.makedirs(p); subprocess.run(["git", "-C", p, "init", "-q"], check=True); return p


class Source(unittest.TestCase):                                   # runs in CI where playwright is absent
    def js(self):
        return open(os.path.join(HERE, "ui", "app.js"), encoding="utf-8").read().split("const mbRow")[1].split("<h3>Appearance")[0]

    def test_switch_rows_keep_ids_and_are_accessible(self):
        js = self.js()
        for i in SW: self.assertIn(f'mbRow("{i}"', js)
        self.assertEqual(js.count("${mbRow("), 3)
        self.assertNotIn('<input type="checkbox" id="mb_', js)

    def test_projects_section_and_empty_state(self):
        js = self.js()
        self.assertIn("Projects to monitor", js); self.assertIn("No projects added yet.", js); self.assertIn('data-go="projects"', js)
        self.assertIn("data-mbproj", js)


class Backend(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); os.environ["WORKRECEIPT_HOME"] = os.path.join(self.root, "h"); self.addCleanup(os.environ.pop, "WORKRECEIPT_HOME")

    def test_defaults_private_and_adding_projects_never_selects_them(self):
        s = core.load_settings()["menubar"]
        self.assertEqual((s["enabled"], s["names"], s["notify"], s["projects"]), (False, False, False, []))
        core.add_project(mkrepo(self.root, "a")); core.add_project(mkrepo(self.root, "b"))
        self.assertEqual(core.load_settings()["menubar"]["projects"], [])

    def test_multiple_selected_projects_persist(self):
        a, b = mkrepo(self.root, "a"), mkrepo(self.root, "b")
        core.save_settings({"menubar": {"enabled": True, "projects": [a, b]}})
        self.assertEqual(core.load_settings()["menubar"]["projects"], [a, b])


@unittest.skipUnless(t.sync_playwright and t.CHROME, "playwright/Chrome not available")
class Browser(unittest.TestCase):
    setUpClass = classmethod(lambda cls: t.E2E.setUpClass.__func__(cls))
    tearDownClass = classmethod(lambda cls: t.E2E.tearDownClass.__func__(cls))
    page = t.E2E.page

    def open(self, w=1180):
        core.save_settings({"onboarded": True}); pg = self.page(w); pg.goto(self.url + "#settings"); pg.wait_for_selector("#mb_on", state="attached"); return pg

    def test_switch_alignment_and_accessibility(self):
        for w in (1180, 360):
            pg = self.open(w)
            self.assertTrue(pg.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"horizontal overflow at {w}px")
            for i in SW:
                r = pg.evaluate("""i => { const e = document.getElementById(i), sw = e.closest('.sw').getBoundingClientRect(), row = e.closest('.srow').getBoundingClientRect(), tx = e.closest('.srow').querySelector('.stext').getBoundingClientRect();
                  return {role: e.getAttribute('role'), sw: [sw.left, sw.right, sw.width, sw.height], row: [row.left, row.right], tx: tx && [tx.left, tx.right], name: e.getAttribute('aria-labelledby') && document.getElementById(e.getAttribute('aria-labelledby')).textContent, desc: e.getAttribute('aria-describedby') && document.getElementById(e.getAttribute('aria-describedby')).textContent} }""", i)
                self.assertEqual(r["role"], "switch"); self.assertTrue(r["name"] and r["desc"])
                self.assertLessEqual(r["sw"][2], 44); self.assertLessEqual(r["sw"][3], 24)            # compact, not an oversized checkbox
                self.assertGreater(r["sw"][0], r["tx"][1] - 1); self.assertAlmostEqual(r["sw"][1], r["row"][1], delta=16)   # text left, switch right-aligned
            pg.focus("#mb_names"); pg.keyboard.press("Space"); self.assertTrue(pg.is_checked("#mb_names"))
            self.assertEqual(pg.get_attribute("#mb_names", "aria-checked") or "true", "true")
            pg.close()

    def test_default_privacy_and_persistence(self):
        core.save_settings({"menubar": {}}); pg = self.open()
        for i in SW: self.assertFalse(pg.is_checked("#" + i))                                           # names hidden, notifications off, widget off
        pg.click("label.sw:has(#mb_on)"); pg.click("label.sw:has(#mb_notify)"); pg.click("#savesettings"); pg.wait_for_selector("#toast.on")
        m = core.load_settings()["menubar"]; self.assertEqual((m["enabled"], m["names"], m["notify"]), (True, False, True))
        pg.reload(); pg.wait_for_selector("#mb_on", state="attached"); self.assertTrue(pg.is_checked("#mb_on")); self.assertFalse(pg.is_checked("#mb_names"))

    def test_empty_state_navigates_then_added_projects_appear_and_multi_select_persists(self):
        for p in core.load_settings().get("projects", []) if False else []: pass
        core.save_settings({"menubar": {}}); pg = self.open()
        if pg.locator("[data-mbproj]").count() == 0:
            self.assertIn("No projects added yet.", pg.inner_text("#screen"))
            pg.click("#screen button:has-text('Add project')"); pg.wait_for_selector("#screen .ph h2:has-text('Projects')")
        a, b, c = (mkrepo(self.root, "pr" + n) for n in "abc")
        for p in (a, b, c):
            pg.evaluate("p => addProjectFlow(p)", p); pg.wait_for_selector(f"tr[data-pick]:has-text('{os.path.basename(p)}')")      # the app's own add flow (the native picker is absent in a browser)
        self.assertEqual(core.load_settings()["menubar"]["projects"], [])                              # adding never enables monitoring
        sel = lambda p: f"label.srow:has(b:text-is('{os.path.basename(p)}')) input"
        pg.click(".tab[data-go=settings]"); pg.wait_for_selector("#mb_on", state="attached")           # list refreshed without reload
        for p in (a, b, c): self.assertFalse(pg.is_checked(sel(p)))
        pg.click(sel(a)); pg.click(sel(c)); pg.click("#savesettings"); pg.wait_for_selector("#toast.on")
        saved = core.load_settings()["menubar"]["projects"]; self.assertEqual([os.path.basename(x) for x in saved], ["pra", "prc"])
        pg.reload(); pg.wait_for_selector("#mb_on", state="attached")
        self.assertEqual([pg.is_checked(sel(p)) for p in (a, b, c)], [True, False, True])

    def test_screenshot(self):
        out = os.environ.get("WR_SHOT_DIR")
        if not out: self.skipTest("WR_SHOT_DIR not set")
        for w, n in ((1180, "desktop"), (360, "narrow")):
            pg = self.open(w); pg.locator("#mb_on").scroll_into_view_if_needed()
            pg.locator("h3:has-text('Menu bar')").locator("xpath=ancestor::div[contains(@class,'card')][1]").screenshot(path=os.path.join(out, f"settings-menubar-{n}.png")); pg.close()
        for x in list(core.load_settings().get("projects", [])): core.remove_project(x)
        a, b = mkrepo(self.root, "client-site"), mkrepo(self.root, "api-service")   # synthetic repos: two listed, only one selected
        core.add_project(a); core.add_project(b); core.save_settings({"menubar": {"enabled": True, "projects": [a]}})
        for w, n in ((1180, "desktop"), (360, "narrow")):
            pg = self.open(w); pg.locator("#mb_on").scroll_into_view_if_needed()
            pg.locator("h3:has-text('Menu bar')").locator("xpath=ancestor::div[contains(@class,'card')][1]").screenshot(path=os.path.join(out, f"settings-menubar-projects-{n}.png")); pg.close()


if __name__ == "__main__":
    unittest.main()
