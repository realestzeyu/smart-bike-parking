# Cognito user pool: holds usernames, passwords and the email used for password resets.
# Profile, role and telegram_chat_id stay in sbp-users.
# The web app keeps its own login/sign-up/forgot-password pages and calls Cognito server-side
# with boto3 (sign_up, initiate_auth USER_PASSWORD_AUTH, forgot_password). No hosted UI: its callback must be HTTPS except
# on localhost, and phones reach the demo laptop over plain http://<laptop-ip>:8000.

resource "aws_cognito_user_pool" "users" {
  name           = "${local.prefix}-users"
  user_pool_tier = "LITE" # free for the first 10,000 monthly active users

  # Username = sbp-users.id (lowercase login name); case-insensitive.
  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = 8
    require_lowercase                = false
    require_uppercase                = false
    require_numbers                  = false
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # Self sign-up allowed, one step: no verification email. The web app confirms the user
  # (AdminConfirmSignUp) and marks the email as verified (AdminUpdateUserAttributes) itself.
  # auto_verified_attributes is left empty on purpose, so sign_up sends no code.
  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  # Forgotten passwords (cyclists and officers): self-service reset code to the verified email
  # (forgot_password / confirm_forgot_password). An officer can still reset anyone with
  # AdminSetUserPassword as a fallback.
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Cognito's built-in sender: free, ~50 emails/day (plenty for a demo). Sender is
  # no-reply@verificationemail.com, so check spam.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Smart Bike Parking: your code"
    email_message        = "Your Smart Bike Parking code is {####}. It expires in 1 hour."
  }

  mfa_configuration   = "OFF"
  deletion_protection = "INACTIVE" # PoC: allow terraform destroy
}

# Public app client (no secret) used by the web app server.
resource "aws_cognito_user_pool_client" "webapp" {
  name         = "${local.prefix}-webapp"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret               = false
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED" # same error for "no such user" and "wrong password"
}
