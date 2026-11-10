"""Shared Jinja2 setup and display helpers (times are stored UTC, shown in Singapore time)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

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


templates.env.filters.update(sgt_time=sgt_time, sgt_datetime=sgt_datetime, lot_number=lot_number, lot_ref=lot_ref)
