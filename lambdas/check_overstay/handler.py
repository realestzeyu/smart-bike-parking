"""check_overstay: runs on a schedule (EventBridge Scheduler).

Finds open sessions older than OVERSTAY_LIMIT_MINUTES, flags each once as suspected abandoned
(overstay_notified_at), and Telegrams the owner. Diagram: docs/cloud-logic.md section 3.
"""

import os
from datetime import timedelta

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

import sbp_common as c


def lambda_handler(event, context):
    now = c.now_utc()
    limit_minutes = int(os.environ.get("OVERSTAY_LIMIT_MINUTES", "2"))
    cutoff = c.iso(now - timedelta(minutes=limit_minutes))

    flagged = alerted = 0
    for session in open_sessions_older_than(cutoff):
        if not flag_once(session["id"], now):
            continue  # already flagged (e.g. by an overlapping run)
        flagged += 1

        lot_id = session["lot_id"]
        space_id = lot_id.split("#")[0]
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

    summary = {"limit_minutes": limit_minutes, "flagged": flagged, "alerted": alerted}
    c.log_json(fn="check_overstay", action="run", run_at=c.iso(now), **summary)
    return summary


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
