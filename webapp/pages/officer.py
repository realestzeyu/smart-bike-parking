"""J7: officer console (mockup "Government dashboard") and Force unlock. Officers only."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import config
from auth import require_officer
from backend import get_backend
from backend.base import lot_number, parse_lot_ref
from templating import SGT, parse_iso, templates

router = APIRouter()

# Lot states and their colours (same meaning on pins, KPI donut, legend and badges).
RING_COLOURS = {"tamper": "#B91C1C", "clear": "#FF6E00", "in_use": "#0F766E", "free": "#D9D7D0"}
PART_LABELS = {"tamper": "Tamper", "clear": "To clear", "in_use": "In use", "free": "Free"}


def ring_css(counts):
    """Donut ring as flat conic-gradient segments, read counter-clockwise from 12 o'clock:
    tamper, clear, in use, free. CSS draws clockwise, so lay them out from the end (free first)."""
    total = sum(counts[k] for k in RING_COLOURS)
    if not total:
        return RING_COLOURS["free"]
    stops, at = [], 0.0
    for key in ("free", "in_use", "clear", "tamper"):
        end = at + 100 * counts[key] / total
        if end > at:
            stops.append(f"{RING_COLOURS[key]} {at:.2f}% {end:.2f}%")
        at = end
    return "conic-gradient(" + ", ".join(stops) + ")"


def console_data():
    """Everything the console shows, computed from the backend (no stored counters)."""
    b = get_backend()
    spaces = {s["id"]: s for s in b.list_spaces()}
    lots = [lot for sid in spaces for lot in b.list_lots(sid)]

    def where(lot_id):
        space = spaces.get(lot_id.split("#")[0], {})
        return f"{space.get('address', lot_id.split('#')[0])} · Lot {lot_number(lot_id)}"

    names = {}

    def name_of(user_id):
        if user_id not in names:
            names[user_id] = (b.get_user(user_id) or {}).get("name", user_id)
        return names[user_id]

    parked = sorted(b.list_open_sessions(), key=lambda s: s["start_time"])  # longest first
    for s in parked:
        station = spaces.get(s["lot_id"].split("#")[0], {}).get("address", "")
        s.update(where=where(s["lot_id"]), lot_label=f"Lot {lot_number(s['lot_id'])}", station=station,
                 owner=name_of(s["user_id"]), abandoned="overstay_notified_at" in s, ref=s["lot_id"].replace("#", "_"))

    # Unregistered bikes: bike in a free lot for too long, never used the system (derived, nothing stored)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.UNREGISTERED_LIMIT_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    unregistered = sorted(
        ({"lot_id": lot["id"], "lot_label": f"Lot {lot_number(lot['id'])}", "since": lot["bike_present_since"],
          "station": spaces.get(lot["space_id"], {}).get("address", "")}
         for lot in lots
         if lot["status"] == "free" and lot.get("bike_present") and lot.get("bike_present_since", "~") < cutoff),
        key=lambda r: r["since"])  # longest first

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tamper = b.list_tamper_events()
    for e in tamper[:20]:  # only the shown rows need where/owner (one GetItem each on AWS)
        session = b.get_session(e["session_id"]) if e.get("session_id") else None
        e.update(where=where(e["lot_id"]), owner=name_of(session["user_id"]) if session else None)

    # One category per lot, same colours everywhere: tamper (red) > clear (orange) > in_use (green) > free (grey).
    # tamper = a tamper event belongs to the bike parked there now (same session), so it clears when the bike leaves.
    tampered = {e["session_id"] for e in tamper if e.get("session_id")}
    to_clear = {s["lot_id"] for s in parked if s["abandoned"]} | {r["lot_id"] for r in unregistered}

    def category(lot):
        if lot.get("session_id") in tampered:
            return "tamper"
        if lot["id"] in to_clear:
            return "clear"
        return "in_use" if lot["status"] != "free" else "free"

    stations = []
    for sid, space in spaces.items():
        counts = {"in_use": 0, "clear": 0, "tamper": 0, "free": 0}
        for lot in lots:
            if lot["space_id"] == sid:
                counts[category(lot)] += 1
        total = sum(counts.values())
        used = total - counts["free"]
        stations.append({
            "id": sid, "lat": space["lat"], "lng": space["lng"], "address": space["address"],
            "total": total, "used": used, "pct": round(100 * used / total) if total else 0, **counts,
            "ring": ring_css(counts),
        })

    used = sum(s["used"] for s in stations)
    network = {k: sum(s[k] for s in stations) for k in RING_COLOURS}
    return {
        "kpi": {
            "stations": len(spaces),
            "lots": len(lots),
            "utilisation": round(100 * used / len(lots)) if lots else 0,
            "used": used,
            "parts": [{"key": k, "label": PART_LABELS[k], "colour": RING_COLOURS[k], "n": network[k]} for k in RING_COLOURS],
            "abandoned": sum(1 for s in parked if s["abandoned"]),
            "unregistered": len(unregistered),
            "tamper_week": sum(1 for e in tamper if e["detected_time"] >= week_ago),
            "last_tamper": tamper[0]["detected_time"] if tamper else None,
        },
        "parked": parked,
        "abandoned": [s for s in parked if s["abandoned"]],  # suspected abandoned, longest first (Force unlock list)
        "unregistered": unregistered,
        "tamper": tamper[:20],
        "stations": stations,
        "usage": sorted(stations, key=lambda s: -s["pct"]),
    }


def _hour_label(t):
    h = t.astimezone(SGT).hour
    return f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"


RANGES = {24: 1, 168: 6, 720: 24}  # time range (hours) -> bucket size (hours): last 24 h, 7 days, month


def _when(t, hours):
    """Bucket label in SGT: '9 am' for 24 h, 'Wed 9 am' for 7 days, 'Wed 12 Nov' for the month."""
    s = t.astimezone(SGT)
    if hours == 24:
        return _hour_label(t)
    return f"{s:%a} {_hour_label(t)}" if hours == 168 else f"{s:%a} {s.day} {s:%b}"


def history_data(space="all", hours=24, tamper=True):
    """Usage & tamper chart on one count axis (0 .. number of lots): per time bucket, the average number
    of lots in use (sampled every 30 min, every 2 h for the month) and the tamper alerts drawn over it.
    Usage counts parkings made through the app (unregistered bikes leave no history)."""
    b = get_backend()
    spaces = sorted(b.list_spaces(), key=lambda s: s["id"])
    if space not in {s["id"] for s in spaces}:
        space = "all"
    if hours not in RANGES:
        hours = 24
    size = RANGES[hours]
    step = 120 if hours == 720 else 30  # sample interval (minutes)
    mine = (lambda lot_id: True) if space == "all" else (lambda lot_id: lot_id.startswith(space + "#"))

    now = datetime.now(timezone.utc)
    sgt = now.astimezone(SGT)
    end = (sgt.replace(minute=0, second=0, microsecond=0) - timedelta(hours=sgt.hour % size) + timedelta(hours=size)).astimezone(timezone.utc)
    n = hours // size
    starts = [end - timedelta(hours=size * (n - j)) for j in range(n)]
    total = sum(len(b.list_lots(s["id"])) for s in spaces if space in ("all", s["id"])) or 1
    sessions = [(parse_iso(s["start_time"]), parse_iso(s["end_time"]) if s.get("end_time") else None)
                for s in b.list_sessions_since(starts[0].strftime("%Y-%m-%dT%H:%M:%SZ")) if mine(s["lot_id"])]
    alerts = [parse_iso(e["detected_time"]) for e in b.list_tamper_events() if mine(e["lot_id"])] if tamper else []

    buckets = []
    for s0 in starts:
        s1 = s0 + timedelta(hours=size)
        samples = [s0 + timedelta(minutes=step // 2 + step * i) for i in range(size * 60 // step)]
        samples = [t for t in samples if t <= now] or [now]
        used = sum(sum(1 for a, z in sessions if a <= t and (z is None or z > t)) for t in samples) / len(samples)
        buckets.append((s0, used, sum(1 for t in alerts if s0 <= t < s1)))
    top = max([total] + [count for _, _, count in buckets])  # one y-scale for lots and alerts

    # SVG 960 x 204: plot x 44..948, y 12..172 (value 0 at 172, `top` at 12), x labels at y 192.
    slot = 904 / n
    width = round(slot * 0.72, 1)
    cols = []
    for j, (s0, used, count) in enumerate(buckets):
        local = s0.astimezone(SGT)
        x = round(44 + j * slot + (slot - width) / 2, 1)
        h = round(160 * used / top, 1)
        r = min(4, h, width / 2)
        bar = (f"M{x},172 V{172 - h + r} Q{x},{172 - h} {x + r},{172 - h} H{round(x + width - r, 1)} "
               f"Q{x + width},{172 - h} {x + width},{172 - h + r} V172 Z") if h else ""
        label = ""
        if hours == 24 and local.hour % 6 == 0:
            label = _hour_label(s0)
        elif hours == 168 and local.hour == 0:
            label = f"{local:%a}"
        elif hours == 720 and local.weekday() == 0:  # Mondays
            label = f"{local.day} {local:%b}"
        cols.append({"x": x, "cx": round(x + width / 2, 1), "bar": bar, "count": count, "label": label,
                     "ty": round(172 - 160 * count / top, 1),
                     "tip": f"{_when(s0, hours)} · {round(used)} of {total} lots in use" + (f" · {count} tamper" if tamper else "")})
    return {
        "space": space, "hours": hours, "tamper": tamper, "total": total, "cols": cols,
        "ticks": [{"v": v, "y": round(172 - 160 * v / top, 1)} for v in sorted({0, top // 2, top})],
        "spaces": [{"id": s["id"], "address": s["address"]} for s in spaces],
        "tamper_line": " ".join(f"{'M' if i == 0 else 'L'}{c['cx']},{c['ty']}" for i, c in enumerate(cols)),
    }


@router.get("/officer")
def console(request: Request, confirm: str = "", done: str = "", failed: str = ""):
    user = require_officer(request)
    data = console_data()
    pending = next((s for s in data["abandoned"] if s["ref"] == confirm), None)
    m = config.UNREGISTERED_LIMIT_MINUTES
    limit = f"{m // 1440} day{'' if m // 1440 == 1 else 's'}" if m >= 1440 and m % 1440 == 0 else f"{m} min"
    return templates.TemplateResponse(request, "officer.html", {
        **data, "user": user, "confirm": pending, "done": done, "failed": failed, "unregistered_limit": limit,
        "history": history_data(),
    })


@router.get("/officer/history")
def history_refresh(request: Request, space: str = "all", hours: int = 24, tamper: str = ""):
    """Filter changes and the 60 s poll; returns the chart body as an out-of-band swap."""
    require_officer(request)
    return templates.TemplateResponse(request, "_officer_history.html",
                                      {"history": history_data(space, hours, tamper == "on"), "oob": True})


@router.get("/officer/data")
def console_refresh(request: Request):
    """Polled every 5 s by HTMX; returns the KPI cards and tables as out-of-band swaps."""
    require_officer(request)
    return templates.TemplateResponse(request, "_officer_data.html", console_data())


@router.get("/officer/stations.json")
def stations_json(request: Request):
    require_officer(request)
    return console_data()["stations"]


@router.post("/officer/force-unlock/{lot_ref}")
def force_unlock(request: Request, lot_ref: str):
    user = require_officer(request)
    keys = parse_lot_ref(lot_ref)
    b = get_backend()
    if keys and b.mark_releasing(*keys, user["id"], is_officer=True):
        b.publish_open(keys[1])
        return RedirectResponse(f"/officer?done={lot_ref}", status_code=303)
    return RedirectResponse(f"/officer?failed={lot_ref}", status_code=303)
