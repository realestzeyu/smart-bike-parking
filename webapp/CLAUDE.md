# Web app (FastAPI + HTML pages)

One FastAPI app (Jinja2 templates, Tailwind, HTMX, Leaflet) with two parts: **cyclist** pages (map of stations, station sheet, the QR lot page, profile) and the **officer** console. Setup and demo guide: **`README.md`**. It reads/writes DynamoDB and publishes `open` commands to IoT Core with `boto3`. No API Gateway.

> **7 Nov 2026: schema proposal updated** (still DynamoDB). Tables are now `sbp-spaces`, `sbp-lots`, `sbp-users`, `sbp-sessions`, `sbp-tamper-events` with `snake_case` fields; there is **no `opened` confirmation** any more (the lot frees on IR `bike_left`; current lot flow: `design/JOURNEYMAP.md`). Notes further down may still use the old names; `../docs/agreed-names-and-formats.md` is the source of truth.

> **10 Nov 2026:** NiceGUI → FastAPI. `space` gets `lat`/`lng`; `tamper_event` gets `lot_id`. ~~`user.password` plaintext~~ **→ login via Amazon Cognito (later on 10 Nov)**: `user.password` is removed; see "Login (Cognito)" in `../docs/agreed-names-and-formats.md`. Starting data comes from `load_starting_data.py`. Target UI: 3 images in `design/`.

Table names, fields, status rules, payloads and settings: **`../docs/agreed-names-and-formats.md`**. Follow it exactly; don't add fields without updating it.

Visual design: **`design/DESIGN.md`**. Every page follows it; the mockups in `design/` are the spec.
Customer journey maps: **`design/JOURNEYMAP.md`**. follow the flows of the user journey.

## Pages (routes)
| Route | Who | Does |
|---|---|---|
| `/` | anyone | Map of stations with free counts; tap a pin → station sheet (`/space/{id}/sheet`); free lots in the grid link to their lot page. Pins + sheet refresh every 5 s |
| `/lot/{lot_ref}` | cyclist | Opened by the QR, e.g. `/lot/space1_lot3`. Shows lot state and the right action: **Use this lot** (free), **Unlock** (taken by me), "Lot in use" (taken by someone else). After Use: Done / Release again; after Unlock: Done / Unlock again; each press shows "Open signal sent … at 14:52:03" |
| `/login`, `/signup` | anyone | Username + password (sign-up also asks for email; cyclists only). Redirect back to where the user came from (`?next=`) |
| `/profile` | anyone | Logged in: name, role, Connect Telegram, officer console link, **Log out**. Logged out: Log in / Create an account |
| `/connect-telegram` | logged-in cyclist | Part of sign-up: open `t.me/<bot>?start=<code>`, then **Done** → `getUpdates` → save `telegram_chat_id`. Can be skipped and done later |
| `/officer` | role = officer | Lock states, open sessions, overstays (`overstay_notified_at`; open sessions via the `open-sessions` index), unregistered bikes (free lot + `bike_present_since` older than `UNREGISTERED_LIMIT_MINUTES`), tamper log, occupancy, **Force unlock** |
| `/dev` | only when `BACKEND=fake` | Buttons to simulate `bike_arrived`, `bike_left`, `tamper` per lot, and "Run overstay check". Fake mode also sends `bike_left` by itself ~8 s after an Unlock |

QR link format: `http://<laptop-ip>:8000/lot/space1_lot3`.

## Structure
```
webapp/
  main.py            FastAPI app + SessionMiddleware(SESSION_SECRET), includes routes
  config.py          reads .env (python-dotenv)
  auth.py            session login helpers: current_user(), require_user(), require_officer(); passwords checked by the backend
  telegram_link.py   one-time code + getUpdates lookup
  starting_data.py   space1 (real lot) + 3 simulated stations (20 lots each) + officer + demo user
  load_starting_data.py  loads starting_data.py into DynamoDB + Cognito if missing; never overwrites
  backend/
    __init__.py      get_backend(): picks fake or aws from BACKEND
    base.py          the interface (method names below)
    fake.py          in-memory version, seeded from starting_data.py + test accounts
    aws.py           boto3 version (DynamoDB, IoT publish, Cognito)
  pages/             public.py, lot.py, auth_pages.py, officer.py, dev.py
  templates/         Jinja2: _phone.html (phone layout), _tabbar.html, page templates, HTMX partials
  static/            app.css, map.js, mini-map.js, officer.js
  run.sh             one-command start (venv, packages, .env, server)
  requirements.txt   fastapi, uvicorn, jinja2, itsdangerous, python-multipart, boto3, python-dotenv
  .env.example
```

## Backend: fake vs real
All AWS access goes through `backend/`. **Pages never import boto3.** `BACKEND=fake` runs with no AWS at all, so every page can be built and tested before the teammate's infrastructure exists. Switch to `BACKEND=aws` when Terraform is deployed; the pages shouldn't change.

Interface (`backend/base.py`; keep fake and aws in sync):
- Users: `get_user`, `authenticate`, `sign_up` (cyclists), `set_telegram_chat_id`
- Spaces and lots: `list_spaces`, `get_space`, `list_lots(space_id)`, `get_lot`, `claim_lot` (conditional free → taken + session), `mark_releasing` (+ close session; officers skip the owner check)
- Commands: `publish_open(lot_id) -> request_id`
- Read-only: `get_session`, `list_open_sessions`, `list_tamper_events`
- Fake only (for `/dev`): `simulate_event`, `flag_overstays`

Fake backend: `/dev` simulates the ESP32 and the overstay Lambda; after an Unlock it also sends `bike_left` by itself (~8 s). Fake-only test accounts (shown on the login page): `officer` / `officer1`, `alice` / `alice123`; never used with `BACKEND=aws`.

Real backend: `boto3.Session(profile_name=AWS_PROFILE)`; IoT publish uses `client("iot-data", endpoint_url="https://" + IOT_DATA_ENDPOINT)`; lot reads use `ConsistentRead=True`.

## Notes
- **Login state** in the session cookie (`SessionMiddleware`: `username`, `role`). Survives new tabs, so a second QR scan stays logged in. Needs `SESSION_SECRET` from `.env`. Check login at the top of each protected page and redirect to `/login?next=...`.
- **Officer pages** must check `role == "officer"` on every load, not just hide links.
- **Don't block the event loop**: use plain `def` routes for boto3 and Telegram calls (FastAPI runs them in a thread pool).
- **Auto-refresh**: every 5 s on the map pins, the station sheet and the officer console (HTMX polling).
- No unlock confirmation (KIV): the app can't tell if the lock opened. After Unlock the page says "Unlocked…" with Done / Unlock again; the lot stays `releasing` until IR `bike_left`.
- Mobile-first layout for cyclist pages (people use them on phones at the rack).
- Display times in Asia/Singapore.

## Run
```
cd webapp
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env  # BACKEND=fake needs nothing else
uvicorn main:app --host 0.0.0.0 --port 8000   # restart after changes (--reload is unreliable on Windows)
```

## Don'ts
- Don't commit `.env`.
- Passwords go only to Cognito: never store or log them. In `BACKEND=fake`, the fake backend checks passwords in memory instead.
- Don't set a Telegram webhook (breaks `getUpdates`).
- Don't trust the URL alone: the lot ref only says *which* lot; access comes from the logged-in user and the lock's owner.
