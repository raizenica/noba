"""Tests for the cron expression matcher."""
from datetime import datetime

from server.scheduler import _match_cron


def _dt(minute=0, hour=0, day=1, month=1, weekday_iso=1):
    """Build a datetime for testing. weekday_iso: 1=Mon..7=Sun."""
    # Find a date that matches the desired weekday
    # Use 2024 as base year (Jan 1 = Monday)
    # weekday_iso: 1=Mon, 2=Tue, ..., 7=Sun
    d = datetime(2024, month, day, hour, minute)
    return d


class TestCronWildcard:
    def test_all_stars(self):
        assert _match_cron("* * * * *", datetime(2024, 3, 15, 10, 30))

    def test_no_match_minute(self):
        assert not _match_cron("0 * * * *", datetime(2024, 3, 15, 10, 30))

    def test_match_minute(self):
        assert _match_cron("30 * * * *", datetime(2024, 3, 15, 10, 30))


class TestCronExact:
    def test_exact_match(self):
        assert _match_cron("0 3 * * *", datetime(2024, 3, 15, 3, 0))

    def test_exact_no_match(self):
        assert not _match_cron("0 3 * * *", datetime(2024, 3, 15, 4, 0))

    def test_specific_day(self):
        assert _match_cron("0 0 15 * *", datetime(2024, 3, 15, 0, 0))
        assert not _match_cron("0 0 15 * *", datetime(2024, 3, 14, 0, 0))


class TestCronComma:
    def test_comma_list(self):
        assert _match_cron("0,15,30,45 * * * *", datetime(2024, 1, 1, 0, 15))
        assert _match_cron("0,15,30,45 * * * *", datetime(2024, 1, 1, 0, 30))
        assert not _match_cron("0,15,30,45 * * * *", datetime(2024, 1, 1, 0, 10))


class TestCronRange:
    def test_range(self):
        assert _match_cron("* 9-17 * * *", datetime(2024, 1, 1, 12, 0))
        assert _match_cron("* 9-17 * * *", datetime(2024, 1, 1, 9, 0))
        assert _match_cron("* 9-17 * * *", datetime(2024, 1, 1, 17, 0))
        assert not _match_cron("* 9-17 * * *", datetime(2024, 1, 1, 8, 0))
        assert not _match_cron("* 9-17 * * *", datetime(2024, 1, 1, 18, 0))


class TestCronStep:
    def test_star_step(self):
        assert _match_cron("*/15 * * * *", datetime(2024, 1, 1, 0, 0))
        assert _match_cron("*/15 * * * *", datetime(2024, 1, 1, 0, 15))
        assert _match_cron("*/15 * * * *", datetime(2024, 1, 1, 0, 30))
        assert not _match_cron("*/15 * * * *", datetime(2024, 1, 1, 0, 10))

    def test_range_step(self):
        assert _match_cron("0 0-12/3 * * *", datetime(2024, 1, 1, 0, 0))
        assert _match_cron("0 0-12/3 * * *", datetime(2024, 1, 1, 3, 0))
        assert _match_cron("0 0-12/3 * * *", datetime(2024, 1, 1, 6, 0))
        assert not _match_cron("0 0-12/3 * * *", datetime(2024, 1, 1, 1, 0))


class TestCronWeekday:
    def test_sunday(self):
        # 2024-01-07 is a Sunday (isoweekday=7, %7=0)
        assert _match_cron("0 0 * * 0", datetime(2024, 1, 7, 0, 0))
        assert not _match_cron("0 0 * * 0", datetime(2024, 1, 8, 0, 0))  # Monday

    def test_monday(self):
        # 2024-01-08 is a Monday (isoweekday=1, %7=1)
        assert _match_cron("0 0 * * 1", datetime(2024, 1, 8, 0, 0))

    def test_friday(self):
        # 2024-01-05 is a Friday (isoweekday=5, %7=5)
        assert _match_cron("0 0 * * 5", datetime(2024, 1, 5, 0, 0))


class TestCronInvalid:
    def test_too_few_fields(self):
        assert not _match_cron("* *", datetime(2024, 1, 1, 0, 0))

    def test_empty(self):
        assert not _match_cron("", datetime(2024, 1, 1, 0, 0))
