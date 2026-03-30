from datetime import datetime

import pytz


def localize(dt_utc, tz_name: str) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = pytz.UTC.localize(dt_utc)
    tz = pytz.timezone(tz_name or "Europe/Paris")
    return dt_utc.astimezone(tz)


def to_utc(dt_local, tz_name: str) -> datetime:
    tz = pytz.timezone(tz_name or "Europe/Paris")
    if dt_local.tzinfo is None:
        dt_local = tz.localize(dt_local)
    return dt_local.astimezone(pytz.UTC).replace(tzinfo=None)
