# Design: MCP Session-Aware Tools (Listing, Reports, In-Session-Credential Chaptering)

Status: **proposed** — nothing in this doc is implemented. Filed as
[#86](https://github.com/dhk/work-ledger/issues/86).
Author: written by Claude, from a design conversation with the repo owner.
Related: `docs/pattern-library-design.md` (the existing MCP server this
extends), `docs/local-model-chaptering-design.md` (the backend
abstraction Part 4 deliberately does *not* extend, see below),
`work_ledger/mcp_server.py`, `work_ledger/chapters.py`.

## Problem

`work-ledger-mcp` today exposes exactly five tools, all scoped to the
opt-in pattern-library mechanism: `list_patterns`, `report_recommended`,
`report_used`, `submit_review_findings`, `about`. None of the CLI's core
usage/cost/reporting surface is reachable from inside a live Claude
session — there's no way for the assistant to ask "what did this session
cost," list other local sessions, render a report, or run chaptering
without the user separately configuring `ANTHROPIC_API_KEY`.

Four sub-questions, each researched rather than assumed:

1. Can the server know its own session?
2. Can it browse every other local session, gracefully across
   Desktop/CLI/web/license variation?
3. Can it render a report?
4. Can chaptering run on the user's existing session credentials instead
   of a separate `ANTHROPIC_API_KEY`?

## Goals

- Extend `work-ledger-mcp` with tools for the CLI's already-mature Show
  surface (`sessions`, report rendering), not invent new computation —
  every tool proposed here calls existing, tested code paths.
- Any tool whose behavior isn't certain (own-session identity) must say
  so honestly in its output, not present a guess as fact.
- Any tool that spends real money/tokens differently than today's
  default must be opt-in and explicit, per `CLAUDE.md`'s reversibility
  rule ("spends money or touches shared state... needs its own explicit
  opt-in gate, same pattern `patterns enable` already uses").

## Non-goals

- Exposing `chapters`/`activity`/`trend`/`rollup`/`waste`/`limits` as
  full MCP tools in this pass — this doc scopes to the four questions
  above. A broader "every CLI command as an MCP tool" pass is a natural
  follow-on but not designed here.
- Solving own-session identity via anything other than what's documented
  today. If Claude Code later adds a documented session identifier, this
  doc's Part 1 recommendation should be revisited, not worked around with
  a fragile heuristic now.
- MCP sampling. Confirmed unimplemented in Claude Code (see Part 4) —
  tracked upstream at
  [anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785),
  not designed around here.

## Part 1: Own-session identity — not solvable precisely today

**Researched, not assumed.** Claude Code sets `CLAUDE_PROJECT_DIR` when
launching a local/stdio MCP server — documented, reliable, gives the
project root. There is no documented session-UUID (or transcript-path)
equivalent passed to the subprocess, no MCP protocol-level mechanism
confirmed to carry it, and no documented difference in this behavior
across Claude Code CLI, Desktop, or web sessions (silence in the docs,
not a confirmed "same everywhere").

The only remaining move is a heuristic: correlate `CLAUDE_PROJECT_DIR` to
its mangled directory under `~/.claude/projects/`, then guess "most
recently modified transcript in that directory" as "probably me." This
has a real, common failure mode: two sessions open in the same project at
once (exactly the working pattern of the conversation that produced this
doc) make the heuristic's answer non-deterministic and possibly wrong.

**Recommendation: don't build a `current_session` tool that claims
certainty.** If a best-effort version is wanted later, it must be named
and documented as a guess — e.g. `most_likely_session()` returning the
heuristic's answer plus an explicit `confidence: "guess"` field — never
presented as `current_session()`. Reuse `server.py`'s existing
`_matching_transcripts` disambiguation posture (return an explicit
"more than one candidate" result rather than silently picking one) as
the precedent for how to fail honestly here.

## Part 2: All other sessions on this machine — mostly free

`find_all_transcripts()` already sweeps `~/.claude/projects/**/*.jsonl`,
and every multi-session command (`sessions`, `trend`, `rollup`, `serve`,
`waste --cross-session`) already degrades to "no sessions found" rather
than erroring when the directory is empty or missing — exactly the
posture this session's own cloud/remote environment exercises today (its
`~/.claude/projects/` holds exactly one transcript: this session's own).

Proposed tool: `list_sessions(since=None, until=None, top=None)` —
thin wrapper around `build_session_rows()`/`top_n_session_rows()` (the
same functions `sessions`/`sessions --top` and `serve --top` already
share), returning the same row shape `sessions --json` already prints.
No new computation.

**Open, unverified:** whether Team/Enterprise plans redirect or restrict
local transcript storage in a way that changes what's visible here. Not
documented anywhere checked so far; flagging rather than asserting either
way. If a managed deployment turns out to write transcripts somewhere
else (or not at all), this tool's existing "no sessions found" degrade
already covers that case mechanically — but the *reason* shown to the
user would be generic ("none found") rather than specific
("your plan doesn't retain local transcripts"), which would need real
evidence from an actual Team/Enterprise environment to write accurately.

## Part 3: Render reports — straightforward

Proposed tool: `render_report(kind, format="html", transcript=None,
out=None)` where `kind` is `"chapters"` or `"activity"` — same code path
`chapters --report`/`activity --report` already call
(`build_report_html`/`build_activity_report_html`/`render_png`), writes
the file, returns `{path, format}`. Not the raw HTML/PNG bytes as tool
output — that would bloat the assistant's context for no reason a file
path doesn't already solve.

PNG still needs the `report` extra (Playwright) and degrades identically
to the CLI: a clear error naming the missing extra, never a silent
fallback to HTML. No open questions.

## Part 4: In-session-credential chaptering (the flag proposal)

### Why this can't be a fourth `ChapterBackend`

`ChapterBackend.call(outline, prior_chapter_titles) -> BackendResponse`
is a single synchronous function call (see
`docs/local-model-chaptering-design.md`'s Architecture section) —
`AnthropicBackend`/`OllamaBackend` both return a completion from inside
one function. There is no way to implement "ask whatever model is
running this live session" as one synchronous function from inside a
CLI subprocess: a `work-ledger chapters` process spawned via a Bash tool
call has no channel back to the model that spawned it, and MCP sampling
(the protocol-native version of that channel) is confirmed unimplemented
in Claude Code
([anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785),
open since June 2025).

So this doesn't live in `chapters.py`'s backend list. It's a different
shape entirely: two separate tool calls, with the actual reasoning
happening in the assistant's own turn between them, not inside either
tool.

### The two-tool handoff

1. **`get_chaptering_outline(transcript=None)`** — runs exactly the first
   half of `get_chapters()`: load the cache (`_load_cache`), find turns
   not yet chaptered, build the outline (`_build_outline`) and prior-
   titles context (`_build_context`) exactly as today. Returns
   `{outline, prior_chapter_titles, new_prompt_ids, schema}` — the schema
   being `_ChaptersOut.model_json_schema()`, the same one `OllamaBackend`
   already sends to a local model. Makes no model call itself.
2. The assistant reads the outline in its own turn and reasons about it
   — using whatever model the session is already running, no separate
   API call, no separate credential.
3. **`submit_chapters(chapters: [...])`** — receives the structured
   result and runs exactly the second half of `get_chapters()`:
   `_validate_partition(parsed, new_ids)` (the existing safety net that
   already catches a model dropping or duplicating `prompt_id`s — reused
   unchanged, not reimplemented), fallback to a single "Unsorted" chapter
   for anything the response fails to cover validly (same as every other
   backend failure today), then the same cache merge/write
   (`_save_cache`) every other path uses. From the cache file's
   perspective, this looks identical to any other backend having run.

This reuses `_build_context`/`_build_outline`/`_validate_partition`/
`_save_cache` verbatim — the only new code is the tool-call split itself
and the transcript-targeting logic below.

### Which transcript's cache?

Same problem as Part 1, narrower: `get_chaptering_outline`/
`submit_chapters` need to agree on one transcript. Given Part 1's
conclusion, this can't default to a silently-guessed "current session."
Proposed: require an explicit `transcript`/`session` argument (same
`--transcript`/`--session` precedent every other command already uses),
defaulting only when `find_all_transcripts()` + `CLAUDE_PROJECT_DIR`
narrows to exactly one unambiguous candidate — otherwise return the same
"more than one candidate, be specific" shape `server.py`'s
`_matching_transcripts` disambiguation already returns for `serve`,
rather than guessing.

### The flag

Per `CLAUDE.md`'s reversibility rule, this needs its own explicit opt-in
gate — not a runtime check inside the tool, but the tools not existing
at all until asked for:

```
work-ledger-mcp --allow-session-credentials
```

A launch-time flag on `work-ledger-mcp` itself (visible in your own
`claude mcp add work-ledger -- work-ledger-mcp --allow-session-credentials`
command, so opting in is an action you can see in your own config, not a
buried env var). Only when present does the server register
`get_chaptering_outline`/`submit_chapters` at all — off by default means
the tools genuinely don't exist, not "exist but no-op," the stronger of
the two gates already used elsewhere in this codebase (compare
`patterns enable`'s persistent toggle, which gates *behavior* of tools
that always exist).

`WORK_LEDGER_CHAPTER_BACKEND=session` is deliberately **not** proposed as
a parallel CLI-level selector: a bare `work-ledger chapters` typed in a
terminal has no live session to delegate to, so setting a backend value
that can only ever fail there would be confusing rather than useful. The
flag lives only on `work-ledger-mcp`'s launch command, where the
mechanism is actually possible.

### The real trade-off — cost moves, it doesn't disappear

Today, `chapters` prints this before running:

> "Chaptering makes a separate Claude API call (Haiku) — distinct from
> the token-pricing estimate below, and billed to your Anthropic API
> account, **not your Claude Code session**."

In-session-credential chaptering inverts that boundary: chaptering
becomes part of the session's own token usage — the exact thing
work-ledger measures and prices. A chaptered session's own reported cost
would go up because it was chaptered, which is a genuinely different
UX from today's "free, separate side-cost" framing. `--allow-session-
credentials`' own help text (and any UI presenting a chapter produced
this way) needs to say this plainly, not let it be discovered as a
surprise in a later cost report. `render_report`/`list_sessions` are
unaffected — they read already-computed data, they don't run a model.

Also worth being explicit that this is a first: `docs/architecture.md`
frames work-ledger as "a reader, never a participant, in the Claude Code
session itself." Every existing network path is a side-call the
session's own transcript doesn't reflect. This is the first proposal
where work-ledger's own operation shows up inside the thing it measures
— not disqualifying, but a real precedent, not a small tweak.

## Migration / compatibility

- Existing `<session>.chapters.json` cache files are unaffected — a
  chapter written via `submit_chapters` is indistinguishable in format
  from one written by `AnthropicBackend`/`OllamaBackend`.
- Zero change to any existing tool, command, or default. `list_sessions`/
  `render_report` are additive; `get_chaptering_outline`/
  `submit_chapters` don't exist unless `--allow-session-credentials` is
  passed.

## Open questions

1. **Own-session identity** — not a design choice, a documented-today
   fact: not solvable precisely. Revisit only if Claude Code documents a
   session identifier in the future; don't build a heuristic presented
   as certainty in the meantime.
2. **Team/Enterprise local-transcript-storage variance** (Part 2) —
   unverified either way. Needs real evidence from an actual managed
   deployment before writing anything more specific than today's generic
   "no sessions found" degrade.
3. **Exact ambiguity-resolution shape for Part 4's transcript targeting**
   — sketched above (reuse `_matching_transcripts`' disambiguation
   posture) but not fully specified; needs to be pinned down during
   implementation, not before.
4. **Should a produced-via-session-credentials chapter be marked in the
   cache file** (e.g. a `backend: "session"` field, mirroring how the
   cache could in principle record which of Anthropic/Ollama produced
   each chapter today but currently doesn't)? Not decided — today's cache
   format doesn't track backend provenance at all, so this would be new,
   not an extension of an existing field.
5. **MCP sampling** — tracked upstream
   ([anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785)),
   not designed around. If it ships, it would let `get_chaptering_outline`/
   `submit_chapters` collapse into one call - worth revisiting this doc
   at that point, not before.
