"""check_overstay: docs/cloud-logic.md diagram 3 (overstay) and the lock reminders (F1, F2, F4)."""

from datetime import timedelta

import sbp_common

LOT_KEY = {"space_id": "space1", "id": "space1#lot1"}


def ago(minutes):
    return sbp_common.iso(sbp_common.now_utc() - timedelta(minutes=minutes))


def put_session(db, session_id, minutes_ago, user="alice", is_open=True, **extra):
    item = {"id": session_id, "lot_id": "space1#lot1", "user_id": user, "start_time": ago(minutes_ago), **extra}
    if is_open:
        item["is_open"] = "Y"
    else:
        item["end_time"] = ago(0)
    db.Table("sbp-sessions").put_item(Item=item)


def put_lot(db, **fields):
    db.Table("sbp-lots").put_item(Item={**LOT_KEY, "status": "free", "bike_present": False, **fields})


def get_session(db, session_id):
    return db.Table("sbp-sessions").get_item(Key={"id": session_id})["Item"]


def get_lot(db):
    return db.Table("sbp-lots").get_item(Key=LOT_KEY)["Item"]


def run(check_overstay):
    return check_overstay.lambda_handler({}, None)


# ---------- overstay ----------

def test_old_open_session_is_flagged_and_owner_alerted(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    result = run(check_overstay)
    assert (result["flagged"], result["alerted"]) == (1, 1)
    assert get_session(db, "old")["overstay_notified_at"].endswith("Z")
    [(chat_id, text)] = telegram.sent
    assert chat_id == 12345 and "30 min" in text and "Bedok MRT Exit A, lot 1" in text


def test_recent_session_is_not_flagged(db, telegram, check_overstay):
    put_session(db, "new", minutes_ago=1)
    assert run(check_overstay)["flagged"] == 0
    assert "overstay_notified_at" not in get_session(db, "new")


def test_closed_session_is_ignored(db, telegram, check_overstay):
    put_session(db, "closed", minutes_ago=60, is_open=False)
    assert run(check_overstay)["flagged"] == 0


def test_alerts_only_once(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    run(check_overstay)
    assert run(check_overstay)["flagged"] == 0
    assert len(telegram.sent) == 1


def test_flagged_even_without_telegram(db, telegram, check_overstay):
    put_session(db, "bobs", minutes_ago=30, user="bob")
    result = run(check_overstay)
    assert (result["flagged"], result["alerted"]) == (1, 0)
    assert "overstay_notified_at" in get_session(db, "bobs")
    assert telegram.sent == []


def test_overlapping_run_cannot_double_flag(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    assert check_overstay.flag_once("old", sbp_common.now_utc()) is True
    assert check_overstay.flag_once("old", sbp_common.now_utc()) is False


def test_days_are_shown_for_long_overstays(db, telegram, check_overstay):
    put_session(db, "ancient", minutes_ago=3 * 24 * 60 + 90)
    run(check_overstay)
    assert "3 days 1 h" in telegram.sent[0][1]


def test_f2_no_overstay_message_after_suspected_theft(db, telegram, check_overstay):
    """Bike left while taken (theft alert already sent): don't tell the owner to 'collect' it."""
    put_lot(db, status="taken", bike_present=False, user_id="alice", session_id="s1", lock_closed=True)
    put_session(db, "s1", minutes_ago=30)
    result = run(check_overstay)
    assert (result["flagged"], result["skipped_bike_gone"]) == (0, 1)
    assert "overstay_notified_at" not in get_session(db, "s1")
    assert telegram.sent == []


# ---------- F1: lock left open after taking the bike ----------

def test_f1_reminder_after_grace_period(db, telegram, check_overstay):
    put_lot(db, status="awaiting_lock", lock_closed=False, user_id="alice", awaiting_lock_since=ago(2))
    assert run(check_overstay)["lock_reminders"] == 1
    assert get_lot(db)["lock_reminded_at"].endswith("Z")
    [(_, text)] = telegram.sent
    assert "still open" in text and "Bedok MRT Exit A, lot 1" in text


def test_f1_no_reminder_within_grace_period(db, telegram, check_overstay):
    put_lot(db, status="awaiting_lock", lock_closed=False, user_id="alice", awaiting_lock_since=ago(0))
    assert run(check_overstay)["lock_reminders"] == 0
    assert telegram.sent == []


def test_f1_reminder_only_once(db, telegram, check_overstay):
    put_lot(db, status="awaiting_lock", lock_closed=False, user_id="alice", awaiting_lock_since=ago(5))
    run(check_overstay)
    assert run(check_overstay)["lock_reminders"] == 0
    assert len(telegram.sent) == 1


# ---------- F4: claimed but never locked ----------

def test_f4_claimed_but_not_locked_gets_one_nudge(db, telegram, check_overstay):
    put_lot(db, status="taken", bike_present=True, lock_closed=False, user_id="alice", session_id="s1")
    put_session(db, "s1", minutes_ago=2)
    assert run(check_overstay)["lock_reminders"] == 1
    [(_, text)] = telegram.sent
    assert "isn't locked yet" in text
    assert run(check_overstay)["lock_reminders"] == 0  # once only


def test_f4_no_nudge_within_grace_period(db, telegram, check_overstay):
    put_lot(db, status="taken", bike_present=True, lock_closed=False, user_id="alice", session_id="s1")
    put_session(db, "s1", minutes_ago=0)
    assert run(check_overstay)["lock_reminders"] == 0


def test_f4_no_nudge_when_locked_or_bike_gone(db, telegram, check_overstay):
    put_lot(db, status="taken", bike_present=True, lock_closed=True, user_id="alice", session_id="s1")
    put_session(db, "s1", minutes_ago=5)
    assert run(check_overstay)["lock_reminders"] == 0
    put_lot(db, status="taken", bike_present=False, lock_closed=False, user_id="alice", session_id="s1")
    assert run(check_overstay)["lock_reminders"] == 0
