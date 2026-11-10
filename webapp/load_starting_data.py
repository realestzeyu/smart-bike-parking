"""Load the starting rows (starting_data.py) into DynamoDB.

Only creates rows that don't exist yet; never overwrites an existing row, so it is safe to re-run.
Uses AWS_PROFILE, AWS_REGION, TABLE_PREFIX and COGNITO_USER_POOL_ID from webapp/.env.
The officer account is a Cognito user (holds the password) plus an sbp-users row (role = officer).

Run:  cd webapp && python load_starting_data.py
"""

import getpass
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from starting_data import DEMO_USER, LOTS, OFFICER, SPACES, simulated_rows

load_dotenv()
session = boto3.Session(
    profile_name=os.getenv("AWS_PROFILE") or None,
    region_name=os.getenv("AWS_REGION", "ap-southeast-1"),
)
db = session.resource("dynamodb")
cognito = session.client("cognito-idp")
prefix = os.getenv("TABLE_PREFIX", "sbp-")
pool_id = os.getenv("COGNITO_USER_POOL_ID", "")


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

    # Simulated stations (no hardware): lots, their parked sessions, and the demo owner's profile.
    sim_spaces, sim_lots, sim_sessions = simulated_rows()
    for space in sim_spaces:
        create("spaces", space, "id")
    for lot in sim_lots:
        create("lots", lot, "space_id")
    for session in sim_sessions:
        create("sessions", session, "id")
    create("users", DEMO_USER, "id")

    create_officer()


def create_officer():
    """Cognito user + sbp-users row, each only if missing."""
    officer_id = OFFICER["id"]
    users = db.Table(prefix + "users")
    row = users.get_item(Key={"id": officer_id}).get("Item")
    try:
        cognito.admin_get_user(UserPoolId=pool_id, Username=officer_id)
        print(f"exists   Cognito user: {officer_id} (skipped)")
        email = (row or {}).get("email", "")
    except ClientError as e:
        if e.response["Error"]["Code"] != "UserNotFoundException":
            raise
        email = input(f"Email for officer account '{officer_id}': ").strip()
        password = getpass.getpass("Password (at least 8 characters): ")
        cognito.admin_create_user(
            UserPoolId=pool_id, Username=officer_id, MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
        )
        cognito.admin_set_user_password(UserPoolId=pool_id, Username=officer_id, Password=password, Permanent=True)
        print(f"created  Cognito user: {officer_id}")
    if row:
        print(f"exists   {prefix}users: {officer_id} (skipped)")
    else:
        create("users", {**OFFICER, "email": email}, "id")


if __name__ == "__main__":
    main()
