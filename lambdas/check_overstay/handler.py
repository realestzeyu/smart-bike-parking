"""check_overstay: triggered by EventBridge Scheduler.

Placeholder: logs that it ran. Real logic (see docs/agreed-names-and-formats.md section 5) comes next.
"""

import os


def lambda_handler(event, context):
    print(f"check_overstay ran, limit={os.environ.get('OVERSTAY_LIMIT_MINUTES')} min")
    return {"ok": True}
