# Least-privilege IAM user for the FastAPI web app (AWS profile "sbp-webapp" on the laptop).
# DynamoDB on the 5 tables + indexes, and iot:Publish on command topics only.

resource "aws_iam_user" "webapp" {
  name = "${local.prefix}-webapp"
}

resource "aws_iam_access_key" "webapp" {
  user = aws_iam_user.webapp.name
}

resource "aws_iam_user_policy" "webapp" {
  name = "access"
  user = aws_iam_user.webapp.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = flatten([
          for t in local.tables : [t.arn, "${t.arn}/index/*"]
        ])
      },
      {
        Effect   = "Allow"
        Action   = "iot:Publish"
        Resource = "arn:aws:iot:${local.region}:${local.account_id}:topic/space*/*/cmd"
      },
    ]
  })
}
