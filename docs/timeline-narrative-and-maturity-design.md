# Design: Timeline Narrative Summary + Maturity Correlation

Status: proposed, not yet built. Part 1 (narrative summary) is scoped
enough to build directly. Part 2 (maturity correlation) is explicitly a
bigger, undecided idea — see Open Questions; Option A there is buildable,
Option B is deliberately out of scope for this doc.
Author: written by Claude, from a design conversation with the repo owner.
Related: issue #66, `docs/show-tell-do-model.md` (original timeline
proposal), `work_ledger/timeline.py` (issue #44, what this extends),
`work_ledger/rollup.py` (issue #3, the clustering Part 2 Option A reuses),
`PRODUCT_BRIEF.md`'s data-source boundary, `docs/architecture.md`'s
"Data source and boundary" section.

## Problem

`work-ledger timeline` shows day-bucketed chapter-category mix
(feature-build, debugging, refactor, ...) as raw counts/sparklines. Read
directly, it doesn't "pop" — the interesting fact (how your approach has
shifted) is buried in a grid of numbers rather than said in a sentence.
Reviewing it surfaced two related but separately-scoped ideas:

1. Turn the shift itself into a plain-language sentence: "You used to
   spend most days on X; more recently it's Y."
2. Go further and ask whether that shift tracks the actual maturity of
   the work being done — is a move from debugging toward docs/refactor a
   sign an initiative matured, or is the category mix drifting
   independent of what's actually being built?

## Goals

- Narrate a category-mix shift over a queried date range in 1-3
  sentences, deterministically (no LLM/embedding call — matches every
  other Show-stage narrative precedent in this codebase, e.g. `cli.py`'s
  per-session `_session_summary()`).
- Reuse `timeline.py`'s existing `TimelineResult`/`category_counts` — no
  new categorization scheme, no new data source, no new network call.
- Keep the maturity-correlation half explicitly optional/phase 2 — see
  Non-goals and Open Questions. Don't block the narrative summary on it.

## Non-goals (for this pass)

- **Reading the actual project's codebase/git history** to derive a
  "true" maturity signal (test coverage, LOC churn, file staleness).
  This would be a new data source beyond Claude Code's own session
  transcripts — crossing the boundary `docs/architecture.md`'s "Data
  source and boundary" section calls the load-bearing structural choice
  of this project ("a reader, never a participant"). Flagged as a real
  idea, not dismissed, but it needs its own `PRODUCT_BRIEF.md`/
  architecture check and its own design doc before any code gets
  written — not bundled into this one. See Open Questions, Option B.
- **An LLM-generated narrative.** Same reasoning nearly every other
  module in this codebase already applies (`rollup.py`, `waste.py`):
  deterministic template-filling over already-computed data, not a
  second paid API surface, until that's proven insufficient.
- **A single "efficiency" or "maturity" score.** Same non-goal
  `recommend.py`/`PRODUCT_BRIEF.md` already commit to elsewhere —
  specific, inspectable deltas, not a vague index.

## Part 1: narrative summary (buildable now)

### Approach

Split the queried date range into two windows — the first half and
second half of the days actually present in `TimelineResult.days`, not
calendar halves, since usage is bursty and empty days shouldn't dilute
the comparison. Sum `category_counts` within each half, convert to
proportions, and find the categories with the largest proportional
swings (up and down). Render as a short templated sentence: "Early in
this range, `debugging` (42%) and `design-planning` (18%) dominated.
More recently, that's shifted toward `refactor` (35%) and `docs` (20%)."

- Reuses `top_category_labels`/`category_counts` — no new data
  collection.
- Needs a minimum-data guard: too few days or too few categorized turns
  (mirrors `uncached_sessions`'s existing "don't silently show a
  partial/misleading picture" precedent) should say so explicitly rather
  than narrating noise from a handful of data points.
- Surfaces as `work-ledger timeline --summary` (terminal) and as a
  line/section on the `--report`/`serve` HTML view — not a new command;
  this is an additional lens on `timeline`'s existing data, the same
  relationship `activity --report` has to `activity`.

### Open questions (Part 1)

1. Two-window split (first-half/second-half of days-with-data) vs.
   something more deliberate (e.g. `--since` window vs. everything
   before it)? First-half/second-half is simplest and needs no new flag,
   but may not always line up with what a person actually means by
   "used to."
2. Threshold for "large enough swing to mention" — needs a concrete
   number (e.g. only narrate a category if its share moved ≥10 points),
   to avoid narrating noise from small samples.

## Part 2: correlating the shift with maturity (bigger, not decided)

The interesting version of this isn't just "your mix changed" but "did
it change *because the work matured*, or independent of that." Two ways
to get a maturity signal, very different in cost:

**Option A (in-bounds, reuses #3): per-initiative category sequence via
rollup clustering.**
`rollup.py` already clusters chapters into the same recurring initiative
across sessions (deterministic title normalization). A given cluster's
chapters already have a natural time order (session mtime, then turn
order within a session). Read that cluster's own category sequence over
its own lifetime — "the double-counting-bug initiative went
design-planning → feature-build → debugging (×4) → refactor → docs" —
and ask whether that's a healthy taper (settling into fewer, later-stage
categories) or a stall (bouncing between the same 2 categories with no
taper). This uses only data work-ledger already has — no new data
source, no new network call, no non-goal conflict. Cost: it's a *proxy*
for maturity (the category label chaptering already assigned), not
ground truth about the actual code.

**Option B (out-of-bounds for this doc): read the actual project's
state.**
Correlate against something outside the transcript entirely — git commit
history of the project directory the session ran in, test coverage
trend, file churn. This would answer the question more directly, but
it's a structurally different feature: work-ledger has never read
anything except Claude Code's own transcripts (see
`docs/architecture.md`'s "reader, never a participant" framing), and
doing so raises real scope questions (which directory does a session
even map to; is reading a user's actual source tree, not just usage
metadata about it, still consistent with `PRODUCT_BRIEF.md`'s
privacy-first framing) that deserve their own scoping pass, not a rider
on this doc.

**Recommendation (not a decision):** build Part 1 now. Treat Option A as
the natural "Part 2, if this is worth doing at all" — it's a proxy, but
it's free (no new data source) and directly reuses #3's precedent. Leave
Option B as a flagged idea, not scoped further here — if Option A's
proxy turns out to be too weak to be interesting, that's the signal
Option B might be worth a dedicated design doc, not a reason to build it
speculatively now.

### Open questions (Part 2)

1. Is Option A's proxy (category-label taper within a rollup cluster)
   actually interesting, or does chaptering's own category assignment
   not have enough resolution to show a real "maturity curve"? Untested
   — want to eyeball it against a real recurring initiative before
   committing further.
2. What does "healthy taper" vs. "stall" actually look like
   quantitatively, even for Option A? Not designed here — needs real
   cluster data first.
3. Does Option B belong in work-ledger at all, or is "correlate against
   the actual codebase" a fundamentally different tool? Flagged, not
   answered.
4. Is this Show-stage or Tell-stage? A narrative sentence is more
   interpretation than a bar chart, but it doesn't recommend an action
   either. Leaning Show (same precedent as `_session_summary()`), but
   worth a second look once Part 1 is actually built and read back.

## Migration/compatibility

Purely additive — a new `--summary` flag/section on `timeline`, no
schema changes, no changes to existing `TimelineResult`/cache formats.
