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
python scripts/build_demo.py          # HTML only
python scripts/build_demo.py --png    # also the PNG stills used in the README
```

PNG rendering needs the `report` extra (`pip install "work-ledger[report]"`
plus `playwright install chromium`). Without it the HTML is still written
and the PNG step explains why it skipped. If you have a Chromium that
playwright can't locate, point `WORK_LEDGER_CHROMIUM` at it.

See [issue #109](https://github.com/dhk/work-ledger/issues/109) for the
remaining work — chiefly a CI check that regenerating produces no diff,
which is what would make staleness impossible rather than merely unlikely.
