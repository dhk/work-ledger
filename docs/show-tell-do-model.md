# Design: The Show/Tell/Do Model

Status: rubric adopted (see `CLAUDE.md`); the three new directions below
(local web UI, session history, timeline view) are proposed, not yet
built.
Author: written by Claude, from a design conversation with the repo owner.
Related: #3 (cross-session rollup), #4 (trend/time-series view), #5
(waste mining), #6 (deterministic-tool substitution, blocked on #5), #16
(local-model chaptering + unfreeze), #19 (recommend workflow-efficiency
widening), #21 (pattern library), #22/#23 (skill-rot detection), #30
(findings harvesting), #35 (`miso` end-to-end mode).

## Problem

work-ledger's roadmap has, so far, been organized issue-by-issue rather
than around a single throughline. That's fine for shipping individual
features, but it makes two things hard to see at a glance: which stage of
maturity the project is actually in, and — more importantly — which stage
a *new* proposal belongs to before work starts on it. The risk this
doc exists to head off: building an automated "fix it for you" mechanism
(Do) on top of a recommendation (Tell) that's only ever been checked
against a single session's data. That's how a well-intentioned automation
makes a confidently-wrong change.

## The model

1. **Show** — "hear what's going on." Expose the raw shape of a person's
   own Claude Code usage: cost, tokens, what it went to. Read-only. No
   interpretation beyond grouping and labeling.
2. **Tell** — "here's how to change things." Turn what's shown into a
   concrete recommendation a person can act on themselves. Still no side
   effects — reports, never edits.
3. **Do** — "we'll change it for you." Build and deploy something (an
   agent, a script, a scheduled job) that implements a recommendation
   without a human re-typing it by hand.

The stages are sequential in *trust*, not necessarily in *build order* —
deepening Show (e.g. the local web UI below) is legitimate work to do
after Tell has already started, as long as nothing added to it is
secretly a Do-stage side effect.

## Current state, audited against the model

**Show** (mature):
- `chapters` — cost per initiative, with `--detail` drill-down.
- `activity` — cost by kind of work (tool/skill/subagent/direct-reply).
- `limits` — rolling Pro/Max session-window usage.
- `export` — anonymized local file, manual, never auto-sent.
- `chapters --report` / `activity --report` — the one place Show has a
  visual form today, and only as a static generated file (HTML/PNG), not
  a live interface. See "Local web UI" below.

**Tell** (started, thin):
- `recommend` — 3 local, single-session rules today (outlier chapter
  cost, subagent-heavy chapter, repeated skill invocation).
- `patterns` — an external, opt-in library `recommend` can match against,
  with two-counter popularity tracking (#21).
- #19, #22, #23 all widen Tell (new recommendation categories, skill-rot
  detection) — none of them proposes automating a fix, all explicitly
  list that as a non-goal.

**Do** (not started):
- Nothing in the codebase acts on a recommendation automatically.
- #6 (deterministic-tool substitution) is the closest thing to a Do-stage
  proposal in the tracker, and it's deliberately gated: blocked on #5
  actually surfacing a real recurring pattern first, and scoped as "a
  one-off idiosyncratic script," not a standing deployed agent.
- Every doc that comes near automatic action treats "don't act without a
  human" as a load-bearing safety property, not an oversight — `export`
  has no submit flag by design, `patterns` counters are silent no-ops
  without config, `recommend` explicitly lists "auto-editing settings" as
  a non-goal. Moving into Do means deliberately deciding which of those
  stances to relax, not stumbling into it.

## Rule for Do work (adopted, see CLAUDE.md)

Classify any proposed automation by reversibility before scoping it:

| Tier | Example | Human-in-the-loop |
|---|---|---|
| Standalone/additive | generate a new skill file, a new deterministic script, a report | fully automatable |
| Mutates existing config | edit `settings.json`, edit `CLAUDE.md`, retire a skill | propose a diff, human applies |
| Spends money / touches shared state | a scheduled job, a deployed agent, an unattended API call | explicit opt-in gate, same shape as `patterns enable` |

And: don't automate a Tell rule that's only been validated against one
session. Wait for #5-style evidence of a real recurring pattern.

## Three new directions from this conversation

### 1. A local web UI (deepens Show)

Today's output is one-way and ephemeral: a terminal render or a generated
static file (`--report`). There's no persistent, clickable surface to
drill from "here's total cost" down into "here's the chapter, here's the
turn, here's the tool call" without re-running a different CLI flag each
time.

Proposal: `work-ledger serve` (name not decided) starts a local-only web
server (bind to `127.0.0.1`, no auth needed since it's local-only, no
persistent process by default — starts on demand, like `--report` does
today but interactive instead of a static export) that renders:
- A landing page listing sessions (reusing `sessions`' existing data).
- Per-session drill-down mirroring `--detail`: chapters → turns → units,
  clickable rather than flag-driven.
- The existing `--report` visual style (stat tiles, cost bars, hover
  tooltips) as the base look, extended with actual navigation instead of
  a single static page.

This is explicitly a Show-stage enhancement — it changes *how* the
existing data is browsed, not what's computed or acted on. It reuses
`report.py`'s existing rendering rather than inventing a second visual
language.

Open questions:
- One-shot (`--once`-style, serve current data and exit) vs. long-running
  with live refresh (mirrors the existing live-dashboard vs. `--once`
  split already in the CLI)?
- Serve just the pinned/active session, or all local sessions from one
  process (closer to `chapters --all`)?
- Does this want a lightweight framework dependency, or can it stay
  stdlib (`http.server`) plus the HTML `report.py` already generates?

### 2. Local session history (feeds Tell's evidence bar, and trust)

Two motivations came up together and are worth keeping distinct:

- **Mechanical**: several existing proposals (#3 cross-session rollup, #4
  trend view, #5 waste mining) all need *some* persistent store beyond
  "read the currently active transcript" or "re-scan `--all` fresh every
  time." Right now nothing accumulates; every retroactive run re-derives
  everything from raw transcripts plus the per-session chapter cache.
- **Trust-building**: someone won't start caring about this depth of
  detail until they've already accumulated real signal — by the time a
  person is curious enough to ask "what's going on with my usage," they
  likely already have weeks of sessions sitting on disk. Making that
  backlog visible and explorable (not just "starting now, come back
  later") is itself part of building confidence that this tool is worth
  letting run — the more legible it is up front, the less it feels like
  something opaque running in the background.

Proposal: a local, append-only history store (separate from the
per-transcript `.chapters.json` cache, which stays as-is) that periodic
or on-demand runs write into — the natural backing store for #3/#4/#5
rather than a fourth mechanism each reinventing enumeration. Because it's
local-only and derived entirely from data already on disk, backfilling it
from every existing session at once (same sweep `chapters --all` already
does) is a real, immediate demo, not a "wait and see" feature — that
matters directly for the trust point above.

Open questions:
- Same corpus `export` builds toward, or a separate local-only store
  (export is opt-in/manual/anonymized-for-sending; this is local/full-
  detail/for-your-own-tool's-use — probably not the same file)?
- Format: append-only log vs. a small local DB (sqlite) — sqlite is the
  more obvious fit once querying by date range / initiative / activity
  type across sessions matters, which #3/#4 both need.
- Who writes to it — every CLI invocation opportunistically, or a
  separate periodic job? See session-identification question below.

### 3. A timeline / behavior-change view (uses history, needs real timestamps)

Every transcript entry already carries a timestamp; today nothing does
anything with the *trend* of that data beyond `limits`' rolling window.
Once session history (above) exists, a timeline view becomes possible:
cost/activity-mix over time, not just a snapshot — closer to #4's
proposal but framed specifically around *behavior change*: has chapter
mix shifted from debugging to feature-build, has subagent usage gone up,
has skill adoption changed. This is a strong demo candidate precisely
because it's the kind of thing a person can't eyeball from raw
transcripts themselves — it only becomes visible in aggregate.

Concretely, this needs correct handling of the timestamp questions #4
and #19 already flagged rather than glossed over:
- `--since`/`--until` filtering today buckets by transcript
  *last-modified* time (an approximation), not true session start/end —
  fine for a coarse date filter, not fine enough for a real timeline axis.
  A timeline view needs per-turn or per-chapter timestamps, which the
  raw data already has (every transcript line is timestamped) — the gap
  is in what gets carried forward into the aggregated/cached layer, not
  in the source data.
- The rate-limit-hit marker research from #19 is itself a good first
  timeline signal (exact timestamp, exact reset time, no calibration) —
  worth surfacing on the same timeline as cost/activity, not just as a
  `recommend` finding.

Open questions:
- Granularity: per-day is probably right for a first cut (matches
  `--since`/`--until`'s existing `YYYY-MM-DD` grain) — per-session is too
  noisy, per-week may hide real week-over-week shifts.
- Terminal sparkline (cheap, matches #4's "terminal-native option") vs.
  a chart in the local web UI (above) — probably both eventually, web UI
  first since it's the richer surface.
- Does this belong under `activity --report` (activity mix over time),
  under a new `work-ledger timeline`, or as a tab/section of the web UI
  rather than its own subcommand?

### 4. Getting smart about session identification (a prerequisite, not a nice-to-have)

Raised directly: "we need to get smart about how we identify all the
sessions and run them." This matters more once history/periodic runs
exist than it does today, because right now every command is invoked by
a human, once, against one clearly-intended session. A periodic/
background job doesn't have that — it needs to reliably answer "which
sessions exist, which are new since last run, which one is 'this project'
vs. 'that project'" without a human picking.

What already exists to build on: `sessions` (enumeration), `--session
<uuid-or-prefix>` (lookup by transcript id), `session set/status/clear`
(pinning). What's missing for unattended/periodic use:
- **Idempotent incremental discovery** — a periodic run needs "what's new
  since the last sweep," not a full rescan of every transcript under
  `~/.claude/projects/` every time (`chapters --all`'s existing caching
  handles this per-session already; the history store needs the same
  discipline at the session-enumeration level, not just the per-chapter
  level).
- **Stable session identity across the tool's own history store** — the
  transcript UUID is stable and already used everywhere; the open
  question is whether the history store keys on that directly or needs
  its own identifier if/when cross-machine or cross-install merging ever
  matters (probably: keep keying on the transcript UUID, don't invent a
  new id without a reason to).
- **Project/workspace grouping** — `sessions` already surfaces "project"
  per session; a timeline or history view will want to filter/group by
  it (as well as show an all-projects rollup) rather than only ever
  operating per-transcript.

This doesn't need its own new mechanism so much as it needs the existing
`sessions`/`--session`/pinning machinery to be the thing #2's history
store and #3's timeline both build on, rather than a parallel discovery
path getting invented alongside them.

## Non-goals (for this doc)

- Deciding *which* of the three new directions to build first — that's a
  prioritization call, not a design one, and depends on what's most
  useful to demo next.
- Solving Do-stage automation itself. This doc is explicitly about
  Show/Tell maturity (deeper visibility, real history, real trends) and
  the guardrail for when Do-stage work eventually starts — not a design
  for the first Do-stage feature.
- Choosing the local web UI's tech stack, the history store's exact
  schema, or the timeline's exact chart library — flagged as open
  questions above, not decided here.

## Open questions (rolled up from above)

1. Local web UI: one-shot vs. long-running server; single-session vs.
   all-sessions scope; stdlib `http.server` vs. a small framework.
2. History store: same backing data as `export`, or a genuinely separate
   local-only store? Append-only log vs. sqlite?
3. Who writes to the history store — opportunistically on every CLI
   invocation, or a separate periodic job (and if periodic, run via what
   — cron, a Claude Code scheduled trigger, something else)?
4. Timeline granularity (day/week) and where it surfaces (new
   subcommand, `activity --report` extension, or a web-UI-only view).
5. Does session discovery for periodic/unattended runs need anything
   beyond the existing `sessions` enumeration plus incremental-since-
   last-run tracking, or is there a real gap there once nothing is
   human-driven?
