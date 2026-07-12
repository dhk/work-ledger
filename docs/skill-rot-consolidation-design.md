# Design: Detecting and Resolving Skill Rot (Overlapping/Redundant Skills)

Status: proposed, not yet built.
Author: written by Claude, from a design conversation with the repo owner.
Related: `docs/recommend-workflow-efficiency-design.md` (category 3, "new
skills" - proposes *creating* a skill from a recurring pattern; this doc is
the missing other half, what happens after a skill already exists),
`docs/pattern-library-design.md` (the mother ship's per-entry
`recommended_count`/`used_count` is the closest existing precedent for
tracking a piece of reusable knowledge's health over time, but it scores
one entry in isolation - nothing compares two entries against each other),
`CONTRIBUTING-patterns.md` (the review discipline any retire/merge action
here should match).

## Problem

`recommend`'s "new skills" category (see the related doc) only ever
proposes creating a new skill from a recurring signal. Nothing in
work-ledger, or in Claude Code's skill system more broadly, looks
*backward* at the set of skills that already exist for a project. Skills
accumulate the same way duplicated code does: a skill gets written to
solve a real, narrow problem; a related-but-not-identical problem shows up
later and a second skill gets written for it, because that's faster than
reading and extending the first one. Enough sessions later, a project's
skill directory has overlapping trigger conditions and redundant
instructions maintained in two places - and nothing currently treats that
directory as data worth auditing, the way session transcripts already are.

"Rot" isn't one problem with one fix - it's three distinct symptoms, each
with a different correct outcome:

1. **Merge** - two skills whose trigger conditions and content overlap
   enough that they're really one skill split in half (unintended
   duplication, not a real distinction). Fix: combine into one, delete the
   other.
2. **Subsume** - a narrow skill turns out to be a special case of a newer,
   more general one. (Concrete example already sitting in this repo's own
   history: `recommend-workflow-efficiency-design.md`'s validation section
   names a candidate "ship a scoped PR" skill covering branch/commit/push/
   PR/review-request. If that skill gets built, any earlier, narrower
   "open a PR with template" skill becomes exactly this case.) Fix: the
   general skill absorbs the narrow one's edge cases; the narrow skill is
   deleted or left as a one-line pointer.
3. **Move into workflow** - a skill's entire value was procedural
   scaffolding for something that's since become routine enough not to
   need an explicit invocation: it belongs in `CLAUDE.md` as a standing
   convention, in `settings.json` as a hook/permission, or has been made
   redundant by a native capability change. Fix: the knowledge moves out
   of the skill file into passive project config; the skill is retired.

None of these three outcomes is "generate a new skill" - `recommend`'s
existing category 3 has no output shape for "retire" or "merge," only
"create."

## How this is (and isn't) addressed today

- **`recommend` category 3** detects signals for *new* skill candidates
  only. Existing skill lifecycle is explicitly out of its scope.
- **The mother-ship pattern library** is the closest existing precedent -
  it tracks a trust/popularity signal per entry over time. But: (a) its
  entries are mistake/fix write-ups, not the Claude Code skill files
  themselves; (b) nothing in that design compares two entries against each
  other for overlap, it scores each in isolation; (c) there's no
  "retire" or "merge" operation anywhere in its mechanism
  (`list_patterns`/`report_recommended`/`report_used`) - a superseded
  entry just keeps accumulating a stale trust score forever.
- **The `fewer-permission-prompts` skill** (real, already shipped) is
  itself an example of the "move into workflow" outcome happening
  organically - but for a *different* piece of scaffolding (manual
  permission approvals moving into `settings.json`). It's a skill doing
  the moving for something else, not a mechanism that notices a skill
  (itself or a sibling) should be moved or retired.
- Net: nothing currently treats a project's skill directory as data to
  mine, the way session transcripts already are.

## Goals

- Define what a "rotten" skill relationship looks like as a concrete,
  detectable signal - not a vague staleness score.
- Propose (not build) a `work-ledger skills audit`-shaped pass that
  enumerates a project's skills and flags candidate merge/subsume/retire
  pairs, each tied to a specific, inspectable signal - same
  "no vague efficiency score" discipline as `recommend`'s existing rules.
- Stay non-destructive: like `recommend`, this reports, it doesn't act -
  no auto-deleting or auto-merging skill files.

## Non-goals for this pass

- Automatically merging, rewriting, or deleting skill files.
- Cross-project skill libraries - v1 stays scoped to one project's own
  skills, mirroring `pattern-library-design.md`'s "single-person-scoped"
  v1 restraint.
- A generic skill-authoring linter (naming conventions, missing
  frontmatter fields). This is specifically about redundancy/overlap
  *between* skills, not the quality of any one skill on its own.

## Candidate detection signals

1. **Description/trigger overlap.** Compare each skill's description
   field (the text used for triggering) pairwise via embedding similarity
   or simple keyword overlap; flag pairs above a threshold as merge
   candidates. Cheap, needs no session data, can run standalone at any
   time - doesn't block on cross-session data the way signal 3 below does.
2. **Co-invocation displacement.** If session logs show a newer skill
   being invoked in a slot an older skill used to fill - same trailing
   tool-call shape, similar surrounding turns, but after a given date -
   that's evidence of in-progress subsumption, stronger than description
   similarity alone.
3. **Zero-use decay.** A skill unused for N sessions while a newer skill
   covers similar ground is a retire candidate, distinct from a
   still-actively-used skill that merely looks similar on paper. Needs
   cross-session data (issue #3), same dependency `recommend`'s own
   cross-session refinements already have.
4. **Manual audit, v0.** Before any of the above is built, the cheapest
   version of this is literally an instruction: periodically ask an agent
   to read every skill's description side by side and flag overlaps. Worth
   naming explicitly as the zero-code starting point, the same way
   `recommend`'s own rules started as things a person checked by hand
   before being automated.

## Mechanism, v1

Start with signal 1 (description overlap) alone: pure text, no session
data, no dependency on issue #3. Output a report of candidate pairs plus a
suggested action bucket (merge / subsume / move-to-workflow), left for a
human to review and act on - same review discipline
`CONTRIBUTING-patterns.md` already establishes for the pattern library.
Signals 2 and 3 layer on once cross-session data (issue #3) exists, same
sequencing precedent `recommend-workflow-efficiency-design.md` already
uses for its own cross-session-dependent categories.

## Open questions

1. **Where this lives** - a new `work-ledger skills` subcommand, or a
   fifth `recommend` category? Leaning toward a separate subcommand:
   signal 1 needs no session/chapter data at all, unlike every existing
   `recommend` category.
2. **Overlap-threshold tuning** for signal 1 needs real skill sets to
   tune against, not a number to guess up front - same caveat as
   `recommend`'s own repeat-count threshold (open question 3 there).
3. **Does this extend to mother-ship pattern-library entries too?** An
   entry superseded by a newer, more general entry has the same "subsume"
   shape as two local skills - but library entries are PR-reviewed
   content with an immutable `id` (see `pattern-library-design.md`'s open
   question 6), so retirement there means deprecating an id, not editing
   a local file. Worth resolving alongside that doc's open questions
   rather than inventing a second, incompatible retirement mechanism.
4. **Who runs the audit, and how often** - on-demand command only, or
   something `recommend` surfaces opportunistically (e.g. "two of your
   skills' descriptions overlap 80%, consider merging"), the way it
   already surfaces cost outliers without being asked?
