# The 5 tables from docs/agreed-names-and-formats.md section 2. On-demand billing.
# Only key attributes are declared here; other fields are schemaless.
# Seed items are on hold until the schema is settled.

# Keyed by space so one Query(spaceId) lists every lot in a space (availability + free count).
resource "aws_dynamodb_table" "locks" {
  name         = "${local.prefix}-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "spaceId"
  range_key    = "lotId"

  attribute {
    name = "spaceId"
    type = "S"
  }
  attribute {
    name = "lotId"
    type = "S"
  }
}

# Usage archive: Query(lotId) = a lot's parking history.
resource "aws_dynamodb_table" "sessions" {
  name         = "${local.prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lotId"
  range_key    = "startTime"

  attribute {
    name = "lotId"
    type = "S"
  }
  attribute {
    name = "startTime"
    type = "S"
  }
  attribute {
    name = "open"
    type = "S"
  }

  # Sparse: only open sessions have the "open" attribute, so only they appear here.
  global_secondary_index {
    name            = "open-sessions"
    projection_type = "ALL"

    key_schema {
      attribute_name = "open"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "startTime"
      key_type       = "RANGE"
    }
  }
}

resource "aws_dynamodb_table" "users" {
  name         = "${local.prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"

  attribute {
    name = "username"
    type = "S"
  }
}

# One item per space: name, lat, lng (cyclist "nearest spaces").
resource "aws_dynamodb_table" "spaces" {
  name         = "${local.prefix}-spaces"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "spaceId"

  attribute {
    name = "spaceId"
    type = "S"
  }
}

resource "aws_dynamodb_table" "tamper_events" {
  name         = "${local.prefix}-tamper-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lotId"
  range_key    = "at"

  attribute {
    name = "lotId"
    type = "S"
  }
  attribute {
    name = "at"
    type = "S"
  }
}

locals {
  tables = {
    locks         = aws_dynamodb_table.locks
    sessions      = aws_dynamodb_table.sessions
    users         = aws_dynamodb_table.users
    spaces        = aws_dynamodb_table.spaces
    tamper_events = aws_dynamodb_table.tamper_events
  }
}
