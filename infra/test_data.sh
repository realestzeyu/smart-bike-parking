#!/usr/bin/env bash
# Test data + web-app stand-ins for end-to-end testing of the Lambdas on AWS.
# Temporary: real starting data will come from webapp/load_starting_data.py.
#
# Usage (from infra/, after terraform apply):
#   ./test_data.sh load      create space1, lot space1#lot1, user testcyclist (create-only, never overwrites)
#   ./test_data.sh claim     act like the web app's "Use this lot": lot -> taken + open session
#   ./test_data.sh unlock    act like the web app's "Unlock": lot -> releasing + close session
#   ./test_data.sh show      print the lot, sessions and tamper events
#   ./test_data.sh reset     lot back to free/empty; delete test sessions and tamper events
#
# Env: PROFILE (default sbp-admin), TELEGRAM_CHAT_ID (optional: your chat ID, to receive test alerts)
set -euo pipefail

P=(--profile "${PROFILE:-sbp-admin}" --region ap-southeast-1)
LOT_KEY='{"space_id":{"S":"space1"},"id":{"S":"space1#lot1"}}'
USER_ID=testcyclist
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
new_id() { python3 -c 'import uuid; print(uuid.uuid4())'; }

put_new() {  # put an item only if its key doesn't exist yet
  local table=$1 item=$2 key_attr=$3
  if aws dynamodb put-item "${P[@]}" --table-name "$table" --item "$item" \
       --condition-expression "attribute_not_exists($key_attr)" 2>/dev/null; then
    echo "  created in $table"
  else
    echo "  already in $table (left unchanged)"
  fi
}

case "${1:-}" in
  load)
    put_new sbp-spaces '{"id":{"S":"space1"},"address":{"S":"Test Station, Exit A"},"lat":{"N":"1.3240"},"lng":{"N":"103.9300"}}' id
    put_new sbp-lots '{"space_id":{"S":"space1"},"id":{"S":"space1#lot1"},"status":{"S":"free"},"bike_present":{"BOOL":false}}' id
    user='{"id":{"S":"'$USER_ID'"},"name":{"S":"Test Cyclist"},"email":{"S":"test@example.com"},"role":{"S":"cyclist"}'
    [[ -n "${TELEGRAM_CHAT_ID:-}" ]] && user+=',"telegram_chat_id":{"N":"'$TELEGRAM_CHAT_ID'"}'
    put_new sbp-users "$user}" id
    ;;

  claim)
    sid=$(new_id); t=$(now)
    aws dynamodb update-item "${P[@]}" --table-name sbp-lots --key "$LOT_KEY" \
      --update-expression "SET #s = :taken, user_id = :u, session_id = :sid" \
      --condition-expression "#s = :free" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{":taken":{"S":"taken"},":free":{"S":"free"},":u":{"S":"'$USER_ID'"},":sid":{"S":"'$sid'"}}'
    aws dynamodb put-item "${P[@]}" --table-name sbp-sessions --item \
      '{"id":{"S":"'$sid'"},"lot_id":{"S":"space1#lot1"},"user_id":{"S":"'$USER_ID'"},"start_time":{"S":"'$t'"},"is_open":{"S":"Y"}}'
    echo "  lot taken, session $sid"
    ;;

  unlock)
    sid=$(aws dynamodb get-item "${P[@]}" --table-name sbp-lots --key "$LOT_KEY" \
      --query 'Item.session_id.S' --output text)
    aws dynamodb update-item "${P[@]}" --table-name sbp-lots --key "$LOT_KEY" \
      --update-expression "SET #s = :rel" --condition-expression "#s = :taken" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{":rel":{"S":"releasing"},":taken":{"S":"taken"}}'
    aws dynamodb update-item "${P[@]}" --table-name sbp-sessions --key '{"id":{"S":"'$sid'"}}' \
      --update-expression "SET end_time = :t REMOVE is_open" \
      --expression-attribute-values '{":t":{"S":"'$(now)'"}}'
    echo "  lot releasing, session $sid closed (now publish bike_left)"
    ;;

  show)
    echo "--- lot";  aws dynamodb get-item "${P[@]}" --table-name sbp-lots --key "$LOT_KEY" --output json
    echo "--- sessions (space1#lot1)"
    aws dynamodb query "${P[@]}" --table-name sbp-sessions --index-name by-lot \
      --key-condition-expression "lot_id = :l" --expression-attribute-values '{":l":{"S":"space1#lot1"}}' --output json
    echo "--- tamper events"; aws dynamodb scan "${P[@]}" --table-name sbp-tamper-events --output json
    ;;

  reset)
    aws dynamodb update-item "${P[@]}" --table-name sbp-lots --key "$LOT_KEY" \
      --update-expression "SET #s = :free, bike_present = :f REMOVE bike_present_since, user_id, session_id" \
      --expression-attribute-names '{"#s":"status"}' \
      --expression-attribute-values '{":free":{"S":"free"},":f":{"BOOL":false}}'
    for sid in $(aws dynamodb query "${P[@]}" --table-name sbp-sessions --index-name by-lot \
        --key-condition-expression "lot_id = :l" --expression-attribute-values '{":l":{"S":"space1#lot1"}}' \
        --query 'Items[?user_id.S==`'$USER_ID'`].id.S' --output text); do
      aws dynamodb delete-item "${P[@]}" --table-name sbp-sessions --key '{"id":{"S":"'$sid'"}}'
    done
    for tid in $(aws dynamodb scan "${P[@]}" --table-name sbp-tamper-events \
        --filter-expression "lot_id = :l" --expression-attribute-values '{":l":{"S":"space1#lot1"}}' \
        --query 'Items[].id.S' --output text); do
      aws dynamodb delete-item "${P[@]}" --table-name sbp-tamper-events --key '{"id":{"S":"'$tid'"}}'
    done
    echo "  lot reset; test sessions and tamper events deleted"
    ;;

  *)
    sed -n '2,12p' "$0"; exit 1 ;;
esac
