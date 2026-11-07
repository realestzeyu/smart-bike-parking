# The 5 tables from docs/agreed-names-and-formats.md section 2 (team ER diagram as key-value tables).
# On-demand billing: nothing charged while idle. Only key attributes are declared; others are schemaless.

# One item per parking space. Few items: the web app Scans.
resource "aws_dynamodb_table" "spaces" {
  name         = "${local.prefix}-spaces"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# One item per lot, keyed by space so one Query(space_id) lists a space's lots.
resource "aws_dynamodb_table" "lots" {
  name         = "${local.prefix}-lots"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "space_id"
  range_key    = "id"

  attribute {
    name = "space_id"
    type = "S"
  }
  attribute {
    name = "id"
    type = "S"
  }
}

# One item per account. id = the login username.
resource "aws_dynamodb_table" "users" {
  name         = "${local.prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

# One item per parking session (usage archive). Key: id (UUID).
# The current session of a lot is lot.session_id; history per lot uses the by-lot index.
resource "aws_dynamodb_table" "sessions" {
  name         = "${local.prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
  attribute {
    name = "lot_id"
    type = "S"
  }
  attribute {
    name = "start_time"
    type = "S"
  }

  # Query(lot_id) = a lot's usage history, newest first with ScanIndexForward=false.
  global_secondary_index {
    name            = "by-lot"
    projection_type = "ALL"
    key_schema {
      attribute_name = "lot_id"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "start_time"
      key_type       = "RANGE"
    }
  }
}

# Tamper log. Key: id (UUID). Each event belongs to a session (session_id).
resource "aws_dynamodb_table" "tamper_events" {
  name         = "${local.prefix}-tamper-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

locals {
  tables = {
    spaces        = aws_dynamodb_table.spaces
    lots          = aws_dynamodb_table.lots
    users         = aws_dynamodb_table.users
    sessions      = aws_dynamodb_table.sessions
    tamper_events = aws_dynamodb_table.tamper_events
  }
}
