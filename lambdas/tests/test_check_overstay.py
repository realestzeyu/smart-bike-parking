"""check_overstay: docs/cloud-logic.md diagram 3."""

from datetime import timedelta

import sbp_common


def ago(minutes):
    return sbp_common.iso(sbp_common.now_utc() - timedelta(minutes=minutes))


def put_session(db, session_id, minutes_ago, user="alice", is_open=True, **extra):
    item = {"id": session_id, "lot_id": "space1#lot1", "user_id": user, "start_time": ago(minutes_ago), **extra}
    if is_open:
        item["is_open"] = "Y"
    else:
        item["end_time"] = ago(0)
    db.Table("sbp-sessions").put_item(Item=item)


def get_session(db, session_id):
    return db.Table("sbp-sessions").get_item(Key={"id": session_id})["Item"]


def test_old_open_session_is_flagged_and_owner_alerted(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    assert check_overstay.lambda_handler({}, None) == {"limit_minutes": 2, "flagged": 1, "alerted": 1}
    assert get_session(db, "old")["overstay_notified_at"].endswith("Z")
    [(chat_id, text)] = telegram.sent
    assert chat_id == 12345 and "30 min" in text and "Bedok MRT Exit A, lot 1" in text


def test_recent_session_is_not_flagged(db, telegram, check_overstay):
    put_session(db, "new", minutes_ago=1)
    assert check_overstay.lambda_handler({}, None)["flagged"] == 0
    assert "overstay_notified_at" not in get_session(db, "new")


def test_closed_session_is_ignored(db, telegram, check_overstay):
    put_session(db, "closed", minutes_ago=60, is_open=False)
    assert check_overstay.lambda_handler({}, None)["flagged"] == 0


def test_alerts_only_once(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    check_overstay.lambda_handler({}, None)
    assert check_overstay.lambda_handler({}, None)["flagged"] == 0
    assert len(telegram.sent) == 1


def test_flagged_even_without_telegram(db, telegram, check_overstay):
    put_session(db, "bobs", minutes_ago=30, user="bob")
    assert check_overstay.lambda_handler({}, None) == {"limit_minutes": 2, "flagged": 1, "alerted": 0}
    assert "overstay_notified_at" in get_session(db, "bobs")
    assert telegram.sent == []


def test_overlapping_run_cannot_double_flag(db, telegram, check_overstay):
    put_session(db, "old", minutes_ago=30)
    assert check_overstay.flag_once("old", sbp_common.now_utc()) is True
    assert check_overstay.flag_once("old", sbp_common.now_utc()) is False


def test_days_are_shown_for_long_overstays(db, telegram, check_overstay):
    put_session(db, "ancient", minutes_ago=3 * 24 * 60 + 90)
    check_overstay.lambda_handler({}, None)
    assert "3 days 1 h" in telegram.sent[0][1]
