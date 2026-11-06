# Smart Bicycle Parking System: Project Handoff

Full background and reasoning, for humans and for starting a new chat. Reflects decisions aligned on 6 Nov 2026. **Replaces the 5 Nov handoff.**

Exact table names, fields, topics and payloads live in **`agreed-names-and-formats.md`**. If this file and that one disagree, that one wins.

Changes since 5 Nov:
- **Web app = NiceGUI** (was Streamlit). Login persistence solved by `app.storage.user`; QR link format changed.
- **Infrastructure as code = Terraform** (local state, region `ap-southeast-1`).
- **One repo** for everything; **team split**: user builds the web app, teammate builds Terraform + Lambdas.
- Data model details settled: `releasing` lock status, `opened` confirmation written to the locks table, `freeLots` counter rule, overstay flag on sessions, separate tamper-events table.

## 1. Project in one paragraph

A low-cost smart parking system fitted onto existing bicycle racks at Singapore MRT stations, pitched to the government (LTA or town councils, still to confirm). It tackles three problems: bike theft, abandoned bikes, and no visibility of free lots. It is free for cyclists, which is the lesson from SecureMyBike: S$4.7M, about 500 bikes, about S$9,400 per bike space, up to S$48/month for users, closed 28 Dec 2019 because take-up was low.

Assessment: 10 min presentation + 5 min Q&A. Rubric: Innovation, Relevance (IoT + cloud architecture, data flow, design rationale, reliability, scalability), Presentation, Feasibility (working prototype, measured results, costs, failure handling, deployment path), Business Viability (optional).

## 2. Naming

- **Lot** = one lock / one bike position on the rack.
- **Parking space** = a group of lots served by one ESP32.
- DynamoDB key `space1#lot3`; URL/QR `space1_lot3`; topics `space1/lot3/...`.

## 3. Team, repo and status

**Split:** user = web app (`webapp/`). Teammate = Terraform (`infra/`) + Lambdas (`lambdas/`). Simulator and firmware: TBD.

**Repo:** one private GitHub repo `smart-bike-parking`:
```
CLAUDE.md                        short rules for Claude Code (both sides)
docs/handoff.md                  this file
docs/agreed-names-and-formats.md tables, fields, topics, payloads, settings (DRAFT, teammate to review)
infra/                           Terraform
lambdas/handle_event/, lambdas/check_overstay/
webapp/                          NiceGUI app + webapp/CLAUDE.md
simulator/                       fake ESP32 script
firmware/                        ESP32 code (later)
certs/                           device certs (gitignored)
```
Building with **Claude Code** in the repo.

| Item | Status |
|---|---|
| Draft slide deck (Canva, 16 slides, [ADD]/[CHECK] placeholders) | Needs the new architecture and user flow |
| `smart-bicycle-parking.drawio` (user's copy) | Outdated. **Don't edit until asked.** Fix list in section 11 |
| Sequence page of the .drawio | Still the old NFC flow. Needs a full redraw |
| Repo files (CLAUDE.md, docs, .gitignore, skeleton) | Written 6 Nov |

## 4. Architecture

### Per lot
- **QR sticker:** `http://<laptop-ip>:8080/lot/space1_lot3`. Identifies the lot only.
- **IR obstacle sensor:** bike present (1 GPIO).
- **SW-420 vibration sensor:** tamper (1 GPIO).
- **3 V solenoid lock + relay:** relay switched by 1 GPIO.
- **No LEDs** (probably). **No microswitch** (decided).

### Lock wiring
- 3 V solenoid powered by **2× AA batteries** (not the ESP32).
- **Relay module** switched by an ESP32 GPIO; must trigger from **3.3 V**.
- Bolt **out when unpowered** (fail-secure). Confirm on the part.

### ESP32 (one per parking space)
- Connects **directly to AWS IoT Core**: MQTT over TLS, X.509 cert, Wi-Fi (phone hotspot for the demo). Deployment: 4G router or cellular module.
- **No access decisions.** Obeys "open lot N".
- **Edge filtering:** IR ~10 Hz debounced → `bike_arrived` / `bike_left`; SW-420 → `tamper` after e.g. 5 pulses in 3 s, then 60 s cooldown. Raw IR would be ~864,000 messages/day per lot vs ~4 per session.
- Subscribes to `space1/+/cmd`. On `open`: skip if expired (~30 s, needs NTP), pulse relay 1–2 s, publish `opened` **with the command's `requestId`**.
- **Last Will** on `space1/status` (KIV). **No offline buffer.**

### AWS cloud (Terraform)
- **IoT Core** Rule 1: `SELECT *, topic(1) AS space, topic(2) AS lot FROM '+/+/event'` → `handle_event`. Rule 2 (KIV) → `handle_offline`.
- **Lambdas (Python):**

| Lambda | Trigger | Does |
|---|---|---|
| `handle_event` | IoT Rule 1 | Updates `bikePresent`; `releasing` → `free` on `bike_left`; records `opened` confirmations; logs tamper + Telegram to the owner |
| `check_overstay` | EventBridge Scheduler, 1 min demo / 15 min deployment | Open sessions over the limit → Telegram to the owner once; sets `overstayNotifiedAt` (dashboard shows it) |
| `handle_offline` | IoT Rule 2 | **KIV.** Marks a space offline so the web app can warn before sending an unlock |

- **Telegram:** one bot, one-way, `sendMessage` only from Lambdas. No webhook.
- **No API Gateway.**
- **DynamoDB (5 tables, prefix `sbp-`):** locks, sessions (sparse `open-sessions` index), users, spaces (one summary item per space), tamper-events. Details in the agreed file.
- **IAM:** separate least-privilege IAM user for the web app (DynamoDB on these tables + `iot:Publish` on `space*/*/cmd` only).

### Telegram linking (at sign-up)
1. Web app shows "Connect Telegram" → `t.me/<BotName>?start=<one-time-code>` → cyclist taps Start.
2. Cyclist returns and taps "Done".
3. Web app calls `getUpdates`, finds the code, saves `telegramChatId`.

### Web app (NiceGUI, one app)
- Routes: `/` public, `/lot/{lot_ref}` cyclist, `/login`, `/signup`, `/connect-telegram`, `/officer`, `/dev` (fake mode only).
- Reads/writes DynamoDB and publishes `open` with boto3. Laptop: AWS profile `sbp-webapp`; EC2: IAM role.
- **Login:** username + bcrypt hash, kept in `app.storage.user` (cookie signed with `storage_secret`), so repeat QR scans stay logged in.
- **Fake/real backend switch** (`BACKEND=fake|aws`): all AWS calls in `webapp/backend/`, so pages can be built before AWS exists.
- **Confirmation:** after publishing `open`, polls the locks table for its `requestId` (up to ~8 s).
- Refresh: `ui.timer` + `@ui.refreshable`.
- **Hosting:** demo on the laptop (`host=0.0.0.0`, port 8080); phone on the same hotspot. EC2 shown as deployment target.

## 5. Data flows

- **Sensor event:** sensor → ESP32 (state change) → MQTT/TLS `space1/lot3/event` → IoT Core → Rule 1 → `handle_event` → DynamoDB (+ Telegram if tamper)
- **Open command:** phone → web app → DynamoDB → IoT Core publish `space1/lot3/cmd` → ESP32 relay → `opened` event → `handle_event` writes confirmation → web app sees it
- **Overstay:** EventBridge → `check_overstay` → open sessions → Telegram + `overstayNotifiedAt`
- **Telegram linking:** cyclist → bot (`/start code`) → web app `getUpdates` → users table
- **Public/officer pages:** browser → web app → boto3 → DynamoDB
- **Space offline (KIV):** ESP32 drops → Last Will → Rule 2 → `handle_offline`

## 6. User flow

### First time only
Scan any QR → sign up → Connect Telegram.

### Lock mechanism: KIV
- **Option 1:** cable free when vacant. Downsides: tangled/cut/taken; with a slanted bolt anyone can lock without scanning.
- **Option 2 (groupmate):** cable stored locked; open to free it, open again to slot back (needed only with a **straight** bolt).
- **HelloRide style (user's preference):** cable stored locked; **one open**; push back in and it clicks shut. Needs a **slanted bolt**.
- Next step: check the bolt shape.

### Flow (HelloRide style + slanted bolt)
**Vacant:** cable clicked in, lot `free`.

**Lock:** park (IR → `bike_arrived`) → scan QR → log in if needed → "Use this lot" → web app claims the lot (`taken`), opens a session, publishes `open` → relay pulses → `opened` confirmed → cyclist wraps cable and clicks it in. No confirmation → claim undone, "try again".

**Unlock:** scan QR → page sees the owner → "Unlock" → `open` → confirmed → status `releasing`, session closed → cyclist takes bike, clicks cable back → IR `bike_left` → `handle_event` sets `free`.

**Someone else scans a taken lot:** "Lot in use". No command.

**Without the cyclist:** tamper → Telegram to owner + officer log; overstay → Telegram reminder + dashboard.

## 7. Failure handling

| Situation | Handling |
|---|---|
| ESP32 Wi-Fi down | No `opened` → "couldn't reach the lock" → claim undone / nothing changed → officer manual release. Events not buffered |
| Late command after reconnect | ESP32 ignores expired `open` |
| Two users tap "Use this lot" at once | Conditional write: only the first succeeds |
| Lost phone / forgot password | Officer verifies in person → Force unlock |
| Telegram not connected | No alerts; still visible on officer dashboard |
| Cable not clicked back in | Harmless; undetectable (no microswitch) |
| Batteries flat | Fail-secure lock stays shut; staff release |
| Bike leaves without an unlock | Open item: log as possible theft |
| Lambda repeatedly fails | Optional SQS dead-letter queue |

## 8. Design decisions and reasons

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Controller | ESP32 only | Raspberry Pi gateway | Cheaper, low power, Wi-Fi built in. Trade-off: no offline buffer, limited GPIO |
| Cyclist interface | Own web app + simple login | Telegram bot buttons; NFC cards | One app for cyclists, public, officers |
| Web framework | NiceGUI | Streamlit; FastAPI + React template; FastAPI + hand-written HTML | Python only; persistent login via cookie built in; page-per-route suits the QR flow; Streamlit forgets sessions per tab; React template is overkill and assumes PostgreSQL |
| IaC | Terraform | CloudFormation/SAM; console clicks | Teammate's suggestion, transferable skill, generates the IoT cert; one-command rebuild and teardown |
| Repo | One repo | Separate repos | Shared names change together; small team |
| Login | Username + bcrypt | Google OIDC; PIN per lock | Simplest for a PoC. Production: Singpass/Google |
| Cyclist alerts | Telegram, one-way | Web push; SMS | A web page can't alert a closed phone; free and instant |
| Telegram linking | One-time code + `getUpdates` | Webhook Lambda | No inbound endpoint |
| Officer view | Officer-only dashboard | Telegram group | Many lots; tamper log, overstays, Force unlock |
| Lock | 3 V solenoid + relay + AA | SG90 servo; 12 V solenoid | Real lock action; 12 V fail-secure for deployment |
| Microswitch | Not used | Latch switch | Simpler; IR confirms bike |
| Filtering | Edge (state changes only) | Raw readings | Saves data, messages, Lambda calls, DB writes |
| API layer | None | API Gateway | Web app uses boto3 server-side |
| Unlock confirmation | `handle_event` writes `opened` to locks table; web app polls | Web app subscribes to MQTT | boto3 can only publish; no extra connection needed |
| Free-lot count | Atomic counter updated at the two status changes | Recount on every read | One read per space for the public page; scales |
| Alerts sent from | The detecting Lambda | DynamoDB Streams | Fewer parts |
| Dashboard updates | Polling | WebSockets | Far fewer parts |
| Database | DynamoDB | RDS; Aurora Serverless v2 | Key lookups, nothing billed idle; no cold-start delay |
| Overstay trigger | EventBridge Scheduler | On-device; DynamoDB TTL | Abandoned bikes send no events; TTL can be hours late |
| Camera | None | ESP32-CAM | Exact timestamp; authorities use existing CCTV |

## 9. Comparison with HelloRide / Anywheel

- Same pattern: scan QR → server checks user → server opens lock; user closes it by hand.
- Since Jan 2019 LTA requires shared-bike users to scan a QR at a designated spot to end a trip. Our lots know a bike is present via IR.
- Differences: our QR identifies the lot, not the bike; lock on the rack; they have SIM + Bluetooth backup, we have staff Force unlock.

## 10. Hardware and cost

Have: MakePython ESP32, Raspberry Pi + touch screen (unused), phone hotspot, laptop, breadboard, jumper wires.
Per real lot: IR sensor, SW-420, 3 V solenoid, 3.3 V-triggerable relay, flyback diode, 2× AA holder, printed QR. **Prices TBC.**
Still needed: cost per lot / space / bike space vs S$9,400; monthly AWS estimate.

## 11. Diagram fix list (only when asked)

- Gateway box → "ESP32: reads sensors, edge filtering, opens locks on command".
- Lot unit → QR sticker, IR, SW-420, 3 V solenoid + relay (AA).
- MQTT arrow → "MQTT over TLS (Wi-Fi; 4G router in deployment)", events ↑ / commands ↓.
- Cyclist → lot "Scans QR" → Cyclist ↔ Web app (NiceGUI) "scan QR, log in, Use / Unlock".
- **Add Web app → IoT Core "open command"** (biggest gap; also Force unlock).
- Merge the two EC2 boxes into one NiceGUI web app (cyclist + public + officer); arrows to Cyclist and Officer. Label "laptop for demo, EC2 in deployment".
- Web app ↔ DynamoDB "read/write".
- Telegram → Cyclist "tamper, overstay alerts". No Telegram → Officer.
- Events Lambda → Telegram "tamper alert"; add overstay Lambda → Telegram.
- Optional: Cyclist → Telegram "connect once"; Web app → Telegram "getUpdates".
- Rule 2 + `handle_offline`: leave out unless decided.
- EventBridge "daily cron job" → "every 15 min".
- DynamoDB box → locks, sessions, users, spaces, tamper-events.
- Optional: small "Terraform" note on the AWS box.
- Delete the blue "AI say..." note.
- Optional: colour-coded flows with a legend.
- Sequence page: redraw from section 6.

## 12. Q&A answers prepared

- **Why not just scan to unlock?** The QR is public; login proves it's your bike.
- **Why a web app?** Nothing to install; one app for cyclists, public and officers.
- **Why Telegram for alerts?** A web page can't alert a closed phone; Telegram is free and instant.
- **Is the solenoid a real lock?** Demo part; deployment uses a 12 V fail-secure solenoid.
- **What if the internet is down?** No confirmation → nothing changes, cyclist told to contact staff; officer Force unlock / manual release.
- **What if power fails?** Fail-secure lock stays shut; staff release.
- **Can a thief cut the cable / shake the lock?** SW-420 → tamper alert with exact time for CCTV; logged for officers.
- **Doesn't the sensor flood the cloud?** Edge filtering: only state changes.
- **Where's your API layer?** None needed: web app talks to AWS server-side; Lambdas are triggered by IoT Rules and EventBridge.
- **How do you know the lock actually opened?** The ESP32 replies with the command's ID; the web app waits for it and undoes the booking if it never comes.
- **What if two people grab the same lot?** Conditional database write; only one wins.
- **How does it scale?** Serverless pieces scale with lots; one summary item per space; a new space is a Terraform change.
- **How would you deploy it?** Terraform rebuilds the whole backend in minutes; web app moves to EC2.
- **vs SecureMyBike / shared bikes?** Free, nothing to carry, far cheaper per bike space, also handles abandoned bikes and availability.

## 13. Still to do

1. Teammate reviews `agreed-names-and-formats.md` and settles its open items.
2. **Lock mechanism (KIV):** check bolt shape.
3. **`handle_offline` (KIV):** build or leave out.
4. Overstay threshold for deployment (e.g. 3 days).
5. Create the Telegram bot; share the token privately.
6. Set an AWS budget alert (e.g. US$5).
7. Fix the draw.io and redraw the sequence page (when asked).
8. Measured results: scan-to-open, tamper-to-alert, event-to-dashboard times, detection accuracy, false alarms, SW-420 thresholds.
9. Costs (section 10).
10. Singapore bicycle theft statistics.
11. Canva updates: architecture, user flow, comparison column, [CHECK] items.
12. Backup demo video.

## 14. Concepts already explained to the user (don't re-explain unless asked)

Lambda invoked by IoT Rules, not subscribed; edge filtering; why no API Gateway; why no DynamoDB Streams; dashboard polling; authentication vs authorization; why the QR alone can't unlock; Network URL vs localhost; why a bot can only message users who messaged first; `handle_offline`; solenoid needs relay/MOSFET, separate supply, flyback diode, common ground; relay vs MOSFET; slanted vs straight bolt; HelloRide comparison; what IaC is for; Terraform vs CloudFormation vs SAM; one repo vs many; Streamlit vs NiceGUI vs FastAPI templates; why a separate CLAUDE.md for the web app; fake/real backend switch.

## 15. Working style

The user wants to **align before Claude acts**: summarise decisions and confirm before writing files or editing diagrams. Keep answers concise and plain. Don't agree blindly; give an honest recommendation.
