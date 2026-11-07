"""handle_event: triggered by IoT Rule 1 for every '<space>/<lot>/event' message.

Placeholder: logs the event only. Real logic (see docs/agreed-names-and-formats.md section 5) comes next.
"""

import json


def lambda_handler(event, context):
    # The rule adds 'space' and 'lot' from the topic, e.g. {"type": "tamper", "space": "space1", "lot": "lot1"}
    print(json.dumps(event))
    return {"ok": True}
