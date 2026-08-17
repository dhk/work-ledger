# Demo pages

Open any `.html` file here directly in a browser. No install, no
transcripts, no credentials — this is what the tool looks like before you
commit to trying it.

| File | What |
|---|---|
| [`sessions.html`](sessions.html) | `serve`'s landing page — every session as one bar, sortable by cost, recency, duration or tokens |
| [`session-a1f4c8e2.html`](session-a1f4c8e2.html) | A session drill-down: chapters → sections → turns → calls, plus the commits that landed in that window. Click a chapter to open it |
| [`rollup.html`](rollup.html) | `rollup --report` — the same initiative totalled across every session it touched |

The remaining `session-*.html` files are the other four demo sessions,
reachable by clicking through from `sessions.html`.

## Every figure here is fabricated

These pages represent no real session, prompt, repository, or person. The
numbers are illustrative.

Real dogfood data is deliberately not used: a `serve` page carries prompt
text, file paths, working directories and commit subjects, and shipping a
real session as a demo would undercut this project's privacy promise in
the most visible place it has. Each page states this in its own banner, so
the disclosure travels with the asset if a screenshot is ever shared
standalone.

## They're generated, not drawn

`scripts/build_demo.py` writes synthetic transcripts in Claude Code's real
JSONL format, parses them with the real `TranscriptTailer`, prices them
with the real `pricing.py`, and renders them through the real
`report.py` functions — the same code paths that produce your own reports.

Two consequences worth knowing:

- **The arithmetic is real.** Calls sum to turns, turns to sections,
  sections to chapters, chapters to the session total, and every session
  to the $8.38 shown on the landing page. Nothing here is a hand-typed
  number, because nothing here is hand-typed.
- **They can't quietly go stale.** [PR #41](https://github.com/dhk/work-ledger/pull/41)
  is the cautionary tale — a hand-placed asset captioned "matches actual
  product output" that stopped matching about a hundred commits later.
  Regenerating is one command, so a rendering change shows up as a diff
  rather than as a screenshot that silently becomes fiction.

```sh
python3.12 scripts/build_demo.py          # HTML only
python3.12 scripts/build_demo.py --png    # also the PNG stills used in the README
```

**Use Python 3.12** — the version CI regenerates with. Python 3.12 changed
`sum()` to use Neumaier compensated summation for floats, so the same
costs summed on 3.11 and 3.12 differ in their last bits, and those totals
are embedded at full precision in each page's JSON. Regenerating on
another version rewrites files that are otherwise unchanged and fails
`demo-drift` for a reason unrelated to the renderers. Nothing visible
changes either way — the stills come out byte-identical, since the
difference sits fifteen decimal places below anything displayed.

PNG rendering needs the `report` extra (`pip install "work-ledger[report]"`
plus `playwright install chromium`). Without it the HTML is still written
and the PNG step explains why it skipped. If you have a Chromium that
playwright can't locate, point `WORK_LEDGER_CHROMIUM` at it.

## Staleness is enforced, not hoped for

CI regenerates these pages on every pull request and fails if the result
differs from what's committed (`demo-drift` in
`.github/workflows/ci.yml`). A rendering change that doesn't reach the
demo can't merge quietly.

That check covers the **HTML only** — the PNG stills need a real Chromium
that CI deliberately doesn't install. Both come from the same renderers,
so a change big enough to alter a still almost always alters the HTML
first; treat a `demo-drift` failure as the signal to regenerate with
`--png` so the images move with the markup rather than drifting apart
from it.

See [issue #109](https://github.com/dhk/work-ledger/issues/109) for what
remains: which `--report` outputs the demo should cover beyond `serve`
and `rollup`.
