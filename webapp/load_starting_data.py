"""Load the starting rows (starting_data.py) into DynamoDB.

Only creates rows that don't exist yet; never overwrites an existing row, so it is safe to re-run.
Uses AWS_PROFILE, AWS_REGION and TABLE_PREFIX from webapp/.env.

Run:  cd webapp && python load_starting_data.py
"""

import getpass
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from starting_data import LOTS, OFFICER, SPACES

load_dotenv()
session = boto3.Session(
    profile_name=os.getenv("AWS_PROFILE") or None,
    region_name=os.getenv("AWS_REGION", "ap-southeast-1"),
)
db = session.resource("dynamodb")
prefix = os.getenv("TABLE_PREFIX", "sbp-")


def to_dynamo(row):
    # DynamoDB needs Decimal, not float, for numbers.
    return {k: Decimal(str(v)) if isinstance(v, float) else v for k, v in row.items()}


def create(table_name, row, key_field):
    """Put the row only if no row with the same key exists. Returns True if created."""
    try:
        db.Table(prefix + table_name).put_item(
            Item=to_dynamo(row),
            ConditionExpression="attribute_not_exists(#k)",
            ExpressionAttributeNames={"#k": key_field},
        )
        print(f"created  {prefix}{table_name}: {row['id']}")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"exists   {prefix}{table_name}: {row['id']} (skipped)")
            return False
        raise


def main():
    for space in SPACES:
        create("spaces", space, "id")
    for lot in LOTS:
        create("lots", lot, "space_id")

    users = db.Table(prefix + "users")
    if "Item" in users.get_item(Key={"id": OFFICER["id"]}):
        print(f"exists   {prefix}users: {OFFICER['id']} (skipped)")
    else:
        password = getpass.getpass(f"Password for officer account '{OFFICER['id']}': ")
        create("users", {**OFFICER, "password": password}, "id")


if __name__ == "__main__":
    main()
