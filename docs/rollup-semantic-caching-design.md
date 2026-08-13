# Design: Persistent Caching for Semantic Rollup Matching

Status: **proposed, not decided, not built.** Raised in a live session
after using `WORK_LEDGER_ROLLUP_MATCHING=semantic` for real reporting;
started sketching an implementation, then the repo owner flagged the
sketch as under-thought and asked for this doc instead of code, to
revisit deliberately later. Nothing here is authoritative - it's a
starting point for that later conversation, not a spec to implement
as-is.
Author: written by Claude, from an in-progress implementation attempt
that surfaced real open questions before any code shipped.
Related: issue #96 (this doc's own tracking issue), issue #93 (where this
came up), `docs/rollup-semantic-matching-design.md`
(issue #68 - the feature this proposes changing; its Non-goals section
explicitly decided against caching, see below), `docs/session-chaptering-design.md`'s
"Decided: caching, frozen prefix" (the closest existing precedent for a
frozen/incremental cache, and issue #91's fix to it - a cautionary tale
about freezing the wrong thing), `work_ledger/rollup_semantic.py`,
`work_ledger/rollup.py`'s `_apply_semantic_pass`/`RollupResult.key_map`.

## Problem

`WORK_LEDGER_ROLLUP_MATCHING=semantic` (issue #68) batches whatever
chapter titles are still singletons after deterministic matching into
one Haiku call proposing merges among them, every single time `rollup`
(or `waste --cross-session`) runs. That was a **deliberate** decision -
issue #68's own Non-goals section: *"Merge-decision caching, versioning,
or a journal of what got merged with what over time. Explicitly decided
against for this pass: the repo owner is fine with cluster membership
drifting run-to-run... If this needs revisiting later..., that's new
evidence for a follow-up doc - not designed here."*

That evidence arrived: real use means running `rollup`/`rollup --report`
repeatedly (checking a report, regenerating it, feeding `serve`, etc.),
and re-paying (tokens, latency) for the same singleton titles' merge
decisions on every single run is real, recurring waste - not a one-off
annoyance. The ask: run semantic matching deliberately once, "set" the
resulting decisions, and have all the *reporting* that follows (plain
`rollup`, `rollup --report`, `--preview`, `waste --cross-session`) reuse
them for free, indefinitely, until the person explicitly decides to
redo it.

## What got sketched, and why it stalled

Initial direction, from a quick round of questions with the repo owner
(not re-litigated here, but recorded since it's a reasonable starting
point for the real design pass):

- **Trigger: explicit, not automatic.** A deliberate action (e.g.
  `rollup --confirm --set`, or a dedicated subcommand) runs the semantic
  pass and persists its decisions. Plain `rollup` runs never spend
  tokens on their own, even with the env var set - only the explicit
  action calls the model.
- **Staleness: frozen, like `chapters.py`'s cache.** A cached decision
  is never silently revisited by a later run. Refreshed only by an
  explicit action (re-running the "set" step, or clearing the cache
  file by hand).
- **Location: one global cache file** (e.g.
  `~/.config/work-ledger/rollup-semantic-cache.json`), not scoped per
  `--since`/`--until` window - rollup clustering is inherently
  cross-session/cross-project, so a per-scope cache would mean redeciding
  the same titles every time the date range shifts even slightly.

Implementation stalled on a real technical gap in that sketch, not just
polish:

**A cached decision is a *group* fact, not a *title* fact, and new
titles need to be judged against existing groups, not just each other.**
`_apply_semantic_pass` today batches *all* current singletons into one
call and asks "which of these belong together" - a closed-world
question. A cache changes the question a later run needs answered to
"does this brand-new singleton title belong with the 'PAE investigation'
group I already decided on last month, or is it something new" - an
open-world question that needs the *existing* group's representative
title(s) as context, not just the new batch. Naively remapping each
title's `normalize_title()` key through a flat `{key: primary_key}`
cache (the literal persisted form of today's in-run `RollupResult.key_map`)
handles "I've seen this exact title's key before" for free, but does
**nothing** for a differently-worded new title that should join an
existing cached group - which is exactly the paraphrase problem #68 was
built to solve in the first place. A cache that only catches exact
repeats of a title already isn't earning its complexity; the interesting
case is the one it doesn't solve without a real design for "propose
merges against existing groups," not just "propose merges within a
fresh batch."

Other loose threads noticed but not resolved:

- **Does the cache also change `waste --cross-session`?** #68 explicitly
  made both consumers share one clustering entrypoint "so enabling
  `WORK_LEDGER_ROLLUP_MATCHING=semantic` changes clustering for both...
  identically." Does a persisted cache preserve that symmetry, or does
  `waste` want its own cache lifecycle (it's asking a different question -
  "is this a repeated pattern" - not "what's this report's total")?
- **What does "reconsider a bad merge" look like?** #68's Non-goals
  already parked "a full override/correction/pinning system" as out of
  scope, deferred to a separate project. A frozen cache makes a *wrong*
  merge sticky too, not just a right one - does fixing that still route
  through that separate project, or does this doc need its own answer?
- **Cache format/versioning**, invalidation on `rollup_semantic.py` logic
  changes (a schema/prompt change could make an old cached decision mean
  something different than it would today), and whether cache entries
  should carry a timestamp/provenance (which run's `--set` produced this,
  against which title batch) for later debugging - none of this was
  worked out.
- **Interaction with `#66`/`#3`-style "first-seen title kept" and
  `#91`'s "don't freeze a failure" lesson** - a *successful* semantic
  merge is a real, paid decision (same category chaptering's frozen-
  prefix cache already freezes correctly), but this doc should make that
  distinction explicit rather than accidentally repeating #91's mistake
  of freezing something that wasn't actually a completed decision (e.g.
  a batch that partially failed, or a fallback_reason'd call).

## Non-goals (for now)

- **Not designed here**: the actual "judge new title against existing
  groups" mechanism - prompt shape, how much of an existing group's
  context to send back to the model, cost/latency implications of doing
  that per-new-title vs. batched.
- **Not designed here**: override/correction tooling for a bad merge -
  still deferred to the separate project #68 already pointed at, unless
  this doc's eventual real pass decides that's no longer sufficient.
- **Not decided**: whether this ships at all. The token-cost problem is
  real, but a cache that only dedupes exact-repeat titles doesn't solve
  it convincingly - worth confirming the harder "new title vs. existing
  group" mechanism is actually buildable at reasonable cost/complexity
  before committing to this direction over alternatives (e.g. a cheaper
  "only re-run semantic matching if the singleton set actually changed
  since last time" heuristic that doesn't need per-group context at all).

## Open questions

1. Is there a simpler win available first? E.g.: skip the "judge new
   title against existing group" problem entirely - only ever compare
   the *current* run's full singleton batch, but skip the call entirely
   if that batch is identical (same title set) to whatever batch
   produced the last cached result. This solves "don't re-pay for
   reporting on already-decided data" (the actual complaint) without
   solving the harder incremental-new-title problem, at far less design
   cost. Worth scoping before the fuller version.
2. If the fuller "judge against existing groups" version is worth
   building, what does the actual model prompt/schema look like -  is
   it a per-new-title classification call ("does this belong to any of
   these N existing groups, or none"), or does it still work in batches
   but seeded with existing group representatives as extra context?
3. Does `--confirm`'s existing "print what merged" visibility need to
   grow into something that also shows "N titles matched an existing
   cached group for free, M new titles needed a fresh call" - i.e. does
   the visibility/observability need change shape once caching exists?
4. What's the actual command surface - a flag on `rollup` (`--set`), a
   separate subcommand, or something under a different verb entirely
   (this doc's Related section deliberately doesn't presuppose that)?
