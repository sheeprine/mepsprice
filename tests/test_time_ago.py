from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from main import time_ago

FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ago(delta: timedelta) -> datetime:
    # Return naive datetime (as SQLite would) — time_ago normalises it to UTC
    return (FIXED_NOW - delta).replace(tzinfo=None)


def test_none_returns_never():
    assert time_ago(None) == "never"


def test_just_now():
    with patch("main.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        assert time_ago(_ago(timedelta(seconds=30))) == "just now"


def test_minutes_ago():
    with patch("main.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        assert time_ago(_ago(timedelta(minutes=5))) == "5m ago"
        assert time_ago(_ago(timedelta(minutes=59))) == "59m ago"


def test_hours_ago():
    with patch("main.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        assert time_ago(_ago(timedelta(hours=2))) == "2h ago"
        assert time_ago(_ago(timedelta(hours=23))) == "23h ago"


def test_days_ago():
    with patch("main.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        assert time_ago(_ago(timedelta(days=3))) == "3d ago"
        assert time_ago(_ago(timedelta(days=30))) == "30d ago"
