# Web app (NiceGUI)

One NiceGUI app with three parts: **cyclist** pages (opened by the QR on each lot), a **public** page (free lots per space), and an **officer** dashboard. It reads/writes DynamoDB and publishes `open` commands to IoT Core with `boto3`. No API Gateway.

Table names, fields, status rules, payloads and settings: **`../docs/agreed-names-and-formats.md`**. Follow it exactly; don't add fields without updating it.

## Pages (routes)
| Route | Who | Does |
|---|---|---|
| `/` | anyone | Public: free lots per space (reads `sbp-spaces`), auto-refresh |
| `/lot/{lot_ref}` | cyclist | Opened by the QR, e.g. `/lot/space1_lot3`. Shows lot state and the right action: **Use this lot** (free), **Unlock** (taken by me), "Lot in use" (taken by someone else) |
| `/login`, `/signup` | anyone | Username + password. Redirect back to where the user came from (`?next=`) |
| `/connect-telegram` | logged-in cyclist | Part of sign-up: open `t.me/<bot>?start=<code>`, then **Done** → `getUpdates` → save `telegramChatId`. Can be skipped and done later |
| `/officer` | role = officer | Lock states, open sessions, overstays (`overstayNotifiedAt`), tamper log, occupancy, **Force unlock** |
| `/dev` | only when `BACKEND=fake` | Buttons to simulate `bike_arrived`, `bike_left`, `tamper`, and "lock unreachable" per lot |

QR link format: `http://<laptop-ip>:8080/lot/space1_lot3`.

## Structure
```
webapp/
  main.py            ui.run(host="0.0.0.0", port=8080, storage_secret=...), registers pages
  config.py          reads .env (python-dotenv)
  auth.py            bcrypt hashing, current_user(), require_login(), require_officer()
  telegram_link.py   one-time code + getUpdates lookup
  backend/
    __init__.py      get_backend(): picks fake or aws from BACKEND
    base.py          the interface (method names below)
    fake.py          in-memory version, seeded with space1 lots 1-4 + test accounts
    aws.py           boto3 version
  pages/             public.py, lot.py, auth_pages.py, officer.py, dev.py
  requirements.txt   nicegui, boto3, bcrypt, python-dotenv
  .env.example
```

## Backend: fake vs real
All AWS access goes through `backend/`. **Pages never import boto3.** `BACKEND=fake` runs with no AWS at all, so every page can be built and tested before the teammate's infrastructure exists. Switch to `BACKEND=aws` when Terraform is deployed; the pages shouldn't change.

Suggested interface (adjust as needed, keep both versions in sync):
- Users: `get_user`, `create_user`, `set_telegram_chat_id`
- Lots: `get_lot`, `list_lots(space_id)`, `claim_lot` (conditional free → taken + session + freeLots), `undo_claim`, `mark_releasing` (+ close session)
- Commands: `publish_open(lot_id) -> request_id`, `wait_for_opened(lot_id, request_id, timeout)`
- Read-only: `list_spaces`, `list_open_sessions`, `list_tamper_events(space_id)`

Fake backend: `publish_open` sets `lastOpenedRequestId` after ~1 s (simulates the ESP32), unless the lot is set to "unreachable" on `/dev`. Fake-only test accounts: one cyclist and one officer; credentials printed at startup, never used with `BACKEND=aws`.

Real backend: `boto3.Session(profile_name=AWS_PROFILE)`; IoT publish uses `client("iot-data", endpoint_url="https://" + IOT_DATA_ENDPOINT)`; confirmation polling uses `ConsistentRead=True`.

## NiceGUI notes
- **Login state** in `app.storage.user` (`username`, `role`). Survives new tabs, so a second QR scan stays logged in. Needs `storage_secret` from `.env`. Check login at the top of each protected page and redirect to `/login?next=...`.
- **Officer pages** must check `role == "officer"` on every load, not just hide links.
- **Don't block the event loop**: wrap boto3 and Telegram calls with `await run.io_bound(...)`; wait with `await asyncio.sleep`, never `time.sleep`.
- **Auto-refresh**: `@ui.refreshable` section + `ui.timer(5, section.refresh)` on public and officer pages.
- Show a spinner/disabled button while waiting for `opened` (up to ~8 s), then success or "Couldn't reach the lock, try again".
- Mobile-first layout for cyclist pages (people use them on phones at the rack).
- Display times in Asia/Singapore.

## Run
```
cd webapp
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # fill in; BACKEND=fake needs only STORAGE_SECRET
python main.py          # laptop: http://localhost:8080 ; phone on same Wi-Fi: http://<laptop-ip>:8080
```

## Don'ts
- Don't commit `.env` or the `.nicegui/` folder (stores user sessions).
- Don't store plain passwords; bcrypt only.
- Don't set a Telegram webhook (breaks `getUpdates`).
- Don't trust the URL alone: the lot ref only says *which* lot; access comes from the logged-in user and the lock's owner.
