output "region" {
  value = local.region
}

output "iot_data_endpoint" {
  description = "Web app IOT_DATA_ENDPOINT, and the MQTT host for the ESP32 / simulator (port 8883)."
  value       = data.aws_iot_endpoint.data.endpoint_address
}

output "table_prefix" {
  value = "${local.prefix}-"
}

output "table_names" {
  value = { for k, t in local.tables : k => t.name }
}

output "cognito_user_pool_id" {
  description = "Web app COGNITO_USER_POOL_ID (not secret)."
  value       = aws_cognito_user_pool.users.id
}

output "cognito_client_id" {
  description = "Web app COGNITO_CLIENT_ID (public client, not secret)."
  value       = aws_cognito_user_pool_client.webapp.id
}

output "lambda_names" {
  value = { for k, f in aws_lambda_function.fn : k => f.function_name }
}

output "device_cert_files" {
  description = "Per-space cert + key written locally (gitignored). Also download AmazonRootCA1.pem."
  value = {
    for s in var.spaces : s => {
      certificate = local_sensitive_file.cert_pem[s].filename
      private_key = local_sensitive_file.private_key[s].filename
    }
  }
}

output "webapp_access_key_id" {
  value     = aws_iam_access_key.webapp.id
  sensitive = true
}

output "webapp_secret_access_key" {
  value     = aws_iam_access_key.webapp.secret
  sensitive = true
}
