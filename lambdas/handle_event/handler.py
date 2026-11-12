"""handle_event: runs for every ESP32 message on '<space>/<lot>/event' (IoT Rule).

Event from the rule: {"type": "bike_arrived" | "bike_left" | "tamper", "space": "space1", "lot": "lot1", "ts"?: epoch ms}
Logic and diagrams: docs/cloud-logic.md. Field names: docs/agreed-names-and-formats.md.
"""

import uuid

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

import sbp_common as c

VALID_TYPES = {"bike_arrived", "bike_left", "tamper"}
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


def update_lot(item: dict, expected_status, update: str, values: dict) -> None:
    """Update the lot only if it still exists (and still has expected_status, when given)."""
    condition = Attr("id").exists()
    if expected_status is not None:
        condition = condition & Attr("status").eq(expected_status)
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
    if status == "releasing":
        # Unlock confirmed: the owner took the bike.
        update_lot(
            item,
            "releasing",
            "SET #s = :free, bike_present = :f REMOVE bike_present_since, user_id, session_id",
            {":free": "free", ":f": False},
        )
        return {"action": "freed"}

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


def on_tamper(item, status, when):
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

    # releasing: the owner is unlocking (expected vibration). free: no owner to alert.
    put_tamper_event(item, when, session_id, False)
    return {"action": "tamper_logged", "notified": False}


HANDLERS = {
    "bike_arrived": on_bike_arrived,
    "bike_left": on_bike_left,
    "tamper": on_tamper,
}
