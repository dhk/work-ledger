# Design: Optional Semantic Matching for Rollup/Cross-Session Clustering

Status: implemented (issue #68). `work_ledger/rollup_semantic.py` is the
new module; `rollup.build_rollup_result`/`build_rollup` fold its output
back into cluster membership, and `waste.find_cross_session_waste_patterns`
consumes that same result (via its `key_map`) rather than re-deriving its
own clustering - see those modules' docstrings for the final shape. The
Open Questions below were resolved during implementation (noted inline);
everything else in this doc's Architecture/Non-goals sections was already
settled and is unchanged from what shipped.
Author: written by Claude, from analysis + a design conversation with the
repo owner.
Related: issue #68, `work_ledger/rollup.py` (issue #3, what this extends),
`work_ledger/waste.py` (the cross-session half, issue #5, a second
consumer of the same clustering), `docs/local-model-chaptering-design.md`
(the closest precedent for this doc's shape and for the env-var-driven,
persistent-config pattern this reuses), `docs/architecture.md`'s "Network
calls" inventory.

## Problem

`rollup.py`'s v1 clustering (issue #3) matches chapter titles into the
same recurring initiative via deterministic normalization — lowercase,
strip punctuation/whitespace/stopwords, light plural stemming, then exact
match. The module's own docstring named this an accepted false-negative
tradeoff and said explicitly: "if this ever turns out to hide real
recurring cost in practice, that's the signal a v2 (LLM or embedding
clustering) is worth designing."

That signal arrived. Run against real usage (166 sessions), `work-ledger
rollup` came back almost entirely singletons — chapters describing the
same obviously-recurring work (e.g. nine different "run the
reading-list-builder skill" sessions, worded differently each time:
"Execute reading-list-builder daily flow for 2026-06-23", "Initialize
reading list builder daily flow", "Reading List Builder v3.0 Execution",
...) never clustered together at all.

## Investigation

Before proposing a fix, the root cause was checked quantitatively rather
than assumed (see PR history / session notes for the throwaway script
used) — `normalize_title()` is working exactly as documented: the failure
mode is genuine paraphrase (different verbs, embedded dates/versions),
not a punctuation/casing/stopword edge case a normalizer tweak would
catch.

Fuzzy/approximate string matching (`difflib`, `rapidfuzz`, Jaccard word
overlap) was evaluated as a cheaper, local, no-network alternative and
**rejected** — scored against `test_rollup.py`'s own existing
false-positive guards, "Build the v1 dashboard" vs. "Build the v2
dashboard" scores *higher* similarity than several genuine
reading-list-builder matches. There is no single threshold that recovers
the true positives without also merging cases the current test suite
exists to keep separate.

Embeddings (Voyage AI) were evaluated against a second small Haiku pass
(the alternative the original rollup.py docstring already named) and
**a Haiku pass was chosen** — not on cost (both are near-free per title:
Voyage's `voyage-3.5`/`voyage-3.5-lite` embeddings and a batched Haiku
clustering call are both well under a cent for realistic title volumes),
but because this codebase already has every piece of machinery a second
Haiku pass needs (`chapters.py`'s enforced-structured-output pattern, the
"never silent, always a distinguishable fallback message" contract, an
env-var-driven backend-selection precedent from #16), where embeddings
would mean standing up a whole new provider integration for marginal
benefit over reusing what's already built and tested.

## Goals

- Recover the obviously-recurring initiatives v1's deterministic
  matching misses (the reading-list-builder-shaped case above), without
  regressing the false-positive guards v1 already protects (the
  dashboard-v1-vs-v2, login-bug-vs-checkout-bug cases).
- Zero behavior change by default — `rollup`/`waste --cross-session`
  keep today's free, deterministic, zero-network matching unless
  explicitly opted in, mirroring #16's "default backend stays
  unchanged" precedent exactly.
- One clustering mechanism, shared by both consumers — `rollup` and
  `waste --cross-session` must not silently disagree about what counts
  as "the same initiative."

## Non-goals (for this pass)

- **Merge-decision caching, versioning, or a journal of what got merged
  with what over time.** Explicitly decided against for this pass: the
  repo owner is fine with cluster membership drifting run-to-run as an
  accepted consequence of a similarity judgment call, not a defect to
  engineer around yet. If this needs revisiting later (e.g. once real
  usage shows drift that's actually confusing rather than benign), that's
  new evidence for a follow-up doc — not designed here.
- **A full override/correction/pinning system** for a merge the user
  disagrees with. `--confirm` (below) covers visibility; actual
  correction tooling is explicitly out of scope — the repo owner flagged
  a separate project already covers this class of problem "in due
  course." Don't build ahead of that.
- **Embeddings (Voyage or otherwise).** Evaluated and set aside per the
  Investigation section above — not because it's a bad idea in the
  abstract, but because the Haiku-pass approach reuses more of what
  already exists. Worth revisiting only if the Haiku-pass approach proves
  concretely insufficient in practice.

## Architecture

- **Trigger: `WORK_LEDGER_ROLLUP_MATCHING`**, default `deterministic`.
  Set to `semantic` to opt in. Persistent, environment-variable-driven,
  no per-invocation CLI flag — deliberately "fire and forget," mirroring
  `WORK_LEDGER_CHAPTER_BACKEND`'s exact shape from #16 rather than
  inventing a second configuration style.
- **Deterministic pass stays first and unconditional.** `normalize_title()`
  + exact-match clustering runs exactly as it does today, for free, with
  no network call, regardless of the env var. This is the whole dataset's
  first pass, not something semantic matching replaces.
- **Semantic pass only touches what didn't already cluster.** When
  `WORK_LEDGER_ROLLUP_MATCHING=semantic`, collect the singleton
  (`num_sessions == 1`) clusters' display titles left over after the
  deterministic pass, batch them into one structured-output Haiku call
  proposing merges among just that batch (same enforced-JSON-schema
  discipline `chapters.py`'s `_ChaptersOut` already uses — not a prompted
  "return JSON" convention), and fold accepted merges back into the
  cluster list before returning. This bounds the paid/networked surface
  to genuinely-ambiguous titles; anything that already matched
  deterministically never touches the model.
- **New module** (name TBD, e.g. `rollup_semantic.py`) mirroring
  `chapters.py`'s backend-call shape: any failure (no credentials,
  malformed response, refusal) falls back silently to the
  deterministic-only result with a distinguishable printed note — never a
  crash, never a silent difference between "semantic matching found
  nothing new" and "semantic matching couldn't run at all."
- **One shared clustering entrypoint for both consumers.** `waste.py`'s
  `find_cross_session_waste_patterns` currently calls
  `rollup.normalize_title()` directly; this needs to instead go through
  whatever function `build_rollup()` itself now calls, so enabling
  `WORK_LEDGER_ROLLUP_MATCHING=semantic` changes clustering for both
  `rollup` and `waste --cross-session` identically — per the repo owner's
  explicit decision (#3 in the design conversation), not an
  independent per-command opt-in.
- **`--confirm` flag** on `rollup` (and `waste --cross-session`, same
  shared mechanism): when the semantic pass ran, prints which singleton
  titles got merged into which cluster. Deliberately minimal — a
  visibility/observability feature, not an audit trail, not versioned,
  not undoable. Scope capped here on purpose (see Non-goals).
- **No caching between runs.** Every invocation with `semantic` enabled
  re-runs the Haiku pass over whatever's still singleton at that moment.
  Cluster membership can drift between runs as a result — accepted, see
  Non-goals.
- **New network call.** Once built, this is a 5th entry in
  `docs/architecture.md`'s "Network calls" inventory: opt-in via the env
  var, same disclosure standard #16's Ollama addition already set —
  never silent, never blocking core (deterministic) functionality on its
  availability.

## Migration/compatibility

Purely additive. `rollup`/`waste --cross-session` behavior is byte-for-byte
unchanged with the env var unset. Existing rollup clusters aren't cached
between runs today (rebuilt fresh every invocation from cached chapters),
so there's no existing state to migrate.

## Open questions (resolved during implementation)

1. Exact module/function boundary for the shared clustering entrypoint —
   does `build_rollup()` grow an optional semantic step internally, or
   does `cli.py` compose `build_rollup()` (deterministic) +
   a new semantic-merge step explicitly? **Resolved:** `build_rollup()`
   keeps its original signature/return shape (a plain `list[RollupCluster]`,
   byte-for-byte unchanged when the env var is unset) and now delegates to
   a richer sibling, `build_rollup_result()`, which returns the clusters
   plus `semantic_merges`/`semantic_fallback_reason`/`key_map`.
   `waste.find_cross_session_waste_patterns` takes an optional
   pre-computed `RollupResult` (defaulting to computing its own via
   `build_rollup_result` if not given) so `cli.py` can compute clustering
   once per invocation and hand the same result to both the pattern-mining
   logic and the `--confirm` output - this is what guarantees `rollup` and
   `waste --cross-session` agree, and avoids a second (uncached, so
   possibly different) Haiku call in the same run.
2. Batch size ceiling for the Haiku call if someone has hundreds of
   singleton titles in one `rollup` run — one call regardless, or
   chunked? **Resolved (for now):** one call regardless, as this doc
   originally described - still untested at very large singleton counts;
   revisit if that turns out to be a problem in practice.
3. Exact `--confirm` output shape (which titles merged into which
   cluster, and how much detail) — not designed in detail here, kept
   deliberately light per the Non-goals note. **Resolved:** one line per
   merged group, e.g. `Merged via semantic matching: 'Execute
   reading-list-builder daily flow' + 'Initialize reading list builder
   daily flow' → 'reading list builder'` - just the titles and what they
   merged into, nothing else. Independent of `--confirm`, a shorter note
   is always printed when semantic matching is on (a merge count, "found
   nothing new to merge", or the fallback reason) so a run's outcome is
   never silent even without `--confirm`.
