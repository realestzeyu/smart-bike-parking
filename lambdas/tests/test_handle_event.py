"""handle_event: one test per branch of docs/cloud-logic.md diagram 2, plus the unlock race (diagram 7)."""

LOT_KEY = {"space_id": "space1", "id": "space1#lot1"}


def put_lot(db, **fields):
    item = {**LOT_KEY, "status": "free", "bike_present": False, **fields}
    db.Table("sbp-lots").put_item(Item=item)


def get_lot(db):
    return db.Table("sbp-lots").get_item(Key=LOT_KEY)["Item"]


def tamper_events(db):
    return db.Table("sbp-tamper-events").scan()["Items"]


def event(event_type, **extra):
    return {"type": event_type, "space": "space1", "lot": "lot1", **extra}


TAKEN = {"status": "taken", "bike_present": True, "bike_present_since": "2026-11-12T01:00:00Z",
         "user_id": "alice", "session_id": "sess-1"}


# ---------- bad input ----------

def test_bad_payload_is_ignored(db, telegram, handle_event):
    put_lot(db)
    assert handle_event.lambda_handler({"type": "explode", "space": "space1", "lot": "lot1"}, None)["action"] == "ignored"
    assert handle_event.lambda_handler({"type": "tamper"}, None)["action"] == "ignored"
    assert get_lot(db)["bike_present"] is False


def test_unknown_lot_is_ignored_and_not_created(db, telegram, handle_event):
    result = handle_event.lambda_handler({"type": "bike_arrived", "space": "space9", "lot": "lot7"}, None)
    assert result["action"] == "ignored"
    assert "Item" not in db.Table("sbp-lots").get_item(Key={"space_id": "space9", "id": "space9#lot7"})


# ---------- bike_arrived ----------

def test_bike_arrived_sets_present_and_since(db, telegram, handle_event):
    put_lot(db)
    handle_event.lambda_handler(event("bike_arrived"), None)
    lot = get_lot(db)
    assert lot["bike_present"] is True
    assert lot["bike_present_since"].endswith("Z")


def test_bike_arrived_keeps_existing_since(db, telegram, handle_event):
    put_lot(db, bike_present=True, bike_present_since="2026-11-12T01:00:00Z")
    handle_event.lambda_handler(event("bike_arrived"), None)
    assert get_lot(db)["bike_present_since"] == "2026-11-12T01:00:00Z"


# ---------- bike_left ----------

def test_bike_left_while_releasing_frees_the_lot(db, telegram, handle_event):
    put_lot(db, **{**TAKEN, "status": "releasing"})
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "freed"
    lot = get_lot(db)
    assert lot["status"] == "free"
    assert lot["bike_present"] is False
    for gone in ("bike_present_since", "user_id", "session_id"):
        assert gone not in lot
    assert tamper_events(db) == []
    assert telegram.sent == []


def test_bike_left_while_taken_is_suspected_theft(db, telegram, handle_event):
    put_lot(db, **TAKEN)
    result = handle_event.lambda_handler(event("bike_left"), None)
    assert result == {"action": "suspected_theft", "notified": True}
    lot = get_lot(db)
    assert lot["status"] == "taken"  # still owned: officers / owner decide what happens next
    assert lot["bike_present"] is False and "bike_present_since" not in lot
    [record] = tamper_events(db)
    assert record["lot_id"] == "space1#lot1" and record["session_id"] == "sess-1" and record["notified"] is True
    [(chat_id, text)] = telegram.sent
    assert chat_id == 12345 and "without an unlock" in text and "Bedok MRT Exit A, lot 1" in text


def test_bike_left_while_free_just_clears_presence(db, telegram, handle_event):
    put_lot(db, bike_present=True, bike_present_since="2026-11-12T01:00:00Z")
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "bike_absent"
    lot = get_lot(db)
    assert lot["status"] == "free" and lot["bike_present"] is False and "bike_present_since" not in lot
    assert tamper_events(db) == [] and telegram.sent == []


# ---------- tamper ----------

def test_tamper_while_taken_alerts_owner(db, telegram, handle_event):
    put_lot(db, **TAKEN)
    assert handle_event.lambda_handler(event("tamper"), None) == {"action": "tamper_alert", "notified": True}
    [record] = tamper_events(db)
    assert record["session_id"] == "sess-1" and record["notified"] is True
    [(_, text)] = telegram.sent
    assert "tampering" in text


def test_tamper_while_releasing_is_logged_without_alert(db, telegram, handle_event):
    put_lot(db, **{**TAKEN, "status": "releasing"})
    assert handle_event.lambda_handler(event("tamper"), None)["action"] == "tamper_logged"
    [record] = tamper_events(db)
    assert record["session_id"] == "sess-1" and record["notified"] is False
    assert telegram.sent == []


def test_tamper_while_free_is_logged_without_session(db, telegram, handle_event):
    put_lot(db)
    handle_event.lambda_handler(event("tamper"), None)
    [record] = tamper_events(db)
    assert record["lot_id"] == "space1#lot1" and "session_id" not in record and record["notified"] is False
    assert telegram.sent == []


def test_owner_without_telegram_still_logged(db, telegram, handle_event):
    put_lot(db, **{**TAKEN, "user_id": "bob"})
    assert handle_event.lambda_handler(event("tamper"), None)["notified"] is False
    assert len(tamper_events(db)) == 1 and telegram.sent == []


def test_telegram_failure_never_blocks_the_write(db, telegram, handle_event):
    telegram.ok = False
    put_lot(db, **TAKEN)
    assert handle_event.lambda_handler(event("tamper"), None)["notified"] is False
    [record] = tamper_events(db)
    assert record["notified"] is False


def test_no_bot_token_skips_alert(db, telegram, handle_event, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    put_lot(db, **TAKEN)
    assert handle_event.lambda_handler(event("tamper"), None)["notified"] is False
    assert telegram.sent == []


# ---------- race with the web app (diagram 7) ----------

def test_unlock_race_gives_no_false_theft_alert(db, telegram, handle_event, monkeypatch):
    """We read 'taken', the web app switches the lot to 'releasing', then bike_left is processed."""
    put_lot(db, **TAKEN)
    real_read = handle_event.read_lot
    calls = {"n": 0}

    def read_then_web_app_unlocks(space_id, lot_id):
        item = real_read(space_id, lot_id)
        calls["n"] += 1
        if calls["n"] == 1:  # the owner taps Unlock right after our first read
            db.Table("sbp-lots").update_item(
                Key=LOT_KEY, UpdateExpression="SET #s = :r",
                ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":r": "releasing"})
        return item

    monkeypatch.setattr(handle_event, "read_lot", read_then_web_app_unlocks)
    result = handle_event.lambda_handler(event("bike_left"), None)

    assert result["action"] == "freed"
    assert calls["n"] == 2
    assert get_lot(db)["status"] == "free"
    assert tamper_events(db) == [] and telegram.sent == []


# ---------- lock state (solenoid lock feedback wire) ----------

RELEASING = {**TAKEN, "status": "releasing"}


def get_user(db, user_id="alice"):
    return db.Table("sbp-users").get_item(Key={"id": user_id})["Item"]


def test_bike_left_with_lock_closed_frees_the_lot(db, telegram, handle_event):
    put_lot(db, **RELEASING, lock_closed=True)
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "freed"
    assert get_lot(db)["status"] == "free"
    assert "pending_lock_lot_id" not in get_user(db)


def test_bike_left_with_lock_open_ties_account_without_instant_reminder(db, telegram, handle_event):
    """F1: account tied immediately, but no Telegram yet (check_overstay reminds after the grace period)."""
    put_lot(db, **RELEASING, lock_closed=False)
    assert handle_event.lambda_handler(event("bike_left"), None) == {"action": "awaiting_lock"}
    lot = get_lot(db)
    assert lot["status"] == "awaiting_lock" and lot["user_id"] == "alice"
    assert lot["bike_present"] is False and lot["awaiting_lock_since"].endswith("Z")
    assert get_user(db)["pending_lock_lot_id"] == "space1#lot1"
    assert telegram.sent == []


AWAITING = {**RELEASING, "status": "awaiting_lock", "bike_present": False,
            "awaiting_lock_since": "2026-11-17T01:00:00Z"}


def tie_alice(db):
    db.Table("sbp-users").update_item(Key={"id": "alice"}, UpdateExpression="SET pending_lock_lot_id = :l",
                                      ExpressionAttributeValues={":l": "space1#lot1"})


def test_quick_close_frees_lot_with_no_messages(db, telegram, handle_event):
    """F1: wheeled the bike out, then pushed the metal piece in before any reminder: silent."""
    put_lot(db, **AWAITING, lock_closed=False)
    tie_alice(db)
    assert handle_event.lambda_handler(event("lock_closed"), None) == {"action": "lock_closed_freed", "notified": False}
    lot = get_lot(db)
    assert lot["status"] == "free" and lot["lock_closed"] is True
    for gone in ("user_id", "session_id", "awaiting_lock_since"):
        assert gone not in lot
    assert "pending_lock_lot_id" not in get_user(db)
    assert telegram.sent == []


def test_close_after_reminder_sends_thanks(db, telegram, handle_event):
    put_lot(db, **AWAITING, lock_closed=False, lock_reminded_at="2026-11-17T01:02:00Z")
    tie_alice(db)
    assert handle_event.lambda_handler(event("lock_closed"), None)["notified"] is True
    assert "lock_reminded_at" not in get_lot(db)
    assert "closed" in telegram.sent[0][1]


def test_lock_closed_before_bike_left_then_bike_left_frees(db, telegram, handle_event):
    """Cyclist clicks the cable back in, then rides off: no tie needed."""
    put_lot(db, **RELEASING, lock_closed=False)
    assert handle_event.lambda_handler(event("lock_closed"), None)["action"] == "lock_closed"
    assert get_lot(db)["status"] == "releasing"
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "freed"
    assert "pending_lock_lot_id" not in get_user(db)


def test_lock_opened_and_closed_are_recorded(db, telegram, handle_event):
    put_lot(db, **TAKEN)
    handle_event.lambda_handler(event("lock_opened"), None)
    assert get_lot(db)["lock_closed"] is False and get_lot(db)["status"] == "taken"
    handle_event.lambda_handler(event("lock_closed"), None)
    assert get_lot(db)["lock_closed"] is True and get_lot(db)["status"] == "taken"
    assert telegram.sent == []


def test_lot_without_lock_feedback_behaves_as_before(db, telegram, handle_event):
    """No lock_closed field = treated as closed, so nobody gets tied to a lot."""
    put_lot(db, **RELEASING)
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "freed"


def test_tamper_while_awaiting_lock_is_logged_without_alert(db, telegram, handle_event):
    put_lot(db, **{**RELEASING, "status": "awaiting_lock", "bike_present": False}, lock_closed=False)
    assert handle_event.lambda_handler(event("tamper"), None)["action"] == "tamper_logged"
    [record] = tamper_events(db)
    assert "session_id" not in record and telegram.sent == []


def test_lock_closing_during_bike_left_race_frees_instead_of_tying(db, telegram, handle_event, monkeypatch):
    """We read 'lock open', the lock closes, then bike_left is processed: must free, not tie."""
    put_lot(db, **RELEASING, lock_closed=False)
    real_read = handle_event.read_lot
    calls = {"n": 0}

    def read_then_lock_closes(space_id, lot_id):
        item = real_read(space_id, lot_id)
        calls["n"] += 1
        if calls["n"] == 1:
            db.Table("sbp-lots").update_item(Key=LOT_KEY, UpdateExpression="SET lock_closed = :t",
                                             ExpressionAttributeValues={":t": True})
        return item

    monkeypatch.setattr(handle_event, "read_lot", read_then_lock_closes)
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "freed"
    assert calls["n"] == 2
    assert "pending_lock_lot_id" not in get_user(db) and telegram.sent == []


# ---------- tamper cooldown (one episode per lot per TAMPER_COOLDOWN_SECONDS) ----------

def test_ten_tamper_signals_make_one_record_and_one_alert(db, telegram, handle_event):
    put_lot(db, **TAKEN)
    results = [handle_event.lambda_handler(event("tamper"), None)["action"] for _ in range(10)]
    assert results[0] == "tamper_alert"
    assert results[1:] == ["tamper_repeat_dropped"] * 9
    assert len(tamper_events(db)) == 1
    assert len(telegram.sent) == 1


def test_tamper_after_cooldown_is_a_new_episode(db, telegram, handle_event):
    put_lot(db, **TAKEN, last_tamper_at="2026-01-01T00:00:00Z")  # long ago
    assert handle_event.lambda_handler(event("tamper"), None)["action"] == "tamper_alert"
    assert len(tamper_events(db)) == 1 and len(telegram.sent) == 1


def test_cooldown_also_applies_to_free_lots(db, telegram, handle_event):
    put_lot(db)
    handle_event.lambda_handler(event("tamper"), None)
    assert handle_event.lambda_handler(event("tamper"), None)["action"] == "tamper_repeat_dropped"
    assert len(tamper_events(db)) == 1


def test_suspected_theft_is_not_affected_by_tamper_cooldown(db, telegram, handle_event):
    put_lot(db, **TAKEN)
    handle_event.lambda_handler(event("tamper"), None)              # starts a cooldown
    assert handle_event.lambda_handler(event("bike_left"), None)["action"] == "suspected_theft"
    assert len(tamper_events(db)) == 2 and len(telegram.sent) == 2


def test_latency_is_logged_when_device_sends_ts(db, telegram, handle_event, capsys):
    put_lot(db)
    handle_event.lambda_handler(event("bike_arrived", ts=1), None)
    assert '"latency_ms"' in capsys.readouterr().out
