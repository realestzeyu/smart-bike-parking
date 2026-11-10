"""The backend interface. fake.py and aws.py implement the same methods.

Field names follow docs/agreed-names-and-formats.md. Rows are plain dicts.
"""

from datetime import datetime, timezone


def now_iso():
    """Current UTC time as ISO 8601, seconds, e.g. 2026-11-06T07:15:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_lot_ref(lot_ref):
    """'space1_lot3' (URL/QR) -> ('space1', 'space1#lot3') (DynamoDB keys). None if malformed."""
    space_id, sep, lot = lot_ref.partition("_")
    if not sep or not space_id or not lot:
        return None
    return space_id, f"{space_id}#{lot}"


def lot_ref(lot_id):
    """'space1#lot3' -> 'space1_lot3'."""
    return lot_id.replace("#", "_")


def lot_number(lot_id):
    """'space1#lot3' -> '3'."""
    return lot_id.split("#lot")[-1]


class Backend:
    # Users and login (aws: Cognito holds passwords; sbp-users holds name, email, role, telegram_chat_id)
    def get_user(self, user_id): ...
    def authenticate(self, user_id, password): ...  # returns the sbp-users row, or None if wrong
    def sign_up(self, user_id, name, email, password): ...  # cyclists only; returns an error message or None
    def set_telegram_chat_id(self, user_id, chat_id): ...

    # Spaces and lots
    def list_spaces(self): ...
    def get_space(self, space_id): ...
    def list_lots(self, space_id): ...
    def get_lot(self, space_id, lot_id): ...

    # Lot status changes (agreed-names section 3)
    def claim_lot(self, space_id, lot_id, user_id): ...  # free -> taken + session; False if not free
    def mark_releasing(self, space_id, lot_id, user_id, is_officer=False): ...  # taken -> releasing; False if not allowed

    # Commands to the ESP32
    def publish_open(self, lot_id): ...  # returns requestId

    # Read-only lists (officer console)
    def get_session(self, session_id): ...
    def list_open_sessions(self): ...  # sessions with is_open = "Y"
    def list_tamper_events(self): ...  # newest first
