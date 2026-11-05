"""Task 3b: official status pages (GitHub, Cloudflare, Claude via Atlassian Statuspage; Google
Workspace's own JSON) and their outage alerts in "my stack" — on the feeds as saved on 28 Oct 2026."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import LIVE, fixture
from tests.test_security import NO_PHP, REPLAY_NOW, StoreCase, gz
from worldwatch import recon
from worldwatch.board.data import Registry, panel_entries
from worldwatch.collectors import ParseError, all_collectors, my_stack, nvd, status_pages
from worldwatch.http import Fetcher
from worldwatch.runner import run_once

SAVED = {
    status_pages.GITHUB: "statuspage_github_2026-10-28.json.gz",
    status_pages.CLOUDFLARE: "statuspage_cloudflare_2026-10-28.json.gz",
    status_pages.CLAUDE: "statuspage_claude_2026-10-28.json.gz",
    status_pages.GOOGLE: "google_workspace_2026-10-28.json.gz",
}
FETCHED = datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc)
PAGES_DAY = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)  # 19 Oct, 23:00 in CDMX
PAGES_OUTAGE = "8tzbpcnl75jp"  # 19 Oct: "Degraded availability for GitHub Actions, GitHub Pages and Webhooks"
CLOUDFLARE_DAY = datetime(2026, 10, 23, 5, 0, tzinfo=timezone.utc)
CLOUDFLARE_MAJORS = {"qwrtvb4jfvk7", "l3d16334tgjp"}  # 22 Oct, impact major (and four minor ones)


def parsed(collector, now=FETCHED):
    return collector.parse(gz(SAVED[collector]), now)


def by_id(items, native: str):
    return next(i for i in items if json.loads(i.raw)["id"] == native)


def incident(**over) -> dict:
    base = {"id": "abcdef123456", "name": "Incident with Pages", "status": "resolved", "impact": "major",
            "created_at": "2026-10-19T15:49:25.822Z", "started_at": "2026-10-19T15:49:25.822Z",
            "resolved_at": "2026-10-19T18:00:00.000Z", "components": [{"name": "Pages"}], "incident_updates": []}
    return {**base, **over}


def alert_keys(items) -> set:
    return {json.loads(i.raw)["key"].split("/")[1] for i in items if json.loads(i.raw).get("stage") == "outage"}


class Statuspage(unittest.TestCase):
    def test_saved_github_feed(self):
        items = parsed(status_pages.GITHUB)
        self.assertEqual(len(items), 50)
        pages = by_id(items, PAGES_OUTAGE)
        self.assertEqual(pages.title, "GitHub — Degraded availability for GitHub Actions, GitHub Pages and Webhooks")
        self.assertEqual(pages.url, f"https://www.githubstatus.com/incidents/{PAGES_OUTAGE}")
        self.assertEqual(pages.happened_at, "2026-10-19T15:49:25Z")  # when it started, not when fetched
        self.assertEqual(pages.severity, "critical impact")
        self.assertEqual(pages.channel, "status")
        raw = json.loads(pages.raw)
        self.assertEqual(raw["status"], "resolved")
        self.assertEqual(raw["names"][0], ["", "GitHub"])
        self.assertIn(["", "GitHub Pages"], raw["names"])  # a section under its service's name
        self.assertTrue(pages.summary.startswith("GitHub: critical impact, resolved."))

    def test_saved_cloudflare_and_claude_feeds(self):
        self.assertEqual(len(parsed(status_pages.CLOUDFLARE)), 50)
        claude = parsed(status_pages.CLAUDE)
        self.assertEqual(len(claude), 50)
        names = json.loads(claude[0].raw)["names"]
        self.assertEqual(names[0], ["Anthropic", "Claude"])
        self.assertIn(["Anthropic", "Claude Code"], names)
        self.assertTrue(claude[0].url.startswith("https://status.claude.com/incidents/"))

    def test_odd_records_are_skipped_not_fatal(self):
        bad = [incident(id="../../evil"), incident(id="javascript1"), incident(impact="catastrophic"),
               incident(started_at=None, created_at=None), incident(id="good123456")]
        items = status_pages.GITHUB.parse(json.dumps({"incidents": bad}).encode(), FETCHED)
        self.assertEqual([json.loads(i.raw)["id"] for i in items], ["javascript1", "good123456"])
        self.assertTrue(all(i.url.startswith("https://www.githubstatus.com/incidents/") for i in items))

    def test_an_open_incident_says_so(self):
        item = status_pages.GITHUB.parse(json.dumps({"incidents": [incident(
            status="investigating", resolved_at=None,
            incident_updates=[{"created_at": "2026-10-19T16:00:00Z", "body": "We are investigating."},
                              {"created_at": "2026-10-19T15:50:00Z", "body": "older"}])]}).encode(), FETCHED)[0]
        self.assertEqual(json.loads(item.raw)["status"], "investigating")
        self.assertIsNone(json.loads(item.raw)["ended"])
        self.assertIn("major impact, investigating. We are investigating.", item.summary)

    def test_the_newest_update_by_time_not_by_spelling(self):
        item = status_pages.GITHUB.parse(json.dumps({"incidents": [incident(incident_updates=[
            {"created_at": "2026-10-19T10:00:00-07:00", "body": "newest (17:00 UTC)"},
            {"created_at": "2026-10-19T16:00:00Z", "body": "older"},
            {"created_at": "garbage", "body": "odd"}])]}).encode(), FETCHED)[0]
        self.assertIn("newest (17:00 UTC)", item.summary)

    def test_not_the_documented_shape_is_a_parse_error(self):
        for payload in (b"[]", b'{"incidents": {}}', b"<html>"):
            with self.assertRaises(ParseError):
                status_pages.GITHUB.parse(payload, FETCHED)

    @unittest.skipUnless(LIVE, "set WW_LIVE=1 for the live feeds")
    def test_live(self):
        fetcher = Fetcher()
        for collector in status_pages.COLLECTORS:
            with self.subTest(collector.source):
                self.assertGreater(len(collector.parse(fetcher.get(collector.url), datetime.now(timezone.utc))), 5)


class GoogleWorkspace(unittest.TestCase):
    def test_saved_feed(self):
        items = parsed(status_pages.GOOGLE)
        self.assertEqual(len(items), 36)
        impacts = {json.loads(i.raw)["impact"] for i in items}
        self.assertEqual(impacts, {"none", "minor", "major"})
        gmail = next(i for i in items if ["Google", "Gmail"] in json.loads(i.raw)["names"])
        self.assertEqual(json.loads(gmail.raw)["names"][0], ["", "Google Workspace"])
        self.assertTrue(gmail.url.startswith("https://www.google.com/appsstatus/dashboard/incidents/"))
        drive = next(i for i in items if ["", "Google Drive"] in json.loads(i.raw)["names"])
        self.assertTrue(drive.title.startswith("Google Workspace — "))

    def test_several_products_are_named_not_multiple_products(self):
        multi = next(i for i in parsed(status_pages.GOOGLE) if "Gmail, Google Calendar" in i.title)
        self.assertTrue(multi.title.startswith("Google Workspace — Gmail, Google Calendar, Google Chat"), multi.title)

    def test_not_a_list_is_a_parse_error(self):
        with self.assertRaises(ParseError):
            status_pages.GOOGLE.parse(b'{"incidents": []}', FETCHED)


class OutageAlerts(StoreCase):
    def pages(self, collector, now):
        self.store.save_items(parsed(collector, now))

    def test_done_when_a_past_outage_alerts_with_the_service_and_not_without(self):
        self.pages(status_pages.GITHUB, PAGES_DAY)
        with_it = self.derive(NO_PHP + "GitHub\n", PAGES_DAY)
        self.assertIn(PAGES_OUTAGE, alert_keys(with_it))
        alert = next(i for i in with_it if PAGES_OUTAGE in json.loads(i.raw)["key"])
        self.assertEqual(alert.happened_at, "2026-10-19T15:49:25Z")
        self.assertEqual(alert.url, f"https://www.githubstatus.com/incidents/{PAGES_OUTAGE}")
        self.assertEqual(alert.title, "GitHub · GitHub: Degraded availability for GitHub Actions, GitHub Pages and"
                                      " Webhooks — critical impact, resolved")
        self.assertIn('Matched your watchlist entry "GitHub" on GitHub.', alert.summary)
        self.assertEqual(alert.basis, "inferred")
        self.assertEqual(self.derive(NO_PHP, PAGES_DAY), [])
        # A replay never sees what came later (21 Oct's critical incident is in the same saved feed).
        self.assertNotIn("nms1dpzmh9d9", alert_keys(with_it))

    def test_a_part_of_a_service_matches_only_its_own_incidents(self):
        self.pages(status_pages.GITHUB, PAGES_DAY)
        pages_only = self.derive("GitHub Pages\n", PAGES_DAY)
        self.assertIn(PAGES_OUTAGE, alert_keys(pages_only))
        everything = alert_keys(self.derive("GitHub\n", PAGES_DAY))
        self.assertIn("cjwszcf57bff", everything)  # 6 Oct, Webhooks and Pull Requests: no Pages in it
        self.assertNotIn("cjwszcf57bff", alert_keys(pages_only))
        self.assertLess(alert_keys(pages_only), everything)

    def test_a_generic_section_name_is_not_someone_elses_product(self):
        now = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
        self.pages(status_pages.GITHUB, now)
        self.pages(status_pages.CLOUDFLARE, now)
        # Microsoft Copilot and Microsoft Access are not GitHub's Copilot or Cloudflare's Access.
        self.assertEqual(self.derive("Copilot\nAccess\nPages\n", now), [])
        self.assertTrue(alert_keys(self.derive("GitHub Copilot\n", now)))
        self.assertTrue(alert_keys(self.derive("Cloudflare Access\n", now)))

    def test_an_open_incident_alert_keeps_its_day_when_it_resolves(self):
        now = datetime(2026, 10, 19, 17, 0, tzinfo=timezone.utc)
        open_ = incident(status="investigating", resolved_at=None)
        self.store.save_items(status_pages.GITHUB.parse(json.dumps({"incidents": [open_]}).encode(), now))
        first = self.derive("GitHub Pages\n", now, save=True)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].title.endswith("major impact, investigating"), first[0].title)
        later = now + timedelta(hours=2)
        self.store.save_items(status_pages.GITHUB.parse(json.dumps({"incidents": [incident()]}).encode(), later))
        again = self.derive("GitHub Pages\n", later)
        self.assertEqual([(i.id, i.happened_at) for i in again], [(first[0].id, first[0].happened_at)])
        self.assertTrue(again[0].title.endswith("major impact, resolved"))

    def test_claude_and_google_names(self):
        now = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)
        self.pages(status_pages.CLAUDE, now)
        self.pages(status_pages.GOOGLE, now)
        self.assertTrue(alert_keys(self.derive("Claude Code\n", now)))
        self.assertTrue(alert_keys(self.derive("Anthropic = claude\n", now)))
        self.assertEqual(self.derive("Anthropic\n", now), [])  # a vendor alone matches nothing
        drive = self.derive("Google Drive\n", now)
        self.assertEqual({json.loads(i.raw)["key"].split("/")[0] for i in drive if " · " in i.title},
                         {"google-workspace-status"})

    def test_no_impact_raises_no_alert(self):
        now = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
        self.pages(status_pages.GITHUB, now)
        keys = alert_keys(self.derive("GitHub\n", now))
        self.assertNotIn("dnslv7xdl4fj", keys)  # impact "none"
        self.assertIn("wq8305lppdc2", keys)     # impact "minor"

    def test_the_cap_is_shared_but_a_big_outage_goes_over_it(self):
        self.load(CLOUDFLARE_DAY)  # NVD 21-22 Oct: Roundcube's 19 CVEs on 22 Oct
        self.pages(status_pages.CLOUDFLARE, CLOUDFLARE_DAY)
        items = self.derive("Roundcube = roundcube webmail\nCloudflare\n", CLOUDFLARE_DAY)
        on_22 = [i for i in items if " · " in i.title and i.happened_at.startswith("2026-10-22")]
        self.assertEqual(alert_keys(on_22), CLOUDFLARE_MAJORS)  # the 4 minor outages share the 5 and lose
        self.assertEqual(len(on_22), my_stack.CAP_PER_DAY + len(CLOUDFLARE_MAJORS))
        more = next(i.title for i in items if i.title.startswith("+") and "2026-10-22" in i.title)
        self.assertTrue(more.startswith(f"+{19 + 4 - my_stack.CAP_PER_DAY} more"), more)

    def test_a_full_day_keeps_its_alerts_and_still_takes_a_big_outage(self):
        self.load(CLOUDFLARE_DAY)
        first = self.derive("Roundcube = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        shown = {i.id for i in first if " · " in i.title}
        self.pages(status_pages.CLOUDFLARE, CLOUDFLARE_DAY)
        again = self.derive("Roundcube = roundcube webmail\nCloudflare\n", CLOUDFLARE_DAY, save=True)
        on_22 = [i for i in again if " · " in i.title and i.happened_at.startswith("2026-10-22")]
        self.assertLessEqual(shown, {i.id for i in on_22})
        self.assertEqual(alert_keys(on_22), CLOUDFLARE_MAJORS)
        # The big ones never use up the 5: the re-run changes nothing.
        third = self.derive("Roundcube = roundcube webmail\nCloudflare\n", CLOUDFLARE_DAY)
        self.assertEqual({i.id for i in third}, {i.id for i in again})

    def test_an_outage_that_worsens_on_a_full_day_comes_out_of_the_more_line(self):
        self.load(CLOUDFLARE_DAY)
        self.derive("Roundcube = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        day = {"started_at": "2026-10-22T10:00:00Z", "created_at": "2026-10-22T10:00:00Z", "resolved_at": None,
               "status": "investigating", "components": [{"name": "Pages"}]}

        def seen(impact):
            self.store.save_items(status_pages.GITHUB.parse(
                json.dumps({"incidents": [incident(impact=impact, **day)]}).encode(), CLOUDFLARE_DAY))
            return alert_keys(self.derive("Roundcube = roundcube webmail\nGitHub\n", CLOUDFLARE_DAY))

        self.assertEqual(seen("minor"), set())
        self.assertEqual(seen("critical"), {"abcdef123456"})

    def test_a_list_of_parts_still_hears_of_a_big_outage_that_names_no_part(self):
        now = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
        self.pages(status_pages.CLOUDFLARE, now)
        keys = alert_keys(self.derive("Catalogue = cloudflare workers, cloudflare d1\n", now))
        self.assertIn("dk2obcyw2aew", keys)  # 27 Oct, major, ERR_TIMED_OUT for customers: no part named
        minor_no_part = [json.loads(i.raw)["id"] for i in parsed(status_pages.CLOUDFLARE)
                         if len(json.loads(i.raw)["names"]) == 1 and json.loads(i.raw)["impact"] == "minor"]
        self.assertTrue(minor_no_part)
        self.assertFalse(keys & set(minor_no_part))
        self.assertEqual(self.derive("GitHub Pages\n", now), [])  # a part of another service

    def test_days_away_lose_nothing_within_thirty_days(self):
        back = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
        self.pages(status_pages.GITHUB, back)
        self.pages(status_pages.CLOUDFLARE, back)
        self.pages(status_pages.CLAUDE, back)
        collector = my_stack.collector(self.watch("GitHub\nCloudflare\nClaude\n"))
        self.store.save_items(collector.derive(self.store, back))
        self.assertEqual(collector.panel.window, my_stack.LOOKBACK)
        rows = self.store.items_between(my_stack.SOURCE, "2026-09-28", "2026-10-29", limit=my_stack.SCAN_LIMIT)
        entries = panel_entries(self.store, Registry([collector]).panel("my-stack"), back)["entries"]
        self.assertEqual(len(entries), len(rows))  # the oldest day is still on the Board
        self.assertGreater(len(rows), 60)
        days = {}
        for row in rows:
            data = json.loads(row["raw"])
            if data["kind"] == "alert" and data["impact"] == "minor":
                days[row["happened_at"][:10]] = days.get(row["happened_at"][:10], 0) + 1
        self.assertLessEqual(max(days.values()), my_stack.CAP_PER_DAY)  # each day kept its own 5

    def test_a_name_taken_off_the_list_leaves_the_board_and_frees_its_day(self):
        self.load(CLOUDFLARE_DAY)
        self.derive("Roundcube = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        self.assertGreater(self.store.count_items(my_stack.SOURCE), my_stack.CAP_PER_DAY)  # five and a "+14 more"
        self.pages(status_pages.CLOUDFLARE, CLOUDFLARE_DAY)
        items = self.derive("Cloudflare\n", CLOUDFLARE_DAY, save=True)
        rows = self.store.items_between(my_stack.SOURCE, "2026-10-01", "2026-10-29", limit=1000)
        self.assertEqual({r["id"] for r in rows}, {i.id for i in items})
        self.assertFalse([r for r in rows if "Roundcube" in r["title"] or r["title"].startswith("+14")])
        on_22 = [r for r in rows if r["happened_at"].startswith("2026-10-22")]
        self.assertEqual(len(on_22), 6)  # all six Cloudflare incidents: Roundcube's five freed the day

    def test_a_renamed_entry_keeps_the_alert_and_its_day(self):
        self.load(CLOUDFLARE_DAY)
        first = self.derive("Roundcube = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        again = self.derive("Mail = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        self.assertEqual({(i.id, i.happened_at) for i in again}, {(i.id, i.happened_at) for i in first})
        self.assertTrue(all(i.title.startswith(("Mail · ", "+")) for i in again))

    def test_a_line_it_cannot_use_removes_nothing(self):
        self.load(CLOUDFLARE_DAY)
        text = "Roundcube = roundcube webmail@PHP@".replace("@", "\n")
        first = self.derive(text, CLOUDFLARE_DAY, save=True)
        with self.assertLogs("worldwatch.watchlist", level="WARNING"):
            self.derive("Round*cube@PHP@".replace("@", "\n"), CLOUDFLARE_DAY, save=True)
        again = self.derive(text, CLOUDFLARE_DAY)
        self.assertEqual({i.id for i in again}, {i.id for i in first})

    def test_forgetting_touches_only_the_named_source(self):
        self.pages(status_pages.GITHUB, PAGES_DAY)
        row = self.store.items_between("github-status", "2026-01-01", "2027-01-01", limit=1)[0]
        self.store.forget_items(my_stack.SOURCE, [row["id"]])
        self.assertEqual(self.store.count_items("github-status"), 50)

    def test_recon_keeps_every_big_outage_of_the_week(self):
        back = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
        for collector in (status_pages.GITHUB, status_pages.CLOUDFLARE, status_pages.CLAUDE):
            self.pages(collector, back)
        collector = my_stack.collector(self.watch("GitHub@Cloudflare@Claude@".replace("@", "\n")))
        items = collector.derive(self.store, back)
        self.store.save_items(items)
        week = {i.id for i in items if i.happened_at >= "2026-10-22" and (i.severity or "-").split()[0] in ("major", "critical")}
        self.assertGreater(len(week), 5)
        section = next(s for s in recon.gather(self.store, [collector], back).sections if s.key == "my-stack")
        self.assertLessEqual(week, {row["id"] for group in section.groups for row in group.rows})

    def test_a_watchlist_that_cannot_be_read_wipes_nothing(self):
        self.load(CLOUDFLARE_DAY)
        first = self.derive("Roundcube = roundcube webmail\n", CLOUDFLARE_DAY, save=True)
        self.assertEqual(my_stack.derive(self.store, CLOUDFLARE_DAY, self.dir / "missing.txt"), [])
        self.assertEqual(self.store.count_items(my_stack.SOURCE), len(first))


class Wiring(StoreCase):
    def test_a_run_asks_fixed_questions_and_shows_outages_on_the_board(self):
        self.watch("GitHub\nSecretService\n")
        requested = []
        answers = {c.url: gz(name) for c, name in SAVED.items()}

        class Fake:
            def get(self, url):
                requested.append(url)
                return answers[url]

        collectors = [c for c in all_collectors(self.dir) if c.source in status_pages.SOURCES or c.derive]
        results = run_once(self.store, collectors, Fake(), PAGES_DAY)
        self.assertTrue(all(r.ok for r in results), results)
        self.assertEqual(sorted(requested), sorted(answers))  # one fixed URL per page, nothing from the list
        self.assertFalse(any("secret" in u.lower() or "github\n" in u.lower() for u in requested))
        registry = Registry(collectors)
        alerts = panel_entries(self.store, registry.panel("my-stack"), PAGES_DAY)["entries"]
        self.assertTrue(any(PAGES_OUTAGE in (e["url"] or "") for e in alerts))
        github = panel_entries(self.store, registry.panel("github-status"), PAGES_DAY)["entries"]
        self.assertEqual(github[0]["url"], f"https://www.githubstatus.com/incidents/{PAGES_OUTAGE}")
        self.assertNotIn(nvd.SOURCE, {r.source for r in results})


if __name__ == "__main__":
    unittest.main()
