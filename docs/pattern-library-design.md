# Design: Shared Pattern Library ("the mother ship")

Status: proposed, not yet built.
Author: written by Claude, from a design conversation with the repo owner.
Related: `docs/recommend-workflow-efficiency-design.md` (the local-only
rule categories this would supplement), `work_ledger/export.py` (a
different, already-shipped mechanism this is NOT a replacement for - see
"How this differs from `export`" below).

## Problem

`recommend` only knows what its own hardcoded rules can detect. There's
no way for it to benefit from a mistake/fix someone else already found
and confirmed, and no way for a good recommendation, once identified, to
become more trusted over time as more people encounter and validate it.
Right now every install starts from zero and stays at zero.

This proposes a shared, versioned library of known **mistakes, patterns,
and fixes** - content the repo owner assembles and curates - that
`recommend` can match against in addition to its own local rules, with
two counters per entry (**times recommended**, **times used**) that
together give each entry a popularity/trust score reflecting real
validation, not just how clever it sounds on paper.

## Scope for v1 (explicit)

- **Single-person-scoped.** v1 does not do cross-user personalization or
  rank recommendations by other users' behavior. It only: (1) pulls the
  shared public library read-only, to match against this person's own
  session; (2) reports back two simple counters when a library entry is
  recommended and, separately, confirmed used. No session content, no
  user identity beyond whatever's needed to avoid double-counting (see
  Open Questions).
- This is deliberately much narrower than aggregating everyone's usage
  data into a corpus - it's a shared, crowd-validated knowledge base with
  usage telemetry, not a corpus of individual cost/usage data.

## How this differs from `export` (don't conflate the two)

`export` (already shipped) sends **this user's own aggregated cost data**
outward, manually, to build toward a future corpus - content flows from
the user outward, nothing flows back in.

This is the reverse and a different kind of content: a **library
maintained externally** flows *into* `recommend` (read-only), and only a
tiny, content-free usage signal (two counters against a pattern ID) flows
back out. No session data, no cost figures, no chapter titles ever cross
this boundary in either direction. They could compose later - an `export`
corpus could eventually seed new library entries - but that's future
work, not v1, and the two mechanisms should stay conceptually and
technically separate until there's a real reason to merge them.

## Why an MCP server specifically

A plain read-only file (even just a JSON file on a public URL) would
cover the "pull the library" half with zero hosting. The reason to reach
for MCP instead: Claude Code already speaks MCP natively, which means the
library doesn't have to stay a batch, after-the-fact CLI report. If the
mother ship is exposed as an MCP server, it can be connected directly to
a live Claude Code session as a tool - Claude could consult known
patterns *during* the session and flag a match in the moment, not just
when the user later runs `work-ledger recommend`. That live-matching
capability is the actual argument for MCP over a static file; it's not
needed for the read-only "pull the library" case on its own.

## Content model

```
PatternEntry:
  id
  title
  category            # maps to recommend's existing categories - cost /
                       # user-actions / configuration / new-skill /
                       # new-tool - not a new open-ended taxonomy
  pattern              # what recurring signal/behavior is being observed
  use_case             # a concrete scenario where this actually showed up
  diagnosis            # why this happens - the root cause, not a
                       # restatement of `pattern`
  fix                  # the concrete, actionable remedy
  recommended_count
  used_count
```

Five content fields rather than the two ("description"/"fix") first
drafted here - `use_case` and `diagnosis` earn their place as separate
fields rather than folding into a longer `pattern` description: a use
case grounds the entry in something real instead of an abstract rule, and
an explicit diagnosis forces the fix to address a stated root cause
rather than just the symptom - both make an entry easier to review and
harder to submit vaguely. See `CONTRIBUTING-patterns.md` and
`patterns/TEMPLATE.md` for the exact submission shape, and
`.github/ISSUE_TEMPLATE/pattern-submission.yml` for the same five fields
as a structured issue form, for raising a candidate before it's a
finished entry.

Deliberately not a generic rule-matching DSL for v1: new entries describe
a known mistake/fix in the same shape `recommend`'s own hardcoded rules
already use (see `docs/recommend-workflow-efficiency-design.md`'s four
categories), rather than inventing a query language a contributor would
need to learn. A library entry either maps to one of `recommend`'s
existing detection mechanisms with different parameters, or it's out of
scope for v1 matching (still fine as documentation, just not
auto-detectable yet).

## Mechanism, v1

Three operations against the mother-ship MCP server:

- `list_patterns` - read-only, no auth needed (it's public content).
  `recommend` fetches this (cached locally, refreshed periodically) and
  checks for matches alongside its own built-in rules.
- `report_recommended(pattern_id)` - called when a library entry's
  pattern is matched and shown to a user.
- `report_used(pattern_id)` - called when there's a confirmed signal the
  user actually applied the fix.

`report_used` is the genuinely hard part. Three options, increasing in
complexity and decreasing in how soon they're buildable:

1. **Explicit confirmation** - `work-ledger recommend --mark-used <id>`,
   the user tells the tool it helped. Zero inference risk, but relies on
   the user bothering to confirm. Recommended starting point for v1 -
   simplest, and honest about being an undercount rather than pretending
   to detect adoption automatically.
2. **Heuristic** - the flagged pattern stops recurring in later
   turns/sessions after being shown. Plausible but risks false
   attribution (the pattern could stop for unrelated reasons). Not v1.
3. **Live correlation** - if surfaced as an MCP tool call mid-session,
   correlate with an immediate subsequent action in the same session.
   Most accurate, most work, depends on the live-matching capability
   above actually being built first. Not v1.

## Hosting / infrastructure reality check

This is genuinely new infrastructure commitment, not a small extension of
what's shipped so far - worth being as explicit about this as the earlier
corpus-mechanism discussion was, since that discussion specifically chose
manual export over a hosted endpoint to avoid exactly this commitment.
`report_recommended`/`report_used` need *some* live, callable backend;
that's unavoidable if the counters are supposed to reflect real usage
rather than being faked with a static file.

Two things can be split to minimize what actually needs to run
persistently:

- **The content itself** (the mistakes/patterns/fixes text) can live as
  version-controlled files in a public repo - readable, reviewable, and
  contributed to via ordinary PRs, same trust model as the rest of this
  project. `list_patterns` can serve this straight from a raw file URL or
  GitHub Pages - effectively free to host, no server needed for reads.
- **The two counters** are the only part that needs a live write path.
  Smallest real option for a solo maintainer: one small serverless
  function (e.g. a Cloudflare Worker) plus a tiny key-value store,
  fronting just `report_recommended`/`report_used` - not a full database,
  not a general-purpose API.

The MCP server, in this framing, is a thin shim: static content plus a
minimal counter-increment endpoint, not a large service to operate.

## Non-goals for this pass

- Cross-user personalization or ranking by other users' behavior.
- Automatic "used" detection beyond explicit confirmation (option 1
  above).
- A generic pattern-matching DSL - entries map to `recommend`'s existing
  rule categories, not a new open-ended language.
- **Automated moderation or acceptance.** The submission *format* is
  defined (issue form + PR template, see Content model above) so
  proposing an entry - by a person or by an agent instructed to - is
  mechanical, but every entry still goes through ordinary human PR
  review, same as any other change to this repo. No auto-merge, no
  automated quality scoring of submissions themselves.

## Open questions

1. **Decided: popularity scoring - raw counts, no derived formula.**
   Display "recommended N times, used M times" as-is; no single score is
   computed at all. Chosen specifically to avoid inventing a weighting
   scheme that would need defending ("why is used_count worth 5x?") and
   to stay consistent with this project's existing stance against a
   single opaque efficiency number. Cost accepted: nothing to sort a list
   of entries by except one of the two raw counts directly.
2. **Decided: "used" means explicit confirmation only, for v1.**
   `work-ledger recommend --mark-used <id>` - the user says it helped,
   after the fact. No heuristic detection (pattern stops recurring) and
   no live MCP-session correlation for v1; both remain possible future
   work if explicit confirmation turns out to undercount too heavily in
   practice, but neither is needed to ship the core mechanism.
3. **Content quality / abuse - lower-priority than it first sounds, and
   worth saying why.** Popularity points create an incentive to game them
   (fake "used" reports for a bad entry), but every entry is already
   manually PR-reviewed before it ever goes live (see
   `CONTRIBUTING-patterns.md`) - the only thing an abuser can inflate is
   the *counter* on an already-accepted, already-vetted entry, never get
   bad content published in the first place. That's a meaningfully
   smaller problem than an open content-moderation hole, which is why a
   manual PR-review gate is treated as sufficient for v1 without further
   abuse-specific tooling. `report_used` calls still need enough
   rate-limiting/dedup (see decision 4) that one install can't trivially
   inflate a single entry's count, but this is deliberately deferred as
   lower-stakes, not an oversight.
4. **Decided: per-install random UUID for the two report calls.**
   Generated once on opt-in, stored locally, sent with every
   `report_recommended`/`report_used` call. No PII, never tied to a
   person - exists purely so the backend can dedup repeated reports from
   the same install and apply basic rate-limiting, which full anonymity
   would rule out entirely.
5. **Offline behavior is a hard requirement, not a real open question:**
   if the mother-ship endpoint is unreachable, `recommend` must fall back
   to its local-only rules silently, exactly like `chapters` already
   falls back to "Unsorted" on any chaptering failure. Stated explicitly
   here so it doesn't get accidentally violated during implementation.
6. **Decided: `id` is immutable once merged.** An entry's `id` is what
   `--mark-used <id>` and the mother-ship counters key off of (see
   `CONTRIBUTING-patterns.md`). Editing it in place after merge would
   orphan its counters and silently break any outstanding `--mark-used`
   calls, so a rename instead requires retiring the old entry (kept for
   history) and adding a fresh one with a new id - never an in-place edit
   of `id`. `title` stays freely editable; only `id` is frozen. Same
   class of concern as decision 4 (both protect what the counters key
   off of), called out separately since this one is a content-review
   discipline rather than a backend design choice.

## Implementation notes (v1, built)

- **The concrete v1 matching mechanism**: each `PatternEntry` gets an
  optional `maps_to` frontmatter field naming an existing `recommend.py`
  `rule_id` (`outlier-chapter-cost`, `subagent-heavy-chapter`,
  `repeated-skill-invocation`). `recommend` only ever surfaces a library
  entry alongside a local rule that actually fired with the same
  `rule_id` - filling in the "maps to recommend's existing detection
  mechanisms with different parameters" language from the Content model
  section above with an actual field, since the doc had deliberately left
  the exact mechanism unspecified.
- **Packaging gap, disclosed rather than solved**: `patterns/*.md`
  content lives at the repo root, a sibling of the `work_ledger/` package
  - this works today for anyone running from a checkout (how this
  project develops and tests everything), but a real `pip install
  work-ledger` from PyPI only installs the `work_ledger/` package, not
  the repo root's `patterns/` directory. Shipping the bundled content as
  proper package data (or fetching it from a published URL at runtime)
  is real follow-up work, not solved in this pass - see `work_ledger/
  patterns.py`'s `DEFAULT_PATTERNS_DIR` comment.
- **No backend was deployed.** `work_ledger/pattern_client.py` implements
  the client side (install id, opt-in flag, best-effort
  `report_recommended`/`report_used` calls to a configurable
  `WORK_LEDGER_PATTERN_BACKEND_URL`) and `work_ledger/mcp_server.py`
  implements a local, runnable MCP server exposing `list_patterns`/
  `report_recommended`/`report_used` as tools - but there is still no
  publicly hosted counter service. Anyone using this today needs to point
  `WORK_LEDGER_PATTERN_BACKEND_URL` at their own deployed instance;
  without one, matching and display still work locally, reporting is
  just a documented no-op.
