# Web app

The cyclist and officer website for Smart Bicycle Parking. FastAPI serves HTML pages (Jinja2 templates, Tailwind, HTMX, Leaflet maps). It talks to AWS server-side with boto3: DynamoDB for data, IoT Core to send `open` commands to the ESP32, Cognito for logins. No API Gateway.

- **Cyclists (phone):** map of stations with live free counts → tap a station → tap a free lot (or scan the lot's QR code) → **Use this lot** → later **Unlock**.
- **Officers (desktop):** console with stations, utilisation, suspected abandoned bikes, bikes parked without using the system, tamper log and **Force unlock**.

Runs in two modes, set by `BACKEND` in `.env`:
- `fake` (default): everything in memory, no AWS needed. Data resets when the server restarts.
- `aws`: real DynamoDB, IoT Core and Cognito (needs the Terraform in `../infra/` deployed).

## Demo day (AWS mode)

**Already done once (no need to repeat):** AWS deployed with Terraform, `.env` set to `BACKEND=aws` with the Terraform values, starting data loaded, `overstay_limit_minutes = 43200` (30 days) applied. Full setup: [`../docs/test-on-aws.md`](../docs/test-on-aws.md).

**On the day, about 5 minutes before presenting:**
1. Connect the laptop and the demo phone to the **same network** (the phone's hotspot is safest; see "Open it on your phone" below).
2. From the repo root:
   ```
   bash webapp/run.sh --reset
   ```
   Type `yes`. It empties the demo data in AWS, reloads it with fresh times, then starts the web app. Logins are kept (officer, your cyclist account, Telegram link). The last summary line should read `4 stations, 61 lots, 46 parked bikes, 1 tamper event`.
3. Wait **1 minute** before showing the officer console: the suspected abandoned bikes appear only after the `check_overstay` Lambda's next run (every minute).
4. Open the addresses `run.sh` prints: laptop → `/officer` (log in as `officer`), phone → `/` (log in as your cyclist). Ignore the "Demo accounts (fake mode)" line: those accounts don't exist in AWS.
5. Stop with **Ctrl+C** when done. Never run `terraform destroy` before the demo (new keys, re-flash the ESP32, all logins gone).

**What the console shows right after the reset:** 4 stations, about 3 suspected abandoned bikes (parked 38 days), 3 unregistered bikes, 1 tamper (on a parked bike at Upper Changi MRT Exit B, shown red), an empty real lot at Upper Changi MRT Exit C. The usage chart only shows real use (no fake history in AWS).

**Backup if the ESP32 misbehaves:** send its events from a terminal instead (needs Docker Desktop running). From the repo root:
```
export PATH="$PWD/bin:$PATH"
EP=$(cd infra && terraform output -raw iot_data_endpoint); echo "$EP"
pub() { aws iot-data publish --topic space1/lot1/event --cli-binary-format raw-in-base64-out \
          --payload "{\"type\":\"$1\"}" --endpoint-url "https://$EP" --profile sbp-admin; }
```
Then `pub bike_arrived`, `pub lock_opened`, `pub lock_closed`, `pub bike_left`, `pub tamper` stand in for the real sensors (no output = sent). Order of events per flow: `../docs/test-on-aws.md` step 8.

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
| `/dev` | fake mode only | Pretend to be the ESP32 / Lambdas: `bike_arrived`, `bike_left`, `tamper`, `lock_opened`, `lock_closed`, run overstay check |

## Demo walk-through (fake mode)
1. `/dev` → Upper Changi MRT Exit C, Lot 1 → **bike_arrived** (a bike is now in the lot).
2. Phone: `/` → tap the "1 free" pin → tap lot **1** → **Use this lot** → sign up → Skip Telegram → **Use this lot** → "Lock released … Open signal sent at …". The fake lock now reports open; on `/dev` press **lock_closed** (you pushed the metal piece in) → **Done**: "Your bike is parked and locked".
3. Laptop: Profile → Log out → log in as `officer` → `/officer`. After 2 min, `/dev` → **Run overstay check** moves the bike to Suspected abandoned bikes. On `/dev` press **tamper**: it appears in the Tamper log within 5 s.
4. Phone: open the lot page again → **Unlock** → "Unlocked. Please take your bike…". About 8 s later the fake backend reports `bike_left` by itself (as if you took the bike, lock still open): the page switches to "Lock still open: please push the metal piece back in", and using another lot is blocked. On `/dev` press **lock_closed** → "Lock closed. Thanks!", the lot is free and the map pin updates. With real hardware the IR sensor and the lock's feedback wire do this.
5. Force unlock (officer clears an abandoned bike): in the console, Suspected abandoned bikes → **Force unlock** on a row → confirm.

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
3. Load the starting rows (stations, lots, simulated bikes, 1 tamper, officer account): `python load_starting_data.py`. Safe to re-run: it never overwrites. To start over with fresh data: `bash run.sh --reset` (see Demo day).
4. Start the server as above. `/dev` doesn't exist in AWS mode: the real ESP32 sends the events (or `pub` from a terminal, see Demo day).

## Where things are
| Path | What |
|---|---|
| `main.py` | App setup, login redirects, registers the pages |
| `pages/` | Routes: `public.py` (map, station sheet), `lot.py` (QR page), `auth_pages.py` (login, sign-up, profile, Telegram), `officer.py` (console), `dev.py` |
| `templates/` | Jinja2 HTML; `_phone.html` is the shared phone layout |
| `static/` | `app.css`, `map.js` (cyclist map), `mini-map.js`, `officer.js` |
| `backend/` | All AWS access: `fake.py` (in memory), `aws.py` (boto3), `base.py` (shared interface) |
| `starting_data.py` / `load_starting_data.py` | Stations, lots and accounts; the script loads them into DynamoDB + Cognito |
| `reset_data.py` | Demo-day reset (`bash run.sh --reset`): wipes and reloads the demo data, keeps logins |
| `Dockerfile` | Container image (`docker compose up --build` from the repo root) |
| `design/` | Mockups, `DESIGN.md` (visual rules), `JOURNEYMAP.md` (user flows) |
| `CLAUDE.md` | Rules for building this app with Claude Code |

Table names, fields and MQTT payloads: [`../docs/agreed-names-and-formats.md`](../docs/agreed-names-and-formats.md).
