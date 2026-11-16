# Reference design language: forensic notes

Reference: agenthover.app, inspected 2026-11-16 in Chrome with computed styles read from the live DOM. Tags: **[M]** measured from computed CSS or the stylesheet, **[O]** observed visually in a screenshot, **[E]** estimated.

## Method and limits
- Tooling: Claude in Chrome (live page, JavaScript `getComputedStyle`, screenshots). Chrome DevTools MCP and Firecrawl were not available in this session.
- The browser viewport could not be resized. It was **1728×962 at 2× DPR** [M]. Mobile and tablet were evaluated by loading the site in a same-origin iframe at 390px, which triggers the site's own media queries [M].
- Not captured: full-page tablet screenshot, tile hover states, dark theme rendering. The site declares light and dark support [M] and a theme toggle is in the nav [O].
- Reference screenshots are saved locally in `design-reference/screenshots-local/` and are **not committed** (they contain the reference's artwork).
- Nothing here copies the reference's name, wording, logo, laurel badge, wallpaper artwork or screenshots.

## Principles worth learning from
1. **Quiet canvas, one saturated action.** Near-white page, near-black text, grey secondary text; the only strong color is a single teal gradient button.
2. **Hairlines over shadows.** Cards are flat tinted fills with a 1px border at 7% black; shadow is reserved for floating things (nav) and the primary button.
3. **Product as proof.** The first thing below the headline is a large real app window. Feature cards each hold a tiny real UI fragment, not an icon.
4. **Tight display type.** Large headline, weight 500 (not bold), negative tracking, short lines, centered.
5. **One uniform rhythm.** 1000px column, 10px grid gap, repeated 16px radius.
6. **Restrained motion.** One reveal curve at 0.7s; 0.2s transitions everywhere else; reduced motion honored.

## Color [M unless noted]
| Role | Value |
|---|---|
| Page | `rgb(250,250,249)` = #fafaf9 |
| Ink | `rgb(21,21,21)` = #151515 |
| Muted text | `rgb(106,106,106)` = #6a6a6a |
| Faint text / fine print | `rgb(154,154,151)` = #9a9a97 |
| Tile fill | `rgb(241,241,239)` = #f1f1ef |
| Card fill | white |
| Border (soft / strong) | `rgba(0,0,0,.07)` / `rgba(0,0,0,.11)` |
| Accent gradient | #12a394 → #0b8a7d (180°) |
| Accent glow | `rgba(18,163,148,.32)` |
| Nav fill | `rgba(255,255,255,.75)` |
| Background glow behind hero | pale teal radial, top center [O/E] |

## Typography [M]
Family: Inter Variable with system fallbacks. Body 15px / 22.5px.
| Element | Size / weight | Tracking | Line height | Color |
|---|---|---|---|---|
| H1 | 64px / 500 | −2.24px (−0.035em) | 67.84px (1.06) | ink |
| H1 second line | italic, −2.56px | | | ink |
| H2 | 44px / 500 (`clamp(30px,4.6vw,44px)`) | −1.32px (−0.03em) | 48.4px | ink |
| Pricing/closing H2 | 40px / 500 | −1.2px | 60px | ink |
| H3 (tile) | 16px / 500 | −0.16px | 24px | ink |
| Hero paragraph | 16px / 400 | normal | 25.6px | muted, 30px below |
| Tile text | 13.5px | | 20.9px | muted |
| FAQ question / answer | 15px 500 / 14px | | 22.4px | ink / muted |
| Fine print, footer | 12px | | 18px | faint |
| Nav link | 13px / 400 (brand 600) | | | muted, active ink |

Mobile (390px) [M]: H1 40px, −1.4px, lh 42.4px; H2 30px, −0.9px, lh 33px.

## Shape and depth [M]
Pill radius 999px (nav, buttons). Tiles 16px. Pricing card 18px. App window ≈18px. Nav shadow `0 8px 30px rgba(0,0,0,.08)`. Primary button shadow `inset 0 1px 0 rgba(255,255,255,.22), 0 6px 22px -6px glow`. Tiles and cards have no shadow.

## Imagery [O]
App window shown on a dotted, pale-blue wallpaper in a carousel with arrows, thumbnails and a pause control. A small laurel-framed badge sits above the headline.
