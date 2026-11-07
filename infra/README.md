# infra: AWS backend (Terraform)

This folder builds the whole AWS side of Smart Bicycle Parking with one command: DynamoDB tables, IoT Core (device certificate, policy, rule), the two Lambdas, the overstay schedule, a limited IAM user for the web app, and a cost alert. Everything is in `ap-southeast-1` (Singapore).

You can deploy your own copy into any AWS account by following this guide from top to bottom. It takes about 15 minutes the first time.

Tables, fields, topics and payloads are defined in [`../docs/agreed-names-and-formats.md`](../docs/agreed-names-and-formats.md) (includes the schema diagram). Change that file first if you need a schema change.

---

## What gets created

| File | Creates |
|---|---|
| `dynamodb.tf` | 5 on-demand tables: `sbp-spaces`, `sbp-lots`, `sbp-users`, `sbp-sessions` (+ `by-lot` index for usage history), `sbp-tamper-events` |
| `iot.tf` | For each parking space: an IoT thing (`space1`), its certificate (saved to `../certs/space1/`) and device policy. Plus a rule that sends every `<space>/<lot>/event` message to `handle_event` |
| `lambdas.tf` | `sbp-handle-event` and `sbp-check-overstay` (Python 3.13), zipped from `../lambdas/`, each with its own least-privilege role and 7-day logs |
| `scheduler.tf` | EventBridge Scheduler that runs `check_overstay` (every minute for the demo; can be switched off) |
| `webapp_iam.tf` | IAM user `sbp-webapp`: DynamoDB on the 5 tables + `iot:Publish` on `space*/*/cmd` only |
| `budget.tf` | Monthly budget `sbp-monthly`: emails you at 80% of US$5 spent, or if the month is forecast to go over |
| `outputs.tf` | Values you need afterwards (IoT endpoint, table names, web app key) |
| `variables.tf` | Settings you can change (see [Settings](#settings)) |

No API Gateway, no EC2, no database server: nothing that bills by the hour. The web app runs on a laptop for the demo.

---

## 1. Install the tools

You need **Terraform ≥ 1.5** and the **AWS CLI v2**.

**Windows (PowerShell)**
```powershell
winget install Hashicorp.Terraform
winget install Amazon.AWSCLI
```
Reopen your terminal / VS Code afterwards.

**Linux or WSL (bash)**
```bash
# Terraform (HashiCorp apt repo)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform

# AWS CLI v2 (Ubuntu's own "awscli" package no longer exists). Run from your home folder, not the repo.
cd ~
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && rm -rf awscliv2.zip aws
```

Check: `terraform -version` and `aws --version`.

> Use **one** environment for Terraform (e.g. only WSL, or only PowerShell). Plan files can't move between Terraform versions, and both would share the same state file.

---

## 2. Give Terraform access to your AWS account

Terraform needs an AWS key with admin rights (it creates IAM roles and users). Don't use your root account's keys.

1. Sign in to the [AWS console](https://console.aws.amazon.com/). Choose **Asia Pacific (Singapore)** at the top right.
2. **IAM → Users → Create user**. Name: `sbp-admin`. Leave console access unticked.
3. **Attach policies directly** → tick **AdministratorAccess** → create.
4. Open the user → **Security credentials** → **Create access key** → **Command Line Interface (CLI)** → create. The secret is shown only once.
5. Save it as a profile on your machine (type the values in; never paste keys into chat or files in the repo):
   ```
   aws configure --profile sbp-admin
   ```
   | Prompt | Enter |
   |---|---|
   | Access Key ID | `AKIA...` from step 4 |
   | Secret Access Key | the secret from step 4 |
   | Default region name | `ap-southeast-1` (the code, **not** "Asia Pacific (Singapore)") |
   | Default output format | `json` |
6. Check: `aws sts get-caller-identity --profile sbp-admin` should print `...:user/sbp-admin`.

> **AWS Academy / Learner Lab accounts won't work as-is**: they block creating IAM users and roles, and their keys expire every few hours. Use a personal AWS account.

**WSL users with the key saved on Windows:** point WSL at the Windows files instead of configuring twice:
```bash
echo 'export AWS_CONFIG_FILE="/mnt/c/Users/<WindowsUser>/.aws/config"' >> ~/.bashrc
echo 'export AWS_SHARED_CREDENTIALS_FILE="/mnt/c/Users/<WindowsUser>/.aws/credentials"' >> ~/.bashrc
source ~/.bashrc
```
(The CLI will warn the file "is accessible by other users". That's how WSL shows Windows files; it's still protected by your Windows account.)

---

## 3. Fill in your settings

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```
Edit `terraform.tfvars`:
```hcl
aws_profile        = "sbp-admin"
budget_email       = "you@example.com"   # gets the cost alerts
telegram_bot_token = ""                  # leave empty until the bot exists
overstay_check_enabled = true            # set false to pause the overstay check
```
`terraform.tfvars` is gitignored. Never commit it.

---

## 4. Deploy

```bash
terraform init                # first time only: downloads providers
terraform validate            # checks the code
terraform plan -out=tfplan    # shows what will be created; changes nothing
terraform apply tfplan        # creates it (about 1 minute)
```
A fresh account should show **`Plan: 29 to add, 0 to change, 0 to destroy`**.

Afterwards, `terraform output` prints the IoT endpoint, table names and Lambda names.

---

## 5. Check it works

**a) Tables, Lambdas, schedule exist**
```bash
P="--profile sbp-admin"
aws dynamodb list-tables $P --query "TableNames[?starts_with(@,'sbp-')]"
aws lambda list-functions $P --query "Functions[?starts_with(FunctionName,'sbp-')].FunctionName"
aws scheduler get-schedule --name sbp-check-overstay $P --query State
ls ../certs/space1/        # certificate.pem.crt, private.pem.key
```
Expect the 5 `sbp-` tables, both Lambdas, `ENABLED`.

**b) A device event reaches `handle_event`**
```bash
EP=$(terraform output -raw iot_data_endpoint)
aws iot-data publish --topic space1/lot1/event --cli-binary-format raw-in-base64-out \
  --payload '{"type":"bike_arrived"}' --endpoint-url "https://$EP" $P
sleep 8
aws logs tail /aws/lambda/sbp-handle-event --since 5m $P
```
Expect a log line `{"type": "bike_arrived", "space": "space1", "lot": "lot1"}`.
(Or use the console: **IoT Core → MQTT test client → Publish**.)

**c) The overstay check runs every minute**
```bash
aws logs tail /aws/lambda/sbp-check-overstay --since 5m $P
```
Expect `check_overstay ran, limit=2 min` once a minute.

**d) The web app key is limited correctly**
```bash
aws configure set aws_access_key_id     "$(terraform output -raw webapp_access_key_id)"     --profile sbp-webapp
aws configure set aws_secret_access_key "$(terraform output -raw webapp_secret_access_key)" --profile sbp-webapp
aws configure set region ap-southeast-1 --profile sbp-webapp

# Allowed (no output = success):
aws iot-data publish --topic space1/lot1/cmd --cli-binary-format raw-in-base64-out \
  --payload '{"action":"open","requestId":"test","expires":0}' --endpoint-url "https://$EP" --profile sbp-webapp
# Denied (expect ForbiddenException):
aws iot-data publish --topic space1/lot1/event --cli-binary-format raw-in-base64-out \
  --payload '{"type":"tamper"}' --endpoint-url "https://$EP" --profile sbp-webapp
# Allowed: read a table
aws dynamodb scan --table-name sbp-lots --select COUNT --profile sbp-webapp
```
A brand-new key can take ~10 s to start working.

---

## 6. Hand values to the other parts

**Web app** (`webapp/.env`, with `BACKEND=aws`):
| `.env` | From |
|---|---|
| `AWS_PROFILE` | `sbp-webapp` (configured as in 5d) |
| `AWS_REGION` | `ap-southeast-1` |
| `IOT_DATA_ENDPOINT` | `terraform output -raw iot_data_endpoint` |
| `TABLE_PREFIX` | `sbp-` |

Send the web app key (`terraform output -raw webapp_access_key_id` / `webapp_secret_access_key`) to whoever runs the web app **privately**, never in git or a group chat.

**ESP32 / simulator:**
- MQTT host: the same `iot_data_endpoint`, port **8883**
- Client ID: `space1` (must match, or the connection is refused)
- Certificate and key: `../certs/space1/certificate.pem.crt`, `../certs/space1/private.pem.key`
- Root CA: download [`AmazonRootCA1.pem`](https://www.amazontrust.com/repository/AmazonRootCA1.pem) into the same folder
- Publish to `space1/<lot>/event`, subscribe to `space1/+/cmd`

---

## Day-to-day changes

| I want to... | Do this |
|---|---|
| Change Lambda code | Edit `../lambdas/<name>/handler.py`, then `terraform plan -out=tfplan && terraform apply tfplan` (it re-zips automatically) |
| Add a parking space | Add it to `spaces` in `terraform.tfvars`, e.g. `["space1", "space2"]`, then plan + apply. New cert appears in `../certs/space2/` |
| Add the Telegram bot | Put the token in `telegram_bot_token`, then plan + apply |
| Pause the overstay check | `overstay_check_enabled = false`, plan + apply |
| Switch to deployment timings | `overstay_limit_minutes = 4320` (3 days), `overstay_check_schedule = "rate(15 minutes)"` |
| View / edit data by hand | Console → **DynamoDB → Explore items** → pick a table |
| See Lambda logs | `aws logs tail /aws/lambda/sbp-handle-event --follow --profile sbp-admin` |

Always read the plan before applying. Anything marked **destroy** or **must be replaced** on a table deletes its data.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `aws_profile` | `sbp-admin` | AWS CLI profile Terraform deploys with |
| `region` | `ap-southeast-1` | AWS region |
| `spaces` | `["space1"]` | One IoT thing + cert per parking space (= per ESP32) |
| `budget_email` | (required) | Gets the budget alerts |
| `budget_limit_usd` | `5` | Monthly budget |
| `telegram_bot_token` | `""` | Lambdas skip alerts while empty |
| `overstay_check_enabled` | `true` | Turns the overstay schedule on/off |
| `overstay_limit_minutes` | `2` | Session age that counts as overstay / suspected abandoned |
| `overstay_check_schedule` | `rate(1 minute)` | How often `check_overstay` runs |

---

## Cost

Expected: **close to US$0/month** for the prototype, idle or in use. Everything is billed per use: DynamoDB on-demand (storage free up to 25 GB, fractions of a cent per thousand requests), Lambda and EventBridge Scheduler (inside the permanent free allowances even with a check every minute), IoT Core (cents), CloudWatch Logs (free up to 5 GB). IAM and the budget are free. The budget email is the safety net.

What *could* cost money: firmware sending raw sensor readings instead of state changes (~US$25–30/month per lot in IoT messages), or hosting the web app on EC2 (~US$10–15/month).

## Tear down

```bash
terraform destroy
```
Removes everything, **including all table data**. The next `apply` creates a **new device certificate** (re-flash the ESP32) and a **new web app key** (redo step 5d, re-share it). Only destroy when you are finished.

## Never commit

All gitignored already: `terraform.tfstate*` (contains the device private key and web app secret), `terraform.tfvars`, `tfplan`, `build/`, `../certs/`. **Do** commit `.terraform.lock.hcl` (pins provider versions).

The state file is local, so only the person who ran `apply` can change this deployment. Back it up somewhere private; losing it means Terraform no longer knows what it created.

---

## Troubleshooting

| Error | Cause / fix |
|---|---|
| `Provided region_name 'Asia Pacific (Singapore)' doesn't match a supported format` | Region set to the display name. Fix: `aws configure set region ap-southeast-1 --profile sbp-admin` |
| `InvalidClientTokenId` / `security token included in the request is invalid` | The access key was deleted or mistyped. Create a new one (step 2) |
| `plan file was created by Terraform X, but this is Y` | Plan made by a different Terraform install (e.g. PowerShell vs WSL). Run `terraform plan -out=tfplan` again in the same shell you apply from |
| `Command 'aws' not found` (WSL) | Install AWS CLI v2 with the official installer (step 1), not apt |
| `ForbiddenException` on `iot-data publish` | The key isn't allowed on that topic. Expected for `sbp-webapp` on `.../event`; otherwise check the topic spelling |
| `EntityAlreadyExists` / `ResourceConflictException` on apply | Resources with the same names already exist in this account (e.g. someone else deployed here). Use a separate account, or destroy the other copy |
| Budget alert email never arrives | Normal until spending reaches 80% of the limit |
