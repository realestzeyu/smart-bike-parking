# Agreed Names and Formats

What the web app side and the AWS side have agreed on: table names, fields, who writes what, MQTT topics, payloads, and settings. Both halves are built against this file, so if anything here changes, update the file and tell the other side.

**Status: DRAFT.** Items marked **[?]** need a decision.

**Changed 7 Nov 2026 (AWS side):** `sbp-locks` key is now `spaceId` + `lotId` (so one Query lists a space's lots); `sbp-spaces` gains `lat`/`lng` and loses `freeLots`, `totalLots`, `online`, `lastSeen` (free count = count of `free` lots from that Query); sessions gain `durationMinutes`; `by-space` index and `spaceId` removed from tamper events; `users.createdAt` removed. Web app side: claim/undo no longer touch a counter.

---

## 1. IDs and formats

| Thing | Format | Example |
|---|---|---|
| Space ID | `space<N>` | `space1` |
| Lot ID (DynamoDB) | `<spaceId>#lot<N>` | `space1#lot3` |
| Lot ref (URL / QR) | `<spaceId>_lot<N>` (`#` breaks URLs) | `space1_lot3` |
| Timestamps in DynamoDB | ISO 8601, UTC, seconds | `2026-11-06T07:15:00Z` |
| `requestId` | UUID4 string | `"9b1f..."` |
| `expires` (in commands) | Unix epoch seconds | `1762413330` |

Times are shown to users in Singapore time (UTC+8). The **Lambda's receive time** is the official time for events (the ESP32 clock is not trusted).

---

## 2. DynamoDB tables

All created by Terraform. Names use the prefix `sbp-`. Region `ap-southeast-1`. On-demand billing.

### `sbp-locks`: one item per lot
Key: `spaceId` (S, partition) + `lotId` (S, sort). `Query(spaceId)` returns every lot in a space (per-lot availability + free count). `GetItem` needs both; both come from the lot ref / topic.

| Field | Type | Meaning | Written by |
|---|---|---|---|
| `spaceId` | S | `space1` | seed |
| `lotId` | S | `space1#lot3` | seed |
| `status` | S | `free` / `taken` / `releasing` (see section 3) | web app, `handle_event` |
| `ownerUsername` | S | current user; removed when free | web app, `handle_event` (removes) |
| `since` | S | when `status` last changed | web app, `handle_event` |
| `sessionStart` | S | `startTime` of the current session (to find it) | web app |
| `bikePresent` | BOOL | from IR events | `handle_event` |
| `lastOpenedRequestId` | S | `requestId` from the latest `opened` event | `handle_event` |
| `lastOpenedAt` | S | time of that `opened` event | `handle_event` |

### `sbp-sessions`: one item per parking session (kept as the usage archive)
Key: `lotId` (S, partition) + `startTime` (S, sort). `Query(lotId)` = that lot's usage history.
GSI `open-sessions`: partition `open` (S), sort `startTime`. **Sparse**: only open sessions have `open`.

| Field | Type | Meaning | Written by |
|---|---|---|---|
| `lotId`, `startTime` | S | key | web app |
| `ownerUsername` | S | who parked | web app |
| `open` | S | `"Y"` while open; **removed** when closed | web app |
| `endTime` | S | set when closed | web app |
| `durationMinutes` | N | `endTime − startTime`, set when closed (usage stats) | web app |
| `overstayNotifiedAt` | S | set when an overstay alert was sent = **suspected abandoned** flag (stops repeats; dashboard lists these) | `check_overstay` |

### `sbp-users`: one item per account
Key: `username` (S)

| Field | Type | Meaning | Written by |
|---|---|---|---|
| `username` | S | key, lowercase | web app |
| `passwordHash` | S | bcrypt hash | web app |
| `role` | S | `cyclist` / `officer` | web app (officers created by script, not sign-up) |
| `telegramChatId` | N | set after Connect Telegram; may be missing | web app |

Lambdas only **read** `telegramChatId` from here.

### `sbp-spaces`: one item per parking space (cyclist "nearest spaces" list)
Key: `spaceId` (S). Few items, so the web app Scans and sorts by distance from the phone's location.

| Field | Type | Meaning | Written by |
|---|---|---|---|
| `spaceId` | S | key | seed |
| `name` | S | display name, e.g. `Bedok MRT Exit A` | seed |
| `lat`, `lng` | N | location (decimal degrees) | seed |

No `freeLots` counter: free count = lots with `status = free` from `Query sbp-locks (spaceId)`.

### `sbp-tamper-events`: tamper log for the officer dashboard
Key: `lotId` (S, partition) + `at` (S, sort). No index: dashboard Scans (small table) and sorts newest first. Space = part of `lotId`.

| Field | Type | Meaning | Written by |
|---|---|---|---|
| `lotId`, `at` | S | key | `handle_event` |
| `ownerUsername` | S | owner at the time (may be missing if lot was free) | `handle_event` |
| `notified` | BOOL | Telegram alert sent successfully | `handle_event` |

### Seed data
`sbp-locks` items for each real lot (`status = free`, `bikePresent = false`) and one `sbp-spaces` item per space (`name`, `lat`, `lng`). Seeded by Terraform (`aws_dynamodb_table_item`, `ignore_changes` on the item) — **on hold until the schema is final.** Prototype: `space1`, 1 lot (`space1#lot1`).

---

## 3. Lot status and who changes it

```
free ──(web app: "Use this lot", after `opened` confirmed)──▶ taken
taken ──(web app: "Unlock" or officer Force unlock, after `opened` confirmed)──▶ releasing
releasing ──(handle_event: bike_left)──▶ free
```

| Change | Who | Also does |
|---|---|---|
| free → taken | web app | conditional update (`status = free`) so two users can't grab the same lot; set `ownerUsername`, `since`, `sessionStart`; create the session |
| taken → releasing | web app | close the session (`endTime`, `durationMinutes`, remove `open`) |
| releasing → free | `handle_event` on `bike_left` | remove `ownerUsername`; set `since` |

Rules:
- `bike_left` while `taken` (bike gone without an unlock): **[?]** just set `bikePresent = false`, or also log it in `sbp-tamper-events` as a possible theft. Suggest: log it.
- `bike_arrived` / `bike_left` always update `bikePresent`.

### "Use this lot" order (web app)
1. Conditional update lot → `taken` (fails if not free → "Lot in use").
2. Create session.
3. Publish `open` (section 4).
4. Poll `sbp-locks` (strongly consistent read, every ~0.5 s, up to ~8 s) until `lastOpenedRequestId` == our `requestId`.
5. No confirmation → **undo** steps 1–2 (back to `free`, delete session), show "Couldn't reach the lock, try again".

### "Unlock" order (web app)
1. Check the user is the owner (officers skip this for Force unlock).
2. Publish `open`, poll for confirmation as above.
3. Confirmed → set `releasing` and close the session. Not confirmed → change nothing, show error.

---

## 4. MQTT topics and payloads

| Topic | Direction | Payload |
|---|---|---|
| `space1/lot3/event` | ESP32 → cloud | `{"type": "bike_arrived"}` / `{"type": "bike_left"}` / `{"type": "tamper"}` / `{"type": "opened", "requestId": "<uuid>"}` |
| `space1/lot3/cmd` | cloud (web app) → ESP32 | `{"action": "open", "requestId": "<uuid>", "expires": <epoch s>}` |
| `space1/status` | IoT Core (Last Will) → cloud | `{"status": "offline"}` **KIV** |

- `expires` = now + 30 s. The ESP32 ignores expired commands (needs NTP time; if no NTP, it skips the check).
- The ESP32 must echo the `requestId` in its `opened` event. That's how the web app knows its command worked.
- Events may include an optional `"ts"`; the Lambda ignores it and uses its own time.

**IoT Rule 1:** `SELECT *, topic(1) AS space, topic(2) AS lot FROM '+/+/event'` → `handle_event`.
`handle_event` builds the lock key as `spaceId = space`, `lotId = space + "#" + lot`.

**ESP32 IoT policy:** connect as client ID `space1`; publish `space1/*/event` and `space1/status`; subscribe/receive `space1/*/cmd`.

---

## 5. What each Lambda does with the tables

**`handle_event`**
- `bike_arrived` → `bikePresent = true`.
- `bike_left` → `bikePresent = false`; if `releasing` → free (section 3).
- `opened` → `lastOpenedRequestId`, `lastOpenedAt`.
- `tamper` → write `sbp-tamper-events`; if the lot has an owner with `telegramChatId`, send Telegram (lot, time in SGT); set `notified`.
- (`handle_event` never touches `sbp-spaces`.)

**`check_overstay`** (every 1 min for demo)
- Query `open-sessions` GSI. For each session older than `OVERSTAY_LIMIT_MINUTES` with no `overstayNotifiedAt`: send Telegram to the owner, set `overstayNotifiedAt`.

---

## 6. Settings

### Terraform outputs the web app needs
| Output | Used as |
|---|---|
| `iot_data_endpoint` (e.g. `xxxx-ats.iot.ap-southeast-1.amazonaws.com`) | `IOT_DATA_ENDPOINT` |
| table names (all `sbp-...`) | `TABLE_PREFIX=sbp-` |
| web app IAM access key + secret (sensitive) | AWS profile `sbp-webapp` on the laptop |

### Web app IAM permissions (least privilege)
- DynamoDB: `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `Scan` on the 5 tables and their indexes.
- IoT: `iot:Publish` on `arn:aws:iot:ap-southeast-1:<account>:topic/space*/*/cmd` only.

### Web app `.env` (gitignored; see `webapp/.env.example`)
`BACKEND`, `AWS_PROFILE`, `AWS_REGION`, `IOT_DATA_ENDPOINT`, `TABLE_PREFIX`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `STORAGE_SECRET`

### Lambda environment variables (Terraform)
`TABLE_PREFIX`, `TELEGRAM_BOT_TOKEN` (sensitive variable), `OVERSTAY_LIMIT_MINUTES` (demo `2`, deployment e.g. `4320` = 3 days)

### Telegram
- One bot. Whoever creates it (BotFather) shares the token **privately** with both sides. Never in the repo.
- The web app uses it for `getUpdates` (Connect Telegram at sign-up). The Lambdas use it for `sendMessage`.
- **No webhook** may be set on the bot, or `getUpdates` stops working.

---

## 7. Open items [?]
1. ~~Seed lots via Terraform or a script.~~ Terraform, on hold until the schema is final.
2. `bike_left` while `taken`: log as possible theft? (suggested yes)
3. `handle_offline`: build or leave out (KIV). If built, it needs its own place to store `online` / `lastSeen` (removed from `sbp-spaces`).
4. ~~Real lot count in the prototype.~~ 1 space, 1 lot for now.
