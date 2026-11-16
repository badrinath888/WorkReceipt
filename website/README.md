# WorkReceipt website — visual design prototype (M7)

Design-approval prototype only. Not deployed, no checkout, no public download. The desktop app, report engine, PDF code and packaging are untouched.

## Run it
Static HTML/CSS/JS, no build step, no dependencies.

    open website/index.html                      # or:
    python3 -m http.server -d website 8800       # http://127.0.0.1:8800

## Contents
- `index.html`, `styles.css`, `script.js` — the site
- `assets/product/*.webp` — **real captures of the WorkReceipt v0.5.1 app** (run from this repo on `examples/make_demo_workspace.py` synthetic data) and of `examples/example_report.html`
- `assets/fonts/` Inter Variable and `assets/logo.svg` — reused from the app, not new
- `screenshots/` — review captures (desktop full, mobile full, hero, showcase, pricing, mobile menu, tablet)

## Design decisions
1. **Own identity, shared DNA.** Warm paper off-white (`#faf8f4`) replaces the app's cool grey; teal is reserved for one primary CTA, active states, check icons and the headline accent. Everything else is charcoal and hairlines.
2. **Receipt motif.** The torn-edge report preview and dashed dividers echo the logo; this is the one memorable device, used once.
3. **Real product, honestly labeled.** The showcase uses genuine app captures, each tagged "synthetic demo data". No invented UI, features, testimonials or statistics.
4. **Floating pill nav** collapses to a menu button below 860px; active section is marked with a dot.
5. **Download is truthful.** "Download for Mac" goes to a release-status block that states no public build exists. No file link, no fake installer.
6. **Pricing is a layout placeholder.** Two cards ("Private beta", "Price to be announced"), a visible "not finalized" banner, and disabled buttons. No amounts, no checkout.
7. **Trust language mirrors the product.** "Best-effort redaction", "requests are not proof of completion", "checks are not re-run" come straight from the README and report text.
8. **Motion is minimal.** 0.7s fade-rise on scroll, 0.2s hover lifts, tab fade. `prefers-reduced-motion` disables all of it.
9. **Accessibility.** Skip link, WAI-ARIA tabs with arrow-key support, visible focus rings, `aria-expanded` menu with Esc to close, native `<details>` FAQ, alt text on every screenshot.

## Design tokens
All tokens are CSS custom properties at the top of `styles.css`.

### Color
| Token | Value | Use |
|---|---|---|
| `--bg` | `#faf8f4` | page |
| `--bg-2` | `#f3f0e9` | alternating bands, chips |
| `--surface` | `#fffefb` | cards, nav |
| `--ink` | `#1c1c1a` | headings, dark buttons |
| `--ink-2` | `#454540` | body emphasis |
| `--muted` | `#64645d` | secondary text (≥4.9:1 on `--bg`) |
| `--teal` / `--teal-hi` | `#0b7a6f` / `#0f9488` | CTA gradient, accents |
| `--teal-ink` | `#085f56` | teal text on tint |
| `--amber` | `#a66a00` | "synthetic / not final" notices |
| `--line` / `--line-2` | `rgba(28,28,26,.09 / .15)` | borders |

### Typography
Inter Variable (bundled), mono: system `ui-monospace`.
| Token | Size | Weight / tracking |
|---|---|---|
| display | `clamp(2.5rem, 6.2vw, 4.5rem)` | 500 / −0.04em / lh 1.02 |
| h2 | `clamp(1.875rem, 3.8vw, 2.875rem)` | 500 / −0.03em |
| h3 | 1.25rem | 600 / −0.015em |
| lead | `clamp(1.0625rem, 1.6vw, 1.25rem)` | 400, `--muted` |
| body / small / micro | 1rem / .875rem / .75rem | 400 |

### Spacing (4px base)
`4, 8, 12, 16, 24, 32, 48, 72, 112` → `--s1…--s9`. Section padding 112px (72px tablet/mobile). Content width 1160px.

### Shape and elevation
Radius: pill `999px`, card `20px`, window `18px`, control `12px`. Shadows: `--shadow-card` (resting), `--shadow-float` (nav, hover), `--shadow-win` (Mac window).

### Components
- **Buttons:** pill, 14×22px. Primary (teal gradient + inset highlight), ghost (surface + hairline), dark, disabled (`aria-disabled`, flat).
- **Chip / eyebrow:** pill, 12–13px, hairline border.
- **Card:** surface, 20px radius, resting shadow, 3px hover lift.
- **Mac window:** 3 traffic-light dots, title bar, real screenshot, amber "synthetic" badge.
- **Tabs:** pill segmented control, selected = ink fill.
- **FAQ:** `<details>` card, chevron rotates on open.
- **Receipt:** white sheet with conic-gradient torn bottom edge.

### Breakpoints
`1020px` (tablet: 2-column grids), `860px` (menu button, single-column sections), `640px` (mobile: full-width CTAs, scrolling tabs).
