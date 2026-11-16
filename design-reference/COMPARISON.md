# Reference vs WorkReceipt: visual comparison

Method: both pages rendered at identical viewport sizes, **1440×900** (desktop) and **390×844** (mobile). The reference was loaded in Chrome inside a same-origin iframe of that size (its own media queries apply); the prototype was rendered with headless Chrome. Side-by-side images were composed from those captures and are not committed because they contain the reference's artwork. This is a visual comparison by eye plus measured values, not a pixel diff. No similarity percentage is claimed.

## Iteration log
| Pass | Finding | Change |
|---|---|---|
| 1 | Prototype v1 reused the reference's skeleton too closely: teal gradient pill button, 0.7s/18px fade-up on every section, eyebrow chips, one accented headline word, uniform card grid | Rebuilt around WorkReceipt's own subject (the itemized receipt) |
| 2 | Hero headline ≈86px on four lines with an orphaned word, vs. the reference's 64px on two lines | Display size capped at 64px (`clamp(2.5rem,4.6vw,4rem)`), balanced to two lines |
| 3 | On mobile the hero pushed all product imagery below the first screen (reference shows it) | CTAs sit side by side, hero padding and lead size reduced; receipt now starts near the fold |
| 4 | Mobile overflow from long CTA text in the download section and a grid min-width bug | Scoped mobile CTA rules to the hero; added `min-width:0` to grid children |

## What now matches (comparable quality)
- **Hierarchy:** one headline, one supporting paragraph, one primary action, then product proof within the first screen on desktop.
- **Headline scale:** 64px at ≥1391px, same as the reference's measured 64px; weight is heavier (600 vs 500) by choice.
- **Floating nav:** fixed, 14px from the top, blurred translucent fill, hairline border, soft shadow; collapses to a menu button on small screens.
- **Hairlines over heavy shadows:** borders carry structure; shadow only on the nav, product windows and receipt paper.
- **Product as proof:** large real app window in the hero and a real-screenshot showcase.
- **Restraint:** one orchestrated motion, no scroll-jacking or parallax; reduced motion disables all animation.

## Deliberate differences (WorkReceipt's own identity)
| Area | Reference | WorkReceipt |
|---|---|---|
| Page color | cool white #fafaf9 | warm paper #f5f2ea, ivory #fdfbf7 sheets |
| Typeface | Inter | Bricolage Grotesque (display and UI) with IBM Plex Mono for receipt data |
| Headline | centered, two lines, italic second line | left aligned, plain, no accent word |
| Primary button | teal gradient pill | solid ink rectangle, radius 10px; teal reserved for state and links |
| Hero art | app window on dotted wallpaper carousel | a receipt that prints, beside a real app window |
| Features | 3×3 grid of tiles with UI fragments | itemized ledger rows with a mono source tag |
| Motion | 0.7s fade-up on every section | one print animation in the hero; 0.3s fade on tab switches |
| Privacy | text in the feature grid | dark section with an interactive before/after redaction demo |
| Pricing | soft panel with one white card and license selector | an itemized bill with "to be announced" lines and no price |
| Footer/FAQ | centered, minimal | two-column FAQ, four-column footer |

## Remaining gaps (honest)
- **Polish gap in product imagery:** the reference frames its app window on designed artwork; WorkReceipt shows plain screenshots. Intentional, but it makes the hero feel plainer.
- **Mobile screenshots are small:** the app's desktop UI shrinks to unreadable detail inside 358px. A mobile-specific crop or zoomed fragment would read better.
- **Tablet:** checked in the prototype at 820px; the reference's tablet layout was not screenshotted, so tablet comparison is by media-query values only.
- **Interaction depth:** the reference's carousel and license selector have no equivalent here; WorkReceipt has tabs, steps and a redaction toggle instead.
- **Hover states of the reference were not captured.**
