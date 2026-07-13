# work-ledger

[![tests](https://github.com/dhk/work-ledger/actions/workflows/ci.yml/badge.svg)](https://github.com/dhk/work-ledger/actions/workflows/ci.yml)

A lightweight usage analytics tool for individual Claude Code users — the
person watching their own $20/month or $100/month subscription, not a team
with an observability stack.

**Goals:**
- Near-real-time visibility into what a session or automation is costing
- Something you can open and read, not a raw log dump or a Prometheus/Grafana
  stack to stand up and maintain
- Attribute cost back to what caused it — a slash command, a skill
  invocation, a subagent call, a block of work — so it can say "this cost
  $X" and then "here's what to cut"

Design and scope are being worked out in
[dhk/adventures-in-ai#34](https://github.com/dhk/adventures-in-ai/issues/34),
including prior art already checked (OTEL-based team tools, a macOS
rate-limit widget) and open questions on data source (session transcripts vs.
a local OTEL sink) and real-time mechanism.

## Install

```sh
pip install --user work-ledger
```

(Drop `--user` if you're installing into an active virtualenv - `--user`
fails outright there.)

Or, if you trust me, the same fast path as a one-liner:

```sh
curl -fsSL https://raw.githubusercontent.com/dhk/work-ledger/main/scripts/install.sh | bash
```

Reviewing a script before piping it into your shell is a reasonable
instinct — it's right here: [`scripts/install.sh`](scripts/install.sh).
For a slower, more explicit path (an editable clone, troubleshooting), see
[INSTALL.md](INSTALL.md).

## Usage

```
work-ledger              # live dashboard, watching the most recently active session
work-ledger --once       # print current totals once and exit
work-ledger --detail     # break each prompt down into its underlying units of work
work-ledger --transcript path/to/session.jsonl   # watch a specific transcript

work-ledger chapters                    # group prompts into initiatives, cost per initiative
work-ledger chapters --detail           # same, drilled down to each initiative's underlying calls
work-ledger chapters --only "<title|index>" --detail   # drill into just one initiative
work-ledger chapters --json             # machine-readable output

work-ledger chapters --all              # chapter every session found under ~/.claude/projects/, retroactively
work-ledger chapters --all --since 2026-07-01 --until 2026-07-11   # limit to a date range
work-ledger chapters --all --json       # machine-readable, one row per session

work-ledger chapters --report                          # write a visual HTML report to a file
work-ledger chapters --report --format png --out x.png  # same, as a PNG image

work-ledger export                                # write an anonymized usage export to a local file
work-ledger export --since 2026-07-01 --out x.json     # same, filtered to a date range

work-ledger recommend                             # local-only, rule-based recommendations for one session
work-ledger recommend --json                           # machine-readable output
```

By default, cost/tokens are shown per prompt turn (one row per message you
send). `--detail` expands each turn into its underlying **units of work** —
one row per actual LLM call (one `message.id`) — and specifically labels
`Skill:` and `Subagent:` calls so fan-out cost is visible instead of folded
into the turn total.

**Known limitation on subagent attribution**: this environment writes
subagent transcripts to a separate `<session>/subagents/agent-<id>.jsonl`
file with a `.meta.json` sidecar naming the exact `toolUseId` that spawned
it, which `work-ledger` uses for exact correlation. Claude Code's transcript
format is internal/undocumented and can differ by install or version — an
older or different setup that instead inlines subagent activity as
`isSidechain` entries in the main transcript file is not specifically
handled; those entries are currently just ignored rather than guessed at,
so subagent cost may not roll up on such installs. Skill invocations run
inline in the main chain, so only the invoking call itself is labeled — any
follow-on work the skill drives isn't currently bounded as belonging to that
skill (transcripts don't mark a clear skill-scope boundary).

**Bug fixed in this pass**: Claude Code writes one JSONL line per content
block (thinking/text/tool_use) rather than one line per full LLM response,
but repeats the complete `usage` block on every line belonging to the same
message. The original version summed `usage` per line, overcounting cost by
roughly 2-4x on any multi-block response. Costs are now deduped by
`message.id` so each real API call is counted exactly once — cost estimates
from before this fix should be treated as inflated.

## Chapters (semantic grouping)

See `docs/example-session.md` for real, checked-in output from a live run
(not a mockup) — the terminal table, the `--json` shape, and notes on how
to read it.

`work-ledger chapters` answers a different question than the rest of the
tool: not "what did this prompt/call cost" but "what did this *initiative*
cost" — e.g. "Build the v1 dashboard," "Fix the double-counting bug." That
grouping can't be derived structurally (one initiative can span many
prompts, one prompt can touch several), so `chapters` makes a small,
separate call to Claude Haiku to label the boundaries, then reports cost
per initiative by summing the same `Turn`/`Unit` data everything else in
this tool uses — no new cost math, just a grouping label on top.

- **Costs real money, kept small and visible.** The chaptering call itself
  typically costs a fraction of a cent to a few cents per session (Haiku,
  small input). The CLI prints what that pass cost.
- **Requires its own Anthropic API credentials** (`ANTHROPIC_API_KEY`, or
  an `ant auth login` profile) — separate from your Claude Code session,
  since this is a direct API call this tool makes on your behalf. Without
  credentials (or on any other failure), it doesn't crash — it falls back
  to a single "Unsorted" chapter and says so explicitly.
- **Results are cached and frozen.** A `<session-id>.chapters.json` file
  next to the transcript remembers what's already been chaptered.
  Re-running only chapters newly-added prompts; it never re-pays for or
  retitles a chapter that's already been written, even if later turns make
  clear an earlier chapter should have been named differently. See
  `docs/session-chaptering-design.md` for the full design and the
  known tradeoff this accepts.
- **Linked to `--detail`, not a separate report.** `chapters --detail`
  drills every chapter down into the same turn/unit rows `--detail` shows
  on its own — the point of chaptering is "here's what to cut," which
  means seeing the actual calls behind an expensive initiative, not just
  its dollar total.
- **Works retroactively, across every session at once, with `--all`.**
  `chapters` normally only looks at the active transcript; `--all` runs it
  over every `.jsonl` found under `~/.claude/projects/`, printing one row
  per session plus a grand total. Each session still has its own cache, so
  running `--all` repeatedly only pays for genuinely new turns, same as
  the single-transcript case. `--since`/`--until` (`YYYY-MM-DD`) narrow
  this to a date range — filtered by the transcript file's last-modified
  time, which is an approximation of when the session happened, not its
  exact start/end (a session spanning midnight is bucketed by its last
  write). A single very long retroactively-chaptered session can still run
  into the model's output cap before finishing (falls back to "Unsorted"
  for the remainder rather than crashing) — see `MAX_TOKENS` in
  `chapters.py`.
- **`--report` generates a visual page**, matching the design of the
  one-off chart example from
  [issue #7](https://github.com/dhk/work-ledger/issues/7): stat tiles, a
  per-chapter cost bar with hover-able section segments, light/dark mode.
  `--format html` (default) has no extra dependency. `--format png`
  screenshots that HTML via a headless browser and needs the optional
  `report` extra: `pip install "work-ledger[report]"` followed by a
  one-time `playwright install chromium`. Without that, `--format png`
  fails with a clear message rather than crashing — it never silently
  falls back to HTML. Not yet supported together with `--all` (that's a
  different chart shape — see issue #4/#7).
- **Each chapter also gets a `category`**, chosen by the same Haiku pass
  from a small fixed list (`feature-build`, `bug-fix`, `refactor`,
  `design-planning`, `debugging`, `docs`, `review-feedback`,
  `tooling-infra`, `other`) — not free text. This exists specifically so
  `export` (below) can report cost rollups without ever transmitting a
  chapter's actual title.

## Export (anonymized, manual)

```
work-ledger export                                         # write an export to work-ledger-export-<date>.json
work-ledger export --since 2026-07-01 --until 2026-07-11   # limit to a date range
work-ledger export --out my-export.json                    # choose the output path
```

**work-ledger never sends anything anywhere on its own.** `export` writes
a local JSON file — session/chapter counts, token/cost totals, and a
rollup by the fixed `category` taxonomy above — that you can inspect and,
if you choose, send somewhere yourself (a support request, a shared corpus
someone's collecting, whatever). There is no submit/upload flag; this is
the entire mechanism, deliberately.

What's in the file: aggregate totals only, plus one bucket per category
with its own totals. What's **not** in the file, ever: chapter titles,
prompt or tool content, transcript paths, session identifiers — anything
that could identify the work itself rather than just its shape. Getting a
category for each chapter still needs chaptering to have run (the same
Haiku pass `chapters --all` already makes), so exporting sessions that
haven't been chaptered yet incurs that same small, disclosed cost.

The point of collecting this at all: `recommend` (below) currently only
reasons about a single session's own data. A large enough anonymized
corpus is what would let it also say "your bug-fix chapters cost more
than typical" instead of just "this chapter looks expensive relative to
your other chapters this session" — that corpus-relative layer doesn't
exist yet; `export` is the first step toward having the data for it.

## Recommendations (local-only, experimental)

```
work-ledger recommend             # rule-based recommendations for the active session
work-ledger recommend --json      # machine-readable output
```

A first cut at turning "here's what this cost" into "here's what to do
about it." `recommend` runs a small set of concrete, local-only heuristics
over one session's own `Turn`/`Unit`/`Chapter` data — no corpus, no extra
LLM call beyond chaptering itself:

- **Outlier chapter cost** — a chapter costing well above this session's
  own median chapter cost.
- **Subagent-heavy chapter** — a chapter where dispatching subagents ate
  most of its cost, worth checking against doing the same work inline.
- **Repeated skill invocation** — the same skill run several times within
  one chapter, a candidate for replacing with a plain deterministic script
  (see [issue #6](https://github.com/dhk/work-ledger/issues/6)).

This is intentionally a short list of defensible rules, not a big
speculative rule engine — and it's entirely local. A corpus-relative
dimension ("compared to other users' bug-fix chapters") is future work
that depends on `export` above actually accumulating a corpus first.

## Pattern library (opt-in, experimental)

```
work-ledger patterns enable            # turn on community pattern matching (off by default)
work-ledger patterns disable
work-ledger patterns status            # show enabled/disabled, install id, backend config
work-ledger patterns list              # list locally-available pattern entries

work-ledger recommend --mark-used <id> # confirm you applied a pattern's fix
```

A shared, versioned library of known mistakes/patterns/fixes (see
[`docs/pattern-library-design.md`](docs/pattern-library-design.md)) that
`recommend` can surface alongside its own local rules. **Off by default**
— nothing changes about `recommend`'s output, and no network call ever
happens, until you run `patterns enable`.

- **Matching is rule-based, not a generic pattern DSL.** Each library
  entry (see `patterns/*.md`, format documented in
  [`CONTRIBUTING-patterns.md`](CONTRIBUTING-patterns.md)) optionally
  declares `maps_to`, an existing `recommend` rule id. A library entry
  only ever gets shown alongside a local rule that actually fired with a
  matching id — there's no independent matching against raw transcript
  data.
- **Popularity is two raw counts, not a formula.** Each entry tracks how
  many times it's been recommended and how many times someone confirmed
  they used the fix (`--mark-used <id>`) — displayed as-is, deliberately
  no single derived score (see the design doc's decided open questions).
- **No publicly shared counter service.** The maintainer runs a personal
  instance of `backend/` for their own use (v1 is explicitly
  single-person-scoped — see the design doc), but it isn't exposed for
  other installs to report to. Deploy `backend/` yourself (see
  `backend/README.md`) and set `WORK_LEDGER_PATTERN_BACKEND_URL` to have
  `recommended`/`used` counts actually update anywhere. Without it,
  everything still works locally (matching, display, `--mark-used`
  confirmation) — there's just nowhere to report to, which is a silent
  no-op, never an error.
- **A local MCP server** (`work-ledger-mcp`, needs the `patterns` extra:
  `pip install "work-ledger[patterns]"`) exposes `list_patterns`,
  `report_recommended`, and `report_used` as MCP tools over stdio —
  connect it to a Claude Code session to consult known patterns live,
  not just when `recommend` runs after the fact. Same reasoning as the
  design doc: this is the actual argument for MCP over a static file.
- **`submit_review_findings`** (same MCP server) forwards code-review
  findings — the same shape `ReportFindings` already produces — to the
  backend for later manual curation into new library entries (see
  [`docs/review-findings-harvesting-design.md`](docs/review-findings-harvesting-design.md)).
  v1, personal-only: only call it on explicit instruction, after a review
  already ran, for a repo you actually have the right to forward findings
  from. Needs both `WORK_LEDGER_PATTERN_BACKEND_URL` and a separate
  `WORK_LEDGER_FINDINGS_TOKEN` shared secret (unlike the counters, this
  accepts free text, so it requires a real bearer-token credential, not
  just the opt-in gate) — set the same token on the backend deployment.
  Silent no-op, same as the other tools, if the library isn't enabled or
  either is unconfigured.

## Session limits (Claude Pro/Max)

```
work-ledger limits                          # live rolling-5h-window token total across all sessions
work-ledger limits --once                   # snapshot instead of live
work-ledger limits --window-hours 5         # default 5, matching Claude's session window
work-ledger limits --set-threshold 500000   # save your own calibrated token threshold
work-ledger limits --json                   # machine-readable
```

This tracks a different thing than the rest of the tool: not dollar cost,
but the Claude Pro/Max **rolling usage window** ("why did I run out of
session limit") that started this whole project. It's explicitly an
**estimate, not an official number** — Anthropic doesn't publish the exact
token/message threshold for that window, and Claude Code's own `/status`
that shows a live percentage is local-display-only, not exportable.

What `limits` actually does: sums real token usage — the same `Turn` data
the rest of the tool already parses — across **every** session (not just
the active one) in a rolling window ending now (default 5 hours). That's a
real number. Turning it into a percentage needs a threshold this tool
can't know on its own, so you calibrate it yourself: next time Claude Code
tells you you've hit your limit, check what `work-ledger limits` reported
at that moment and save it with `--set-threshold`. The threshold is stored
in `~/.config/work-ledger/limits_threshold.json`, separate from any
per-transcript cache.

## Status

v1 built: near-real-time terminal dashboard reading Claude Code's own
session transcripts, no telemetry setup required. Cost/token attribution
works at the per-prompt-turn level (default), per-unit-of-work level
(`--detail`, with skill/subagent calls specifically labeled), and the
per-initiative level (`chapters`, linked back into `--detail`), which can
now also be applied retroactively across every past session at once
(`chapters --all`, with `--since`/`--until` date filtering). A visual
HTML/PNG report (`chapters --report`) covers the "show me" case, and
`limits` gives a self-calibrated read on the separate Claude Pro/Max
session-limit question. Chapters now also carry a fixed `category`
alongside their free-text title, feeding two new, early pieces:
`export` (an anonymized, manual, opt-in usage export — no automatic
network call, ever) and `recommend` (a first cut at local-only, rule-based
recommendations for a single session). `recommend` can now optionally
(opt-in, off by default) match against a shared pattern library and show
community-sourced fixes alongside its own findings, including a local MCP
server for live in-session matching — see "Pattern library" above; no
publicly hosted counter backend exists yet, that part is still
bring-your-own.

Not yet done: cross-session/historical rollup (only watches one transcript
at a time); Sonnet 5 introductory pricing isn't modeled (runs a little high
until 2026-08-31); chapter granularity for very short sessions is left
entirely to the model's judgment (see open question in the design doc);
`recommend`'s corpus-relative dimension depends on `export` actually
accumulating a corpus, which doesn't exist yet; the pattern library has no
publicly shared counter backend (bring your own, see above).

## Development

```sh
pip install -e ".[test]"
pytest
```

The suite is fully offline and hermetic: every test builds its own
synthetic transcript files under a temp directory (see `tests/conftest.py`)
rather than touching `~/.claude/projects/` or `~/.config/work-ledger/`, and
the one call that costs real money (`chapters`' Haiku pass) is mocked at
the `chapters._call_model` seam rather than actually invoked. Covers
`transcript.py` (the message.id dedup fix, skill/subagent labeling,
subagent-transcript correlation), `pricing.py`, `chapters.py` (partition
validation, cache round-trip, the frozen-prefix/continuation-merge
behavior, and the model-call fallback paths - refusal, malformed shape,
exception), `export.py`, `recommend.py`, `limits.py`, and `cli.py`'s pure
helper functions.

## License

[MIT](LICENSE)
