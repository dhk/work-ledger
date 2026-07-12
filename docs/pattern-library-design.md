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
  description        # the mistake/pattern being described
  fix_description     # the recommended remedy
  category            # maps to recommend's existing categories - cost /
                       # user-actions / configuration / skill / tool -
                       # not a new open-ended taxonomy
  recommended_count
  used_count
```

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
- Content moderation tooling beyond "the repo owner reviews PRs to the
  content repo" - no self-service submission pipeline yet.

## Open questions

1. **Popularity scoring formula.** Raw `used_count`, a ratio
   (`used_count / recommended_count` as a "confirmed-useful rate"), or a
   weighted combination that favors confirmed use over just being shown
   often? Not decided - a ratio needs a minimum-sample floor or a
   brand-new entry with 1 use out of 1 recommendation looks artificially
   perfect.
2. **What counts as "used," beyond v1's explicit confirmation** - is
   heuristic detection (option 2) worth building before option 3, or
   should the gap between "confirmed" and "live-correlated" just stay a
   gap for now?
3. **Content quality / abuse.** Popularity points create an incentive to
   game them (fake "used" reports for a bad entry). At solo-maintainer
   scale, a manual PR-review gate on the content repo is probably
   sufficient for v1 - but `report_used` calls themselves need at least
   enough rate-limiting/dedup (see question 5) that one install can't
   trivially inflate a single entry's count.
4. **Offline behavior is a hard requirement, not a real open question:**
   if the mother-ship endpoint is unreachable, `recommend` must fall back
   to its local-only rules silently, exactly like `chapters` already
   falls back to "Unsorted" on any chaptering failure. Stated explicitly
   here so it doesn't get accidentally violated during implementation.
5. **Identity/auth for the two report calls.** Fully anonymous means no
   way to prevent double-counting or trivial abuse; a lightweight
   per-install random UUID (still no PII, never tied to a person) would
   let the backend dedup repeated reports from the same install without
   requiring any real identity system. Leaning toward the UUID approach,
   not decided.
