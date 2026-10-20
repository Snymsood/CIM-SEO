"""Weekly reruns must preserve the completed calendar week."""

from datetime import date

from seo_utils import get_weekly_date_windows


def test_monday_and_tuesday_use_same_completed_week():
    expected = (date(2026, 10, 12), date(2026, 10, 18),
                date(2026, 10, 5), date(2026, 10, 11))
    assert get_weekly_date_windows(date(2026, 10, 19)) == expected
    assert get_weekly_date_windows(date(2026, 10, 20)) == expected


def test_sunday_uses_previous_completed_week():
    assert get_weekly_date_windows(date(2026, 10, 18)) == (
        date(2026, 10, 5), date(2026, 10, 11),
        date(2026, 9, 28), date(2026, 10, 4),
    )
