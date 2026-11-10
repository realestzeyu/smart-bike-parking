"""Starting rows for the database. Used by load_starting_data.py (real DynamoDB) and the fake backend.

Field names follow docs/agreed-names-and-formats.md section 2.
"""

# Coordinates are approximate (Upper Changi MRT). Double-check against Exit C before the demo.
SPACES = [
    {"id": "space1", "address": "Upper Changi MRT Exit C", "lat": 1.3417, "lng": 103.9613},
]

LOTS = [
    {"space_id": "space1", "id": "space1#lot1", "status": "free", "bike_present": False},
]

# The password is NOT stored here. load_starting_data.py asks for it when creating this account.
OFFICER = {"id": "officer", "name": "Officer", "email": "", "role": "officer"}
