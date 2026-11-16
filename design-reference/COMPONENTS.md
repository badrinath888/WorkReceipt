# Reference components

Tags: **[M]** measured, **[O]** observed.

## Floating nav [M]
44px tall pill, 440px wide, padding 5×6, 2px gap. Fill white at 75% opacity, 1px `rgba(0,0,0,.11)` border, shadow `0 8px 30px rgba(0,0,0,.08)`. Brand: 13px / 600 with a small square logo, padding 3×12×3×4. Links: 13px / 400, 32px tall, padding 6×10, fully rounded, muted grey turning to ink on hover (`color .2s`). Active link is ink with a tiny dot beneath [O]. A theme toggle icon ends the row [O].

## Buttons [M]
Both 40px tall, 14px / 500, padding 0×20, pill.
- **Primary:** white text, gradient #12a394→#0b8a7d, inset top highlight, soft teal drop glow. Hover: glow grows to `0 8px 30px -4px`.
- **Ghost:** white fill, 1px `rgba(0,0,0,.11)` border, ink text. Hover: fill changes to a slightly darker page tone.
- Transitions: `background, transform, box-shadow, border-color` at 0.2s.

## Feature tile [M]
316×304, fill #f1f1ef, 1px `rgba(0,0,0,.07)` border, radius 16, padding 16×18×20, no shadow. Top: ~176px illustration area holding a miniature, real-looking UI fragment (keys, a dialog, progress bars, small chart, pills). Below: 16px/500 title, 13.5px muted description.

## Mini UI fragments [O]
White rounded cards at small scale, 11–12px type, one saturated accent per fragment (teal bars, red/amber/green action buttons). Keyboard shortcut keys drawn as raised white squares.

## Product window [O/M]
Mac-style window with faint traffic lights, sidebar with a black selected pill, uppercase 10px group labels, white stat cards with 11px deltas. Presented over a decorative wallpaper, with round white prev/next buttons, thumbnail strip and a caption line beneath.

## Pricing panel [O/M]
Large rounded soft-grey panel (radial tint). Left: small label, 40px heading, three icon + title + one-line benefit rows. Right: white card, radius 18, 1px border, padding 22, with a segmented control (1/3/5 licenses), a large price, a divider, three check items, and a full-width primary button.

## FAQ [M/O]
560px column. Question 15px/500, answer 14px/22.4px muted. Rows separated by whitespace and hairlines; questions are plain text, not boxed.

## Footer [M]
Centered or inline 12px faint text, padding 28/16/40, repeated anchor links.
