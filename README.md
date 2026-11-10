# Smart Bicycle Parking

Cloud Computing and IoT project (PoC). Smart locks on existing bike racks at Singapore MRT stations: reduces theft and abandoned bikes, and shows where free lots are.

## How it works
ESP32 (sensors + solenoid lock) ⇄ AWS IoT Core (MQTT) → Lambdas → DynamoDB ⇄ FastAPI web app. Telegram sends alerts to cyclists.

## Layout
| Folder | Contents |
|---|---|
| `webapp/` | FastAPI + HTML pages: cyclist and officer pages |
| `lambdas/` | `handle_event`, `check_overstay` (Python) |
| `infra/` | Terraform for the whole AWS backend (`ap-southeast-1`). Setup guide: [`infra/README.md`](infra/README.md) |
| `simulator/` | Fake ESP32 for testing without hardware |
| `firmware/` | ESP32 code |
| `certs/` | Device certificates (gitignored) |
| `docs/` | `handoff.md`, `agreed-names-and-formats.md` (table, field and topic names) |

## Run the web app
Not built yet: `webapp/main.py` is still an old NiceGUI template, to be replaced by the FastAPI app. Once built:
```
cd webapp
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env     # BACKEND=fake needs only SESSION_SECRET
uvicorn main:app --host 0.0.0.0 --port 8000 --reload   # http://localhost:8000
```

See `CLAUDE.md` for project rules and `webapp/CLAUDE.md` for web app details.
