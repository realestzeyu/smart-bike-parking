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
    {"id": "space2", "address": "Upper Changi MRT Exit A", "lat": 1.3440, "lng": 103.9628, "free": 12},
    {"id": "space3", "address": "SUTD Campus Centre", "lat": 1.3413, "lng": 103.9640, "free": 2},
    {"id": "space4", "address": "Upper Changi MRT Exit B", "lat": 1.3411, "lng": 103.9588, "free": 0},
]
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
    k = 0
    for st in SIMULATED_STATIONS:
        spaces.append({key: st[key] for key in ("id", "address", "lat", "lng")})
        free_lots = {(i * 7) % LOTS_PER_SIMULATED_STATION + 1 for i in range(st["free"])}  # spread across the rack
        for n in range(1, LOTS_PER_SIMULATED_STATION + 1):
            lot_id = f"{st['id']}#lot{n}"
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
