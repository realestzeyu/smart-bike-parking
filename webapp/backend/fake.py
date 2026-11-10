"""In-memory backend for building and demoing without AWS (BACKEND=fake).

Starts from the same rows as load_starting_data.py (starting_data.py).
simulate_event() and flag_overstays() stand in for the ESP32 and the Lambdas (used by /dev).
"""

import copy
import threading
import uuid
from datetime import datetime, timedelta, timezone

from starting_data import LOTS, OFFICER, SPACES

from .base import Backend, now_iso

# Fake-only accounts (plaintext, never used with BACKEND=aws).
FAKE_ACCOUNTS = {
    OFFICER["id"]: {**OFFICER, "password": "officer"},
    "alice": {"id": "alice", "name": "Alice Tan", "email": "alice@example.com", "password": "alice", "role": "cyclist"},
}


class FakeBackend(Backend):
    def __init__(self):
        self._lock = threading.Lock()
        self.users = copy.deepcopy(FAKE_ACCOUNTS)
        self.spaces = {s["id"]: dict(s) for s in SPACES}
        self.lots = {(l["space_id"], l["id"]): dict(l) for l in LOTS}
        self.sessions = {}
        self.tamper_events = {}
        self.published = []  # (lot_id, payload) log of open commands

    # Users
    def get_user(self, user_id):
        u = self.users.get(user_id)
        return dict(u) if u else None

    def create_user(self, user):
        with self._lock:
            if user["id"] in self.users:
                return False
            self.users[user["id"]] = dict(user)
            return True

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
            self.sessions[session_id] = {"id": session_id, "lot_id": lot_id, "user_id": user_id, "start_time": now_iso()}
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
            self.sessions[lot["session_id"]]["end_time"] = now_iso()
            return True

    # Commands
    def publish_open(self, lot_id):
        request_id = str(uuid.uuid4())
        self.published.append((lot_id, {"action": "open", "requestId": request_id}))
        return request_id

    # Read-only lists
    def get_session(self, session_id):
        s = self.sessions.get(session_id)
        return dict(s) if s else None

    def list_open_sessions(self):
        return [dict(s) for s in self.sessions.values() if "end_time" not in s]

    def list_tamper_events(self):
        return sorted((dict(e) for e in self.tamper_events.values()), key=lambda e: e["detected_time"], reverse=True)

    # Fake-only: what the ESP32 + handle_event / check_overstay would do
    def simulate_event(self, space_id, lot_id, event_type):
        with self._lock:
            lot = self.lots[(space_id, lot_id)]
            if event_type == "bike_arrived":
                lot["bike_present"] = True
            elif event_type == "bike_left":
                lot["bike_present"] = False
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
                if s and s["start_time"] < cutoff and "notified_overstay" not in s:
                    s["notified_overstay"] = now_iso()
                    flagged += 1
        return flagged
