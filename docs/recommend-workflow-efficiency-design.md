# Design: Recommend Workflow-Efficiency Improvements from Session Logs

Status: proposed, not yet built.
Author: written by Claude, from a design conversation with the repo owner.
Related: `work_ledger/recommend.py` (existing, cost-only heuristics this
extends), issue #5 (recurring-pattern/waste mining), issue #6
(deterministic-tool substitution, blocked on #5), issue #3 (cross-session
rollup - needed for some signals here).

## Problem

`recommend` today answers one question: "which chapter cost more than it
should have." That's useful but narrow - it only reasons about dollars,
and only within a single session. It has nothing to say about a different,
equally real class of waste: a workflow that's *inefficient* even when no
single call is expensive - the same manual step repeated every session,
the same tool permission approved by hand every time, a repeated pattern
that a skill, a config change, or a different tool would remove entirely.

This doc proposes widening `recommend`'s scope from "what cost too much"
to "what would make this workflow better," across four concrete
recommendation categories: **user actions**, **configuration**, **new
skills**, and **new tools**.

## A concrete signal that already exists, verified against real data

While scoping this, checked whether Claude Code's own transcripts record
anything usable for the "user actions" category - specifically, whether
hitting the Claude Pro/Max session limit (the original motivation for
`work-ledger limits`) is recorded anywhere beyond the token totals
`limits.py` already sums.

It is. Claude Code writes a synthetic assistant message when a request is
rate-limited:

```json
{
  "type": "assistant",
  "timestamp": "2026-07-11T23:15:14.228Z",
  "error": "rate_limit",
  "apiErrorStatus": 429,
  "message": {
    "model": "<synthetic>",
    "content": [{"type": "text", "text": "You've hit your session limit · resets 11:40pm (UTC)"}]
  }
}
```

Confirmed against this project's own session transcript (5 occurrences).
This is strictly better than `limits.py`'s current self-calibrated
token-threshold estimate: it's the actual event, with an exact timestamp
and reset time, parsed straight out of the transcript - no calibration,
no guessing. This becomes the first concrete "user action" signal below
(see Category 1), and is also worth a smaller, standalone improvement to
`limits.py` itself independent of this doc (surfacing "you hit your limit
N times this week, at these times" directly, alongside the existing
rolling-window estimate).

## Goals

- Widen `recommend` from cost-only to workflow-efficiency broadly, without
  discarding the existing cost-based rules (outlier chapter cost,
  subagent-heavy chapters, repeated skill invocation) - those stay, this
  adds categories alongside them.
- Every recommendation traces to a concrete, inspectable signal in the
  logs - no vague "you could be more efficient," always "here's the
  specific repeated thing, here's how many times, here's what to do."
- Keep the existing rule's shape: local-only where possible, no corpus
  dependency required to ship a first version (cross-session signals are
  called out separately, not required for v1).
- Stay a small, curated set of checks, same philosophy as the existing
  module's docstring ("a first cut... not a big speculative rule engine").

## Non-goals (for this pass)

- Automatically applying any recommendation (e.g. auto-editing
  `settings.json`, auto-installing a skill). `recommend` reports, it
  doesn't act - matches the existing module and the tool's broader
  "never do anything surprising" posture.
- Cross-session pattern mining in full (issue #5) - this doc identifies
  which of its signals need cross-session data and defers those, rather
  than re-designing #5 here.
- A generic "efficiency score" or single number - recommendations stay a
  list of discrete, specific findings, same as today.

## The four recommendation categories

### 1. User actions

Behavioral signals about *how* the user is working, not what any single
call cost.

- **Session-limit hits** (the verified signal above): scan for
  `isApiErrorMessage` + `error: "rate_limit"` entries. A session with
  multiple hits, or hits clustering at a similar time of day across
  multiple sessions (needs cross-session data - see Open Questions),
  surfaces as "you hit your session limit N times this week, usually
  around HH:MM - consider spacing out heavy work, or this is a signal
  your current plan tier doesn't match your usage."
- **High interruption/redo rate**: turns that get abandoned or
  immediately re-asked with clarifying instructions can indicate the
  *user's* request was underspecified, not that the model did anything
  wrong. Signal: a short turn immediately followed by a much longer
  clarifying turn on the same topic. Needs care to distinguish from
  normal iterative work - likely the hardest signal in this doc to get
  right without false positives (see Open Questions).

### 2. Configuration

Signals that point at a `settings.json`/`CLAUDE.md`/permissions change,
not a code or workflow change.

- **Repeated manual permission approvals**: the same Bash command pattern
  or MCP tool approved by hand across many turns is exactly what the
  existing `fewer-permission-prompts` skill already detects manually
  ("Scan your transcripts for common read-only Bash and MCP tool calls,
  then add a prioritized allowlist to `.claude/settings.json`"). That
  skill is real prior art and a bar to reach, not a hypothetical - the
  goal here is for `recommend` to surface the same finding automatically
  as part of its regular output, not replace the skill (a user can still
  run it directly for the deeper pass).
- **Thin or missing `CLAUDE.md`**: sessions that repeatedly re-explain the
  same project context (same file paths, same conventions restated) are a
  signal that context which should live in `CLAUDE.md` is instead being
  retyped every session.

### 3. New skills

A recurring multi-step pattern - the same sequence of tool calls, close
enough in structure across multiple turns or sessions - is a candidate
for a Claude Code skill (a named, reusable procedure), not just a
one-off script (that's issue #6's framing, for arbitrary deterministic
tools; a *skill* specifically is the Claude-Code-native version of the
same idea, and deserves its own category since it's a different kind of
artifact with a different install path).

- Signal: near-identical tool-call sequences (same tools, same rough
  order) recurring across chapters/sessions, above some repeat threshold.
- Overlaps with issue #5 (waste mining) for the detection mechanism - the
  difference is the recommended fix (a skill) vs. #5's broader framing
  (any fix). This category is what #5's output would feed into once #5
  exists; not re-designed here.

### 4. New tools

Where the recurring pattern isn't a procedure the model already knows how
to do well, but a capability gap - the same manual back-and-forth that an
MCP connector or tool integration would remove entirely (e.g. repeatedly
copying data between two systems by hand, repeatedly asking for something
a dedicated tool would do in one call).

- Hardest category to detect from logs alone versus categories 1-3, since
  it requires recognizing "this manual workaround exists because tool X
  is missing," not just "this pattern repeats." Likely needs to stay the
  most conservative/rare of the four categories in a first version -
  flagged only for very clear, repeated cases, not attempted generically.

## Data needs: single-session vs. cross-session

Categories 1 (partially) and 3 benefit significantly from cross-session
data (issue #3, not built yet) - "this happens every session" is a
stronger, more actionable finding than "this happened once in this
session." Categories 2 and 4, and the non-clustering part of category 1
(a single session with multiple rate-limit hits), work fine single-session
and can ship without waiting on #3.

Proposed sequencing: ship what works single-session first (permission
patterns, thin CLAUDE.md, rate-limit hits within one session), and defer
the cross-session-dependent refinements (rate-limit clustering across
sessions, skill-candidate detection across sessions) until #3 exists -
same "don't build ahead of the data" principle already applied to #5/#6.

## Open questions

1. **False-positive risk on "high interruption/redo rate."** Of the four
   categories, this is the one most likely to misfire on completely normal
   iterative work. Needs either a conservative threshold decided against
   real sessions, or possibly dropping it from v1 entirely and starting
   with the other three categories, which have clearer signals.
2. Does the rate-limit-hit signal belong in `recommend`, in `limits`, or
   both? It's arguably as much a `limits.py` feature (the module already
   owns "session limit" framing) as a `recommend` one. Leaning toward:
   surface raw hit history in `limits` (a factual report), and have
   `recommend` reference it as one input among several for a "user
   actions" finding - not decided.
3. What repeat-count threshold makes a skill/tool recommendation (category
   3/4) worth surfacing rather than noise? Needs tuning against real
   sessions, not a number to guess at up front.
4. Should recommendations from these new categories carry an estimated
   time-savings figure (turns/minutes) the way cost-based ones carry a
   dollar figure, or is "this happened N times" sufficient on its own?
