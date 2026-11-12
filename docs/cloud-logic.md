# Cloud logic (Lambdas)

How `handle_event` and `check_overstay` behave. **Status: plan, agreed before building (10 Nov 2026).** Field names and payloads come from [`agreed-names-and-formats.md`](agreed-names-and-formats.md); if the two disagree, that file wins.

Decisions baked in:
- Tamper while the lot is `releasing` → stored, **no alert** (the owner is unlocking).
- Every lot write is **conditional on the status just read**; on conflict, re-read and decide again (max 3 tries).
- Telegram failures never block a database write. DynamoDB errors raise → Lambda retries (up to 2).
- One JSON log line per event (measured results).
- Officer flags *stuck releasing* and *unregistered bike* are computed by the web app when the page loads (no Lambda involved).

---

## 1. Lot status

```mermaid
stateDiagram-v2
    [*] --> free
    free --> taken: web app - Use this lot (needs bike_present; claim + session, is_open=Y)
    taken --> free: web app - Cancel (delete session)
    taken --> releasing: web app - Unlock / officer Force unlock (end_time, remove is_open)
    releasing --> free: handle_event - bike_left (unlock confirmed)
    releasing --> releasing: owner taps Unlock again (re-send open)
```

## 2. `handle_event` (every ESP32 event, via IoT Rule)

```mermaid
flowchart TD
    A["IoT Rule: space1/lot1/event<br/>{type, space, lot, ts?}"] --> B{"Valid type and fields?"}
    B -- no --> X1["Log and ignore"]
    B -- yes --> C["GetItem lot<br/>space_id=space1, id=space1#lot1"]
    C --> D{"Lot exists?"}
    D -- no --> X2["Log unknown lot, ignore"]
    D -- yes --> E{"type?"}

    E -- bike_arrived --> F["bike_present = true<br/>bike_present_since = now (if not set)"]

    E -- bike_left --> G{"lot status?"}
    G -- releasing --> G1["status = free, bike_present = false<br/>remove bike_present_since, user_id, session_id"]
    G -- taken --> G2["bike_present = false, remove bike_present_since<br/>put tamper event: lot_id + session_id"]
    G2 --> T1["Telegram owner:<br/>bike left without unlock (suspected theft)"]
    G -- free --> G3["bike_present = false<br/>remove bike_present_since"]

    E -- tamper --> H{"lot status?"}
    H -- taken --> H1["put tamper event: lot_id + session_id"]
    H1 --> T2["Telegram owner:<br/>someone is tampering with your bike"]
    H -- releasing --> H2["put tamper event: lot_id + session_id<br/>notified = false, no alert (owner unlocking)"]
    H -- free --> H3["put tamper event: lot_id only<br/>notified = false, no alert (no owner)"]

    G1 --> W{"Write condition<br/>status unchanged?"}
    G2 --> W
    G3 --> W
    W -- "no: web app changed the lot" --> C
    W -- yes --> L["Log one JSON line"]
    F --> L
    T1 --> L
    T2 --> L
    H2 --> L
    H3 --> L
```

Conditional writes: lot updates carry `ConditionExpression: status = :read_status AND attribute_exists(id)`. A failed condition means the web app changed the lot between our read and write (e.g. the owner just tapped Unlock), so we re-read and take the right branch. This prevents a false theft alert. Max 3 tries, then log and stop.

## 3. `check_overstay` (EventBridge Scheduler: every 1 min demo, 15 min deployment)

```mermaid
flowchart TD
    A["Scheduler tick"] --> B["Query open-sessions index<br/>is_open = Y and start_time older than limit<br/>(all pages)"]
    B --> C{"Any sessions?"}
    C -- no --> Z["Log summary, done"]
    C -- yes --> D["For each session"]
    D --> E["Set overstay_notified_at = now<br/>only if not already set"]
    E --> F{"Update succeeded?"}
    F -- "no: already flagged" --> D
    F -- yes --> G["Marked suspected abandoned<br/>(officer dashboard sees it)"]
    G --> H{"Owner has telegram_chat_id<br/>and bot token set?"}
    H -- no --> D
    H -- yes --> J["Telegram owner:<br/>your bike at address, lot N<br/>parked for X, please collect it"]
    J --> D
```

## 4. Telegram alert (helper in both Lambdas)

```mermaid
flowchart LR
    A["Need to alert owner"] --> B["GetItem sbp-users<br/>telegram_chat_id"]
    B --> C{"chat id and token set?"}
    C -- no --> D["Skip, log, notified = false"]
    C -- yes --> E["GetItem sbp-spaces: address<br/>time in SGT (UTC+8)"]
    E --> F["POST api.telegram.org sendMessage<br/>5 s timeout, standard library only"]
    F --> G{"OK?"}
    G -- yes --> H["notified = true"]
    G -- no --> I["Log error, notified = false<br/>(never blocks the DB write)"]
```

## 5. Officer view flags (web app, computed on page load)

```mermaid
flowchart TD
    A["Officer dashboard loads"] --> B["Query lots per space<br/>+ open sessions (open-sessions index)"]
    B --> C{"Per lot / session"}
    C --> D["Suspected abandoned:<br/>session has overstay_notified_at"]
    C --> E["Stuck releasing:<br/>status = releasing and session end_time<br/>older than RELEASE_TIMEOUT_MINUTES"]
    C --> F["Unregistered bike:<br/>status = free, bike_present = true,<br/>bike_present_since older than UNREGISTERED_LIMIT_MINUTES"]
```

## 6. Example: tamper on a parked bike

```mermaid
sequenceDiagram
    participant ESP as ESP32 (space1)
    participant IoT as IoT Core + Rule
    participant HE as handle_event
    participant DB as DynamoDB
    participant TG as Telegram
    participant C as Cyclist phone

    ESP->>IoT: space1/lot1/event {type: tamper, ts}
    IoT->>HE: {type: tamper, space: space1, lot: lot1, ts}
    HE->>DB: GetItem sbp-lots (space1, space1#lot1)
    DB-->>HE: status = taken, user_id, session_id
    HE->>DB: GetItem sbp-users, sbp-spaces
    HE->>TG: sendMessage(chat_id, "Tampering at ... 14:05")
    TG-->>C: Alert
    HE->>DB: PutItem sbp-tamper-events (lot_id, session_id, notified = true)
    HE->>HE: log JSON line (latency_ms)
```

## 7. Example: unlock racing with bike_left (why writes are conditional)

```mermaid
sequenceDiagram
    participant W as Web app
    participant HE as handle_event
    participant DB as DynamoDB

    HE->>DB: GetItem lot (status = taken)
    W->>DB: lot -> releasing (owner tapped Unlock)
    HE->>DB: Update lot ... IF status = taken
    DB-->>HE: ConditionalCheckFailed
    HE->>DB: GetItem lot again (status = releasing)
    HE->>DB: Update lot -> free IF status = releasing
    Note over HE: No false theft alert
```

## 8. Logging (measured results)

One JSON line per handled event or overstay run, e.g.

```json
{"fn": "handle_event", "type": "tamper", "lot_id": "space1#lot1", "status": "taken",
 "action": "alert", "notified": true, "received_at": "2026-11-10T06:05:01Z",
 "device_ts": 1762754700580, "latency_ms": 420}
```

CloudWatch Logs Insights queries over these give event counts, alert success rate, and ESP32-to-cloud latency (when the ESP32 sends `ts`).

## 9. Testing plan

- **Unit tests** (`lambdas/tests/`, pytest + moto, dev-only, not deployed): one test per branch of diagrams 2 and 3, plus the race in diagram 7. Telegram is faked.
- **Test data:** `infra/test_data.sh` puts `space1`, `space1#lot1` and a test user (create-only), plus a reset. Replaced later by `webapp/load_starting_data.py`.
- **End-to-end on AWS:** `aws iot-data publish` events, simulate claim/unlock with CLI writes, check DynamoDB, logs and Telegram.

## Where the code is (built 12 Nov)

| File | Contents |
|---|---|
| `lambdas/handle_event/handler.py` | diagram 2 + the race retry (diagram 7) |
| `lambdas/check_overstay/handler.py` | diagram 3 |
| `lambdas/shared/sbp_common.py` | time, JSON logging, DynamoDB tables, Telegram helper (diagram 4); zipped into both Lambdas by `infra/lambdas.tf` |
| `lambdas/tests/` | 22 unit tests (pytest + moto) |
| `infra/test_data.sh` | test data + web-app stand-ins (`load`, `claim`, `unlock`, `show`, `reset`) |

Run the unit tests (from `lambdas/`): `python -m venv .venv`, install `requirements-dev.txt`, then `python -m pytest tests -q`. See `infra/README.md` for the end-to-end test on AWS.
