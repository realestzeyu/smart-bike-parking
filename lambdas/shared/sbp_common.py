"""Shared helpers for both Lambdas: time, JSON logging, DynamoDB tables, Telegram alerts.

Terraform zips this file next to each Lambda's handler.py (see infra/lambdas.tf).
Standard library + boto3 only (boto3 is built into the Lambda runtime).
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

SGT = timezone(timedelta(hours=8))  # Singapore has no daylight saving
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_dynamodb = None


# ---------- time ----------

def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    """UTC ISO 8601 string, e.g. 2026-11-06T07:15:00Z (the format stored in DynamoDB)."""
    return dt.astimezone(timezone.utc).strftime(ISO_FORMAT)


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, ISO_FORMAT).replace(tzinfo=timezone.utc)


def sgt(dt: datetime) -> str:
    """Time shown to users, e.g. '12 Nov 14:05'."""
    return dt.astimezone(SGT).strftime("%d %b %H:%M")


def human_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} day{'s' if days != 1 else ''} {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


# ---------- logging ----------

def log_json(**fields) -> None:
    """One JSON line per handled event (CloudWatch Logs Insights reads these for measured results)."""
    print(json.dumps(fields, default=str))


# ---------- DynamoDB ----------

def table(name: str):
    """sbp-<name> table, e.g. table('lots') -> sbp-lots."""
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(os.environ.get("TABLE_PREFIX", "sbp-") + name)


def reset_clients() -> None:
    """Tests only: forget the cached DynamoDB resource."""
    global _dynamodb
    _dynamodb = None


def lot_label(space_id: str, lot_id: str) -> str:
    """'Bedok MRT Exit A, lot 1' (falls back to the space ID if the space has no address)."""
    space = table("spaces").get_item(Key={"id": space_id}).get("Item") or {}
    lot_number = lot_id.split("#lot")[-1]
    return f"{space.get('address', space_id)}, lot {lot_number}"


# ---------- Telegram ----------

def send_telegram(chat_id, text: str) -> bool:
    """Send one message. Returns True if Telegram accepted it. Never raises."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return False
    data = urllib.parse.urlencode({"chat_id": int(chat_id), "text": text}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(json.load(response).get("ok"))
    except Exception as error:  # network error, HTTP 4xx/5xx, bad JSON: alert lost, data still saved
        # Log the error type and message only (never the URL: it contains the bot token).
        log_json(fn="telegram", action="send_failed", error=f"{type(error).__name__}: {error}")
        return False


def alert_owner(user_id: str, space_id: str, lot_id: str, make_text) -> bool:
    """Telegram the lot's owner. make_text(label) builds the message. Returns True if sent.

    Skips (False) when there's no bot token, no owner, or the owner hasn't connected Telegram.
    """
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not user_id:
        return False
    user = table("users").get_item(Key={"id": user_id}).get("Item") or {}
    chat_id = user.get("telegram_chat_id")
    if not chat_id:
        return False
    return send_telegram(chat_id, make_text(lot_label(space_id, lot_id)))


def epoch_ms() -> int:
    return int(time.time() * 1000)
