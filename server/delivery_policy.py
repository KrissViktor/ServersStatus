"""Automatic Telegram delivery windows in Moscow time."""
from datetime import datetime, timedelta, timezone

MSK=timezone(timedelta(hours=3))


def opening_hour(now):
    return 8 if datetime.fromtimestamp(now,MSK).weekday()<5 else 12


def delivery_window(now):
    hour=datetime.fromtimestamp(now,MSK).hour
    return opening_hour(now)<=hour<20
