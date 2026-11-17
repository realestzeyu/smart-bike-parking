"""handle_event: runs for every ESP32 message on '<space>/<lot>/event' (IoT Rule).

Event from the rule: {"type": "bike_arrived" | "bike_left" | "tamper" | "lock_closed" | "lock_opened",
                      "space": "space1", "lot": "lot1", "ts"?: epoch ms}
Logic and diagrams: docs/cloud-logic.md. Field names: docs/agreed-names-and-formats.md.

Lock state comes from the solenoid lock's feedback wire (lock_closed / lock_opened). A lot that has
never reported it (no lock_closed field) is treated as closed, so lots without the wire behave as before.
"""

import os
import uuid
from datetime import timedelta

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

import sbp_common as c

VALID_TYPES = {"bike_arrived", "bike_left", "tamper", "lock_closed", "lock_opened"}

# Lock counts as closed unless the lock has reported it open.
LOCK_IS_CLOSED = Attr("lock_closed").not_exists() | Attr("lock_closed").eq(True)
LOCK_IS_OPEN = Attr("lock_closed").eq(False)
MAX_TRIES = 3  # re-reads after a conditional write fails (the web app changed the lot meanwhile)


class LotChanged(Exception):
    """The lot's status changed between our read and our write."""


def lambda_handler(event, context):
    received = c.now_utc()
    received_ms = c.epoch_ms()
    event = event or {}
    event_type, space, lot = event.get("type"), event.get("space"), event.get("lot")

    log = {"fn": "handle_event", "type": event_type, "received_at": c.iso(received)}
    device_ts = event.get("ts")
    if isinstance(device_ts, (int, float)):
        log["device_ts"] = device_ts
        log["latency_ms"] = received_ms - int(device_ts)

    if event_type not in VALID_TYPES or not space or not lot:
        c.log_json(**log, action="ignored", reason="bad payload", event=event)
        return {"action": "ignored"}

    space_id, lot_id = space, f"{space}#{lot}"
    log["lot_id"] = lot_id

    for attempt in range(1, MAX_TRIES + 1):
        item = read_lot(space_id, lot_id)
        if item is None:
            c.log_json(**log, action="ignored", reason="unknown lot")
            return {"action": "ignored"}
        status = item.get("status", "free")
        try:
            result = HANDLERS[event_type](item, status, received)
        except LotChanged:
            c.log_json(**log, action="retry", status=status, attempt=attempt)
            continue
        c.log_json(**log, status=status, **result)
        return result

    c.log_json(**log, action="gave_up", reason="lot kept changing")
    return {"action": "gave_up"}


def read_lot(space_id: str, lot_id: str):
    return c.table("lots").get_item(
        Key={"space_id": space_id, "id": lot_id}, ConsistentRead=True
    ).get("Item")


def lock_is_closed(item: dict) -> bool:
    return item.get("lock_closed", True) is not False


def update_lot(item: dict, expected_status, update: str, values: dict, extra_condition=None) -> None:
    """Update the lot only if it still exists (and still has expected_status / extra_condition, when given)."""
    condition = Attr("id").exists()
    if expected_status is not None:
        condition = condition & Attr("status").eq(expected_status)
    if extra_condition is not None:
        condition = condition & extra_condition
    kwargs = {
        "Key": {"space_id": item["space_id"], "id": item["id"]},
        "UpdateExpression": update,
        "ConditionExpression": condition,
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    if "#s" in update:
        kwargs["ExpressionAttributeNames"] = {"#s": "status"}  # "status" is a DynamoDB reserved word
    try:
        c.table("lots").update_item(**kwargs)
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise LotChanged() from error
        raise  # real DynamoDB error: let Lambda retry


def put_tamper_event(item: dict, when, session_id, notified: bool) -> str:
    event_id = str(uuid.uuid4())
    record = {
        "id": event_id,
        "lot_id": item["id"],
        "detected_time": c.iso(when),
        "notified": notified,
    }
    if session_id:
        record["session_id"] = session_id
    c.table("tamper-events").put_item(Item=record)
    return event_id


def set_pending_lock(user_id, lot_id: str) -> None:
    """Tie the account to the lot: the web app blocks new claims while this is set."""
    if not user_id:
        return
    try:
        c.table("users").update_item(
            Key={"id": user_id},
            UpdateExpression="SET pending_lock_lot_id = :lot",
            ConditionExpression=Attr("id").exists(),  # never create a user record
            ExpressionAttributeValues={":lot": lot_id},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        c.log_json(fn="handle_event", action="pending_lock_skipped", reason="unknown user", user_id=user_id)


def clear_pending_lock(user_id, lot_id: str) -> None:
    """Release the account, but only if it's still tied to this lot."""
    if not user_id:
        return
    try:
        c.table("users").update_item(
            Key={"id": user_id},
            UpdateExpression="REMOVE pending_lock_lot_id",
            ConditionExpression=Attr("pending_lock_lot_id").eq(lot_id),
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


# ---------- one function per event type ----------

def on_bike_arrived(item, status, when):
    # Doesn't depend on status. Keep the first arrival time if one is already set.
    update_lot(
        item,
        None,
        "SET bike_present = :t, bike_present_since = if_not_exists(bike_present_since, :now)",
        {":t": True, ":now": c.iso(when)},
    )
    return {"action": "bike_present"}


def on_bike_left(item, status, when):
    if status == "releasing" and lock_is_closed(item):
        # Unlock confirmed and the lock is closed again: the owner is done.
        update_lot(
            item,
            "releasing",
            "SET #s = :free, bike_present = :f "
            "REMOVE bike_present_since, user_id, session_id, lock_reminded_at",
            {":free": "free", ":f": False},
            extra_condition=LOCK_IS_CLOSED,
        )
        return {"action": "freed"}

    if status == "releasing":
        # Owner took the bike but left the lock open: tie their account to the lot until it closes.
        update_lot(
            item,
            "releasing",
            "SET #s = :await, bike_present = :f, awaiting_lock_since = :now "
            "REMOVE bike_present_since, lock_reminded_at",  # fresh reminder for this new situation
            {":await": "awaiting_lock", ":f": False, ":now": c.iso(when)},
            extra_condition=LOCK_IS_OPEN,
        )
        set_pending_lock(item.get("user_id"), item["id"])
        # No Telegram here: many cyclists push the metal piece back in a few seconds after wheeling
        # the bike out. check_overstay reminds them only if it's still open after LOCK_REMINDER_MINUTES.
        return {"action": "awaiting_lock"}

    if status == "awaiting_lock":
        # Already waiting for the lock; nothing else to change.
        update_lot(item, "awaiting_lock", "SET bike_present = :f REMOVE bike_present_since", {":f": False})
        return {"action": "bike_absent"}

    if status == "taken":
        # Bike gone without an unlock: suspected theft.
        update_lot(item, "taken", "SET bike_present = :f REMOVE bike_present_since", {":f": False})
        notified = c.alert_owner(
            item.get("user_id"), item["space_id"], item["id"],
            lambda label: (
                f"🚨 Your bike at {label} left the rack without an unlock ({c.sgt(when)} SGT). "
                "If this wasn't you, please contact station staff."
            ),
        )
        put_tamper_event(item, when, item.get("session_id"), notified)
        return {"action": "suspected_theft", "notified": notified}

    # free
    update_lot(item, "free", "SET bike_present = :f REMOVE bike_present_since", {":f": False})
    return {"action": "bike_absent"}


def start_tamper_episode(item, when) -> bool:
    """Per-lot cooldown: True only for the first tamper in TAMPER_COOLDOWN_SECONDS (a new episode).

    Atomic conditional write on the lot, so parallel Lambda copies handling a burst of tamper
    events can't both win: exactly one records the episode, the rest are repeats.
    """
    cooldown = int(os.environ.get("TAMPER_COOLDOWN_SECONDS", "60"))
    cutoff = c.iso(when - timedelta(seconds=cooldown))
    try:
        c.table("lots").update_item(
            Key={"space_id": item["space_id"], "id": item["id"]},
            UpdateExpression="SET last_tamper_at = :now",
            ConditionExpression=Attr("id").exists()
            & (Attr("last_tamper_at").not_exists() | Attr("last_tamper_at").lte(cutoff)),
            ExpressionAttributeValues={":now": c.iso(when)},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def on_tamper(item, status, when):
    if not start_tamper_episode(item, when):
        # Repeat within the cooldown: no tamper row, no Telegram (just this log line).
        return {"action": "tamper_repeat_dropped"}

    session_id = item.get("session_id") if status in ("taken", "releasing") else None

    if status == "taken":
        notified = c.alert_owner(
            item.get("user_id"), item["space_id"], item["id"],
            lambda label: (
                f"⚠️ Someone may be tampering with your bike at {label} ({c.sgt(when)} SGT). "
                "Please check on it."
            ),
        )
        put_tamper_event(item, when, session_id, notified)
        return {"action": "tamper_alert", "notified": notified}

    # releasing: the owner is unlocking (expected vibration). free / awaiting_lock: no bike of theirs to protect.
    put_tamper_event(item, when, session_id, False)
    return {"action": "tamper_logged", "notified": False}


def on_lock_closed(item, status, when):
    if status == "awaiting_lock":
        # The cyclist came back and closed it: free the lot and release their account.
        update_lot(
            item,
            "awaiting_lock",
            "SET #s = :free, lock_closed = :t "
            "REMOVE user_id, session_id, awaiting_lock_since, lock_reminded_at",
            {":free": "free", ":t": True},
        )
        clear_pending_lock(item.get("user_id"), item["id"])
        notified = False
        if item.get("lock_reminded_at"):
            # Only confirm if we reminded them; a quick close needs no messages at all.
            notified = c.alert_owner(
                item.get("user_id"), item["space_id"], item["id"],
                lambda label: f"✅ Lock at {label} closed. Thanks! You can use any lot again.",
            )
        return {"action": "lock_closed_freed", "notified": notified}

    # Any other status: just record it (e.g. after a claim it confirms the bike is locked).
    update_lot(item, None, "SET lock_closed = :t REMOVE lock_reminded_at", {":t": True})
    return {"action": "lock_closed"}


def on_lock_opened(item, status, when):
    # Expected after an open command (claim or unlock); the cloud only records it.
    update_lot(item, None, "SET lock_closed = :f", {":f": False})
    return {"action": "lock_opened"}


HANDLERS = {
    "bike_arrived": on_bike_arrived,
    "bike_left": on_bike_left,
    "tamper": on_tamper,
    "lock_closed": on_lock_closed,
    "lock_opened": on_lock_opened,
}
