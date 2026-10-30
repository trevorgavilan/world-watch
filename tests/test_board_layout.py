"""The Board's layout in a real browser: a draggable globe / list divider remembered per browser,
lists that fold, and a source strip that stays one row (Trevor, 28 Oct: "things should be resizable").

Each test opens the real page from a real Board server in headless Edge, with the page's own CSP.
"""

import json
import unittest

from tests.browser import Browser, find_browser
from tests.helpers import NOW, temp_dir
from tests.test_board import HOSTILE, real_feed_store, start
from worldwatch.collectors import all_collectors
from worldwatch.item import iso_utc
from worldwatch.store import Store

EXE = find_browser()
READY = "document.querySelectorAll('#panels .box').length > 0 && document.querySelectorAll('#fresh .dot').length > 0"
SIDE = "document.querySelector('.side').getBoundingClientRect().width"
GLOBE = "document.querySelector('#globe').getBoundingClientRect().width"
# Every policy breach the page causes. globe.gl's own <style> tags are the one known, harmless kind (FINDINGS).
WATCH_CSP = ("window.__csp = []; document.addEventListener('securitypolicyviolation', "
             "(e) => window.__csp.push(e.effectiveDirective + ' ' + e.blockedURI));")


def layout_store():
    """The saved real feeds, with all ten sources in the run: one fetched, one failing with hostile text."""
    path = real_feed_store()
    store = Store(path)
    store.record_run("cisa-kev", NOW, NOW, ok=False, n_items=0, error=HOSTILE, next_due=iso_utc(NOW), fail_count=1)
    store.close()
    return path


@unittest.skipUnless(EXE, "no Edge or Chrome on this machine")
class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collectors = all_collectors(temp_dir())
        cls.srv = start(layout_store(), cls.collectors)
        cls.addClassCleanup(cls.srv.server_close)
        cls.addClassCleanup(cls.srv.shutdown)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/"
        cls.b = Browser(EXE)
        cls.addClassCleanup(cls.b.close)
        cls.csp_script = cls.b.before_each_page(WATCH_CSP)

    def setUp(self):
        self.b.size(1280, 800)
        if not self.b.run(f"location.href === {json.dumps(self.url)}"):
            self.b.open(self.url, READY)
        self.b.run("localStorage.clear()")
        self.reload()

    def reload(self):
        self.b.open(self.url, READY)

    def divider_centre(self):
        return self.b.run("(() => { const r = document.querySelector('#divider').getBoundingClientRect();"
                          " return [r.left + r.width / 2, r.top + r.height / 2]; })()")

    # -- the source strip --------------------------------------------------------------------------

    def test_strip_is_one_row_at_1280_px_and_wider(self):
        for width in (1280, 1910, 2560):
            self.b.size(width, 900)
            self.reload()
            rows = self.b.run("[...document.querySelectorAll('.bar > *, #fresh .dot')]"
                              ".filter((n) => n.offsetParent !== null)"
                              ".map((n) => Math.round(n.getBoundingClientRect().top + n.getBoundingClientRect().height / 2))")
            self.assertLessEqual(max(rows) - min(rows), 6, f"{width} px: the strip wraps ({rows})")
            self.assertLess(self.b.run("document.querySelector('.bar').offsetHeight"), 56, width)
            spill = self.b.run("(() => { const box = (s) => document.querySelector(s).getBoundingClientRect();"
                               " const dots = [...document.querySelectorAll('#fresh .dot')].map((d) => d.getBoundingClientRect());"
                               " return [Math.max(...dots.map((d) => d.right)) - box('#fresh').right,"
                               " box('#fresh').right - box('#fresh-sum').left, box('.recon').right - innerWidth]; })()")
            self.assertTrue(all(s <= 0.5 for s in spill), f"{width} px: the strip spills over ({spill})")

    def test_one_dot_per_source_in_the_run(self):
        dots = self.b.run("[...document.querySelectorAll('#fresh .dot')].map((d) => d.getAttribute('aria-label'))")
        self.assertEqual(len(dots), len(self.collectors))
        for c in self.collectors:
            self.assertTrue(any(d.startswith(c.source) for d in dots), c.source)
        states = self.b.run("[...document.querySelectorAll('#fresh .dot')].map((d) => d.className)")
        self.assertIn("dot ok", states)
        self.assertIn("dot never", states)

    def test_a_dot_tells_its_details_on_hover_and_click(self):
        title = self.b.run("document.querySelector('#fresh .dot[aria-label^=\"cisa-kev\"]').title")
        self.assertIn("last error", title)
        self.assertTrue(self.b.run("document.querySelector('#fresh-detail').hidden"))
        self.b.run("document.querySelector('#fresh .dot[aria-label^=\"cisa-kev\"]').click()")
        detail = self.b.run("(() => { const d = document.querySelector('#fresh-detail');"
                            " return [d.hidden, d.textContent, d.querySelectorAll('img, script').length]; })()")
        self.assertFalse(detail[0])
        self.assertIn("cisa-kev", detail[1])
        self.assertIn(HOSTILE, detail[1], "the error is shown as text")
        self.assertEqual(detail[2], 0, "the error was never parsed as HTML")
        self.b.run("document.querySelector('#fresh .dot[aria-label^=\"cisa-kev\"]').click()")
        self.assertTrue(self.b.run("document.querySelector('#fresh-detail').hidden"), "a second click closes it")

    # -- the divider -------------------------------------------------------------------------------

    def test_dragging_the_divider_resizes_and_survives_a_reload(self):
        before = self.b.run(SIDE)
        x, y = self.divider_centre()
        self.b.drag(x, y, x - 200)
        self.assertAlmostEqual(self.b.run(SIDE), before + 200, delta=2)
        self.b.wait_for("Math.abs(document.querySelector('#globe canvas').getBoundingClientRect().width - "
                        f"{GLOBE}) < 2", timeout=5)  # the globe redraws at its new size
        self.reload()
        self.assertAlmostEqual(self.b.run(SIDE), before + 200, delta=2, msg="the split is remembered")

    def test_home_and_end_take_the_divider_to_its_limits(self):
        self.b.run("document.querySelector('#divider').focus()")
        self.b.key("Home", "Home", 36)
        self.assertAlmostEqual(self.b.run(GLOBE), 300, delta=1)
        self.b.key("End", "End", 35)
        self.assertAlmostEqual(self.b.run(SIDE), 260, delta=1)

    def test_a_click_without_a_drag_keeps_the_default(self):
        x, y = self.divider_centre()
        self.b.mouse("mousePressed", x, y)
        self.b.mouse("mouseReleased", x, y, buttons=0)
        self.assertIsNone(self.b.run("localStorage.getItem('ww.board.side')"))

    def test_the_divider_moves_with_the_arrow_keys(self):
        before = self.b.run(SIDE)
        self.b.run("document.querySelector('#divider').focus()")
        self.b.key("ArrowLeft", "ArrowLeft", 37)
        self.assertGreater(self.b.run(SIDE), before + 10)
        self.assertEqual(self.b.run("Number(document.querySelector('#divider').getAttribute('aria-valuenow'))"),
                         round(self.b.run(SIDE)))
        self.b.key("ArrowRight", "ArrowRight", 39)
        self.assertAlmostEqual(self.b.run(SIDE), before, delta=2)

    def test_the_split_keeps_the_globe_and_lists_on_screen(self):
        x, y = self.divider_centre()
        self.b.drag(x, y, 5)  # far left: the lists would swallow the globe
        self.assertGreaterEqual(self.b.run(GLOBE), 300)
        x, y = self.divider_centre()
        self.b.drag(x, y, 1275)  # far right: the lists would vanish
        self.assertGreaterEqual(self.b.run(SIDE), 260)

    def test_a_smaller_window_never_hides_the_globe(self):
        self.b.size(1910, 900)
        self.reload()
        x, y = self.divider_centre()
        self.b.drag(x, y, 600)
        self.b.size(1000, 800)
        self.b.wait_for(f"{GLOBE} >= 300", timeout=5)
        self.assertGreaterEqual(self.b.run(SIDE), 260)

    def test_junk_in_storage_never_breaks_the_layout(self):
        for side, folded in (("-5000", "{bad"), ("99999", '"panel:kev"'), ("abc", "[1, 2]"), ("", "null"),
                             ("1e9", '{"panel:kev": true}'), ("NaN", "")):
            with self.subTest(side=side, folded=folded):
                self.b.run(f"localStorage.setItem('ww.board.side', {json.dumps(side)});"
                           f"localStorage.setItem('ww.board.folded', {json.dumps(folded)})")
                self.reload()
                self.assertGreaterEqual(self.b.run(SIDE), 260, (side, folded))
                self.assertGreaterEqual(self.b.run(GLOBE), 300, (side, folded))
                self.assertTrue(self.b.run("[...document.querySelectorAll('#panels ol')].every((o) => !o.hidden)"),
                                (side, folded))

    def test_a_browser_that_refuses_storage_still_works(self):
        script = self.b.before_each_page(
            "Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('no', 'SecurityError'); } });")
        try:
            self.reload()
            before = self.b.run(SIDE)
            x, y = self.divider_centre()
            self.b.drag(x, y, x - 100)
            self.assertAlmostEqual(self.b.run(SIDE), before + 100, delta=2)
            self.b.run("document.querySelector('#panels .fold').click()")
            self.assertTrue(self.b.run("document.querySelector('#panels ol').hidden"))
        finally:
            self.b.forget_script(script)
            self.reload()  # the next test needs storage back

    def test_a_narrow_screen_stacks_without_a_divider(self):
        self.b.size(700, 900)
        self.reload()
        self.assertFalse(self.b.run("document.querySelector('#divider').offsetParent !== null"))
        self.assertAlmostEqual(self.b.run(SIDE), self.b.run(GLOBE), delta=2)

    # -- folding lists -----------------------------------------------------------------------------

    def test_lists_fold_and_stay_folded_after_a_reload(self):
        first = "document.querySelector('#panels .box')"
        self.assertEqual(self.b.run(f"{first}.querySelector('.fold').getAttribute('aria-expanded')"), "true")
        self.b.run(f"{first}.querySelector('.fold').click()")
        self.assertTrue(self.b.run(f"{first}.querySelector('ol').hidden"))
        self.assertEqual(self.b.run(f"{first}.querySelector('.fold').getAttribute('aria-expanded')"), "false")
        self.reload()
        self.assertTrue(self.b.run(f"{first}.querySelector('ol').hidden"), "the fold is remembered")
        self.assertFalse(self.b.run("document.querySelectorAll('#panels .box')[1].querySelector('ol').hidden"))
        self.b.run(f"{first}.querySelector('.fold').click()")
        self.reload()
        self.assertFalse(self.b.run(f"{first}.querySelector('ol').hidden"))

    def test_the_layers_list_folds_too(self):
        self.b.run("document.querySelector('#layers-box .fold').click()")
        self.assertTrue(self.b.run("document.querySelector('#layers').hidden"))
        self.reload()
        self.assertTrue(self.b.run("document.querySelector('#layers').hidden"))

    # -- D-17 still holds in the browser -----------------------------------------------------------

    def test_the_page_breaks_no_policy_rule_but_globe_gl_s_known_styles(self):
        x, y = self.divider_centre()
        self.b.drag(x, y, x - 50)
        self.b.run("document.querySelector('#panels .fold').click(); document.querySelector('#fresh .dot').click()")
        breaches = self.b.run("window.__csp")
        self.assertIn("style-src-elem inline", breaches, "the watch saw nothing: it never ran")
        self.assertTrue(all(b == "style-src-elem inline" for b in breaches), breaches)

    def test_the_page_asks_nothing_of_any_host_but_its_own(self):
        hosts = self.b.run("[...new Set(performance.getEntriesByType('resource').map((e) => new URL(e.name).host))]")
        self.assertEqual(hosts, [f"127.0.0.1:{self.srv.server_port}"])


if __name__ == "__main__":
    unittest.main()
