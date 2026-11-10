# Design

Every page follows this file. **The three mockups in this folder are the spec**; don't invent a different style.

| Mockup | Page |
|---|---|
| `App map of stations.png` | `/` cyclist map (phone) |
| `App station details.png` | station sheet (phone); the QR lot page reuses this style |
| `Government dashboard.png` | `/officer` console (desktop) |

## Colour
| Token | Hex | Use |
|---|---|---|
| teal | `#0F766E` | free, primary buttons, links, active tab |
| amber | `#B45309` | few lots left; parked 14–30 days |
| alert (red) | `#B91C1C` | over the abandon limit; removal due |
| stone (grey) | `#6B6A63` | occupied lot, "Full" pin, secondary text |
| ground | `#EEF0EA` | map background |
| page | `#F6F5F1` | page background (console) |
| surface | `#FFFFFF` | sheets, cards, tables |
| ink | `#1F1F1C` | main text |

Tints for badges: teal soft `#E3F1EF`, amber soft `#FDF3E7`, red soft `#FBE9E9`. Hairline borders `#E4E2DC`.

## Type
- **IBM Plex Sans** for all UI text. Weights 400 / 500 / 600 / 700.
- **IBM Plex Mono** only for durations and times in tables (e.g. `46 days`).
- One large numeral for the free count ("**12** of 20 lots free").
- Sentence case everywhere.

## Layout
- **Phone (cyclist):** full-bleed map; white bottom sheet with a grab handle; tab bar at the bottom (Map active; My parking and Profile greyed out). Pins are pills with the free count. The QR lot page uses the bottom-sheet look.
- **Desktop (console):** header with logo + title; row of 4 KPI cards; map (2/3) beside "Longest-parked bicycles" (1/3); tamper log full width.
- Text is left-aligned.

## Avoid
- Gradients.
- Blurred or glass panels.
- A shadow on every card (cards use a hairline border; only floating controls on the map get a light shadow).
- Emoji as icons (use simple inline SVG line icons).
- 01 / 02 / 03 numbering.
- Centred text blocks.
- More than one corner radius: one small radius (10 px) everywhere; pins, pill buttons and badges are fully rounded as in the mockups.

## Quality floor
Responsive, visible keyboard focus, reduced motion respected, no browser `alert` / `confirm` (confirm on the page instead).
