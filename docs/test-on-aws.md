# Run in Docker and test on your own AWS account

Top to bottom: run the web app in Docker, deploy the AWS side with Terraform, load the starting data, then test the database **and the Lambda logic without any hardware** by publishing fake ESP32 events from your laptop.

Everything runs through Docker: you don't install Python packages, Terraform or the AWS CLI. You need **Docker** (Docker Desktop must be running) and a **personal AWS account** (AWS Academy / Learner Lab accounts block the IAM users and roles this creates).

Details on what Terraform creates, settings and cost: [`infra/README.md`](../infra/README.md). Lot states and events: [`agreed-names-and-formats.md`](agreed-names-and-formats.md) section 3.

---

## 1. Run the web app locally (fake mode, no AWS)

From the repo root:
```bash
mkdir -p ~/.aws              # once; the container mounts it (read-only)
docker compose up --build
```
Open http://localhost:8000 (phone on the same Wi-Fi: `http://<laptop-ip>:8000`; find the IP with `hostname -I`). Demo accounts: `officer` / `officer1`, `alice` / `alice123`. The demo helper `/dev` has buttons that act as the ESP32 (bike arrived / left, tamper, lock opened / closed).

Stop with `Ctrl+C`. After changing code, run `docker compose up --build` again.

## 2. Terraform and the AWS CLI through Docker

The repo has two small wrappers, `bin/aws` and `bin/terraform`, that run the official Docker images. Put them on your PATH **once per terminal**, from the repo root:
```bash
export PATH="$PWD/bin:$PATH"
aws --version          # first run downloads the image
terraform -version
```
They use your `~/.aws` profiles and write files (state, certificates) into the repo as you, all gitignored.

## 3. Give Terraform access to your AWS account

1. AWS console, region **Asia Pacific (Singapore)** at the top right.
2. **IAM → Users → Create user** `sbp-admin`, no console access, **Attach policies directly → AdministratorAccess**.
3. Open the user → **Security credentials → Create access key → Command Line Interface (CLI)**. The secret is shown once.
4. Save it as a profile (type it in; never paste keys into chat or into the repo):
   ```bash
   aws configure --profile sbp-admin
   # Access Key ID, Secret, region: ap-southeast-1, output: json
   aws sts get-caller-identity --profile sbp-admin      # should print ...:user/sbp-admin
   ```

## 4. Deploy

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```
In `terraform.tfvars`, set `budget_email` to your email (cost alerts). Leave `telegram_bot_token` empty for now.
```bash
terraform init
terraform validate
terraform plan -out=tfplan      # read it: a fresh account shows "31 to add, 0 to change, 0 to destroy"
terraform apply tfplan          # about 1 minute
terraform output                # endpoint, table names, Cognito IDs
```
This creates the 5 DynamoDB tables, Cognito, IoT Core (thing, certificate in `certs/space1/`, rule), both Lambdas, the every-minute overstay schedule, the limited `sbp-webapp` IAM user and a US$5 budget alert. All pay-per-use: idle cost is about US$0.

## 5. Settings for the web app (AWS mode)

Still in `infra/`. Save the web app's limited key as the `sbp-webapp` profile:
```bash
aws configure set aws_access_key_id     "$(terraform output -raw webapp_access_key_id)"     --profile sbp-webapp
aws configure set aws_secret_access_key "$(terraform output -raw webapp_secret_access_key)" --profile sbp-webapp
aws configure set region ap-southeast-1 --profile sbp-webapp
aws dynamodb scan --table-name sbp-lots --select COUNT --profile sbp-webapp   # works (a new key can take ~10 s)
```
Edit `webapp/.env` (create it from `webapp/.env.example` if missing). Where the value is a command, **run it (in `infra/`) and paste what it prints**, not the command itself:
| Setting | Value |
|---|---|
| `BACKEND` | `aws` |
| `SESSION_SECRET` | output of `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `AWS_PROFILE` | `sbp-webapp` |
| `AWS_REGION` | `ap-southeast-1` |
| `IOT_DATA_ENDPOINT` | `terraform output -raw iot_data_endpoint` |
| `TABLE_PREFIX` | `sbp-` |
| `COGNITO_USER_POOL_ID` | `terraform output -raw cognito_user_pool_id` |
| `COGNITO_CLIENT_ID` | `terraform output -raw cognito_client_id` |

## 6. Load the starting data

From the repo root:
```bash
docker compose build
docker compose run --rm webapp python load_starting_data.py
```
It creates `space1` (Upper Changi, real lot `space1#lot1`), 3 simulated stations with 20 lots each, their parked demo bikes, and the officer account. It asks for the officer's email and password (at least 8 characters). Safe to re-run: it never overwrites.

## 7. Check the database

```bash
docker compose up
```
- Open http://localhost:8000: the map shows the 4 stations from DynamoDB.
- **Sign up** a cyclist (this creates a Cognito user and an `sbp-users` row). Skip Connect Telegram for now.
- Log in as `officer` at http://localhost:8000/officer.
- AWS console → **DynamoDB → Explore items** → pick a table (`sbp-lots`, `sbp-users`, `sbp-sessions`, `sbp-tamper-events`). Rows change as you use the app.

## 8. Test the Lambdas without hardware

Your laptop plays the ESP32: it publishes the same MQTT events to IoT Core, the IoT Rule runs `handle_event`, and the web app shows the result. The web app's `open` commands go to `space1/lot1/cmd` with no device listening; that's fine.

In a second terminal, **from the repo root** (these lines only last for this terminal; redo them in a new one):
```bash
cd ~/smart-bike-parking          # repo root (adjust if yours is elsewhere)
export PATH="$PWD/bin:$PATH"
EP=$(cd infra && terraform output -raw iot_data_endpoint); echo "$EP"   # must print xxxx-ats.iot.ap-southeast-1.amazonaws.com
pub() { aws iot-data publish --topic space1/lot1/event --cli-binary-format raw-in-base64-out \
          --payload "{\"type\":\"$1\"}" --endpoint-url "https://$EP" --profile sbp-admin; }
logs() { aws logs tail /aws/lambda/sbp-handle-event --since 5m --profile sbp-admin; }
```
A successful `pub` prints **nothing**; any output is an error and the event was not sent. Quick check: `pub bike_arrived; sleep 4; logs` should end with a line containing `"action": "bike_present"`.

Open the lot page http://localhost:8000/lot/space1_lot1 logged in as your cyclist. After each `pub`, wait ~2 s and reload (or watch it refresh). `logs` shows one JSON line per event, and DynamoDB → `sbp-lots` shows the row.

**A. Park and lock**
| You do | Lot | Lock | Page shows |
|---|---|---|---|
| `pub bike_arrived` | free | closed | "This lot is free" |
| tap **Use this lot** | taken | closed | "Lock released…" |
| `pub lock_opened` | taken | open | (reload) "Lock open: push it in" |
| `pub lock_closed` | taken | closed | "Your bike is parked and locked" |

**B. Unlock, take the bike first, then push the lock back in**
| You do | Lot | Lock | Page shows |
|---|---|---|---|
| tap **Unlock** | releasing | closed | "Unlocked…" (refreshes every 5 s) |
| `pub lock_opened` | releasing | open | same |
| `pub bike_left` | awaiting_lock | open | "Lock still open: please push the metal piece back in" |
| open a free lot at another station (map → station → free lot) | | | "Close the lock at Upper Changi MRT Exit C, lot 1 first" |
| `pub lock_closed` | free | closed | "Lock closed. Thanks!" |

Variant: `pub lock_closed` **before** `pub bike_left` → lot goes straight to `free`.

**C. Tamper.** Do A again, then `pub tamper` → a row in `sbp-tamper-events` with the session; the officer console tamper log shows it. A second `pub tamper` within 60 s is dropped (`tamper_repeat_dropped` in `logs`).

**D. Bike gone without an unlock (suspected theft).** With the lot taken (A), `pub bike_left` → a tamper row; the lot page shows "Bike not detected". Tap **Unlock** → "Your bike was no longer detected at this lot", lot `free`.

**E. Overstay and reminders** (`check_overstay`, every minute; demo limits). Park (A) and wait 2+ minutes → the session gets `overstay_notified_at` and the officer console counts it as abandoned. Leave the lock open after a claim for 1+ minute → the lot gets `lock_reminded_at`. Logs: `aws logs tail /aws/lambda/sbp-check-overstay --since 5m --profile sbp-admin`.

Optional, Lambda unit tests (no AWS):
```bash
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD/lambdas:/w" -w /w python:3.12-slim-bookworm \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest tests -q -p no:cacheprovider"   # 42 passed
```

## Demo day: fresh data with one command

Testing leaves rows behind, and the simulated bikes' parking times are fixed when they're loaded, so they age every day. Right before the demo, from the repo root:
```bash
bash webapp/run.sh --reset
```
Type `yes`. It empties `sbp-spaces`, `sbp-lots`, `sbp-sessions` and `sbp-tamper-events`, reloads the stations and simulated bikes with times starting from now, then starts the web app as usual. **Kept:** all logins (Cognito + `sbp-users`: officer, cyclists, Telegram links). **Untouched:** everything else in AWS (IoT, certificate, Lambdas, schedule, keys). Anything other than `yes` cancels and deletes nothing. Plain `bash webapp/run.sh` never deletes anything.

Set `overstay_limit_minutes` in `infra/terraform.tfvars` (and `terraform apply`) **before** resetting: with the demo value `2`, every simulated bike is flagged abandoned within a minute. `43200` (30 days) flags only the oldest few.

## 9. Telegram alerts

(Added in the next step.)

## 10. Tear down

```bash
cd infra
terraform destroy
```
Deletes everything, **including all table data and Cognito users**. The next `apply` makes a new device certificate and a new web app key (redo step 5). Only destroy when you're finished. The state file `infra/terraform.tfstate` is local and gitignored: don't delete it while things are deployed, or Terraform loses track of them.

## Troubleshooting
| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` / `docker.sock: no such file` | Start Docker Desktop |
| `aws: command not found` | `export PATH="$PWD/bin:$PATH"` from the repo root (once per terminal) |
| `The config profile (sbp-webapp) could not be found` | Do step 5 (the web app runs as `sbp-webapp`) |
| `SESSION_SECRET must be set` | Set it in `webapp/.env` (step 5) |
| `InvalidClientTokenId` | Access key deleted or mistyped: make a new one (step 3) |
| Web app can't read `~/.aws` (permission denied) | The container user is uid 1000; check `id -u`. If yours differs, tell the team |
