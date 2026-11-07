# Smart Bicycle Parking System

School IoT + cloud project (PoC). Smart locks fitted to existing bicycle racks at Singapore MRT stations, pitched to LTA / town councils. Solves bike theft, abandoned bikes, and not knowing where free lots are. Free for cyclists. Assessed by a 10-min demo + Q&A, so a **working, reliable demo beats extra features**.

## Naming
- **Lot** = one lock / one bike position. **Parking space** = a group of lots served by one ESP32.
- Lot ID in the database (`lot.id`): `space1#lot3`. In URLs/QR: `space1_lot3`. In MQTT topics: `space1/lot3/...`.

## Stack
- **ESP32** (one per parking space) → **AWS IoT Core** (MQTT over TLS, X.509 cert). Sensors per lot: IR (bike present), SW-420 (tamper), 3 V solenoid via relay (lock).
- **IoT Rule** → Lambda `handle_event`. **EventBridge Scheduler** → Lambda `check_overstay`. Lambdas are Python.
- **DynamoDB** (on-demand, key-value): `sbp-spaces`, `sbp-lots`, `sbp-users`, `sbp-sessions`, `sbp-tamper-events` (team ER diagram + needed fields; proposal 7 Nov).
- **Web app**: NiceGUI (Python). Cyclist, public and officer pages in one app. Talks to AWS directly with `boto3`.
- **Telegram**: one-way alerts to cyclists only (tamper, overstay), sent by the Lambdas.
- **Infra**: Terraform in `infra/`, local state, region `ap-southeast-1`.

## Exact table names, fields, topics and payloads
See `docs/agreed-names-and-formats.md`. **Both halves depend on it.** Don't invent or rename fields; if something needs to change, update that file first and tell the other side.

## Repo layout
- `infra/` Terraform (user, since 7 Nov)
- `lambdas/handle_event/`, `lambdas/check_overstay/` Lambda code (user, since 7 Nov)
- `webapp/` NiceGUI app (teammate; see `webapp/CLAUDE.md`)
- `simulator/` fake ESP32 script for testing without hardware
- `firmware/` ESP32 code (later)
- `certs/` device certificates (gitignored)
- `docs/` handoff (full background) and the agreed names/formats

## Hard rules
- **Never commit secrets**: certificates/private keys, `.env`, Terraform state, `*.tfvars`, Telegram bot token, NiceGUI `storage_secret`, AWS keys.
- **No API Gateway.** The web app calls AWS server-side with boto3; Lambdas are triggered by IoT Rules and EventBridge only.
- **The cloud decides access; the ESP32 just obeys `open`.** No access logic on the device; it never locks on its own (IR only reports). `bike_left` confirms an unlock.
- **ESP32 sends state changes only** (edge filtering), never raw sensor readings.
- Times stored in UTC ISO 8601 (`2026-11-06T07:15:00Z`); shown to users in Singapore time.
- Keep it simple. It's a PoC; prefer the fewest moving parts.

## Working style
Summarise the plan and confirm before large changes or new dependencies. Keep explanations short and plain.
