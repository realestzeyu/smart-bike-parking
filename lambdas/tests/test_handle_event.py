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


def test_latency_is_logged_when_device_sends_ts(db, telegram, handle_event, capsys):
    put_lot(db)
    handle_event.lambda_handler(event("bike_arrived", ts=1), None)
    assert '"latency_ms"' in capsys.readouterr().out
