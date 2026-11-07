variable "region" {
  description = "AWS region for everything."
  type        = string
  default     = "ap-southeast-1"
}

variable "aws_profile" {
  description = "AWS CLI profile Terraform deploys with (an admin profile, NOT sbp-webapp)."
  type        = string
  default     = "sbp-admin"
}

variable "spaces" {
  description = "Parking space IDs. Each gets one IoT thing (= one ESP32), certificate and policy."
  type        = set(string)
  default     = ["space1"]
}

variable "telegram_bot_token" {
  description = "Telegram bot token for the Lambdas. Leave empty until the bot exists (alerts are then skipped)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "overstay_limit_minutes" {
  description = "Session age that triggers an overstay alert. Demo: 2. Deployment: e.g. 4320 (3 days)."
  type        = number
  default     = 2
}

variable "overstay_check_schedule" {
  description = "How often check_overstay runs. Demo: rate(1 minute). Deployment: rate(15 minutes)."
  type        = string
  default     = "rate(1 minute)"
}

variable "budget_email" {
  description = "Email for the monthly AWS budget alert."
  type        = string
}

variable "budget_limit_usd" {
  description = "Monthly budget alert threshold in USD."
  type        = string
  default     = "5"
}
