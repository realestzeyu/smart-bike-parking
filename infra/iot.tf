# One IoT thing + certificate + policy per parking space (one ESP32 each).

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}

resource "aws_iot_thing" "space" {
  for_each = var.spaces
  name     = each.key
}

# Terraform generates the key pair. The private key is stored in local state (gitignored)
# and written to certs/<space>/ (gitignored) for the ESP32 / simulator.
resource "aws_iot_certificate" "space" {
  for_each = var.spaces
  active   = true
}

resource "local_sensitive_file" "cert_pem" {
  for_each = var.spaces
  content  = aws_iot_certificate.space[each.key].certificate_pem
  filename = "${path.module}/../certs/${each.key}/certificate.pem.crt"
}

resource "local_sensitive_file" "private_key" {
  for_each = var.spaces
  content  = aws_iot_certificate.space[each.key].private_key
  filename = "${path.module}/../certs/${each.key}/private.pem.key"
}

resource "aws_iot_thing_principal_attachment" "space" {
  for_each  = var.spaces
  thing     = aws_iot_thing.space[each.key].name
  principal = aws_iot_certificate.space[each.key].arn
}

# Agreed policy: connect as client ID = space ID; publish events + status (Last Will);
# subscribe/receive its own lots' commands only.
resource "aws_iot_policy" "space" {
  for_each = var.spaces
  name     = "${local.prefix}-${each.key}-device"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:client/${each.key}"
      },
      {
        Effect = "Allow"
        Action = "iot:Publish"
        Resource = [
          "arn:aws:iot:${local.region}:${local.account_id}:topic/${each.key}/*/event",
          "arn:aws:iot:${local.region}:${local.account_id}:topic/${each.key}/status",
        ]
      },
      {
        Effect   = "Allow"
        Action   = "iot:Subscribe"
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topicfilter/${each.key}/*/cmd"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Receive"
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topic/${each.key}/*/cmd"
      },
    ]
  })
}

resource "aws_iot_policy_attachment" "space" {
  for_each = var.spaces
  policy   = aws_iot_policy.space[each.key].name
  target   = aws_iot_certificate.space[each.key].arn
}

# Rule 1: every lot event -> handle_event. Adds the space and lot from the topic.
resource "aws_iot_topic_rule" "events" {
  name        = "${local.prefix}_events_to_handle_event" # rule names: letters, digits, _ only
  enabled     = true
  sql         = "SELECT *, topic(1) AS space, topic(2) AS lot FROM '+/+/event'"
  sql_version = "2016-03-23"

  lambda {
    function_arn = aws_lambda_function.fn["handle_event"].arn
  }
}

resource "aws_lambda_permission" "iot_invoke_handle_event" {
  statement_id  = "AllowIoTRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["handle_event"].function_name
  principal     = "iot.amazonaws.com"
  source_arn    = aws_iot_topic_rule.events.arn
}
