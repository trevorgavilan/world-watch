import unittest
from datetime import datetime

from tests.helpers import NOW, sample_item
from worldwatch.item import (
    SUMMARY_MAX,
    TITLE_MAX,
    InvalidItem,
    clean_text,
    clean_url,
    item_id,
)


class CleanText(unittest.TestCase):
    def test_strips_tags_and_scripts_text_only(self):
        self.assertEqual(clean_text("<b>Quake</b> &amp; <i>fire</i>", 100), "Quake & fire")

    def test_removes_control_characters_and_collapses_space(self):
        self.assertEqual(clean_text("a\x00b\x1b  \n c", 100), "ab c")

    def test_caps_length(self):
        text = clean_text("x" * 5000, TITLE_MAX)
        self.assertEqual(len(text), TITLE_MAX)
        self.assertTrue(text.endswith("…"))

    def test_none_is_empty(self):
        self.assertEqual(clean_text(None, 10), "")


class CleanUrl(unittest.TestCase):
    def test_keeps_http_and_https(self):
        self.assertEqual(clean_url("https://a.org/x?y=1"), "https://a.org/x?y=1")
        self.assertEqual(clean_url("http://a.org"), "http://a.org")

    def test_drops_dangerous_schemes(self):
        for bad in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "javascript://example.org/%0Aalert(1)", "data:text/html,x", "file:///c:/x", "//a.org", "https://", "https://a.org/\x00"):
            with self.subTest(bad=bad):
                self.assertIsNone(clean_url(bad))

    def test_drops_non_strings(self):
        self.assertIsNone(clean_url(None))
        self.assertIsNone(clean_url(42))


class MakeItem(unittest.TestCase):
    def test_carries_d8_fields(self):
        item = sample_item()
        self.assertEqual(item.source, "test-src")
        self.assertEqual(item.happened_at, "2026-10-23T23:50:00Z")
        self.assertEqual(item.fetched_at, "2026-10-23T23:50:00Z")
        self.assertEqual(item.licence, "test licence")
        self.assertEqual(item.basis, "reported")

    def test_id_is_stable_and_source_scoped(self):
        self.assertEqual(sample_item(1).id, sample_item(1).id)
        self.assertNotEqual(sample_item(1).id, sample_item(1, source="other").id)
        self.assertEqual(sample_item(1).id, item_id("test-src", "native-1"))

    def test_refuses_missing_title_licence_or_id(self):
        for over in ({"title": "  "}, {"licence": ""}, {"native_id": ""}, {"basis": "rumour"}):
            with self.subTest(over=over):
                with self.assertRaises(InvalidItem):
                    sample_item(**over)

    def test_refuses_naive_time(self):
        with self.assertRaises(InvalidItem):
            sample_item(happened_at=datetime(2026, 1, 1))

    def test_bad_url_kept_as_none(self):
        self.assertIsNone(sample_item(url="javascript:alert(1)").url)

    def test_coordinates_validated_as_a_pair(self):
        self.assertEqual((sample_item(lat=19.4, lon=-99.1).lat, sample_item(lat=19.4, lon=-99.1).lon), (19.4, -99.1))
        bad = sample_item(lat=95.0, lon=-99.1)
        self.assertIsNone(bad.lat)
        self.assertIsNone(bad.lon)
        self.assertIsNone(sample_item(lat=float("nan"), lon=1.0).lat)
        self.assertIsNone(sample_item(lat=True, lon=1.0).lat)

    def test_unknown_lang_becomes_none(self):
        self.assertIsNone(sample_item(lang="fr").lang)

    def test_summary_capped(self):
        self.assertLessEqual(len(sample_item(summary="y" * 9000).summary), SUMMARY_MAX)


if __name__ == "__main__":
    unittest.main()
