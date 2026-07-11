# Context Snapshot: work-ledger v1 (Claude Code usage analytics for individuals)
Generated: 2026-07-11T19:50:31Z
Branch: main
Status: in-progress
Description: New repo + working v1 terminal cost dashboard, unrefined

## Objective
Build a lightweight, near-real-time Claude Code usage/cost tracker for individuals — someone watching their own $20/month or $100/month subscription, not a team with an OTEL/Prometheus/Grafana stack. Differentiator over existing tools: attribute cost to specific blocks of work ("this cost $X"), not just a session-level number.

## Authoritative Inputs
- **Origin**: Came out of the user asking "why did I run out of Claude session limit" during the reading-with-ears session (see companion snapshot in that repo). That led to instrumenting one pipeline's headless calls (`usage.jsonl` in reading-with-ears), which surfaced the real gap: nothing like this exists for a solo user across *all* Claude Code usage, not just one automation's headless calls.
- **Design ticket**: [`adventures-in-ai#34`](https://github.com/dhk/adventures-in-ai/issues/34) — has the full requirements writeup, prior-art research, and open questions. Read that first if picking this up cold.
- **Explicit user brief**: "what's the simplest, even if imperfect, solution... assume someone can install python on the CLI" → then "write the terminal version" (as opposed to a browser/web dashboard, which was the other option discussed).
- **Prior art checked (see issue #34 and its comments for detail)**:
  - [ColeMurray/claude-code-otel](https://github.com/ColeMurray/claude-code-otel) and [aygp-dr/claude-code-metrics-lab](https://github.com/aygp-dr/claude-code-metrics-lab) — both real, both require standing up an OTEL collector + Prometheus + Grafana. Too heavy for "just open something."
  - [gxjansen/claude-code-meter](https://github.com/gxjansen/claude-code-meter) — closer: 91-star, actively-maintained macOS Übersicht widget showing the 5hr/7day *rate-limit window percentage* in real time. Does NOT do cost-in-dollars, does NOT attribute to specific work, macOS-only. Overlaps on "real-time" but misses the actual differentiator (attribution + actionable insight).
  - Claude Code's own `/cost` (= `/usage`), `/usage-credits`, `/status` — all local-display-only, not exportable/scriptable, single-session only.

## Technical Decisions

### Data source: session transcripts, not OTEL
**Decision**: Read `~/.claude/projects/<project-hash>/<session-id>.jsonl` directly — Claude Code's own local session logs.
**Why**: Zero setup (no `CLAUDE_CODE_ENABLE_TELEMETRY`, no collector to run), works retroactively on history that already exists, and — critically — was verified live (not assumed) to contain everything needed:
  - Every `assistant`-type line has a full `usage` block (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, plus a `cache_creation` sub-object splitting 5m vs 1h writes) **and** the `model` string.
  - Every `user`-type line carries a `promptId` — this became the free attribution unit ("block of work" = one user prompt turn) without needing Claude Code hook events at all.
**Alternatives rejected**: OTEL export (heavier, needs a receiver even if lightweight — deferred to a possible v2, not ruled out); Claude Code hooks (researched via the `claude-code-guide` agent — hooks only pass `session_id`/`transcript_path`, not usage data, so a hook would still need to parse the transcript itself; no advantage over just tailing it directly).
**State**: implemented, working.

### Real-time mechanism: plain polling, not a filesystem watcher
**Decision**: Poll the most-recently-modified `.jsonl` every ~1s, tracking a byte offset (`f.seek(offset)` / `f.tell()`), read only new lines since last poll.
**Why**: "Simplest, even if imperfect" was explicit — a proper watcher (inotify/fswatch/watchdog) is a dependency and more code for marginal benefit at 1s granularity.
**State**: implemented.

### Display: terminal (`rich`), not a browser
**Decision**: `rich.live.Live` + `rich.table.Table`, redrawn on each poll that detects new lines. One dependency (`rich`), one process, no server, no browser.
**Why**: User explicitly said "write the terminal version" after being offered the choice between terminal and browser as the two floor-of-simplicity options. The browser version (Python `http.server` + one static HTML page polling a JSON endpoint) was scoped but not built — still the natural v2 if wanted.
**State**: implemented, smoke-tested (both `--once` snapshot mode and live-watching mode ran without crashing).

### Pricing table
**Decision**: Hardcoded per-model `$/MTok` rates in `pricing.py`, pulled via the `claude-api` skill (not from memory) mid-session to avoid stale numbers: Sonnet 5 $3/$15, Opus 4.8 $5/$25, Haiku 4.5 $1/$5, Fable 5 $10/$50. Cache read = 0.1× input rate, cache write 5m = 1.25× input rate, cache write 1h = 2× input rate (Anthropic's standard multipliers, applied per-model since the transcript's `cache_creation` block already splits 5m/1h token counts).
**Why**: These are the only accurate numbers available without live-querying the Models API per calculation (which would add latency/complexity for a terminal tool polling every second).
**Alternatives rejected**: Querying `client.models.retrieve()` for live rates — deferred, static table is fine until Anthropic changes pricing.
**State**: implemented. **Known imprecision, accepted deliberately**: Sonnet 5's introductory pricing ($2/$10 through 2026-08-31) is NOT modeled — uses the standard $3/$15 rate, so current estimates run slightly high until that date.

### Unknown-model handling
**Decision**: If a transcript's `model` string isn't in the pricing table, `estimate_cost_usd()` returns `None` (not `0`), and the CLI flags the row/total with "?" / "(some models unpriced)" rather than silently under-counting.
**Why**: Verified this actually fires in practice — the real test run against this session's own transcript showed "(some models unpriced)" on the total, meaning at least one subagent call used a model string not in the table. Better to be visibly incomplete than silently wrong.
**State**: implemented. **Not yet investigated**: which specific model string(s) are hitting this — worth checking `rate_for()` misses in a future session if the gap matters.

## Artifacts

### `github.com/dhk/work-ledger` (new repo, private)
**Purpose**: Home for this tool. Created fresh per the user's explicit direction ("we'll create a new repo") rather than building inside `adventures-in-ai`, specifically to avoid repeating the reading-with-ears extraction cycle later.
**Status**: v1 committed and pushed (`0cc96e9`).
**Naming**: User chose "work-ledger" via custom AskUserQuestion answer (rejected the offered options `claude-ledger`/`session-ledger`/`claude-odometer`/`cost-lens`) — generalizes past "Claude Code" specifically and pairs with the "attribute cost to blocks of work" framing.

### `work_ledger/pricing.py`
**Purpose**: Per-model `$/MTok` table + `estimate_cost_usd(model, usage) -> float | None`.
**Status**: completed for v1's needs.

### `work_ledger/transcript.py`
**Purpose**: `find_active_transcript()` (most-recently-modified `.jsonl` under `~/.claude/projects/`), `TranscriptTailer` class (byte-offset polling, per-`promptId` `Turn` aggregation).
**Status**: completed for v1's needs.
**Key logic**: Turns are grouped by tracking "current promptId" = the promptId of the most recently seen `user`-type entry; all subsequent `assistant`-type entries attribute to that turn until the next `user` entry. Does NOT currently distinguish sidechain/subagent messages from the main chain (`isSidechain` field exists in the transcript schema but is unused) — a subagent's cost gets attributed to whatever the "current" promptId happens to be at the time, which is usually but not always correct.

### `work_ledger/cli.py`
**Purpose**: `work-ledger` (live dashboard) and `work-ledger --once` (snapshot) commands.
**Status**: completed for v1, tested against this session's real transcript — showed genuine per-turn costs (e.g. the reading-with-ears extraction turns costing $0.03–$13 each) and a running total ($61.34 at last check, with the unpriced-model caveat noted above).

## Validation

### Live test against this session's own transcript
```
work-ledger --once
```
**Expected**: A table of prompt turns with plausible token counts and costs, plus a total row.
**Actual**: Worked exactly as expected — 20+ real turns rendered, costs ranged from $0.03 (quick replies) to $13.04 (a large background-agent turn), running total $61.3444 with "(some models unpriced)" correctly flagged. Confirmed the tool is functionally correct on real data, not just synthetic.

### Live-mode smoke test
Ran `work-ledger` (no `--once`) in the background for ~3s via a subshell, killed it, checked for tracebacks in captured output.
**Expected**: No crash.
**Actual**: No crash, no traceback. (Note: `rich.Live`'s terminal control codes don't render meaningfully when output is redirected to a file instead of a real TTY — this is expected rich behavior, not a bug; wasn't able to visually verify the live redraw *looks* right in a real terminal from this session, only that the process doesn't error.)

## Warnings
- ⚠️ **Not yet visually verified in a real interactive terminal** — only tested via `--once` (renders fine) and a backgrounded/redirected live-mode run (doesn't crash, but couldn't see the actual live redraw behavior). Next session should just run `work-ledger` directly in a terminal and eyeball it.
- ⚠️ The "(some models unpriced)" flag is real and currently unexplained — some model string(s) appearing in this session's transcript aren't in `RATES` in `pricing.py`. Likely a subagent (Explore/general-purpose) using a different model tier, or a `<synthetic>`-style internal model name. Worth a quick `grep model` pass over a transcript to find it.
- ⚠️ Package is installed **editable** (`pip3 install --user --break-system-packages -e .`) on this machine only — not published anywhere, no CI, no tests directory yet.

## Known Gaps & Limitations
- ❌ **Attribution granularity stops at "user prompt turn"**: the ticket's stretch goal was slash-command/skill-level attribution ("this skill's subagent fan-out is your biggest line item"). Not attempted in v1 — `isSidechain` and skill-invocation markers in the transcript are unused. — *Impact*: can't yet answer "which skill/command is expensive," only "which prompts were expensive." — *Workaround*: none; scoped as future work in the design ticket.
- ❌ **No historical/cross-session view**: only watches one transcript (the most recently modified) at a time. Can't answer "how much did I spend this week across all sessions." — *Impact*: no trend/weekly view yet. — *Decision*: acceptable for v1's "watch my current session" framing; a multi-file aggregator is natural v2 scope.
- ⚠️ **Sonnet 5 intro pricing not modeled** (see Technical Decisions above) — costs run slightly high until 2026-08-31.
- ⚠️ **No tests** — verification so far is manual (`--once` against a real transcript, a background smoke test). Nothing regression-proof yet.

## Out of Scope
- The browser/web-dashboard variant — explicitly deferred; user chose terminal first.
- OTEL as a data source — could be added later as an alternative/supplement, not pursued in v1.
- Multi-session/historical aggregation — noted above as a gap, not attempted.
- Per-skill/per-command cost attribution — the ticket's "bonus" feature, not attempted in v1.

## Next Actions
- [ ] Run `work-ledger` directly in a real terminal (not backgrounded/redirected) to visually confirm the live table redraws correctly
- [ ] Find and fix (or at least identify) the unpriced-model gap — `grep '"model"' <transcript>.jsonl | sort -u` against a transcript with `some models unpriced` showing, cross-check against `pricing.py`'s `RATES` dict
- [ ] Decide whether to pursue per-command/skill attribution next (the ticket's differentiator) — would need to look at how slash-command invocations and Task/subagent calls show up structurally in the transcript (the `isSidechain` field and tool_use blocks with subagent-launching tools are the likely starting point)
- [ ] Consider adding a `pyproject.toml` classifier / README badge / basic test if this moves toward being shared publicly
- [ ] Circle back to `adventures-in-ai#34` and update it with a link to this snapshot + what shipped vs. what's still open

---
*Resume:* load this file in your next session.
