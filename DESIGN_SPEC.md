# WorkReceipt UI — design specification
Measured from agenthover.app's rendered page in Chrome (computed styles + screenshots, 2026-11-14). Only tokens, not assets, were taken; logo, copy, illustrations and imagery are original.

| Area | Measured on reference | Used here |
|---|---|---|
| Font | Inter Variable, body 15px/22.5px | Inter Variable (bundled woff2, offline) |
| H1 | 64px / 500 / -2.24px (-0.035em), lh 1.06, italic second line | same, clamp() down to 38px on mobile |
| H2 | 44px / 500 / -1.32px | app page titles 22px/600/-0.025em |
| Canvas | #FAFAF9, ink #151515, muted #6A6A6A, secondary #4A4A4A | same; dark theme added |
| Accent | teal #0B8A7D → #12A394 gradient CTA, inset 1px highlight, 0 6px 22px -6px glow | same |
| Secondary button | white, 1px rgba(0,0,0,.11), pill | same; primary actions are ink-black pills (as the reference's "Export") |
| Chips/pills | #F3F3F1, 1px rgba(0,0,0,.07), 999px, 13px, 6px 14px | same |
| Nav | fixed pill, 44px tall, 13px links, muted→ink on hover (0.2s), dot under active | same, with blur and soft shadow |
| App window | white, large radius (≈22px), deep soft shadow, left sidebar (active = black pill), uppercase 10px section labels | same |
| Cards | white, 1px hairline, 14px radius, 12px titles, 20–24px stat values, 11px deltas, mini sparklines | same |
| Chart | beige bars, one orange (#F26A21) highlight bar | same (real weekly session counts) |
| Motion | 0.2s color/transform/shadow transitions; subtle rise on hover | same; view fade-in 0.35s; honors prefers-reduced-motion |
| Breakpoints | sidebar collapses on narrow screens | 980px (sidebar hides, grids stack), 560px (compact) |

Not measurable from the browser (documented, not invented): the reference's exact app-window radius/shadow inside its screenshot carousel (rendered as image), and its page-scroll animations.
