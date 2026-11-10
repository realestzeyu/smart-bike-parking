# Web app (FastAPI + HTML pages)

One FastAPI app (Jinja2 templates, Tailwind, HTMX, Leaflet) with three parts: **cyclist** pages (opened by the QR on each lot), a **public** page (free lots per space), and an **officer** dashboard. It reads/writes DynamoDB and publishes `open` commands to IoT Core with `boto3`. No API Gateway.

> **7 Nov 2026: schema proposal updated** (still DynamoDB). Tables are now `sbp-spaces`, `sbp-lots`, `sbp-users`, `sbp-sessions`, `sbp-tamper-events` with `snake_case` fields; there is **no `opened` confirmation** any more (unlock is confirmed by IR `bike_left`; claim has Retry / Cancel). Notes further down may still use the old names; `../docs/agreed-names-and-formats.md` is the source of truth.

> **10 Nov 2026:** NiceGUI → FastAPI. `space` gets `lat`/`lng`; `tamper_event` gets `lot_id`. `user.password` is **plaintext** (PoC only, no bcrypt). Starting data comes from `load_starting_data.py`. Target UI: 3 images in `design/`.

Table names, fields, status rules, payloads and settings: **`../docs/agreed-names-and-formats.md`**. Follow it exactly; don't add fields without updating it.

Visual design: **`design/DESIGN.md`**. Every page follows it; the mockups in `design/` are the spec.
Customer journey maps: **`design/JOURNEYMAP.md`**. follow the flows of the user journey.

## Pages (routes)
| Route | Who | Does |
|---|---|---|
| `/` | anyone | Public: free lots per space (reads `sbp-spaces`), auto-refresh |
| `/lot/{lot_ref}` | cyclist | Opened by the QR, e.g. `/lot/space1_lot3`. Shows lot state and the right action: **Use this lot** (free), **Unlock** (taken by me), "Lot in use" (taken by someone else) |
| `/login`, `/signup` | anyone | Username + password. Redirect back to where the user came from (`?next=`) |
| `/connect-telegram` | logged-in cyclist | Part of sign-up: open `t.me/<bot>?start=<code>`, then **Done** → `getUpdates` → save `telegram_chat_id`. Can be skipped and done later |
| `/officer` | role = officer | Lock states, open sessions, overstays (`notified_overstay`), tamper log, occupancy, **Force unlock** |
| `/dev` | only when `BACKEND=fake` | Buttons to simulate `bike_arrived`, `bike_left`, `tamper`, and "lock unreachable" per lot |

QR link format: `http://<laptop-ip>:8000/lot/space1_lot3`.

## Structure
```
webapp/
  main.py            FastAPI app + SessionMiddleware(SESSION_SECRET), includes routes
  config.py          reads .env (python-dotenv)
  auth.py            plaintext password check, current_user(), require_login(), require_officer()
  telegram_link.py   one-time code + getUpdates lookup
  load_starting_data.py  creates space/lot rows + officer account if missing; never overwrites
  backend/
    __init__.py      get_backend(): picks fake or aws from BACKEND
    base.py          the interface (method names below)
    fake.py          in-memory version, seeded with space1 lots 1-4 + test accounts
    aws.py           boto3 version
  pages/             public.py, lot.py, auth_pages.py, officer.py, dev.py (+ templates/ for Jinja2)
  requirements.txt   fastapi, uvicorn, jinja2, itsdangerous, python-multipart, boto3, python-dotenv
  .env.example
```

## Backend: fake vs real
All AWS access goes through `backend/`. **Pages never import boto3.** `BACKEND=fake` runs with no AWS at all, so every page can be built and tested before the teammate's infrastructure exists. Switch to `BACKEND=aws` when Terraform is deployed; the pages shouldn't change.

Suggested interface (adjust as needed, keep both versions in sync):
- Users: `get_user`, `create_user`, `set_telegram_chat_id`
- Lots: `get_lot`, `list_lots(space_id)`, `claim_lot` (conditional free → taken + session), `undo_claim`, `mark_releasing` (+ close session)
- Commands: `publish_open(lot_id) -> request_id`
- Read-only: `list_spaces`, `list_open_sessions`, `list_tamper_events(space_id)`

Fake backend: `/dev` simulates the ESP32 (e.g. `bike_left` completes an unlock; "unreachable" never sends it). Fake-only test accounts: one cyclist and one officer; credentials printed at startup, never used with `BACKEND=aws`.

Real backend: `boto3.Session(profile_name=AWS_PROFILE)`; IoT publish uses `client("iot-data", endpoint_url="https://" + IOT_DATA_ENDPOINT)`; polling the lot uses `ConsistentRead=True`.

## Notes
- **Login state** in the session cookie (`SessionMiddleware`: `username`, `role`). Survives new tabs, so a second QR scan stays logged in. Needs `SESSION_SECRET` from `.env`. Check login at the top of each protected page and redirect to `/login?next=...`.
- **Officer pages** must check `role == "officer"` on every load, not just hide links.
- **Don't block the event loop**: use plain `def` routes for boto3 and Telegram calls (FastAPI runs them in a thread pool).
- **Auto-refresh**: HTMX polling (`hx-trigger="every 5s"`) on public, lot and officer pages.
- After Unlock, poll the lot until `free` (`bike_left`); after ~2 min show "Lock didn't respond, please contact staff".
- Mobile-first layout for cyclist pages (people use them on phones at the rack).
- Display times in Asia/Singapore.

## Run
```
cd webapp
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # fill in; BACKEND=fake needs only SESSION_SECRET
uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # laptop: http://localhost:8000 ; phone: http://<laptop-ip>:8000
```

## Don'ts
- Don't commit `.env`.
- Passwords are plaintext (PoC only): use throwaway demo passwords; never log them.
- Don't set a Telegram webhook (breaks `getUpdates`).
- Don't trust the URL alone: the lot ref only says *which* lot; access comes from the logged-in user and the lock's owner.
