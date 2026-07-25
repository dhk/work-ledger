# Architecture

Status: adopted — describes the system as built, unlike the other
`docs/*.md` files which mostly propose unbuilt features. Update this file
when the *shape* of the system changes (a new core abstraction, a new
network boundary, a new persisted store) — not for every feature added
inside the existing shape.

This is the "how is it built" reference the roadmap's guardrail step
checks new work against — see `ROADMAP.md`'s "Using this as a guardrail".
For "what it is and why," see `PRODUCT_BRIEF.md`. For per-feature
proposals, see the other files in this directory.

## Data source and boundary

Everything work-ledger knows comes from Claude Code's own local session
transcripts (`~/.claude/projects/**/*.jsonl`), plus their subagent
sidecars (`<session>/subagents/agent-<id>.jsonl` + `.meta.json`). Nothing
is instrumented, no telemetry SDK is embedded in anything — the transcript
already exists for every session regardless of whether work-ledger is
installed. This is the load-bearing structural choice the rest of the
system follows from: work-ledger is a *reader*, never a participant, in
the Claude Code session itself.

Known gap in this boundary, tracked separately: an older/different
install that inlines subagent activity as `isSidechain` entries in the
main transcript file (rather than the separate-file format above) isn't
parsed — see #46.

## Core data model

Three layers, each built strictly on top of the one below it — no layer
re-derives from raw JSONL itself except the bottom one:

1. **`Unit`** (`transcript.py`) — one assistant message, i.e. one real LLM
   API call (`message.id`). Transcripts write one JSONL line per content
   block (thinking/text/tool_use) but repeat the full `usage` block on
   every line for the same message — `Unit` is the dedup boundary that
   fixed the original 2-4x cost overcounting bug. Carries its own
   input/output tokens/cost plus, if it dispatched a subagent, that
   subagent's rolled-up usage too (`subagent_input_tokens` etc. populated
   asynchronously once the sidecar file is found). `Unit.kind` (`text` /
   `skill` / `subagent`) and `Unit.label` are what `activity.py` groups
   by — this is the one place "what kind of work was this" is decided.
2. **`Turn`** (`transcript.py`) — one full prompt exchange: a `prompt_id`
   plus every `Unit` (LLM call) that resulted from it. This is the
   default granularity the CLI dashboard shows; `--detail` drops down to
   the `Unit` level instead.
3. **`Chapter`** (`chapters.py`), made of `Section`s — a labeled group of
   `Turn`s representing one initiative ("Build the v1 dashboard"), plus a
   fixed-taxonomy `category`. This grouping can't be derived
   structurally (one initiative can span many prompts; one prompt can
   touch several), so it's the one layer that isn't purely local
   computation — see "Network calls" below.

Every other module (`activity.py`, `export.py`, `recommend.py`,
`report.py`) computes its view by summing/grouping this same
`Turn`/`Unit`/`Chapter` data — none of them re-parse the transcript or
introduce a competing cost calculation. `pricing.py` is the single seam
where token counts become dollars (`estimate_cost_usd`), keyed by model
id off a hardcoded rate table (`RATES`) — this is also the one place a
model-pricing change (see #47) needs to be reflected.

## Caching and persistence

- **Chapter cache** (`chapters.py`, `_cache_path`) — one
  `<session-id>.chapters.json` file next to each transcript, holding
  already-labeled chapters/prompt-ids. Deliberately **frozen-prefix
  forever**: re-running only chapters newly-added turns, never re-pays
  for or retitles something already cached. Known, accepted tradeoff: an
  early mis-titled chapter can't self-correct later. See
  `docs/session-chaptering-design.md` and #16 (the local-model backend
  proposal that would remove the cost reason for freezing).
- **Session pin** (`session_pin.py`) — a small local file remembering
  which session `chapters`/`activity`/`recommend` should default to,
  separate from the per-transcript cache above.
- **Limits threshold** (`limits.py`) — `~/.config/work-ledger/
  limits_threshold.json`, a user-calibrated token threshold, unrelated to
  any transcript.
- **No cross-session store exists yet.** `chapters --all` re-derives its
  session list by walking `~/.claude/projects/` fresh every run (cheap
  because each session's own `.chapters.json` cache still avoids
  re-chaptering). #42 proposes an actual persisted history store; until
  it lands, "cross-session" always means "re-sweep, then aggregate."

## Network calls (the exhaustive list)

Everything above this line is 100% local. There are exactly three places
work-ledger talks to a network, all opt-in or explicitly disclosed, never
silent:

1. **`chapters`' Haiku pass** — the only place real session content
   (prompt/unit snippets) leaves the machine at all. Requires the user's
   own `ANTHROPIC_API_KEY` (or `ant auth login`); on any failure
   (missing/invalid key, refusal, malformed response, exception) falls
   back to a single "Unsorted" chapter rather than crashing, with a
   specific, distinguishable error message per failure mode.
2. **Pattern-library counters** (`pattern_client.py`) — two anonymous
   counter increments (`report_recommended` / `report_used`) to a
   personally-run backend, only when `patterns enable` has been run and
   `WORK_LEDGER_PATTERN_BACKEND_URL` is set. Silent no-op, never an
   error, if either is missing.
3. **Findings submission** (`mcp_server.py`'s `submit_review_findings`) —
   forwards `ReportFindings`-shaped code-review output to the same
   backend. Needs both the URL above and a separate
   `WORK_LEDGER_FINDINGS_TOKEN` bearer credential, on top of the
   `patterns enable` gate — a stricter bar than the counters since this
   one carries free text. Same silent-no-op-if-unconfigured behavior.

`export` is explicitly **not** on this list — it writes a local file and
stops; there is no fourth network call hiding behind it.

## Module map

| Module | Owns |
|---|---|
| `transcript.py` | Locating/tailing transcripts; `Unit`/`Turn`; the message.id dedup fix; subagent sidecar correlation |
| `chapters.py` | `Section`/`Chapter`; the Haiku labeling pass; frozen-prefix cache |
| `activity.py` | Grouping cost by `Unit.kind`/`skill_name`/`subagent_agent_type`/`tool_names` — no API call |
| `pricing.py` | The `RATES` table and `estimate_cost_usd` — the only tokens→dollars conversion in the codebase |
| `export.py` | Building the local anonymized export JSON — never sends it anywhere |
| `recommend.py` | Local, rule-based heuristics over `Turn`/`Unit`/`Chapter` |
| `patterns.py` | Loading the shared pattern library's local `*.md` entries |
| `pattern_client.py` | Opt-in gate, per-install anonymous id, counter reporting to the backend |
| `limits.py` | Rolling Pro/Max session-window usage; self-calibrated threshold |
| `timeline.py` | Day-bucketing `activity.py`'s categorization plus cached chapter categories - how practice changed over time, not what it cost |
| `trend.py` | Day/week-bucketing `Turn.cost_usd` - is spend trending up or down, the cost axis `timeline.py` deliberately excludes |
| `report.py` | Self-contained HTML/PNG rendering shared by `chapters --report` / `activity --report` |
| `session_pin.py` | The "pin a session" mechanism |
| `mcp_server.py` | The local MCP server exposing pattern-library tools over stdio |
| `cli.py` | Argument parsing and the live terminal dashboard; wires every module above into subcommands |

## Structural constraints (don't violate without updating this doc)

- A new feature that reads transcript data goes through `transcript.py`'s
  existing `Unit`/`Turn` — it does not re-parse JSONL itself.
- A new feature that needs grouping/labeling beyond what `Unit.kind` or
  `Chapter.category` already provide extends those, rather than inventing
  a parallel categorization scheme (this is why the timeline view, #44,
  is scoped as "reuse `activity.py`'s taxonomy with a time axis added,"
  not a new one).
- Any new network call is opt-in, disclosed in this file's "Network
  calls" section, and never blocks core (local-only) functionality on its
  availability.
- Any new persisted store lives beside the transcript it derives from (or
  in `~/.config/work-ledger/`, matching `limits.py`'s precedent) — not in
  a location that implies it's synced or shared anywhere.
