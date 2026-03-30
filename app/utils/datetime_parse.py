from datetime import datetime

import pytz


def local_input_to_utc_naive(local_str: str, tz_name: str) -> datetime:
    """Convertit une chaîne type datetime-local en datetime UTC naïf (stockage DB)."""
    local_str = local_str.strip()
    if "T" not in local_str:
        raise ValueError("Format attendu : YYYY-MM-DDTHH:MM")
    dt = datetime.fromisoformat(local_str)
    tz = pytz.timezone(tz_name or "Europe/Paris")
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    utc = dt.astimezone(pytz.UTC)
    return utc.replace(tzinfo=None)


def utc_naive_to_local_str(dt, tz_name: str, fmt: str = "%d/%m/%Y %H:%M") -> str:
    if dt is None:
        return ""
    utc = pytz.UTC.localize(dt) if dt.tzinfo is None else dt.astimezone(pytz.UTC)
    local = utc.astimezone(pytz.timezone(tz_name or "Europe/Paris"))
    return local.strftime(fmt)
