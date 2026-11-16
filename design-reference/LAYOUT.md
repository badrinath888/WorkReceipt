# Reference layout and responsive rules

Tags: **[M]** measured, **[O]** observed, **[E]** estimated. Desktop measured at a 1728px viewport.

## Container [M]
- Content column `max-width: 1000px`, 16px side padding. FAQ column 560px.
- Hero text block 968px wide inside the column; hero screenshot 966×603.
- Nav is `position: sticky; top: 14px` inside a full-width wrapper, centered.

## Section order and vertical rhythm [M]
| Section | Top (px from page top) | Height | Notes |
|---|---|---|---|
| Nav | 14 | 44 | floating pill, 440px wide |
| Hero | 58 | 1500 | padding 88 / 40; badge, 2-line H1, 2 lines of text, 2 buttons, fine print, product carousel |
| Supported-tools strip | 1635 | 66 | flex, 14px gap |
| Features | 1803 | 1475 | 120px above; centered H2 + subhead, 3-column tile grid |
| Pricing | 3438 | 649 | one large soft panel: benefits left, one card right |
| FAQ | 4247 | 616 | 560px column, centered H2 |
| Closing call to action | 5022 | 272 | centered H2 + the same buttons |
| Footer | 5414 | 86 | 12px text, padding 28/16/40 |
Total document height 5500px.

## Grid [M]
- Features: 3 columns × 316px, **10px gap**, tile 316×304, 176px illustration area above a 16px title and 2-line description.
- Pricing: card 340×417 on the right of a wide rounded panel [O: panel ≈ 570px wide, soft grey, radial tint].

## Alignment [O]
Everything in the hero, section headings and closing block is centered. Tile and FAQ text is left aligned. Pricing benefits are left aligned.

## Responsive rules
Media queries in the stylesheet [M]: `width < 900px`, `width < 760px`, `width < 560px`, and `prefers-reduced-motion: reduce`.
Observed at 390px [M/O]: nav stays a pill with fewer links; hero padding becomes 64/16/40; H1 40px, H2 30px; carousel shrinks to the column width with arrows and thumbnails kept; buttons keep their size and sit side by side; page height grows from 5500 to 7428px (single-column stacking).
Tablet (820px) was not screenshotted; behavior is inferred from the 900px and 760px breakpoints [E].

## Spacing scale in use [M/E]
2, 5–6, 10, 14, 16, 18, 20, 22, 28, 30, 40, 64, 88, 120. Large gaps between sections are 120px at desktop.
