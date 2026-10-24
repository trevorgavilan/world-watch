import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import NOW, sample_item, temp_dir
from worldwatch import runner
from worldwatch.collectors import Collector, ParseError
from worldwatch.http import FetchError, RateLimited
from worldwatch.store import Store


def fake_collector(source, interval_s=600, items=1):
    def parse_records(data, fetched_at):
        return [lambda n=n: sample_item(n, source=source, fetched_at=fetched_at) for n in range(items)]

    return Collector(source=source, channel="news", url=f"https://example.org/{source}",
                     interval_s=interval_s, licence="test", parse_records=parse_records)


class FakeFetcher:
    """Answers per URL: bytes, or an exception to raise."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        answer = self.answers.get(url, b"{}")
        if isinstance(answer, Exception):
            raise answer
        return answer


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class RunOnce(unittest.TestCase):
    def setUp(self):
        self.store = Store(temp_dir() / "ww.sqlite3")
        self.a = fake_collector("a", items=2)
        self.b = fake_collector("b", items=3)

    def tearDown(self):
        self.store.close()

    def test_first_run_fetches_everything_and_schedules_next(self):
        fetcher = FakeFetcher()
        results = runner.run_once(self.store, [self.a, self.b], fetcher, NOW)
        self.assertEqual({r.source: r.n_items for r in results}, {"a": 2, "b": 3})
        self.assertEqual(self.store.count_items(), 5)
        self.assertEqual(self.store.source_state("a")["next_due"], iso(NOW + timedelta(seconds=600)))

    def test_not_due_is_skipped(self):
        fetcher = FakeFetcher()
        runner.run_once(self.store, [self.a], fetcher, NOW)
        runner.run_once(self.store, [self.a], fetcher, NOW + timedelta(seconds=599))
        self.assertEqual(len(fetcher.calls), 1)
        runner.run_once(self.store, [self.a], fetcher, NOW + timedelta(seconds=600))
        self.assertEqual(len(fetcher.calls), 2)

    def test_network_down_loses_nothing_and_next_run_recovers(self):
        runner.run_once(self.store, [self.a, self.b], FakeFetcher(), NOW)
        self.assertEqual(self.store.count_items(), 5)
        down = FakeFetcher({self.a.url: FetchError("no network"), self.b.url: FetchError("no network")})
        later = NOW + timedelta(seconds=600)
        results = runner.run_once(self.store, [self.a, self.b], down, later)
        self.assertTrue(all(not r.ok for r in results))
        self.assertEqual(self.store.count_items(), 5)  # nothing lost
        state = self.store.source_state("a")
        self.assertEqual(state["fail_count"], 1)
        self.assertEqual(state["last_error"], "no network")
        self.assertEqual(state["last_ok_at"], iso(NOW))
        retry_at = later + timedelta(seconds=runner.RETRY_BASE_S)
        self.assertEqual(state["next_due"], iso(retry_at))
        back = runner.run_once(self.store, [self.a, self.b], FakeFetcher(), retry_at)
        self.assertTrue(all(r.ok for r in back))
        self.assertEqual(self.store.source_state("a")["fail_count"], 0)

    def test_one_broken_source_does_not_stop_the_others(self):
        fetcher = FakeFetcher({self.a.url: ParseError("garbage")})
        results = runner.run_once(self.store, [self.a, self.b], fetcher, NOW)
        self.assertEqual({r.source: r.ok for r in results}, {"a": False, "b": True})
        self.assertEqual(self.store.count_items(), 3)

    def test_a_bug_in_a_collector_does_not_stop_the_others(self):
        def explode(data, fetched_at):
            raise RuntimeError("bug")

        broken = Collector(source="x", channel="news", url="https://example.org/x",
                           interval_s=600, licence="t", parse_records=explode)
        results = runner.run_once(self.store, [broken, self.b], FakeFetcher(), NOW)
        self.assertEqual({r.source: r.ok for r in results}, {"x": False, "b": True})

    def test_backoff_doubles_and_is_capped(self):
        delays = [runner.failure_delay_s(n, rate_limited=False, retry_after_s=None) for n in range(1, 12)]
        self.assertEqual(delays[0], runner.RETRY_BASE_S)
        self.assertEqual(delays[1], runner.RETRY_BASE_S * 2)
        self.assertEqual(max(delays), runner.RETRY_MAX_S)
        self.assertEqual(delays, sorted(delays))

    def test_rate_limit_backs_off_longer_and_honours_retry_after(self):
        self.assertEqual(runner.failure_delay_s(1, rate_limited=True, retry_after_s=None), runner.RATE_LIMIT_BASE_S)
        self.assertEqual(runner.failure_delay_s(1, rate_limited=True, retry_after_s=5000), 5000)
        self.assertEqual(runner.failure_delay_s(20, rate_limited=True, retry_after_s=None), runner.RATE_LIMIT_MAX_S)

    def test_rate_limited_source_is_scheduled_with_rate_limit_delay(self):
        fetcher = FakeFetcher({self.a.url: RateLimited("429", None)})
        runner.run_once(self.store, [self.a], fetcher, NOW)
        expected = NOW + timedelta(seconds=runner.RATE_LIMIT_BASE_S)
        self.assertEqual(self.store.source_state("a")["next_due"], iso(expected))

    def test_save_failure_is_recorded_not_raised(self):
        def bad_rows(data, fetched_at):
            from dataclasses import replace
            return [lambda: replace(sample_item(1, source="a"), title=None)]

        bad = Collector(source="a", channel="news", url="https://example.org/a",
                        interval_s=600, licence="t", parse_records=bad_rows)
        results = runner.run_once(self.store, [bad], FakeFetcher(), NOW)
        self.assertFalse(results[0].ok)
        self.assertEqual(self.store.source_state("a")["fail_count"], 1)


class HostAndClock(unittest.TestCase):
    def setUp(self):
        self.store = Store(temp_dir() / "ww.sqlite3")

    def tearDown(self):
        self.store.close()

    def test_rate_limit_on_a_host_defers_its_other_sources_without_a_failure(self):
        one = Collector(source="g1", channel="news", url="https://api.same.org/1", interval_s=3600,
                        licence="t", parse_records=lambda d, f: [])
        two = Collector(source="g2", channel="news", url="https://api.same.org/2", interval_s=3600,
                        licence="t", parse_records=lambda d, f: [])
        other = fake_collector("elsewhere")
        fetcher = FakeFetcher({one.url: RateLimited("429", None)})
        results = runner.run_once(self.store, [one, two, other], fetcher, NOW)
        self.assertEqual(fetcher.calls, [one.url, other.url])
        self.assertEqual([r.source for r in results], ["g1", "elsewhere"])
        deferred = self.store.source_state("g2")
        self.assertEqual(deferred["next_due"], self.store.source_state("g1")["next_due"])
        self.assertEqual(deferred["fail_count"], 0)
        self.assertEqual(len(self.store.runs_since(iso(NOW))), 2)  # a deferral is not a run

    def test_a_next_due_far_in_the_future_counts_as_due(self):
        a = fake_collector("a", interval_s=600)
        far = NOW + timedelta(days=30)  # stored while the clock ran ahead
        self.store.record_run("a", NOW, NOW, ok=True, n_items=0, error=None, next_due=iso(far), fail_count=0)
        self.assertTrue(runner.is_due(self.store, a, NOW))
        near = NOW + timedelta(seconds=500)
        self.store.record_run("a", NOW, NOW, ok=True, n_items=0, error=None, next_due=iso(near), fail_count=0)
        self.assertFalse(runner.is_due(self.store, a, NOW))
        backing_off = NOW + timedelta(seconds=runner.RATE_LIMIT_MAX_S - 60)
        self.store.record_run("a", NOW, NOW, ok=True, n_items=0, error=None, next_due=iso(backing_off), fail_count=3)
        self.assertFalse(runner.is_due(self.store, a, NOW))


class Loop(unittest.TestCase):
    def test_a_failing_cycle_is_logged_and_the_loop_goes_on(self):
        store = Store(temp_dir() / "ww.sqlite3")
        clock = [NOW]
        real_state = store.source_state
        calls = {"n": 0}

        def flaky_state(source):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real_state(source)

        store.source_state = flaky_state

        def sleep(seconds):
            clock[0] += timedelta(seconds=seconds)

        with self.assertLogs("worldwatch.runner", level="ERROR"):
            runner.run_loop(store, [fake_collector("a")], FakeFetcher(), now=lambda: clock[0], sleep=sleep,
                            tick_s=60, stop_at=NOW + timedelta(seconds=150))
        self.assertEqual(len(store.runs_since(iso(NOW))), 1)  # cycle 1 failed, cycle 2 fetched
        store.close()

    def test_loop_runs_cycles_and_calls_after_cycle_when_something_arrived(self):
        store = Store(temp_dir() / "ww.sqlite3")
        clock = [NOW]
        built = []

        def now():
            return clock[0]

        def sleep(seconds):
            clock[0] += timedelta(seconds=seconds)

        a = fake_collector("a", interval_s=600)
        runner.run_loop(store, [a], FakeFetcher(), after_cycle=lambda results: built.append(len(results)),
                        now=now, sleep=sleep, tick_s=300, stop_at=NOW + timedelta(seconds=1250))
        # cycles at 0, 300, 600, 900, 1200: fetches at 0, 600, 1200
        self.assertEqual(built, [1, 1, 1])
        self.assertEqual(len(store.runs_since(iso(NOW))), 3)
        store.close()


if __name__ == "__main__":
    unittest.main()
