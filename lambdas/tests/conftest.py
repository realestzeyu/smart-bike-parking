"""Test setup: fake DynamoDB (moto) with the same tables/keys as infra/dynamodb.tf, and a fake Telegram."""

import importlib.util
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

LAMBDAS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAMBDAS / "shared"))

import sbp_common  # noqa: E402


def load_handler(name: str):
    """Both Lambdas have a handler.py, so load each under its own module name."""
    spec = importlib.util.spec_from_file_location(f"{name}_handler", LAMBDAS / name / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_tables(dynamodb):
    def make(name, keys, attrs, gsis=None):
        kwargs = {
            "TableName": f"sbp-{name}",
            "KeySchema": keys,
            "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in attrs],
            "BillingMode": "PAY_PER_REQUEST",
        }
        if gsis:
            kwargs["GlobalSecondaryIndexes"] = gsis
        dynamodb.create_table(**kwargs)

    def gsi(name, hash_key, range_key):
        return {
            "IndexName": name,
            "KeySchema": [
                {"AttributeName": hash_key, "KeyType": "HASH"},
                {"AttributeName": range_key, "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }

    make("spaces", [{"AttributeName": "id", "KeyType": "HASH"}], ["id"])
    make("lots", [{"AttributeName": "space_id", "KeyType": "HASH"},
                  {"AttributeName": "id", "KeyType": "RANGE"}], ["space_id", "id"])
    make("users", [{"AttributeName": "id", "KeyType": "HASH"}], ["id"])
    make("sessions", [{"AttributeName": "id", "KeyType": "HASH"}],
         ["id", "lot_id", "user_id", "is_open", "start_time"],
         [gsi("by-lot", "lot_id", "start_time"), gsi("by-user", "user_id", "start_time"),
          gsi("open-sessions", "is_open", "start_time")])
    make("tamper-events", [{"AttributeName": "id", "KeyType": "HASH"}], ["id"])


@pytest.fixture
def db(monkeypatch):
    """Fresh fake DynamoDB per test, seeded with space1 (address) and user alice (Telegram linked)."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TABLE_PREFIX", "sbp-")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("OVERSTAY_LIMIT_MINUTES", "2")
    with mock_aws():
        sbp_common.reset_clients()
        dynamodb = boto3.resource("dynamodb")
        create_tables(dynamodb.meta.client)
        dynamodb.Table("sbp-spaces").put_item(Item={"id": "space1", "address": "Bedok MRT Exit A"})
        dynamodb.Table("sbp-users").put_item(
            Item={"id": "alice", "name": "Alice", "email": "a@example.com", "role": "cyclist",
                  "telegram_chat_id": 12345})
        dynamodb.Table("sbp-users").put_item(
            Item={"id": "bob", "name": "Bob", "email": "b@example.com", "role": "cyclist"})  # no Telegram
        yield dynamodb
        sbp_common.reset_clients()


@pytest.fixture
def telegram(monkeypatch):
    """Records messages instead of calling Telegram. Set telegram.ok = False to simulate a failure."""
    class Fake:
        ok = True
        sent = []

    fake = Fake()
    fake.sent = []

    def send(chat_id, text):
        fake.sent.append((int(chat_id), text))
        return fake.ok

    monkeypatch.setattr(sbp_common, "send_telegram", send)
    return fake


@pytest.fixture
def handle_event():
    return load_handler("handle_event")


@pytest.fixture
def check_overstay():
    return load_handler("check_overstay")
