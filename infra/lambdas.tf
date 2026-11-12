# The two Python Lambdas. Code is zipped from ../lambdas/<name>/ (entry point handler.lambda_handler).

locals {
  lambdas = {
    handle_event = {
      timeout = 10
      env     = {}
      # Updates the lot (status, bike_present), logs tamper/theft, reads the owner's telegram_chat_id.
      statements = [
        {
          actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
          resources = [aws_dynamodb_table.lots.arn]
        },
        {
          actions   = ["dynamodb:PutItem"]
          resources = [aws_dynamodb_table.tamper_events.arn]
        },
        {
          actions   = ["dynamodb:GetItem"]
          resources = [aws_dynamodb_table.users.arn, aws_dynamodb_table.spaces.arn] # alert: chat id + address
        },
      ]
    }
    check_overstay = {
      timeout = 30
      env     = { OVERSTAY_LIMIT_MINUTES = tostring(var.overstay_limit_minutes) }
      # Queries the open-sessions index, sets overstay_notified_at, reads the owner's telegram_chat_id.
      statements = [
        {
          actions   = ["dynamodb:Query"]
          resources = ["${aws_dynamodb_table.sessions.arn}/index/open-sessions"]
        },
        {
          actions   = ["dynamodb:UpdateItem"]
          resources = [aws_dynamodb_table.sessions.arn]
        },
        {
          actions   = ["dynamodb:GetItem"]
          resources = [aws_dynamodb_table.users.arn, aws_dynamodb_table.spaces.arn] # alert: chat id + address
        },
      ]
    }
  }
}

# Each zip = that Lambda's handler.py + the shared helper (lambdas/shared/sbp_common.py).
data "archive_file" "fn" {
  for_each    = local.lambdas
  type        = "zip"
  output_path = "${path.module}/build/${each.key}.zip"

  source {
    filename = "handler.py"
    content  = file("${path.module}/../lambdas/${each.key}/handler.py")
  }
  source {
    filename = "sbp_common.py"
    content  = file("${path.module}/../lambdas/shared/sbp_common.py")
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${local.prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = 7
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.lambdas
  name               = "${local.prefix}-${replace(each.key, "_", "-")}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "fn" {
  for_each = local.lambdas

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = each.value.statements
    content {
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.lambdas
  name     = "access"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}

resource "aws_lambda_function" "fn" {
  for_each         = local.lambdas
  function_name    = "${local.prefix}-${replace(each.key, "_", "-")}"
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.13"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.fn[each.key].output_path
  source_code_hash = data.archive_file.fn[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = 128

  environment {
    variables = merge({
      TABLE_PREFIX       = "${local.prefix}-"
      TELEGRAM_BOT_TOKEN = var.telegram_bot_token
    }, each.value.env)
  }

  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn]
}
