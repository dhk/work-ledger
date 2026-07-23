# Communications assets

Marketing/social diagrams built for a cost-audit-style post about work-ledger.
All numbers in these assets are **fabricated for illustration** — not derived
from any real transcript — and each asset says so directly in its own text
(kicker/subtitle), so the disclosure travels with the image if it's shared on
its own.

- `chapters-synthetic-detail.png` — rendered through work-ledger's actual
  `chapters --report` HTML/PNG pipeline (see `work_ledger/report.py`), fed
  synthetic chapter/section data. Tall, detailed, app-screenshot style — good
  as an in-article or reply image once a reader's already engaged.
- `chapters-synthetic-editorial.png` / `.html` — a wider, editorial layout
  built for this content specifically (headline copy baked in, one bar per
  chapter with section detail beneath). Better as a lead image for
  LinkedIn/Substack since it reads at a glance.
- `substack-draft-cost-audit.md` — draft post copy built around these charts.

To regenerate or tweak the editorial chart, edit `chapters-synthetic-editorial.html`
directly and re-screenshot it (Playwright/Chromium, viewport width 1456).
