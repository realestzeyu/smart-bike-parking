"""Demo-day reset: wipe the demo data in DynamoDB and load it fresh (BACKEND=aws only).

Empties sbp-spaces, sbp-lots, sbp-sessions and sbp-tamper-events, then loads starting_data.py again,
so the simulated bikes' parking times start from now. Keeps every login: Cognito users and sbp-users
rows (officer, cyclists, Telegram links) stay; only a leftover pending_lock_lot_id is removed.
Touches nothing else in AWS (IoT, Lambdas, schedule, Cognito, keys).

Run:  bash run.sh --reset      (resets, then starts the web app)
  or  python reset_data.py     (from webapp/, reset only)
"""

import contextlib
import io
import os
import sys

from dotenv import load_dotenv

load_dotenv()
if os.getenv("BACKEND", "fake") != "aws":
    print("Reset skipped: BACKEND is not aws (fake data starts fresh on every start anyway).")
    sys.exit(0)

import load_starting_data as loader  # noqa: E402  (after the BACKEND check: it connects to AWS)
from starting_data import DEMO_USER, LOTS, SPACES, simulated_rows, simulated_tamper  # noqa: E402

# Table -> its key fields (infra/dynamodb.tf). Listed here because the web app key can't DescribeTable.
WIPED = {"spaces": ["id"], "lots": ["space_id", "id"], "sessions": ["id"], "tamper-events": ["id"]}


def wipe(name):
    """Delete every row, one DeleteItem each (the web app key has no BatchWriteItem). Returns the count."""
    table = loader.db.Table(loader.prefix + name)
    keys = WIPED[name]
    names = {f"#k{i}": k for i, k in enumerate(keys)}
    kwargs, count = {"ProjectionExpression": ", ".join(names), "ExpressionAttributeNames": names}, 0
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            table.delete_item(Key={k: item[k] for k in keys})
            count += 1
        if "LastEvaluatedKey" not in page:
            return count
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def untie_users():
    """Remove pending_lock_lot_id ("lock still open" tie) from any account; its lot is about to be reset."""
    users, count = loader.db.Table(loader.prefix + "users"), 0
    for item in users.scan(ProjectionExpression="id, pending_lock_lot_id").get("Items", []):
        if "pending_lock_lot_id" in item:
            users.update_item(Key={"id": item["id"]}, UpdateExpression="REMOVE pending_lock_lot_id")
            count += 1
    return count


def main():
    answer = input(f"Wipe the demo data in AWS ({loader.prefix}* tables) and reload it fresh? Logins are kept. Type yes: ")
    if answer.strip().lower() != "yes":
        print("Cancelled. Nothing was deleted.")
        sys.exit(1)

    for name in WIPED:
        print(f"emptied  {loader.prefix}{name}: {wipe(name)} rows")
    print(f"untied   {untie_users()} account(s) from a lock left open")

    sim_spaces, sim_lots, sim_sessions = simulated_rows()
    sim_tamper = simulated_tamper(sim_lots)
    with contextlib.redirect_stdout(io.StringIO()):  # the loader prints one line per row; keep it short
        for space in SPACES + sim_spaces:
            loader.create("spaces", space, "id")
        for lot in LOTS + sim_lots:
            loader.create("lots", lot, "space_id")
        for session in sim_sessions:
            loader.create("sessions", session, "id")
        for event in sim_tamper:
            loader.create("tamper-events", event, "id")
        loader.create("users", DEMO_USER, "id")
    loader.create_officer()  # normally "exists (skipped)"; asks for email/password only if the officer is missing
    print(f"loaded   {len(SPACES + sim_spaces)} stations, {len(LOTS + sim_lots)} lots, "
          f"{len(sim_sessions)} parked bikes, {len(sim_tamper)} tamper event (times start from now)")


if __name__ == "__main__":
    main()
