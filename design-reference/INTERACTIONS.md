# Reference interactions

Tags: **[M]** read from the stylesheet or computed styles, **[O]** observed.

## Scroll reveal [M]
Elements with `.reveal` start at `opacity: 0; transform: translateY(18px)` and, when intersecting, gain `.is-in` (`opacity: 1; transform: none`). Transition: `opacity .7s, transform .7s cubic-bezier(.2,.7,.2,1)`. Under `prefers-reduced-motion: reduce` the reveal is disabled (opacity 1, no transition, no transform).

## Keyframes [M]
Two exist: `rise` and `pulse`. `pulse` is most likely the notification badge in the product demo [E]; `rise` is a small entrance.

## Nav [M/O]
Sticky at `top: 14px`. Link color transitions in 0.2s. The active section link turns ink and shows a dot [O]. Anchor links scroll to sections (`scroll-margin-top: 80px` on sections) [M].

## Buttons [M]
Primary hover grows the teal glow; ghost hover tints the fill. All state changes 0.2s.

## Hero carousel [O]
Prev/next round buttons, a thumbnail strip beneath with the current item outlined, a caption line that changes with the slide, and a pause button.

## Pricing selector [O]
Segmented control switches license count and price.

## Theme [M/O]
Light/dark color-scheme support and a toggle in the nav.

## What the reference does **not** do (observed)
No parallax, no scroll-jacking, no hover zoom on screenshots, no cursor effects. Motion is almost entirely the one reveal and 0.2s state transitions.
