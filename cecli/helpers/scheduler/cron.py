"""Schedule parsing and next-run computation for the workflow scheduler.

Supported expression forms:

- 5-field cron strings (``"*/30 * * * *"``), evaluated with croniter.
- Presets: ``@hourly`` / ``@daily`` / ``@weekly`` / ``@monthly`` / ``@yearly``
  and intervals ``@every <N><s|m|h|d|w>``.
- ``None`` / empty string — manual-only workflow (never due by clock).

All returned datetimes are timezone-aware UTC. The *timezone* parameter
selects the wall-clock zone the cron expression is interpreted in (an IANA
name such as ``"UTC"`` or ``"America/New_York"``); the sentinel ``"local"``
and ``None`` both mean UTC, which keeps scheduler behavior deterministic
across machines. Named zones need an IANA tz database, which Windows lacks:
``tzdata`` is therefore required there, while UTC itself never needs one.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Optional, Tuple

CRON_PRESETS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

_INTERVAL_RE = re.compile(r"^@every\s+(\d+)(s|m|h|d|w)$", re.IGNORECASE)

# Names that mean "exactly UTC". Answered without consulting the IANA database
# so a bare host (Windows ships none) can still schedule in UTC.
_UTC_ALIASES = frozenset({"utc", "z", "zulu", "universal", "gmt", "etc/utc", "etc/gmt"})

_INTERVAL_UNITS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


def parse_schedule(expr: Optional[str]) -> Tuple[str, Any]:
    """Classify *expr* as ``('cron', str)``, ``('interval', timedelta)`` or ``('manual', None)``.

    Raises ``ValueError`` for malformed schedules.
    """

    if expr is None:
        return ("manual", None)

    text = str(expr).strip()
    if not text:
        return ("manual", None)

    lowered = text.lower()
    if lowered in CRON_PRESETS:
        return ("cron", CRON_PRESETS[lowered])

    match = _INTERVAL_RE.match(lowered)
    if match:
        amount = int(match.group(1))
        if amount <= 0:
            raise ValueError(f"schedule interval must be positive: {expr!r}")
        return ("interval", amount * _INTERVAL_UNITS[match.group(2)])

    if not _looks_like_cron(text):
        raise ValueError(f"invalid schedule expression: {expr!r}")

    from croniter import croniter

    if not croniter.is_valid(text):
        raise ValueError(f"invalid cron expression: {expr!r}")

    return ("cron", text)


def next_run(
    expr: Optional[str],
    after_dt: datetime,
    timezone: Optional[str] = None,
) -> Optional[datetime]:
    """Return the first run strictly after *after_dt*, or ``None`` for manual schedules.

    *timezone* is an IANA name; ``'local'``/``None`` are treated as UTC.
    """

    engine, value = parse_schedule(expr)

    if engine == "manual":
        return None

    after_utc = _to_utc(after_dt)

    if engine == "interval":
        return _to_utc(after_utc + value)

    from croniter import croniter

    zone = resolve_timezone(timezone)
    base = after_utc.astimezone(zone)
    nxt = croniter(value, base).get_next(datetime)

    return _to_utc(nxt)


def is_due(
    expr: Optional[str],
    at_dt: datetime,
    timezone: Optional[str] = None,
    window: timedelta = timedelta(minutes=1),
) -> bool:
    """True if a run of *expr* falls inside ``[at_dt - window, at_dt]`` (test helper)."""

    previous = next_run(expr, _to_utc(at_dt) - window, timezone=timezone)

    return previous is not None and previous <= _to_utc(at_dt)


def resolve_timezone(timezone: Optional[str]):
    """Map a config timezone to a tzinfo (``'local'``/None/UTC aliases -> UTC).

    Raises ``ValueError`` for names the IANA database does not know.
    """

    if timezone is None:
        return dt_timezone.utc

    lowered = str(timezone).strip().lower()
    if not lowered or lowered in _UTC_ALIASES or lowered == "local":
        return dt_timezone.utc

    from zoneinfo import ZoneInfo

    try:
        return ZoneInfo(str(timezone).strip())
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {timezone!r}{_tzdb_hint()}") from exc


# ── private helpers ─────────────────────────────────────────────────────


def _looks_like_cron(text: str) -> bool:
    """Accept 5-field cron (and tolerate a leading ``*/`` style minute)."""

    return len(text.split()) == 5


def _tzdb_hint() -> str:
    """Suffix naming the real cause when a host simply has no tz database."""

    from zoneinfo import available_timezones

    try:
        if available_timezones():
            return ""
    except OSError:
        pass

    return " (no IANA tz database found - install the 'tzdata' package)"


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to aware UTC (naive input is assumed UTC)."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=dt_timezone.utc)

    return dt.astimezone(dt_timezone.utc)
