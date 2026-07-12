# work-ledger

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
session-limit question.

Not yet done: cross-session/historical rollup (only watches one transcript
at a time); Sonnet 5 introductory pricing isn't modeled (runs a little high
until 2026-08-31); no automated tests yet; chapter granularity for very
short sessions is left entirely to the model's judgment (see open question
in the design doc).

## License

[MIT](LICENSE)
