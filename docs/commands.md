# Command reference

This is the detailed reference for work-ledger's command-line surfaces. For a concise product overview, installation choices, and privacy boundary, start with the [project README](../README.md).

## Upgrading

```sh
work-ledger cycle                # upgrade this install in place
work-ledger cycle --check-status # see what it would do, without doing it
```

Detects whether this is an editable clone (`git pull`) or a
pipx/uv-tool/pip install (the matching upgrade command) automatically —
no need to remember which one applies to you. Never auto-restarts
`serve`/`work-ledger-mcp`; it tells you if one looks like it's running so
you can restart it yourself. See [INSTALL.md](../INSTALL.md#upgrading) for
detail.

## Usage

```
work-ledger              # live dashboard, watching the most recently active session
work-ledger --once       # print current totals once and exit
work-ledger --detail     # break each prompt down into its underlying units of work
work-ledger --transcript path/to/session.jsonl   # watch a specific transcript
work-ledger --session 0daf9882                   # same, but by (a prefix of) its transcript UUID

work-ledger chapters                    # group prompts into initiatives, cost per initiative
work-ledger chapters --detail           # same, drilled down to each initiative's underlying calls
work-ledger chapters --only "<title|index>" --detail   # drill into just one initiative
work-ledger chapters --json             # machine-readable output

work-ledger chapters --all              # chapter every session found under ~/.claude/projects/, retroactively
work-ledger chapters --all --since 2026-07-01 --until 2026-07-11   # limit to a date range
work-ledger chapters --all --json       # machine-readable, one row per session

work-ledger chapters --report                          # write a visual HTML report to a file
work-ledger chapters --report --format png --out x.png  # same, as a PNG image

work-ledger activity                              # cost grouped by activity type (tool/skill/subagent/direct-reply)
work-ledger activity --json                            # machine-readable output
work-ledger activity --report                          # same visual style as chapters --report, as HTML
work-ledger activity --report --format png --out x.png  # same, as a PNG image
work-ledger activity --report --top 10                  # show only the 10 costliest types, rest folded into "Other"

work-ledger miso                                  # "make it so" - chaptering + both HTML/PNG reports, end-to-end
work-ledger miso --check-status                        # check credentials/report-extra only, touch nothing
work-ledger miso --all --since 2026-07-01              # chaptering summary across every session (no reports - see below)

work-ledger timeline                              # how tool usage and approach have changed, day-bucketed (last 30 days by default)
work-ledger timeline --since 2026-06-01                # a longer look-back
work-ledger timeline --summary                         # plain-language narrative of the category-mix shift, alongside the usual view
work-ledger timeline --json                            # machine-readable output
work-ledger timeline --report                          # same visual style as chapters --report, as HTML (narrative included when there's enough data)
work-ledger timeline backfill                          # chapter any uncached sessions in range first (small API cost), then show

work-ledger trend                                 # is spend going up or down - cost bucketed by day (last 30 days by default)
work-ledger trend --bucket week                        # same, bucketed by ISO week instead of day
work-ledger trend --since 2026-06-01                   # a longer look-back
work-ledger trend --json                               # machine-readable output
work-ledger trend --report                             # same visual style as chapters --report, as HTML

work-ledger serve                                 # local-only web UI - browse every session, drill into chapters/turns/units
work-ledger serve --port 9000                          # different port (default 8765)
work-ledger serve --top 5                              # pin the landing page to the 5 most expensive sessions, same ranking as `sessions --top`

work-ledger sessions                              # list every local session: project, last-active, first/last prompt, cost
work-ledger sessions --since 2026-07-01                # limit to a date range
work-ledger sessions --top 10                          # the 10 most expensive sessions, cost-sorted, instead of newest-first
work-ledger sessions --json                            # machine-readable output

work-ledger session set abc123    # pin a session - chapters/activity/recommend default to it until cleared
work-ledger session status        # show what's currently pinned, if anything
work-ledger session clear         # unpin - back to defaulting to the most recently active session

work-ledger about                                 # this install's version/commit/last-updated/author block
work-ledger about --json                          # machine-readable output

work-ledger export                                # write an anonymized usage export to a local file
work-ledger export --since 2026-07-01 --out x.json     # same, filtered to a date range

work-ledger recommend                             # local-only, rule-based recommendations for one session
work-ledger recommend --json                           # machine-readable output

work-ledger waste                                 # within-session waste mining - repeated file reads/subagent dispatches, and their cost
work-ledger waste --json                               # machine-readable output
work-ledger waste --report                             # same visual style as chapters --report, as HTML
work-ledger waste --report --format png --out x.png     # same, as a PNG image
work-ledger waste --cross-session                      # same pattern kinds, across every session of the same initiative

work-ledger rollup                                # cluster the same recurring initiative's chapters across every session, total cost
work-ledger rollup --since 2026-07-01 --until 2026-07-11   # limit to a date range
work-ledger rollup --json                              # machine-readable output

work-ledger history sync                          # incrementally update the local session history store
work-ledger history status                        # show what's stored (row count, last sync time)
```

By default, cost/tokens are shown per prompt turn (one row per message you
send). `--detail` expands each turn into its underlying **units of work** —
one row per actual LLM call (one `message.id`) — and specifically labels
`Skill:` and `Subagent:` calls so fan-out cost is visible instead of folded
into the turn total.

`--transcript`/`--session` (mutually exclusive, both available on every
subcommand that targets a specific session) pick a session explicitly
instead of the default "most recently active one." `--session` takes a
session's local transcript UUID — or a short prefix of one, like a git
commit hash — and searches `~/.claude/projects/` for a matching filename;
an ambiguous prefix lists every match instead of guessing. This is **not**
the same id as a `claude.ai/code` `session_...` URL — that's a separate,
unrelated identifier with no local mapping to a transcript file, so it
can't be looked up this way. Don't know which session you want yet? Run
`work-ledger sessions` first — no chaptering, no API call, just a list of
every session with enough to identify one (project, last-active time,
first/last prompt, cost) and its id to pass to `--session`.

**Order matters for `chapters`/`activity`/`recommend`: put `--transcript`/
`--session` *after* the subcommand name**, e.g.
`work-ledger chapters --session abc123`, not
`work-ledger --session abc123 chapters`. Placing it before the subcommand
name is rejected with an explicit error rather than silently picking the
wrong session — a real gap in how Python's `argparse` resolves the same
flag when it's defined on both the top-level parser and a subcommand's own
parser.

**`work-ledger session set <id>` pins a session** so `chapters`/`activity`/
`recommend` all default to it instead of "most recently active," until
`work-ledger session clear` — useful when you're watching an older or
less-active session and don't want to pass `--session` on every single
command. An explicit `--transcript`/`--session` on a specific command
still overrides the pin for that one call.

**`work-ledger history sync`** incrementally updates a small local sqlite
database (`~/.config/work-ledger/history.db`, issue #42) with one row per
session (turn count, cost, cached chapter count, last-synced time). A
session whose transcript hasn't changed since the last sync is skipped
without being re-read - only new or modified sessions cost anything to
sync. This is purely additive: nothing else (`chapters --all`, `timeline`,
`trend`, `serve`) depends on it or reads from it yet - they keep working
exactly as before via their own live sweeps of `~/.claude/projects/`. It
exists so a future cross-session feature (starting with #3) has a
persisted store to build on instead of re-inventing its own.

**Known limitation on subagent attribution**: this environment writes
subagent transcripts to a separate `<session>/subagents/agent-<id>.jsonl`
file with a `.meta.json` sidecar naming the exact `toolUseId` that spawned
it, which `work-ledger` uses for exact correlation. Claude Code's transcript
format is internal/undocumented and can differ by install or version — an
older or different setup that instead inlines subagent activity as
`isSidechain` entries in the main transcript file is not specifically
handled; those entries are currently just ignored rather than guessed at,
so subagent cost may not roll up on such installs. This isn't just prose —
`work-ledger`/`chapters`/`activity` count these skipped entries and print a
`Warning:` line the moment it happens, rather than showing a number that
looks complete but isn't (`--json`'s `chapters --all` rows also carry a
`skipped_sidechain_count` field). Skill invocations run inline in the main
chain, so only the invoking call itself is labeled — any follow-on work the
skill drives isn't currently bounded as belonging to that skill (transcripts
don't mark a clear skill-scope boundary, and no other correlatable signal —
timestamp proximity, tool-call clustering — is solid enough to build a
heuristic on instead of a real marker). `--detail` and `activity` print a
`Note:` line whenever a `Skill:` unit is present, as a reminder that its
follow-on cost is folded into ordinary turn cost rather than the skill.

**Bug fixed in this pass**: Claude Code writes one JSONL line per content
block (thinking/text/tool_use) rather than one line per full LLM response,
but repeats the complete `usage` block on every line belonging to the same
message. The original version summed `usage` per line, overcounting cost by
roughly 2-4x on any multi-block response. Costs are now deduped by
`message.id` so each real API call is counted exactly once — cost estimates
from before this fix should be treated as inflated.

## Chapters (semantic grouping)

See [example-session.md](example-session.md) for real, checked-in output from a live run
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
  to a single "Unsorted" chapter and says so explicitly, with a specific
  reason: no key found at all vs. a key that was sent but rejected by the
  server (invalid/revoked) get distinctly worded messages, so you know
  whether to set a key or check an existing one, rather than one generic
  "chaptering call failed" for both.
- **Optional local backend (Ollama), so session content never has to leave
  the machine.** Set `WORK_LEDGER_CHAPTER_BACKEND=ollama` (default:
  `anthropic`) to chapter against a local [Ollama](https://ollama.com)
  server instead of the hosted API — no `ANTHROPIC_API_KEY` needed, and
  cost is always `$0.0` (wall-clock time is shown in its place, since a
  local pass isn't free of overhead). Configure with:
  - `WORK_LEDGER_CHAPTER_MODEL` — the model name as pulled into Ollama
    (e.g. `qwen2.5:14b`), required for this backend.
  - `OLLAMA_HOST` — defaults to `http://localhost:11434`.
  - `WORK_LEDGER_OLLAMA_MAX_TOKENS` — output-token ceiling for the local
    call (default `4096`, lower than the hosted backend's 16000, since a
    long generation can take minutes rather than seconds on modest local
    hardware).

  Requires the optional `ollama` PyPI package: `pip install
  "work-ledger[local-chapters]"`. If that package isn't installed, or the
  local server isn't reachable, chaptering fails with a specific message
  and falls back to "Unsorted" — it never silently falls back to the
  Anthropic backend instead. A smaller local model is meaningfully more
  likely to violate the chapter-partition constraint than Haiku, so seeing
  "Unsorted" more often is expected, not a bug — see
  [local-model-chaptering-design.md](local-model-chaptering-design.md)'s "Reliability implications".

  No specific local model is benchmarked or recommended here yet — **Qwen
  2.5 14B** and **Llama 3.1** (8B or larger) are reasonable, untested
  starting points if you want to try this out, not a vetted
  recommendation (see the design doc's open question on quality vs.
  Haiku 4.5, which hasn't been evaluated against real sessions).

  The frozen-prefix caching behavior below is identical for both backends
  — using Ollama does not change when/whether a chapter gets revised;
  that's a separate, still-open design question (see the design doc's
  "Unfreezing chapters").
- **Results are cached and frozen.** A `<session-id>.chapters.json` file
  next to the transcript remembers what's already been chaptered.
  Re-running only chapters newly-added prompts; it never re-pays for or
  retitles a chapter that's already been written, even if later turns make
  clear an earlier chapter should have been named differently. See
  [session-chaptering-design.md](session-chaptering-design.md) for the full design and the
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

## Activity breakdown

`work-ledger activity` answers a different question than `chapters`: not
"which initiative cost this" but "which *kind* of work" — a tool call
(`Tool: Bash`, `Tool: Edit`, ...), an MCP server call (`MCP: github`), a
skill or subagent invocation (same `Skill:`/`Subagent:` labels `--detail`
already uses), or a plain reply with no tool call at all
(`Direct response (no tool call)`).

- **Needs no `ANTHROPIC_API_KEY` and makes no API call.** Everything it
  groups by (`Unit.kind`, `skill_name`, `subagent_agent_type`,
  `tool_names`) is already parsed locally from the transcript — unlike
  `chapters`, there's no Haiku pass, no cost, and no fallback-to-Unsorted
  case to worry about. Useful on its own, and as a fallback view when
  chaptering isn't set up.
- **`--report` matches `chapters --report`'s visual style** (same stat
  tiles, bar-per-category, legend, hover tooltips, light/dark mode) —
  sorted by cost, most expensive first. By default it shows activity
  types individually until their running cost crosses 80% of the total,
  then folds the rest into one residual "Other/final 20%" bucket, so the
  chart stays readable even with a long tail of one-off tool calls.
  `--other-threshold` adjusts that cutoff fraction (e.g. `0.9` for 90%),
  or use `--top N` for a hard count cutoff instead (e.g. `--top 10` for
  exactly the 10 costliest types) — `--top` takes precedence if both are
  given. The table and `--json` views are unaffected by either — they
  always show every activity type, uncollapsed.

## Make it so (`miso`, end-to-end)

`work-ledger miso` ("make it so" — [issue #35](https://github.com/dhk/work-ledger/issues/35))
runs the tool end-to-end in one command instead of remembering the right
sequence of flags: chaptering, then both the `chapters` and `activity`
terminal tables, then an HTML report for each, then a PNG for each if
rendering is available. It's pure orchestration — every step calls the
exact same functions `chapters`/`activity --report` already call
(`get_chapters`, `build_report_html`, `build_activity_report_html`,
`render_png`); nothing is reimplemented, and no new network call happens
beyond chaptering's existing Haiku pass.

- **Always checks status up front, before doing anything.** Every `miso`
  run starts by printing whether it has Anthropic credentials for
  chaptering and whether PNG rendering is available (the `report` extra
  installed) — so a missing key or a missing dependency is visible before
  any partial work happens, not discovered halfway through. This mirrors
  the `git rebase`-style framing the issue asks for: always know where
  things stand and what to do about it.
- **`--check-status` runs only that check.** No transcript is read, no API
  call is made, no file is written — a pure environment diagnostic you can
  run on its own to answer "is everything set up," printing exactly what
  a real run would do differently if something's missing (fall back to
  "Unsorted," skip PNG) and the fix for each.
- **Degrades, never just fails.** No `ANTHROPIC_API_KEY` (or an
  `ant auth login` profile)? Chaptering falls back to a single "Unsorted"
  chapter — the same behavior `chapters` already has, surfaced here as
  part of `miso`'s own status output rather than only showing up mid-run.
  No `report` extra installed? PNG rendering is skipped for both reports,
  with HTML still written and a clear one-line reason why PNG didn't
  happen — never a hard failure over something optional.
- **Defaults to the active/pinned session**, same as `chapters`/`activity`
  — `--transcript`/`--session` pick a specific one.
- **`--all` reuses `chapters --all`'s existing cross-session sweep**
  (same `--since`/`--until` convention) for the chaptering summary only —
  visual reports aren't generated in this mode, the same scope limit
  `chapters --report` already has (see issue #4/#7). Drop `--all` and
  pick one session to get its HTML/PNG reports.
- **Output files**: `work-ledger-miso-chapters-<session>.<html|png>` and
  `work-ledger-miso-activity-<session>.<html|png>`, written to the current
  directory — distinct names from `chapters --report`'s own defaults so
  the two don't collide if you run both.

## Timeline (practice over time)

`work-ledger timeline` answers a different question than either `chapters`
or `activity`: not "what did this cost" but "how has the way I work
changed" — day-bucketed tool/skill/subagent mix (reusing `activity`'s own
categorization, just sliced by date) alongside chapter-category mix
(`feature-build`, `debugging`, ...), so you can see whether your approach
has shifted over time, not just your spend.

- **Defaults to the last 30 days** if neither `--since` nor `--until` is
  given — there's no persisted cross-session history store yet (see the
  [show-tell-do-model.md](show-tell-do-model.md) design doc), so every run re-derives from
  transcripts fresh, same as `chapters --all`. `--since 2026-06-01` for a
  longer look-back.
- **Makes no API call by itself.** The activity-mix panel needs nothing
  beyond what's already parsed locally. The chapter-category panel only
  ever reads chapters that are **already cached** — it never triggers a
  new Haiku pass as a side effect of looking at a timeline. If some
  sessions in range aren't chaptered yet, it says so and points you at
  `timeline backfill` rather than silently showing a partial mix.
- **`timeline backfill`** chapters any session in range that isn't fully
  cached yet (same small, disclosed Haiku cost as `chapters --all` —
  already-cached sessions cost nothing to re-touch), then shows the
  resulting timeline in one call.
- **Terminal output is a Unicode sparkline per series**, each scaled
  independently against its own max — comparing sparkline *height* across
  two different series isn't meaningful, only one series' own shape over
  time is. `--report` renders the same day-by-day data as an HTML/PNG
  page, same visual system as `chapters --report`/`activity --report`.
- **`--json`** emits the full per-day activity/category counts for
  programmatic use.
- **`--summary`** adds a short, deterministic plain-language narrative of
  how the chapter-category mix has shifted, printed above the usual
  sparkline view (additive, not a replacement for it): the days-with-data
  in range are split into a first half and second half, category shares
  are compared between them, and categories whose share moved by at least
  10 percentage points get named. For example:

  ```
  Summary  Early in this range, debugging (42%) and design-planning (18%) dominated. More recently, that's shifted toward refactor (35%) and docs (20%).
  ```

  If there isn't enough data yet (fewer than 4 populated days, or fewer
  than 10 categorized turns total, or no category's share moved enough to
  be worth mentioning), it says so explicitly instead of narrating noise
  from a handful of data points — same "don't silently show a misleading
  picture" precedent as the uncached-sessions warning above. `--report`'s
  HTML output includes the same narrative line whenever there's enough
  data, with no separate flag needed. See
  [timeline-narrative-and-maturity-design.md](timeline-narrative-and-maturity-design.md) for the full design
  (Part 1 of that doc; Part 2, correlating the shift with maturity, is
  still proposed and not built).

## Trend (cost over time)

`work-ledger trend` answers the question `timeline` deliberately doesn't:
not "how has my practice changed" but "is my spend going up or down" — a
real time series of dollars, bucketed by day (default) or `--bucket week`,
across every session in range. `chapters --all` already lists per-session
totals, but that's a flat list; this re-slices the same per-turn cost data
by calendar period so a trend is visible at a glance instead of read off a
long table by hand.

- **Cost only, not activity mix** — a deliberately narrower, complementary
  view to `timeline`'s tool/skill/subagent/approach-category breakdown.
  Reads only `Turn.cost_usd`/`Turn.timestamp`, so unlike `timeline`'s
  chapter-category panel there's no cached-vs-uncached distinction and no
  API call, ever: every period's cost is either fully priced or flagged
  unknown, never partial.
- **Defaults to the last 30 days** if neither `--since` nor `--until` is
  given, same re-derive-fresh-every-run precedent as `chapters --all`/
  `timeline` (no persisted cross-session store yet).
- **Terminal output is a sparkline** (same scaling convention as
  `timeline`'s) plus a per-period table with cost, turn count, and a
  proportional bar, so you get both the at-a-glance shape and the exact
  numbers. `--report` renders the same data as an HTML/PNG page, same
  visual system as `chapters --report`/`timeline --report`.
- **`--json`** emits the full per-period cost/turn-count/pricing-coverage
  data for programmatic use.

## Local web UI

`work-ledger serve` starts a small, local-only web server (bound to
`127.0.0.1` — there's no `--host` flag, so it can never be pointed
anywhere else) for browsing session data as a page instead of re-running
CLI flags. A landing page lists every local session, sorted by cost by
default; click one to drill into its chapters → sections → turns → units,
the same grouping `chapters --detail` shows in the terminal.

- **Sortable** by cost, recency, duration, or total tokens — a row of
  buttons above the list, client-side (no server round-trip), each
  showing the sessions with the most of that metric first. The bar length
  itself always reflects cost regardless of sort (a consistent visual
  scale — recency in particular has no numeric "size" of its own to scale
  a bar by), so sort order and the figure shown are what change per
  metric, not the bars' relative lengths.
- **Each session gets a one-line summary** — reused from its cached
  chapter titles when it's already been chaptered (free, since it only
  reads the cache), or its first prompt as a fallback for a session that
  isn't chaptered yet.
- **`--top N` pins the landing page to just the N costliest sessions** —
  same ranking `sessions --top` uses, so the two always agree. The page's
  title and header show the active scope (`top 5 by cost`, plus any
  `--since`/`--until` range) so a filtered view is never mistaken for
  "every session".
- **Each session's own page shows the date range (from/to) it actually
  spans** — its title/subtitle, derived from its first and last turn's
  real timestamps, not the transcript file's last-modified time. A
  same-day session collapses to one date with a time range; a
  long-running or resumed session shows both full dates.
- **The chapters → sections → turns → units drill-down is sortable too** —
  by Time (chronological, the default), Calls, or $, another client-side
  button row. The chosen key cascades through every nesting level at
  once (chapters among chapters, turns within a section, units within a
  turn), not just the top one, so "most expensive first" holds true
  wherever you drill in next. Re-sorting doesn't collapse whatever
  `<details>` you already had open.
- **Read-only and makes no API call.** Browsing only ever reads chapters
  that are already cached (same as `timeline`) — opening this UI can
  never trigger a paid chaptering pass as a side effect.
- **Long-running**, like the plain live dashboard — `Ctrl-C` to stop.

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
LLM call beyond chaptering itself. The first three rules are cost-based;
the rest widen `recommend` to workflow-efficiency signals beyond cost (see
[issue #19](https://github.com/dhk/work-ledger/issues/19) and
[recommend-workflow-efficiency-design.md](recommend-workflow-efficiency-design.md)):

- **Outlier chapter cost** — a chapter costing well above this session's
  own median chapter cost.
- **Subagent-heavy chapter** — a chapter where dispatching subagents ate
  most of its cost, worth checking against doing the same work inline.
- **Repeated skill invocation** — the same skill run several times within
  one chapter, a candidate for replacing with a plain deterministic script
  (see [issue #6](https://github.com/dhk/work-ledger/issues/6)).
- **Session-limit hits** — Claude Code's own synthetic `rate_limit`
  transcript entry, deduped by reset time (a retry storm against the same
  limit window is one event, not several). The same deduped hit history is
  also surfaced by `work-ledger limits` itself.
- **Session interruptions** — a literal `[Request interrupted by user]`
  marker recurring in genuine user-message content; repeated interruptions
  can mean a request was underspecified up front.
- **Recurring tool-call sequence** — the same multi-step Bash/tool shape
  (e.g. a `git checkout` / `git commit` / `git push` / `gh pr create`
  cycle) repeating often enough in one session to be a named-skill
  candidate.

This is intentionally a short list of defensible rules, not a big
speculative rule engine — and it's entirely local. Two other categories
from issue #19's design doc — repeated manual permission approvals and
missing/thin `CLAUDE.md` context ("configuration"), and recurring manual
workarounds that point at a missing tool integration ("new tools") — are
deliberately not implemented: the doc's own validation against a real
session couldn't confirm the first is even recoverable from
`~/.claude/projects` transcripts (it may need `.claude/settings.json`
instead), and found no signal either way for the second. A corpus-relative
dimension ("compared to other users' bug-fix chapters") is future work
that depends on `export` above actually accumulating a corpus first.

## Waste mining (within-session and cross-session, experimental)

```
work-ledger waste                                       # flag repeated within-session patterns and their cost
work-ledger waste --json                                # machine-readable output
work-ledger waste --report                              # same visual style as chapters --report, as HTML
work-ledger waste --report --format png --out x.png      # same, as a PNG image

work-ledger waste --cross-session                        # same pattern kinds, across every session of the same initiative
work-ledger waste --cross-session --since 2026-07-01     # limit the cross-session sweep to a date range
work-ledger waste --cross-session --json                 # machine-readable output
work-ledger waste --cross-session --confirm               # with WORK_LEDGER_ROLLUP_MATCHING=semantic, show what merged
```

`work-ledger` can tell you *what* something cost; `waste` starts answering
*whether it was wasteful, and whether it keeps happening*
(see [issue #5](https://github.com/dhk/work-ledger/issues/5)).
Like `activity`, it's Show-stage: read-only, no API call, no chaptering
required. It flags two recurring patterns and reports "this happened N
times, costing $X total" for each:

- **Repeated file read** — the same file `Read` by more than one LLM call.
  A single call that happens to `Read` the same path twice isn't counted
  as a repeat (occurrences/cost are per-`Unit`, not per raw tool call) —
  see the same "same real API call, not a raw tool_use block" accounting
  discipline used everywhere else in this tool.
- **Repeated subagent dispatch** — the same subagent (agent type +
  near-identical description, matched via normalized-exact string
  comparison — no embedding/LLM call, no new paid dependency) dispatched
  more than once.

Plain `waste` looks within one session. If that session already has cached
chapters (from a prior `work-ledger chapters` run — `waste` never triggers
that pass itself), each pattern is scoped to the chapter it fell in rather
than just the whole session; without cached chapters, everything is
scoped to "whole session."

**`--cross-session` looks across every session of the same recurring
initiative**, using [issue #3](https://github.com/dhk/work-ledger/issues/3)'s
clustering — the same clustering `rollup` (below) computes, deterministic
by default and optionally extended by its semantic matching pass — to
decide what counts as "the same initiative" in the first place. The same
file re-read across three unrelated sessions is a coincidence, not a
pattern, unless those three sessions are actually the same ongoing
initiative. It only reads chapters already cached (never triggers a
chaptering pass, same as `rollup`), and only reports a pattern once it
spans 2+ distinct sessions — a repeat confined to one session is already
fully covered by plain `waste`, so it isn't reported twice. Can't be
combined with `--transcript`/`--session`/`--report`; use `--since`/
`--until` to limit the sweep, same as `rollup`.

`--cross-session` shares `rollup`'s `WORK_LEDGER_ROLLUP_MATCHING`
env var and `--confirm` flag (see `rollup`'s own section below for the
full explanation) — the two commands are guaranteed to agree on cluster
membership, by construction, since `waste --cross-session` computes its
clustering through the exact same code `rollup` does rather than a
second, independent pass.

**Deliberately not prescriptive**, for both halves. `waste` surfaces the
pattern and its cost and stops there — it doesn't suggest what to do
about it, that's [issue #6](https://github.com/dhk/work-ledger/issues/6),
which stays deliberately blocked until real, recurring evidence has
accumulated from actual usage of this command, not just a design opinion
about what the tool likely reveals.

## Rollup (cross-session, experimental)

```
work-ledger rollup                                         # total cost per recurring initiative, across every session
work-ledger rollup --since 2026-07-01 --until 2026-07-11   # limit to a date range
work-ledger rollup --json                                  # machine-readable output
work-ledger rollup --confirm                                # with WORK_LEDGER_ROLLUP_MATCHING=semantic, show what merged
```

`chapters --all` already lists every session side by side with its own
chapters, but each session's chapters stay siloed — there's no way to
answer "how much has 'Fix the double-counting bug' cost in total, across
every session it touched" from that flat list alone. `rollup` answers
exactly that ([issue #3](https://github.com/dhk/work-ledger/issues/3)):
it clusters chapter titles that recur across sessions and sums cost per
cluster, sorted most-expensive-first.

- **Clustering is deterministic title normalization, not an LLM or
  embedding pass.** Titles are lowercased, punctuation/whitespace
  collapsed, a short stopword list stripped, and lightly stemmed
  (plurals only); two titles that reduce to the same normalized string
  are treated as one initiative. This is the same call
  [issue #5](https://github.com/dhk/work-ledger/issues/5)'s
  subagent-matching (`waste`) already made for a similar "near-identical"
  matching problem — no second paid API surface until simple matching is
  actually proven too weak. Genuinely-reworded titles ("Fix the
  double-counting bug" vs. "resolve the cost overcount issue") won't
  match — an accepted false-negative tradeoff for staying local/free/
  deterministic; see `work_ledger/rollup.py`'s module docstring and
  `tests/test_rollup.py` for the tradeoffs found validating this.
- **`Unsorted` chapters are excluded from clustering** — chaptering's own
  fallback label isn't a real initiative, and matching two sessions'
  unrelated fallback chapters together would be a pure false positive.
- **Never triggers a new chaptering pass.** Only whatever's already
  cached per session is clustered — run `chapters`/`chapters --all` first
  for any session you want reflected here; uncached sessions are called
  out explicitly rather than silently under-counted.
- **No default date window** (unlike `trend`/`timeline`'s 30-day
  default): the point of a rollup is a true total across every session an
  initiative touched, not a recent slice.

### Optional semantic matching (`WORK_LEDGER_ROLLUP_MATCHING=semantic`, issue #68)

Run against real usage, v1's deterministic clustering above came back
almost entirely singletons — chapters describing the same obviously
recurring work, worded differently each time, never clustered together at
all (see [`rollup-semantic-matching-design.md`](rollup-semantic-matching-design.md)
for the full investigation). Setting `WORK_LEDGER_ROLLUP_MATCHING=semantic`
opts into a second pass: whatever chapter titles are still singletons
after the deterministic pass above are batched into **one** Claude Haiku
call (structured-output, enforced JSON schema — the same discipline
`chapters`' own Haiku pass uses) proposing merges among just that batch.

- **Off by default** (`deterministic`, today's behavior, unchanged) —
  this is a persistent, fire-and-forget environment variable, not a
  per-invocation CLI flag, mirroring `WORK_LEDGER_CHAPTER_BACKEND`'s exact
  shape from issue #16. Read fresh on every run, so flipping it takes
  effect immediately.
- **One shared clustering entrypoint.** `rollup` and `waste --cross-session`
  both compute clustering through the same code (`rollup.build_rollup_result`),
  so enabling this env var changes what both commands consider "the same
  initiative" identically — they can't silently disagree.
- **Every failure mode degrades gracefully.** No credentials, a rejected
  key, a refusal, a malformed response, or any other exception all fall
  back silently to the deterministic-only result, with a distinguishable
  printed note — never a crash, and never silently identical to "nothing
  new to merge this run."
- **No caching or versioning of merge decisions.** Every run with
  semantic matching on re-proposes merges fresh from whatever's still a
  singleton at that moment; cluster membership can drift run to run as an
  accepted consequence, not a bug.
- **`--confirm`** (on both `rollup` and `waste --cross-session`) prints
  exactly which singleton titles merged into which cluster, when the
  semantic pass actually ran and found something to merge — deliberately
  minimal, visibility only, not an audit trail.
- Uses `chapters.CHAPTER_MODEL` (`claude-haiku-4-5`, the same model
  `chapters` itself already calls) — no separate model configuration.

## Pattern library (opt-in, experimental)

```
work-ledger patterns enable            # turn on community pattern matching (off by default)
work-ledger patterns disable
work-ledger patterns status            # show enabled/disabled, install id, backend config
work-ledger patterns list              # list locally-available pattern entries

work-ledger recommend --mark-used <id> # confirm you applied a pattern's fix
```

A shared, versioned library of known mistakes/patterns/fixes (see
[`pattern-library-design.md`](pattern-library-design.md)) that
`recommend` can surface alongside its own local rules. **Off by default**
— nothing changes about `recommend`'s output, and this feature makes no
network call until you run `patterns enable` and configure a backend URL.

- **Matching is rule-based, not a generic pattern DSL.** Each library
  entry (see `patterns/*.md`, format documented in
  [`CONTRIBUTING-patterns.md`](../CONTRIBUTING-patterns.md)) optionally
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
  [backend/README.md](../backend/README.md)) and set `WORK_LEDGER_PATTERN_BACKEND_URL` to have
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
  See [INSTALL.md](../INSTALL.md#using-work-ledger-inside-claude-mcp)
  for the exact `claude mcp add`/Claude Desktop setup steps and this
  server's scope (patterns only — no usage/cost tools yet).
- **`submit_review_findings`** (same MCP server) forwards code-review
  findings — the same shape `ReportFindings` already produces — to the
  backend for later manual curation into new library entries (see
  [`review-findings-harvesting-design.md`](review-findings-harvesting-design.md)).
  v1, personal-only: only call it on explicit instruction, after a review
  already ran, for a repo you actually have the right to forward findings
  from. Needs both `WORK_LEDGER_PATTERN_BACKEND_URL` and a separate
  `WORK_LEDGER_FINDINGS_TOKEN` shared secret (unlike the counters, this
  accepts free text, so it requires a real bearer-token credential, not
  just the opt-in gate) — set the same token on the backend deployment.
  It returns without submitting, same as the other reporting tools, if the
  library isn't enabled or either setting is unconfigured.

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

## About block (issue #75)

```
work-ledger about          # this install's version/commit/last-updated/author block
work-ledger about --json   # machine-readable output
```

Every user-facing surface this tool ships — every CLI command, the
`work-ledger-mcp` server (an `about` tool alongside the pattern-library
ones), `work-ledger serve`'s pages, and every generated report (`chapters
--report`/`activity --report`/etc.) — carries the same small metadata
block: a short description, version, last-updated date/time, commit SHA
(when resolvable from an editable git checkout — never guessed for a
published install), and author/repo attribution
(`davehk@gmail.com`, `www.dhk.io`,
[github.com/dhk/work-ledger](https://github.com/dhk/work-ledger)). The
point is traceability, not a feature in itself — a screenshot, an exported
HTML report, or a `serve` instance someone else stumbled onto can always
be traced back to exactly what produced it. One shared computation
(`work_ledger/about.py`) backs all four surfaces so they can't drift from
each other. See [about-block-design.md](about-block-design.md).

## Development

```sh
pip install -e ".[test]"
pytest
```

The suite is fully offline and hermetic: every test builds its own
synthetic transcript files under a temp directory (see `tests/conftest.py`)
rather than touching `~/.claude/projects/` or `~/.config/work-ledger/`, and
all hosted model calls are mocked rather than actually invoked. Covers
`transcript.py` (the message.id dedup fix, skill/subagent labeling,
subagent-transcript correlation, and `Unit.read_paths` - a Read tool_use
call's target file path, captured narrowly for `waste.py` rather than a
generic capture-every-tool-input field), `pricing.py`, `chapters.py`
(partition validation, cache round-trip, the frozen-prefix/continuation-merge
behavior, and the model-call fallback paths - refusal, malformed shape,
exception, plus the cache-only `cached_chapters`/`has_uncached_turns`
helpers `timeline` relies on), `export.py`, `recommend.py`, `waste.py`
(repeated-read/repeated-subagent detection, chapter-vs-whole-session
scoping, the normalized-exact subagent-description match), `limits.py`,
`timeline.py` (day-bucketing, category-mix, top-label ranking),
`trend.py` (day/week cost-bucketing, unknown-model-cost flagging),
`rollup.py` (title normalization/stemming, cross-session clustering,
`Unsorted`-exclusion, cost/session/chapter rollup), `history.py` (the
local sqlite session-history store - incremental sync skipping unchanged
transcripts by mtime, re-sync picking up a modified transcript, row
round-trip), and `cli.py`'s pure helper functions.

CI (`.github/workflows/ci.yml`) runs the suite with `pytest-cov` and a
`--cov-fail-under` gate set from what the suite actually measures (not a
guessed round number - see #48), ratcheted up as coverage gaps close.
`report.py`'s `render_png` is marked `# pragma: no cover` and excluded from
that number on purpose - exercising it for real needs the optional `report`
extra's Chromium download (`playwright install chromium`), which the
default CI job doesn't install.

`backend/` (the small Vercel/Upstash service behind the pattern-library
counters and findings submission - see "What this deliberately doesn't do"
in [backend/README.md](../backend/README.md)) has its own minimal route-level smoke tests
(`backend/test/`, run via `node --test` - no extra test framework needed)
covering the counter-increment and findings-submission endpoints: each
route responds, and rejects malformed input. Run with `npm ci && npm test`
from `backend/`. CI runs this as its own non-blocking job (`backend-test`)
so a regression there doesn't hold up the Python matrix.

## License

[MIT](../LICENSE)
