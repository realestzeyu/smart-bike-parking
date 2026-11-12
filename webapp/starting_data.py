"""Starting rows for the database. Used by load_starting_data.py (real DynamoDB) and the fake backend.

Field names follow docs/agreed-names-and-formats.md section 2.
"""

import uuid
from datetime import datetime, timedelta, timezone

# Coordinates are approximate (Upper Changi MRT). Double-check against Exit C before the demo.
SPACES = [
    {"id": "space1", "address": "Upper Changi MRT Exit C", "lat": 1.3417, "lng": 103.9613},
]

LOTS = [
    {"space_id": "space1", "id": "space1#lot1", "status": "free", "bike_present": False},
]

# The password is NOT stored here. load_starting_data.py asks for it when creating this account.
OFFICER = {"id": "officer", "name": "Officer", "email": "", "role": "officer"}

# ---- Simulated stations (no hardware) so the map and console look like a real network ----
# 20 lots each: one available, one with few left, one full. Coordinates approximate, all near space1.
SIMULATED_STATIONS = [
    {"id": "space2", "address": "Upper Changi MRT Exit A", "lat": 1.3440, "lng": 103.9628, "free": 12, "unregistered": 2},
    {"id": "space3", "address": "SUTD Campus Centre", "lat": 1.3413, "lng": 103.9640, "free": 2, "unregistered": 1},
    {"id": "space4", "address": "Upper Changi MRT Exit B", "lat": 1.3411, "lng": 103.9588, "free": 0, "unregistered": 0},
]
# "unregistered" = free lots with a bike in them that never used the system (officer console flag).
# How long each of those bikes has been there (minutes), cycled.
_UNREGISTERED_MINUTES = [26 * 1440, 9 * 60, 5 * 1440]
LOTS_PER_SIMULATED_STATION = 20

# Owner of every simulated parked bike. Profile row only: it has no login.
DEMO_USER = {"id": "demo", "name": "Demo Cyclist", "email": "demo@example.com", "role": "cyclist"}

# How long each simulated bike has been parked (minutes), cycled across the occupied lots.
_PARKED_MINUTES = [45, 130, 300, 720, 1500, 2 * 1440, 4 * 1440, 6 * 1440, 11 * 1440, 17 * 1440, 23 * 1440, 38 * 1440]


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def simulated_rows(now=None):
    """(spaces, lots, sessions) for the simulated stations. Session ids are fixed, so re-loading never duplicates."""
    now = now or datetime.now(timezone.utc)
    spaces, lots, sessions = [], [], []
    k = u = 0
    for st in SIMULATED_STATIONS:
        spaces.append({key: st[key] for key in ("id", "address", "lat", "lng")})
        free_lots = {(i * 7) % LOTS_PER_SIMULATED_STATION + 1 for i in range(st["free"])}  # spread across the rack
        unregistered = set(sorted(free_lots)[:st["unregistered"]])
        for n in range(1, LOTS_PER_SIMULATED_STATION + 1):
            lot_id = f"{st['id']}#lot{n}"
            if n in unregistered:
                since = now - timedelta(minutes=_UNREGISTERED_MINUTES[u % len(_UNREGISTERED_MINUTES)])
                u += 1
                lots.append({"space_id": st["id"], "id": lot_id, "status": "free", "bike_present": True,
                             "bike_present_since": _iso(since)})
                continue
            if n in free_lots:
                lots.append({"space_id": st["id"], "id": lot_id, "status": "free", "bike_present": False})
                continue
            session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "sbp-demo/" + lot_id))
            start = now - timedelta(minutes=_PARKED_MINUTES[k % len(_PARKED_MINUTES)] + k)
            k += 1
            sessions.append({"id": session_id, "lot_id": lot_id, "user_id": DEMO_USER["id"],
                             "start_time": _iso(start), "is_open": "Y"})
            lots.append({"space_id": st["id"], "id": lot_id, "status": "taken", "bike_present": True,
                         "user_id": DEMO_USER["id"], "session_id": session_id})
    return spaces, lots, sessions


# ---- Fake mode only: the last 24 h of history, so the officer's 24 h charts aren't empty ----
# Not loaded into DynamoDB (times are relative to "now" and would go stale; real use fills AWS).
# Commuter shape in Singapore time: parkings started per hour, and how long they last (minutes).
_STARTS_BY_SGT_HOUR = {6: 1, 7: 3, 8: 4, 9: 2, 11: 1, 12: 2, 13: 1, 15: 1, 17: 2, 18: 2, 19: 1, 20: 1}


def _duration_minutes(sgt_hour, k):
    if sgt_hour < 10:
        return 540 + (k * 37) % 90  # commuters: in the morning, out in the evening
    return 90 + (k * 23) % 90  # short visits


def simulated_history(lots, now=None, days=7):
    """(closed sessions, tamper events) from the last `days` days, on simulated lots. Fake backend only."""
    now = now or datetime.now(timezone.utc)
    spare = [l["id"] for l in lots if l["status"] == "free" and not l["bike_present"] and not l["id"].startswith("space1#")]
    busy_until = {lot_id: now - timedelta(days=days + 1) for lot_id in spare}
    sessions, k = [], 0
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    for h in range(24 * days, 0, -1):
        start_hour = hour0 - timedelta(hours=h)
        sgt_hour = (start_hour + timedelta(hours=8)).hour
        for _ in range(_STARTS_BY_SGT_HOUR.get(sgt_hour, 0)):
            start = start_hour + timedelta(minutes=(k * 17) % 60)
            end = start + timedelta(minutes=_duration_minutes(sgt_hour, k))
            k += 1
            lot_id = next((l for l in spare if busy_until[l] <= start), None)
            if end >= now or not lot_id:
                continue
            busy_until[lot_id] = end
            sessions.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sbp-history/{k}")), "lot_id": lot_id,
                             "user_id": DEMO_USER["id"], "start_time": _iso(start), "end_time": _iso(end)})
    taken = next((l for l in lots if l["status"] == "taken" and l["id"].startswith("space4#")), None)
    # Spread over the week (hours ago), mostly at night; the last one is on a bike still parked.
    tamper = [{"lot_id": spare[i % len(spare)], "minutes_ago": h * 60 + 20}
              for i, h in enumerate([150, 122, 98, 74, 51, 26, 21, 14])]
    tamper.append({"lot_id": taken["id"], "session_id": taken["session_id"], "minutes_ago": 140} if taken else None)
    events = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sbp-history/tamper/{i}")), "lot_id": t["lot_id"],
               "detected_time": _iso(now - timedelta(minutes=t["minutes_ago"])), "notified": "session_id" in t,
               **({"session_id": t["session_id"]} if "session_id" in t else {})}
              for i, t in enumerate(tamper) if t]
    return sessions, events
