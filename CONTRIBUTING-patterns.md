# Contributing a pattern

How to propose a new entry for work-ledger's shared pattern library - a
curated collection of known mistakes, patterns, and fixes that `recommend`
can match against alongside its own local rules. See
`docs/pattern-library-design.md` for the full mechanism this feeds; this
file only covers the submission format.

## Two ways in

1. **Open an issue** using the "Pattern submission" template if you're not
   yet sure whether something is a real, recurring pattern - this is for
   raising an idea for discussion before it's vetted.
2. **Open a PR directly** if you're already confident in the pattern and
   want to propose the finished entry - this is the faster path, and the
   one to use if you're instructing an agent (e.g. Claude, mid-session) to
   turn something it just noticed into a proposal.

## PR format

Add one new file at `patterns/<slug>.md`, where `<slug>` is a short,
kebab-case, unique identifier (e.g.
`patterns/repeated-pr-shipping-sequence.md`). Copy `patterns/TEMPLATE.md`
and fill in every field - that file shows the exact shape required.

Required, all mandatory:

- **`id`** (frontmatter) - kebab-case, unique, and **must match `<slug>`
  in the filename exactly** (e.g. `patterns/repeated-pr-shipping-sequence.md`
  has `id: repeated-pr-shipping-sequence`). This is the identifier
  `--mark-used <id>` and the mother-ship counters key off of - see
  `docs/pattern-library-design.md`'s open questions for why this is
  treated as immutable once merged.
- **`title`** (frontmatter) - short, concrete name.
- **`category`** (frontmatter) - one of `cost`, `user-actions`,
  `configuration`, `new-skill`, `new-tool` - matches `recommend`'s
  existing categories (see `docs/recommend-workflow-efficiency-design.md`).
- **Pattern** - what recurring signal is being observed, specific enough
  that someone else could recognize the same thing in their own session.
- **Use Case** - a concrete scenario where this actually showed up, not an
  abstract description.
- **Diagnosis** - why this happens (the root cause) - not just a
  restatement of the Pattern section.
- **Fix** - the concrete, actionable remedy.

Leave `recommended_count` and `used_count` at `0` - these are populated by
the mother-ship counters described in `docs/pattern-library-design.md`,
never hand-edited in a PR.

## What makes a good entry

- **Diagnosis is a real root cause, not a restatement.** "This happens
  because the user does X" isn't a diagnosis if X is just the Pattern
  again - explain *why* X happens.
- **Use Case is a specific, real scenario**, not "sometimes users do
  this."
- **Fix is actionable and checkable** - concrete enough that "used" (per
  the mother-ship mechanism) has an unambiguous meaning: someone reading
  it later should be able to tell whether they actually did the fix or
  not.

## Review

Entries are reviewed like any other PR to this repo - there's no separate
approval pipeline or automated moderation yet (see
`docs/pattern-library-design.md`'s non-goals).
