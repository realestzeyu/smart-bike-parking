"""Settings from webapp/.env (see .env.example)."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BACKEND = os.getenv("BACKEND", "fake")  # fake | aws

# Signs the login cookie. In fake mode a random one is fine (logins reset on restart).
SESSION_SECRET = os.getenv("SESSION_SECRET") or ""
if not SESSION_SECRET:
    if BACKEND == "aws":
        raise SystemExit("SESSION_SECRET must be set in webapp/.env when BACKEND=aws")
    SESSION_SECRET = secrets.token_hex(32)

AWS_PROFILE = os.getenv("AWS_PROFILE") or None
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
IOT_DATA_ENDPOINT = os.getenv("IOT_DATA_ENDPOINT", "")
TABLE_PREFIX = os.getenv("TABLE_PREFIX", "sbp-")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")
