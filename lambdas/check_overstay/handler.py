"""check_overstay: runs on a schedule (EventBridge Scheduler). Two scheduled checks:

1. Overstay: open sessions older than OVERSTAY_LIMIT_MINUTES are flagged once as suspected abandoned
   (overstay_notified_at) and the owner is Telegrammed. Sessions whose bike has already gone
   (bike_left while taken = suspected theft, already alerted) are skipped.
2. Lock reminders: one Telegram per lot (lock_reminded_at) when the lock is still open for longer
   than LOCK_REMINDER_MINUTES, either
   - awaiting_lock: the owner took the bike but left the lock open, or
   - taken: the owner claimed the lot but never pushed the metal piece in (bike not secured).

Diagrams: docs/cloud-logic.md section 3.
"""

import os
from datetime import timedelta

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

import sbp_common as c


def lambda_handler(event, context):
    now = c.now_utc()
    summary = {**check_overstays(now), **check_lock_reminders(now)}
    c.log_json(fn="check_overstay", action="run", run_at=c.iso(now), **summary)
    return summary


# ---------- 1. overstay ----------

def check_overstays(now) -> dict:
    limit_minutes = int(os.environ.get("OVERSTAY_LIMIT_MINUTES", "2"))
    cutoff = c.iso(now - timedelta(minutes=limit_minutes))

    flagged = alerted = skipped = 0
    for session in open_sessions_older_than(cutoff):
        lot_id = session["lot_id"]
        space_id = lot_id.split("#")[0]

        if bike_is_gone(space_id, lot_id):
            skipped += 1  # suspected theft: already alerted by handle_event; "please collect" would be wrong
            c.log_json(fn="check_overstay", action="overstay_skipped", reason="bike gone",
                       session_id=session["id"], lot_id=lot_id)
            continue

        if not flag_once(session["id"], now):
            continue  # already flagged (e.g. by an overlapping run)
        flagged += 1

        parked_for = c.human_duration(now - c.parse_iso(session["start_time"]))
        notified = c.alert_owner(
            session.get("user_id"), space_id, lot_id,
            lambda label: (
                f"🕒 Your bike at {label} has been parked for {parked_for}. "
                "Please collect it soon, or it may be treated as abandoned."
            ),
        )
        alerted += notified
        c.log_json(
            fn="check_overstay", action="flagged", session_id=session["id"], lot_id=lot_id,
            user_id=session.get("user_id"), parked_for=parked_for, notified=notified,
        )

    return {"limit_minutes": limit_minutes, "flagged": flagged, "alerted": alerted,
            "skipped_bike_gone": skipped}


def open_sessions_older_than(cutoff: str):
    """Open sessions (sparse open-sessions index) that started before cutoff and aren't flagged yet."""
    kwargs = {
        "IndexName": "open-sessions",
        "KeyConditionExpression": Key("is_open").eq("Y") & Key("start_time").lt(cutoff),
        "FilterExpression": Attr("overstay_notified_at").not_exists(),
    }
    while True:
        page = c.table("sessions").query(**kwargs)
        yield from page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def bike_is_gone(space_id: str, lot_id: str) -> bool:
    lot = c.table("lots").get_item(Key={"space_id": space_id, "id": lot_id}).get("Item") or {}
    return lot.get("bike_present") is False


def flag_once(session_id: str, now) -> bool:
    """Set overstay_notified_at only if it isn't set and the session is still open. True if we set it."""
    try:
        c.table("sessions").update_item(
            Key={"id": session_id},
            UpdateExpression="SET overstay_notified_at = :now",
            ConditionExpression=Attr("overstay_notified_at").not_exists() & Attr("is_open").exists(),
            ExpressionAttributeValues={":now": c.iso(now)},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


# ---------- 2. lock reminders ----------

def check_lock_reminders(now) -> dict:
    grace_minutes = int(os.environ.get("LOCK_REMINDER_MINUTES", "1"))
    cutoff = now - timedelta(minutes=grace_minutes)

    reminded = 0
    for lot in lots_with_open_lock():
        status = lot.get("status")
        if status == "awaiting_lock":
            since = lot.get("awaiting_lock_since")
            message = (
                "🔓 Reminder: the lock at {label} is still open. Please go back and push the "
                "metal piece in. You can't use another lot until it's closed."
            )
        elif status == "taken" and lot.get("bike_present") is not False:
            since = claim_time(lot.get("session_id"))
            message = (
                "🔓 Your bike at {label} isn't locked yet. Please wrap the cable around it and "
                "push the metal piece into the lock."
            )
        else:
            continue
        if not since or c.parse_iso(since) > cutoff:
            continue  # still within the grace period (or no time to judge by)
        if not remind_once(lot, status, now):
            continue  # already reminded, or the lock / status changed meanwhile

        notified = c.alert_owner(lot.get("user_id"), lot["space_id"], lot["id"],
                                 lambda label, m=message: m.format(label=label))
        reminded += 1
        c.log_json(fn="check_overstay", action="lock_reminder", lot_id=lot["id"], status=status,
                   user_id=lot.get("user_id"), notified=notified)

    return {"lock_reminder_minutes": grace_minutes, "lock_reminders": reminded}


def lots_with_open_lock():
    """Lots that are owned (taken / awaiting_lock), lock reported open, not reminded yet. Small table: Scan."""
    kwargs = {
        "FilterExpression": Attr("lock_closed").eq(False)
        & Attr("lock_reminded_at").not_exists()
        & Attr("status").is_in(["taken", "awaiting_lock"]),
    }
    while True:
        page = c.table("lots").scan(**kwargs)
        yield from page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def claim_time(session_id):
    if not session_id:
        return None
    session = c.table("sessions").get_item(Key={"id": session_id}).get("Item") or {}
    return session.get("start_time")


def remind_once(lot: dict, status: str, now) -> bool:
    """Set lock_reminded_at only if the lot is unchanged (same status, lock still open, not reminded)."""
    try:
        c.table("lots").update_item(
            Key={"space_id": lot["space_id"], "id": lot["id"]},
            UpdateExpression="SET lock_reminded_at = :now",
            ConditionExpression=Attr("status").eq(status)
            & Attr("lock_closed").eq(False)
            & Attr("lock_reminded_at").not_exists(),
            ExpressionAttributeValues={":now": c.iso(now)},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
