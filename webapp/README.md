# Web app

The cyclist and officer website for Smart Bicycle Parking. FastAPI serves HTML pages (Jinja2 templates, Tailwind, HTMX, Leaflet maps). It talks to AWS server-side with boto3: DynamoDB for data, IoT Core to send `open` commands to the ESP32, Cognito for logins. No API Gateway.

- **Cyclists (phone):** map of stations with live free counts → tap a station → tap a free lot (or scan the lot's QR code) → **Use this lot** → later **Unlock**.
- **Officers (desktop):** console with stations, utilisation, suspected abandoned bikes, bikes parked without using the system, tamper log and **Force unlock**.

Runs in two modes, set by `BACKEND` in `.env`:
- `fake` (default): everything in memory, no AWS needed. Data resets when the server restarts.
- `aws`: real DynamoDB, IoT Core and Cognito (needs the Terraform in `../infra/` deployed).

## Run it (fake mode)
Needs Python 3.10+. From the repo root (on Windows use **Git Bash**):
```
bash webapp/run.sh
```
The first run creates `.venv`, installs the packages and creates `.env` (fake mode); later runs just start the server. It prints the laptop and phone addresses. Stop with Ctrl+C.

Or by hand (Windows PowerShell, from the repo root):
```
cd webapp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # leave BACKEND=fake; SESSION_SECRET can stay empty in fake mode
uvicorn main:app --host 0.0.0.0 --port 8000
```
Open http://127.0.0.1:8000. Auto-reload (`--reload`) doesn't work reliably on Windows: stop (Ctrl+C) and start again after code changes.

**Test accounts (fake mode only, also shown on the login page):** officer = username `officer`, password `officer1`; cyclist = username `alice`, password `alice123`. Or sign up a new cyclist.

## Pages
| Page | Who | What |
|---|---|---|
| `/` | anyone | Map of stations; tap a pin for the station sheet (lot grid, tap a free lot) |
| `/lot/space1_lot1` | anyone | The QR sticker page: Use this lot / Unlock / Lot in use |
| `/profile` | anyone | Log in, log out, switch account, Connect Telegram, link to the console for officers |
| `/login`, `/signup` | anyone | Sign-up is for cyclists only; officers are created by `load_starting_data.py` |
| `/officer` | officers | Console + Force unlock (refreshes every 5 s) |
| `/dev` | fake mode only | Pretend to be the ESP32 / Lambdas: `bike_arrived`, `bike_left`, `tamper`, run overstay check |

## Demo walk-through (fake mode)
1. `/dev` → Upper Changi MRT Exit C, Lot 1 → **bike_arrived** (a bike is now in the lot).
2. Phone: `/` → tap the "1 free" pin → tap lot **1** → **Use this lot** → sign up → Skip Telegram → **Use this lot** → "Lock released … Open signal sent at …" → **Done**.
3. Laptop: Profile → Log out → log in as `officer` → `/officer`. The bike shows in Longest-parked. On `/dev` press **tamper**: it appears in the Tamper log within 5 s.
4. Phone: open the lot page again → **Unlock** → "Unlocked. Please take your bike…". About 8 s later the fake backend reports `bike_left` by itself (as if you took the bike): the lot is free again and the map pin updates. With real hardware the IR sensor does this.
5. Force unlock: in the console, **Force unlock** on any row → confirm.

The 3 extra stations (Exit A, Exit B, SUTD Campus Centre, 20 lots each) are simulated: they make the map and console look like a real network. Only `space1#lot1` has hardware.

## Open it on your phone
1. Phone and laptop on the **same Wi-Fi** (same network name, not a guest network). Mobile data and VPN off.
2. Find the laptop's IP: `ipconfig` → Wi-Fi → IPv4 Address (e.g. `192.168.0.4`).
3. On the phone type `http://192.168.0.4:8000` (with `http://`).
4. Still can't connect? Many routers block devices from talking to each other. Use the **phone's hotspot** instead (the demo setup): connect the laptop to it, run `ipconfig` again and use the new IP.
5. Also check Windows Firewall allows Python on that network (Windows asks the first time the server starts).

## Switch to AWS
1. Deploy the infra: see [`../infra/README.md`](../infra/README.md).
2. Fill `.env` from the Terraform outputs: `BACKEND=aws`, `SESSION_SECRET` (any long random string), `AWS_PROFILE=sbp-webapp`, `IOT_DATA_ENDPOINT`, `TABLE_PREFIX`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, and the Telegram bot values if you have them.
3. Load the starting rows (stations, lots, simulated bikes, officer account): `python load_starting_data.py`. Safe to re-run: it never overwrites.
4. Start the server as above. `/dev` doesn't exist in AWS mode: the real ESP32 (or the simulator) sends the events.

## Where things are
| Path | What |
|---|---|
| `main.py` | App setup, login redirects, registers the pages |
| `pages/` | Routes: `public.py` (map, station sheet), `lot.py` (QR page), `auth_pages.py` (login, sign-up, profile, Telegram), `officer.py` (console), `dev.py` |
| `templates/` | Jinja2 HTML; `_phone.html` is the shared phone layout |
| `static/` | `app.css`, `map.js` (cyclist map), `mini-map.js`, `officer.js` |
| `backend/` | All AWS access: `fake.py` (in memory), `aws.py` (boto3), `base.py` (shared interface) |
| `starting_data.py` / `load_starting_data.py` | Stations, lots and accounts; the script loads them into DynamoDB + Cognito |
| `design/` | Mockups, `DESIGN.md` (visual rules), `JOURNEYMAP.md` (user flows) |
| `CLAUDE.md` | Rules for building this app with Claude Code |

Table names, fields and MQTT payloads: [`../docs/agreed-names-and-formats.md`](../docs/agreed-names-and-formats.md).
