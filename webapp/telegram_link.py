"""Connect Telegram: find the chat that sent "/start <code>" to our bot (getUpdates, no webhook)."""

import json
import urllib.request

import config


def find_chat_id(code):
    """Return the chat id that sent '/start <code>', or None if not found (or Telegram not set up)."""
    if not config.TELEGRAM_BOT_TOKEN or not code:
        return None
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates?timeout=0&allowed_updates=%5B%22message%22%5D"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            updates = json.load(resp).get("result", [])
    except OSError:
        return None
    for update in reversed(updates):  # newest first
        message = update.get("message") or {}
        if message.get("text", "").strip() == f"/start {code}":
            return message["chat"]["id"]
    return None
