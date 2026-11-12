"""In-memory backend for building and demoing without AWS (BACKEND=fake).

Starts from the same rows as load_starting_data.py (starting_data.py).
simulate_event() and flag_overstays() stand in for the ESP32 and the Lambdas (used by /dev).
"""

import copy
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from starting_data import DEMO_USER, LOTS, OFFICER, SPACES, simulated_history, simulated_rows

from .base import Backend, now_iso

# Fake-only accounts, never used with BACKEND=aws. Passwords are kept apart from the
# user rows, the way Cognito keeps them apart from sbp-users.
FAKE_USERS = {
    OFFICER["id"]: dict(OFFICER, email="officer@example.com"),
    "alice": {"id": "alice", "name": "Alice Tan", "email": "alice@example.com", "role": "cyclist"},
    DEMO_USER["id"]: dict(DEMO_USER),  # owner of the simulated parked bikes; no password, can't log in
}
FAKE_PASSWORDS = {OFFICER["id"]: "officer1", "alice": "alice123"}

# There is no IR sensor in fake mode, so after an Unlock the fake "ESP32" reports bike_left by itself.
BIKE_LEFT_AFTER_SECONDS = 8


class FakeBackend(Backend):
    def __init__(self):
        self._lock = threading.Lock()
        self.users = copy.deepcopy(FAKE_USERS)
        self.passwords = dict(FAKE_PASSWORDS)  # stands in for Cognito
        sim_spaces, sim_lots, sim_sessions = simulated_rows()
        self.spaces = {s["id"]: dict(s) for s in SPACES + sim_spaces}
        self.lots = {(l["space_id"], l["id"]): dict(l) for l in LOTS + sim_lots}
        self.sessions = {s["id"]: dict(s) for s in sim_sessions}
        self.flag_overstays(3 * 1440)  # simulated bikes parked over 3 days start as suspected abandoned
        past_sessions, past_tamper = simulated_history(sim_lots)  # last 30 days, for the officer charts
        self.sessions.update({s["id"]: s for s in past_sessions})
        self.tamper_events = {e["id"]: e for e in past_tamper}
        self.published = []  # (lot_id, payload) log of open commands
        self._leaving = set()  # lots with an automatic bike_left already scheduled

    # Users
    def get_user(self, user_id):
        u = self.users.get(user_id)
        return dict(u) if u else None

    def authenticate(self, user_id, password):
        if self.passwords.get(user_id) != password:
            return None
        return self.get_user(user_id)

    def sign_up(self, user_id, name, email, password):
        with self._lock:
            if user_id in self.users:
                return "That username is taken. Pick another one."
            self.passwords[user_id] = password
            self.users[user_id] = {"id": user_id, "name": name, "email": email, "role": "cyclist"}
            return None

    def set_telegram_chat_id(self, user_id, chat_id):
        self.users[user_id]["telegram_chat_id"] = chat_id

    # Spaces and lots
    def list_spaces(self):
        return [dict(s) for s in self.spaces.values()]

    def get_space(self, space_id):
        s = self.spaces.get(space_id)
        return dict(s) if s else None

    def list_lots(self, space_id):
        return sorted((dict(l) for (sid, _), l in self.lots.items() if sid == space_id), key=lambda l: l["id"])

    def get_lot(self, space_id, lot_id):
        l = self.lots.get((space_id, lot_id))
        return dict(l) if l else None

    # Lot status changes
    def claim_lot(self, space_id, lot_id, user_id):
        with self._lock:
            lot = self.lots.get((space_id, lot_id))
            if not lot or lot["status"] != "free":
                return False
            session_id = str(uuid.uuid4())
            self.sessions[session_id] = {"id": session_id, "lot_id": lot_id, "user_id": user_id,
                                         "start_time": now_iso(), "is_open": "Y"}
            lot.update(status="taken", user_id=user_id, session_id=session_id)
            return True

    def mark_releasing(self, space_id, lot_id, user_id, is_officer=False):
        with self._lock:
            lot = self.lots.get((space_id, lot_id))
            if not lot or lot["status"] != "taken":
                return False
            if not is_officer and lot.get("user_id") != user_id:
                return False
            lot["status"] = "releasing"
            session = self.sessions[lot["session_id"]]
            session["end_time"] = now_iso()
            session.pop("is_open", None)
            return True

    # Commands
    def publish_open(self, lot_id):
        request_id = str(uuid.uuid4())
        self.published.append((lot_id, {"action": "open", "requestId": request_id, "expires": int(time.time()) + 30}))
        space_id = lot_id.split("#")[0]
        lot = self.lots.get((space_id, lot_id))
        # Pretend to be the cyclist + IR sensor: after an unlock, the bike leaves a few seconds later.
        if lot and lot["status"] == "releasing" and lot_id not in self._leaving:
            self._leaving.add(lot_id)
            timer = threading.Timer(BIKE_LEFT_AFTER_SECONDS, self._auto_bike_left, args=(space_id, lot_id))
            timer.daemon = True
            timer.start()
        return request_id

    def _auto_bike_left(self, space_id, lot_id):
        self._leaving.discard(lot_id)
        if self.lots[(space_id, lot_id)]["status"] == "releasing":  # still waiting for the bike to go
            self.simulate_event(space_id, lot_id, "bike_left")

    # Read-only lists
    def get_session(self, session_id):
        s = self.sessions.get(session_id)
        return dict(s) if s else None

    def list_open_sessions(self):
        return [dict(s) for s in self.sessions.values() if s.get("is_open") == "Y"]

    def list_sessions_since(self, since_iso):
        return [dict(s) for s in self.sessions.values() if s.get("end_time", "~") >= since_iso]

    def list_tamper_events(self):
        return sorted((dict(e) for e in self.tamper_events.values()), key=lambda e: e["detected_time"], reverse=True)

    # Fake-only: what the ESP32 + handle_event / check_overstay would do
    def simulate_event(self, space_id, lot_id, event_type):
        with self._lock:
            lot = self.lots[(space_id, lot_id)]
            if event_type == "bike_arrived":
                lot["bike_present"] = True
                lot.setdefault("bike_present_since", now_iso())
            elif event_type == "bike_left":
                lot["bike_present"] = False
                lot.pop("bike_present_since", None)
                if lot["status"] == "releasing":
                    lot["status"] = "free"
                    lot.pop("user_id", None)
                    lot.pop("session_id", None)
            elif event_type == "tamper":
                event_id = str(uuid.uuid4())
                event = {"id": event_id, "lot_id": lot_id, "detected_time": now_iso(), "notified": False}
                if lot.get("session_id"):
                    event["session_id"] = lot["session_id"]
                self.tamper_events[event_id] = event

    def flag_overstays(self, limit_minutes):
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=limit_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        flagged = 0
        with self._lock:
            for lot in self.lots.values():
                s = self.sessions.get(lot.get("session_id")) if lot["status"] == "taken" else None
                if s and s["start_time"] < cutoff and "overstay_notified_at" not in s:
                    s["overstay_notified_at"] = now_iso()
                    flagged += 1
        return flagged
