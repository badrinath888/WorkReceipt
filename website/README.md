# WorkReceipt website: visual design prototype (M7, v3)

Design-approval prototype only. Not deployed, no checkout, no public download. The desktop app, report engine, PDF code and packaging are untouched.

## Run it
Static HTML, CSS and JS. No build step, no dependencies.

    git checkout website-design
    python3 -m http.server -d website 8800      # then open http://127.0.0.1:8800
    # or simply: open website/index.html

## Contents
- `index.html`, `questions/index.html` (separate Questions page), `styles.css`, `script.js`
- `assets/product/*.webp`: captures of the real WorkReceipt v0.5.1 app run on `examples/make_demo_workspace.py` synthetic data, plus `examples/example_report.html`
- `assets/fonts/`: Bricolage Grotesque and IBM Plex Mono (open-source, bundled), `assets/logo.svg` from the app icon
- `screenshots/`: review captures
- `../design-reference/`: forensic notes on the reference site and the comparison

## Design plan (and what changed after review)
**Concept.** The product is a receipt, so the page behaves like one: itemized lines with dotted leaders, a printed slip in the hero, a bill for pricing. Quiet warm paper, charcoal ink, teal only where something is active or confirmed.
**Review against the brief.** The first version borrowed the reference's skeleton (teal gradient pill, fade-up on every section, eyebrow chips, accented headline word, uniform cards). Those were replaced because they described the reference, not WorkReceipt.

## Design decisions
1. One memorable moment: the hero receipt prints once on load (disabled under reduced motion). Everything else is still.
2. Left-aligned editorial layout with varied section structures (slip, tabs, before/after, ledger, steps, dark demo, bill) instead of repeated cards.
3. Real product only: every screenshot is labeled "synthetic data". No testimonials, statistics or invented features.
4. Interactive where it informs: showcase tabs, step selector, a redaction before/after using the app's real `[REDACTED:aws-key]` format and AWS's documented example key.
5. Honest release state: "Download for Mac" jumps to a status block that says no public build exists. Pricing shows no amount; nothing is purchasable.
6. Copy mirrors product semantics: requests are not proof of completion; checks are not re-run; redaction is best-effort.
7. Accessibility: skip link, WAI-ARIA tabs with arrow keys, visible focus rings, Esc closes the menu, native `<details>` FAQ, alt text throughout, reduced-motion support.

## Design tokens (CSS custom properties in `styles.css`)
### Color
| Token | Value | Use |
|---|---|---|
| `--paper` | #f5f2ea | page |
| `--paper-2` | #ece8dd | alternate bands |
| `--sheet` | #fdfbf7 | receipts, windows, nav |
| `--ink` | #1b1c1a | text, primary button, dark section |
| `--graphite` | #5a5952 | secondary text |
| `--faint` | #8c8a80 | decorative leaders only |
| `--teal` / `--teal-hi` | #0a6f65 / #0d8b7f | links, active states, confirmed values |
| `--amber` | #7d5400 | "synthetic / not final" notices |
| `--rule` / `--rule-soft` | ink at 14% / 8% | borders |

### Typography
Bricolage Grotesque (weights 200–800) for everything; IBM Plex Mono 400/500 for receipt and status data only.
| Role | Size | Weight / tracking |
|---|---|---|
| Display | `clamp(2.5rem, 4.6vw, 4rem)` | 600 / −0.045em / lh 1 |
| H2 | `clamp(2rem, 4vw, 3.25rem)` | 600 / −0.035em / lh 1.04 |
| H3 | 1.1875rem (ledger 1.35rem) | 600 / −0.015em |
| Lead | `clamp(1.0625rem, 1.5vw, 1.25rem)` | 400, graphite, ≤52ch |
| Body | 1.0625rem | 400 / lh 1.55 |
| Mono data | .78–.88rem | 400 |

### Spacing and shape
Space scale 4, 8, 12, 16, 24, 32, 48, 72, 112. Content width 1180px. Radii: control 10px, window and nav 14px, receipt paper square with a torn edge. Shadows: window, nav, receipt drop-shadow only.

### Components
Buttons (solid ink, line, dashed disabled), floating nav, Mac window with synthetic-data tag, vertical tabs, step selector, before/after panel, ledger row, redaction demo, receipt slip, bill, FAQ row, status table.

### Breakpoints
1020px (tablet: single-column sections, horizontal tabs), 860px (menu button), 640px (mobile: compact hero CTAs).

## v3 changes
- Explore WorkReceipt: five-screen interactive walkthrough (tabs, arrow keys, stacked panels so nothing jumps; mobile uses a zoomed crop plus a full-screen viewer).
- Six illustrated feature cards (HTML/CSS/SVG) replace the text ledger.
- FAQ moved off the homepage to `questions/` (open `questions/index.html` when using file://).
- Nav now includes Questions; How it works is three static step cards.
