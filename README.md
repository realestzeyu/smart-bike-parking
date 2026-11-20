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
| `bin/` | `aws`, `terraform`: run the AWS CLI / Terraform through Docker (nothing to install) |

## Starting fresh
- **No AWS (fake mode):** `bash webapp/run.sh` (Git Bash on Windows), then open http://127.0.0.1:8000. Needs only Python 3.10+.
- **Your own AWS:** `run.sh` alone isn't enough. Do [`docs/test-on-aws.md`](docs/test-on-aws.md) steps 2–6 once (deploy, `.env`, starting data). Optional: step 9 for Telegram alerts. After that, `bash webapp/run.sh`.
- **Demo day (already deployed):** [`webapp/README.md` → Demo day](webapp/README.md#demo-day-aws-mode).

Details and test accounts: [`webapp/README.md`](webapp/README.md). Project rules: `CLAUDE.md`, `webapp/CLAUDE.md`.
