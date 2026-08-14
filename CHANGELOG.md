# Changelog

Notable changes per released version. Grouped by what it means for
someone using the tool, not by commit — the git log is the commit log.

Versions are `MAJOR.MINOR.PATCH`, still `0.x`: the CLI surface is additive
in practice but not yet promised stable across minor versions.

Releasing is a deliberate, tagged action — see [RELEASING.md](RELEASING.md).

## [Unreleased]

_Nothing yet._

## [0.2.0] — unreleased until tagged

The first release since `0.1.0` (2026-07-13), and a large one: **twelve
new subcommands**, most of which need no Anthropic credentials at all.
`0.1.0` shipped `chapters`, `limits`, `export`, `recommend`, and
`patterns`; anyone installing from PyPI before this release got a CLI
that was both much smaller and much more credential-dependent than the
documentation described ([#103](https://github.com/dhk/work-ledger/issues/103)).

### Added — commands

Everything here except `chapters`-backed views works with **no
credentials configured**.

- **`serve`** — local read-only web UI for browsing sessions, chapters,
  turns and units ([#43](https://github.com/dhk/work-ledger/issues/43)).
  Sortable by cost/recency/duration/tokens with the sort key cascading
  through every level; pins to the top-N sessions by cost; shows a
  session's real date range; a "Commits during this session" panel
  correlated from the session's own `cwd` via local `git log`, with zero
  new network calls ([#87](https://github.com/dhk/work-ledger/issues/87)
  Tier 1); ticket/PR badges parsed from full prompt text; and
  `--merge-sessions` for one combined chronological tree spanning every
  session in scope ([#88](https://github.com/dhk/work-ledger/issues/88)).
- **`activity`** — cost attributed by activity type (tool, skill, direct
  response) rather than by initiative, with `--report` and `--top N`.
- **`timeline`** — how tool/skill/subagent/approach mix changed over time
  ([#44](https://github.com/dhk/work-ledger/issues/44)), plus
  `timeline backfill` and a deterministic narrative summary via
  `--summary`/`--report` ([#66](https://github.com/dhk/work-ledger/issues/66)
  Part 1).
- **`trend`** — cost bucketed by day or week across every session
  ([#4](https://github.com/dhk/work-ledger/issues/4)).
- **`rollup`** — cluster the same initiative across sessions and total
  its cost ([#3](https://github.com/dhk/work-ledger/issues/3)). Opt-in
  semantic matching for titles deterministic normalization can't merge
  ([#68](https://github.com/dhk/work-ledger/issues/68)); cumulative
  spend, three "All other" collapsing modes, CSV output and `--preview`
  ([#93](https://github.com/dhk/work-ledger/issues/93)); `--semantic`
  shorthand, saved flag presets and `--miso`
  ([#97](https://github.com/dhk/work-ledger/issues/97)); `--report`.
- **`waste`** — recurring-work mining within a session, and across every
  session of a recurring initiative via `--cross-session`
  ([#5](https://github.com/dhk/work-ledger/issues/5)).
- **`sessions`** — lightweight cost-ranked listing for finding the
  session you actually want, with `--top N`.
- **`miso`** — "make it so": chapters plus reports end-to-end in one
  command, with `--check-status` and graceful degradation
  ([#35](https://github.com/dhk/work-ledger/issues/35)).
- **`history`** — local sqlite session-history store with incremental,
  mtime-gated sync ([#42](https://github.com/dhk/work-ledger/issues/42)).
- **`session`** — pin a session (`set`/`status`/`clear`) so other
  commands stop needing `--transcript`.
- **`cycle`** — in-place upgrade that detects editable-vs-published
  installs automatically ([#73](https://github.com/dhk/work-ledger/issues/73)).
- **`about`** — description, version, last-updated, commit and
  attribution, shared by the CLI, the MCP server, `serve`, and every
  generated report ([#75](https://github.com/dhk/work-ledger/issues/75)).
- Top-level **`--version`**, which also reports commit and date when
  resolvable.

### Added — other

- Pluggable chapter backends: `WORK_LEDGER_CHAPTER_BACKEND=ollama` runs
  chaptering against a local Ollama server instead of the hosted API, so
  snippets never leave the machine and cost is always $0
  ([#16](https://github.com/dhk/work-ledger/issues/16), backend half).
- `recommend` widened past cost into session-limit hits, interruption
  counts and recurring-tool-sequence skill candidates
  ([#19](https://github.com/dhk/work-ledger/issues/19), 3 of 4
  categories).
- `--session <uuid-or-prefix>` as an alternative to `--transcript`.

### Fixed

- **`claude-opus-5` had no entry in the pricing table**, so on a current
  machine roughly 99% of turns showed `?` instead of a cost — the cost
  half of the tool blank behind a UI where every other column looked
  fully populated. Unpriced models are now *named* wherever a total says
  some exist, and a context-window variant id (`claude-opus-5[1m]`) no
  longer silently inherits the base model's rate
  ([#104](https://github.com/dhk/work-ledger/issues/104)).
- A chaptering call that never got a response (auth rejected, network
  error, backend unavailable) froze into the cache exactly like a real
  decision, permanently skipping retry even after the underlying failure
  was fixed ([#91](https://github.com/dhk/work-ledger/issues/91)).
- `import anthropic` sat outside its surrounding `try`/`except` at three
  call sites, so a broken or incomplete environment crashed instead of
  degrading ([#99](https://github.com/dhk/work-ledger/issues/99)).
- `rollup --semantic` could truncate its response on a large batch of
  titles ([#101](https://github.com/dhk/work-ledger/issues/101)).
- Silent cost loss: `isSidechain` subagents and skill follow-on work
  weren't attributed, and the gap was buried in prose rather than
  surfaced at runtime ([#46](https://github.com/dhk/work-ledger/issues/46)).
- `--transcript`/`--session` placed before a subcommand was silently
  ignored rather than erroring.
- Pattern-library `*.md` files weren't bundled into the wheel, so a real
  `pip install` (as opposed to running from a checkout) found zero
  patterns.
- A `ZeroDivisionError` and an unvalidated `--other-threshold` range; a
  misleading "N sessions have no cached chapters" count in
  `rollup`/`waste --cross-session`.

### Infrastructure

- `backend/` gained test coverage and entered CI, and CI now enforces a
  coverage floor ([#45](https://github.com/dhk/work-ledger/issues/45),
  [#48](https://github.com/dhk/work-ledger/issues/48)).
- A dated forcing-function test for Sonnet 5's introductory-pricing
  cutoff, so the rate gets a second look instead of going quietly stale
  ([#47](https://github.com/dhk/work-ledger/issues/47)).
- Governance artifacts: `PRODUCT_BRIEF.md`, `ROADMAP.md`,
  `docs/architecture.md`, and the show/tell/do rubric.
- This file, plus [RELEASING.md](RELEASING.md), a tag-triggered release
  workflow, and a scheduled release-drift alarm — the absence of any
  release process is why `0.1.0` sat published for 97 commits
  ([#103](https://github.com/dhk/work-ledger/issues/103)).

### Upgrading from 0.1.0

Nothing to migrate — the changes are additive. `work-ledger cycle`
upgrades in place, or `pip install --upgrade work-ledger`. Cached
chapters written by `0.1.0` stay valid and are not re-paid for.

One figure does change: sessions run on `claude-opus-5` were priced at
`?` before and carry real dollar amounts now, so totals covering recent
work will *rise* on upgrade. That's the fix, not a regression — the old
number was missing, not lower.

## [0.1.0] — 2026-07-13

Initial PyPI release: `chapters`, `limits`, `export`, `recommend`, and
`patterns`.
