"""Shared Jinja2 setup and display helpers (times are stored UTC, shown in Singapore time)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

import config

from backend.base import lot_number, lot_ref

SGT = timezone(timedelta(hours=8))

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def parse_iso(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def sgt_time(value):
    """'2026-11-06T00:15:00Z' -> '08:15'."""
    return parse_iso(value).astimezone(SGT).strftime("%H:%M") if value else ""


def sgt_datetime(value):
    """'2026-11-06T00:15:00Z' -> '6 Nov, 08:15'."""
    if not value:
        return ""
    t = parse_iso(value).astimezone(SGT)
    return f"{t.day} {t:%b}, {t:%H:%M}"


def parked_for(start, end=None):
    """How long since start (or until end): '3 days', '5 h 12 min', '4 min'."""
    stop = parse_iso(end) if end else datetime.now(timezone.utc)
    minutes = max(0, int((stop - parse_iso(start)).total_seconds() // 60))
    days, hours, mins = minutes // 1440, minutes // 60 % 24, minutes % 60
    if days:
        return f"{days} day{'' if days == 1 else 's'}"
    if hours:
        return f"{hours} h {mins} min"
    return f"{mins} min"


templates.env.globals["fake_mode"] = config.BACKEND == "fake"  # shows demo-only hints

templates.env.filters.update(
    sgt_time=sgt_time, sgt_datetime=sgt_datetime, parked_for=parked_for, lot_number=lot_number, lot_ref=lot_ref,
)
