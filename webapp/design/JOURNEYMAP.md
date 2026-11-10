# User journeys

## J1. Find a free lot (anyone, no login)
1. Opens http://<laptop-ip>:8000/ on the phone → full-screen map of stations. Pin "1 free" at Upper Changi Exit C. Blue dot = fixed fake "you are here" nearby. No search bar. Tab bar shown: Map active; My parking and Profile greyed out and not clickable.
2. Taps the pin → station sheet slides up: "Upper Changi MRT Exit C", "180 m away, 2 min walk", "1 of 1 lots free", live indicator, lot grid (free / occupied), Get directions (opens Google Maps).
3. Back arrow → map.

## J2. First-time park (new cyclist)
1. Parks the bike in a free lot (IR → bike_arrived).
2. Scans the QR on the lot → /lot/space1_lot1 → "Lot 1 is free" + Use this lot. If IR hasn't seen a bike yet, also shows the hint "No bike detected yet" (button still works).
3. Taps Use this lot → not logged in → Log in page with "Create an account" link.
4. Sign up: username, name, email, password (stored as plaintext, PoC only) → account created, logged in.
5. Connect Telegram screen: "Open Telegram" button → taps Start in Telegram → comes back, taps Done (or Skip for now).
6. Returns to the lot page automatically → taps Use this lot.
7. Lot taken, session starts, open sent → "Lock released. Wrap the cable through your wheel and push it in until it clicks." with a Release again button (sends open again).
8. Leaves. Done.

## J3. Returning cyclist parks
Scans QR → already logged in (cookie) → Use this lot → same as J2.7.

## J4. Collect the bike (owner)
1. Scans the QR → page recognises the owner: "Your bike is parked here since 08:15" + Unlock.
2. Taps Unlock → lot releasing, session ended, open sent → "Lock released. Take your bike and push the cable back in." with an Unlock again button (sends open again).
3. Takes the bike → IR bike_left → handle_event sets the lot free. (No page update needed.)

## J5. Someone else scans a taken lot
Sees "This lot is in use." No buttons. Logged-out users see the same.

## J6. Alerts while away (Telegram, no web page)
- Tamper on their lot → "Someone is tampering with your bike at Upper Changi Exit C, lot 1 (08:42)."
- Parked over the limit → overstay reminder.
Sent by the Lambdas. The web app only stores telegram_chat_id.

## J7. Officer
1. Goes to /officer → logs in with the officer account.
2. Console (refreshes every 5 s): KPI cards (stations monitored, utilisation now, suspected abandoned bikes, tamper alerts in last 7 days), map of stations with abandoned-bike counts, Longest-parked bicycles table, Tamper log.
3. Cyclist lost their phone → officer finds the lot in the table → Force unlock → confirms on the page (no browser popup) → lot releasing, session ended, open sent.

## J8. Demo helper (fake backend only, not shown to users)
/dev: buttons per lot for bike_arrived, bike_left, tamper, and "run overstay check". Stands in for the ESP32 and Lambdas until AWS is live.

## Not in this build
- Unlock confirmation (KIV): the app assumes every open command worked.
- Theft alert when a bike leaves without Unlock: to discuss with teammate (would be in handle_event).
- My parking and Profile tabs, search, usage charts, export report: only if time allows.