# Design: Harvesting Code-Review Findings into the Pattern Library

Status: proposed, not yet built.
Author: written by Claude, from a design conversation with the repo owner.
Related: `docs/pattern-library-design.md` (the mechanism and deployed
backend this extends), `docs/recommend-workflow-efficiency-design.md`
(the "new skills" category this could eventually feed), `work_ledger/
mcp_server.py` and `backend/` (existing code this adds to, not replaces).

## Problem

The pattern library has exactly one entry (`outlier-chapter-cost-review`),
because the only way a new one gets written today is the repo owner
personally noticing a recurring mistake and hand-writing it. Meanwhile,
the repo owner runs code reviews (`/code-review`, `/review`) across many
separate Claude Code sessions - different repos, different virtual
containers on claude.ai/desktop - and each of those reviews already
produces exactly the kind of structured finding (a category, a one-
sentence defect summary, a concrete failure scenario) that a pattern-
library entry is eventually built from. None of that surfaces anywhere
outside the session it happened in. Nothing connects "I keep seeing this
same kind of finding across unrelated repos" to "that should be a pattern
library entry."

## Goals

- **v1 (this pass): personal-only harvesting.** A way for the repo owner
  to forward code-review findings from any of their own sessions/
  containers to the already-deployed backend (`docs/pattern-library-
  design.md`'s Vercel + Upstash Redis service), so scattered review
  output across many repos becomes one place to look for recurring
  patterns, instead of staying siloed per-session.
- **v2 (explicitly later, not designed in depth here): open the same
  path to other `work-ledger` users**, so the corpus grows beyond just
  the repo owner's own repos. Called out now because v1's design choices
  should not make v2 harder than necessary - but v2's actual privacy/
  trust requirements are real work of their own, deferred on purpose
  (see "What v2 actually needs" below).
- Reuse the MCP path already built for `report_recommended`/
  `report_used` (same server, same opt-in gate, same best-effort
  semantics) rather than inventing a second submission mechanism.
- Curation stays manual. This harvests raw material; a human still turns
  a recurring finding into an actual `patterns/*.md` entry, same as
  today's one seeded entry - matches the project's existing "every entry
  is PR-reviewed, no auto-moderation" stance.

## Non-goals for this pass

- Automatic pattern-entry generation from submitted findings. No mining/
  clustering pass, no LLM summarization of "here's a pattern across N
  submissions" - that's plausible future work once there's enough
  volume to make it worth building, not before.
- A public (or even repo-owner-facing custom) read/query API over
  submitted findings. v1 curation happens by browsing the raw data
  directly in the Upstash console - no new tooling to view it.
- Any automatic redaction/anonymization pipeline. v1 is personal-only
  (the repo owner's own data, on their own backend), so this is
  deliberately deferred rather than over-built before v2 needs it for
  real.
- Solving v2's actual privacy/trust model. Flagged everywhere it's
  relevant below, not designed here.

## What's actually being submitted

A code review in this environment already produces findings in a
consistent shape (see `ReportFindings`'s own schema, which `/code-review`
and `/review` already emit): a short category slug, a file (and
optionally a line), a one-sentence summary of the defect, a concrete
failure scenario, and sometimes a verdict (CONFIRMED/PLAUSIBLE) if a
verify pass ran. That shape is *already* close to submission-ready - this
design reuses it directly rather than inventing a new schema a review
workflow would need to be specially adapted to produce.

```
ReviewFinding (submitted, one per array element):
  category            # e.g. "correctness", "simplification", "efficiency"
  summary              # one-sentence statement of the defect
  failure_scenario     # concrete inputs/state -> wrong output/crash
  file                 # repo-relative path, as the review itself produced it
  line                 # optional
  verdict              # optional: "CONFIRMED" | "PLAUSIBLE"

Submission envelope (added by the client, not the reviewer):
  install_id           # the same per-install UUID already used for
                        # report_recommended/report_used
  submitted_at         # server-assigned on receipt, not client-supplied
  findings: [ReviewFinding, ...]
```

Deliberately **not** included: the actual code/diff, full file contents,
or anything beyond the file path a finding already names. The findings
themselves are the raw material - not the surrounding review
conversation, not the rest of the session.

## Mechanism

- **New MCP tool, `submit_review_findings(findings: list[dict])`**, added
  to the existing local `work_ledger/mcp_server.py` alongside
  `list_patterns`/`report_recommended`/`report_used`. A session that just
  ran a code review can call this directly with the findings it already
  produced - no reformatting needed given the schema reuse above.
- **New backend route, `POST /findings`**, on the already-deployed
  `backend/` Vercel project. Stores each submission as one entry in a
  Redis Stream (`XADD findings * ...`) rather than a List or a per-id
  Hash - Streams are the right primitive here specifically because this
  is an append-only log meant to be read back in order later (unlike the
  counters, which only ever need their latest value).
- **Reuses the existing opt-in gate** (`work-ledger patterns enable`) and
  the existing best-effort semantics (never blocks, never crashes,
  silently no-ops if disabled or the backend's unreachable) rather than
  adding a second consent flag - for v1's personal-only scope, one gate
  is enough. (v2 will likely need its own, more explicit consent step -
  see below; not solved here.)
- **No new read endpoint.** For v1, the repo owner browses the `findings`
  stream directly via the Upstash web console when it's time to look for
  patterns. A `GET /findings` route (even a repo-owner-only, token-gated
  one) is reasonable v1.5 work once console-browsing actually becomes
  the bottleneck - not built ahead of that need.

## Curation workflow (v1)

1. Run a code review in any session, any repo, any container.
2. Call `submit_review_findings` with what the review already produced.
3. Periodically (weekly? monthly? - not prescribed here), the repo owner
   opens the Upstash console, skims the `findings` stream, and looks for
   the same kind of finding recurring across unrelated repos/sessions.
4. When one does, they write it up as a real `patterns/*.md` entry by
   hand - via `CONTRIBUTING-patterns.md`'s existing PR process, same as
   the one entry that already exists. Submitted findings are raw
   material for that judgment call, never auto-published.

## What v2 actually needs (explicitly deferred, not designed here)

Opening this to other `work-ledger` users changes the risk profile in a
way v1 doesn't have to solve, and shouldn't try to guess at:

- **Consent has to be its own, explicit gate**, separate from
  `patterns enable`. Reporting an anonymous counter increment
  (today's `report_recommended`/`report_used`) and submitting the actual
  text of a code-review finding from someone else's repo are not the
  same privacy stakes - v2 needs a submitter to knowingly opt into the
  second, not inherit it from the first.
- **Some redaction/review step before findings are visible to anyone but
  the repo owner** - even a file path or a summary sentence can leak
  project/business specifics once the submitter isn't the same person
  curating the corpus.
- **Abuse/volume handling** - v1's "browse the console occasionally"
  curation model does not survive real multi-user submission volume.

None of this blocks v1, which only ever handles the repo owner's own
data on their own backend - but v1's implementation should avoid
decisions that would make bolting these on later harder than necessary
(e.g. the Stream-per-submission shape and the reused install_id concept
both carry forward cleanly; a bespoke v1-only format wouldn't).

## Open questions

1. Should `file` paths be left exactly as the review produced them for
   v1, given it's personal-only anyway? Leaning yes - redaction is a v2
   problem, not a v1 one - but worth confirming rather than assuming.
2. Is a repo-identifying hash (a one-way hash of e.g. the git remote,
   not the literal name) worth adding now, so the curation pass can tell
   "these 5 findings are from the same project" apart from "these 5 are
   from 5 different ones"? Leaning toward skipping it for v1 - add it if
   curation in practice turns out to need that signal, not before.
3. What triggers a curation pass - is "the repo owner remembers to check
   occasionally" good enough, or does this need even a trivial reminder
   mechanism once real volume exists? Not designed here; revisit once
   there's actually a findings stream worth checking.
4. Should `submit_review_findings` require the review to have already
   run a verify pass (only submit `CONFIRMED`/`PLAUSIBLE`-tagged
   findings), or accept anything a review produced? Leaning toward
   accepting everything for v1 - the curator (the repo owner) is the
   filter, not the submission mechanism.
