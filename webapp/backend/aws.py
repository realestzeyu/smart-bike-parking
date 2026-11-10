"""Real backend (BACKEND=aws): DynamoDB + IoT Core with boto3.

Writes follow docs/agreed-names-and-formats.md section 3 (transactions + conditional writes).
"""

import json
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

import config

from .base import Backend, now_iso

_ser = TypeSerializer()


def _plain(item):
    """DynamoDB Decimals -> int/float so templates and JSON work."""
    if item is None:
        return None
    out = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            v = int(v) if v == v.to_integral_value() else float(v)
        out[k] = v
    return out


def _av(d):
    return {k: _ser.serialize(v) for k, v in d.items()}


class AwsBackend(Backend):
    def __init__(self):
        session = boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)
        self.db = session.resource("dynamodb")
        self.client = session.client("dynamodb")
        self.iot = session.client("iot-data", endpoint_url="https://" + config.IOT_DATA_ENDPOINT)
        p = config.TABLE_PREFIX
        self.t_spaces, self.t_lots, self.t_users = p + "spaces", p + "lots", p + "users"
        self.t_sessions, self.t_tamper = p + "sessions", p + "tamper-events"

    def _table(self, name):
        return self.db.Table(name)

    def _scan(self, name, **kw):
        table, items, start = self._table(name), [], None
        while True:
            if start:
                kw["ExclusiveStartKey"] = start
            resp = table.scan(**kw)
            items += resp.get("Items", [])
            start = resp.get("LastEvaluatedKey")
            if not start:
                return [_plain(i) for i in items]

    # Users
    def get_user(self, user_id):
        return _plain(self._table(self.t_users).get_item(Key={"id": user_id}).get("Item"))

    def create_user(self, user):
        try:
            self._table(self.t_users).put_item(Item=user, ConditionExpression="attribute_not_exists(id)")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def set_telegram_chat_id(self, user_id, chat_id):
        self._table(self.t_users).update_item(
            Key={"id": user_id},
            UpdateExpression="SET telegram_chat_id = :c",
            ExpressionAttributeValues={":c": chat_id},
        )

    # Spaces and lots
    def list_spaces(self):
        return self._scan(self.t_spaces)

    def get_space(self, space_id):
        return _plain(self._table(self.t_spaces).get_item(Key={"id": space_id}).get("Item"))

    def list_lots(self, space_id):
        resp = self._table(self.t_lots).query(KeyConditionExpression=Key("space_id").eq(space_id), ConsistentRead=True)
        return [_plain(i) for i in resp.get("Items", [])]

    def get_lot(self, space_id, lot_id):
        resp = self._table(self.t_lots).get_item(Key={"space_id": space_id, "id": lot_id}, ConsistentRead=True)
        return _plain(resp.get("Item"))

    # Lot status changes
    def claim_lot(self, space_id, lot_id, user_id):
        session_id = str(uuid.uuid4())
        try:
            self.client.transact_write_items(TransactItems=[
                {"Update": {
                    "TableName": self.t_lots,
                    "Key": _av({"space_id": space_id, "id": lot_id}),
                    "UpdateExpression": "SET #s = :taken, user_id = :u, session_id = :sid",
                    "ConditionExpression": "#s = :free",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": _av({":taken": "taken", ":free": "free", ":u": user_id, ":sid": session_id}),
                }},
                {"Put": {
                    "TableName": self.t_sessions,
                    "Item": _av({"id": session_id, "lot_id": lot_id, "user_id": user_id, "start_time": now_iso()}),
                }},
            ])
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                return False
            raise

    def mark_releasing(self, space_id, lot_id, user_id, is_officer=False):
        lot = self.get_lot(space_id, lot_id)
        if not lot or lot.get("status") != "taken" or (not is_officer and lot.get("user_id") != user_id):
            return False
        condition, values = "#s = :taken AND session_id = :sid", {":taken": "taken", ":sid": lot["session_id"], ":rel": "releasing"}
        if not is_officer:
            condition += " AND user_id = :u"
            values[":u"] = user_id
        try:
            self.client.transact_write_items(TransactItems=[
                {"Update": {
                    "TableName": self.t_lots,
                    "Key": _av({"space_id": space_id, "id": lot_id}),
                    "UpdateExpression": "SET #s = :rel",
                    "ConditionExpression": condition,
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": _av(values),
                }},
                {"Update": {
                    "TableName": self.t_sessions,
                    "Key": _av({"id": lot["session_id"]}),
                    "UpdateExpression": "SET end_time = :e",
                    "ExpressionAttributeValues": _av({":e": now_iso()}),
                }},
            ])
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException":
                return False
            raise

    # Commands
    def publish_open(self, lot_id):
        space, lot = lot_id.split("#")
        request_id = str(uuid.uuid4())
        payload = {"action": "open", "requestId": request_id, "expires": int(time.time()) + 30}
        self.iot.publish(topic=f"{space}/{lot}/cmd", qos=1, payload=json.dumps(payload))
        return request_id

    # Read-only lists
    def get_session(self, session_id):
        return _plain(self._table(self.t_sessions).get_item(Key={"id": session_id}).get("Item"))

    def list_open_sessions(self):
        return self._scan(self.t_sessions, FilterExpression=Attr("end_time").not_exists())

    def list_tamper_events(self):
        return sorted(self._scan(self.t_tamper), key=lambda e: e["detected_time"], reverse=True)
