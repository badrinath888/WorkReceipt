# Report design: HTML and PDF (v0.5.0)

One stylesheet (`workreceipt.CSS`) drives the in-app preview, the exported HTML and the PDF. Same data, same structure: identity header,
verified-metrics strip, 1 Work requested, 2 Changes delivered (all commits + where they landed), 3 Verification (status chips as text),
4 Human review and sign-off (drawn checkboxes), 5 Basis, 6 Privacy. No list is truncated any more: every request, commit and check recorded
is printed (previously 60 commits / 40 checks, which silently dropped data).

Print CSS: `@page` Letter, 0.7/0.75in margins; headings `break-after:avoid`; rows, requests and sign-off `break-inside:avoid`; table headers
repeat (`thead{display:table-header-group}`); long unbroken strings wrap (`overflow-wrap:anywhere`); colours printed exactly.
Running footer + "Page n of N" use `@page` margin boxes: rendered by Chrome; WKWebView printing ignores them (macOS PDFs have no footer; documented limitation).

## PDF renderers
| Platform | Renderer | Status |
|---|---|---|
| macOS app | WKWebView `NSPrintOperation` (Letter, 0.75in margins) + PDFKit verify; **no slicing fallback** (removed: it cut lines) | NOT verified on a Mac |
| Dev/CLI | headless Chrome `--print-to-pdf` | verified (below) |
Tradeoff: a pure-Python PDF writer (e.g. reportlab) would be renderer-independent but adds a dependency and a second layout to keep in sync with the HTML;
rejected for now. If the Mac print job proves unreliable, that is the next option.

## Real-PDF QA (headless Chrome, `test_pdf_quality.py`)
Every page rasterised and checked: Letter size, blank pages, ink in outer 0.35in, footer "Page i of N" order, all commits/requests present as selectable text, status labels as text,
redaction markers kept and sentinel secret absent from text/metadata/bytes, no heading stranded at a page bottom, teal accent + embedded fonts present.

| Report | Pages | Size | Ink in outer margin (px) |
|---|---|---|---|
| colour | 2 | 612x792 pt | 0 |
| empty | 2 | 612x792 pt | 0 |
| longdesc | 3 | 612x792 pt | 0 |
| long | 159 | 612x792 pt | 0 |
| medium | 7 | 612x792 pt | 0 |
| mixed | 3 | 612x792 pt | 0 |
| redact | 2 | 612x792 pt | 0 |
| short | 2 | 612x792 pt | 0 |
