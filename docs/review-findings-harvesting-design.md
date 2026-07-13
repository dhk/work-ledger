# Design: Harvesting Code-Review Findings into the Pattern Library

Status: implemented (`backend/api/findings.js`, `pattern_client.py`'s
`submit_findings`, `mcp_server.py`'s `submit_review_findings` tool) -
requires `WORK_LEDGER_FINDINGS_TOKEN` set on both sides (see
`backend/README.md`'s "Findings harvesting setup").
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
- Any *automatic* redaction/anonymization pipeline (scanning/rewriting
  finding text to strip secrets algorithmically). Still deferred - real
  engineering effort not justified before there's volume to justify it.
  This is **not** the same as skipping the risk entirely - see "Whose
  codebase is this, actually" below, which is a v1 requirement, not
  deferred.
- Solving v2's actual privacy/trust model. Flagged everywhere it's
  relevant below, not designed here.

## Whose codebase is this, actually (not a v2 problem - a v1 one)

"v1 is personal-only" was drafted to mean "only the repo owner submits,"
and that framing conflates two different things: *who is submitting*
versus *whose code is being reviewed*. `/code-review` runs across many
repos, per the Problem section above - some of those may be an
employer's, a client's, or another otherwise-confidential codebase the
repo owner doesn't unilaterally have the right to forward to a
third-party-hosted Redis instance, opt-in gate or not. A `summary` or
`failure_scenario` can easily quote a secret literal, an internal API
name, or a proprietary algorithm's shape found in the reviewed code. None
of that changes based on who else can later read the data (that's the
v2 boundary) - it's a question of whether sending unredacted third-party
code content off-box is safe *at all*, which is a v1 question.

**v1 requirement, not deferred**: `submit_review_findings` is invoked on
explicit human instruction after a review already ran (see Mechanism
below) - that instruction is the actual safeguard, and this doc should
say so plainly rather than imply it. Before saying "submit those
findings," the reviewer (the repo owner) is the one who has to judge
whether this specific repo's findings are theirs to forward - a company
laptop's client work is a clear no; the repo owner's own open-source
project is a clear yes. No tooling enforces this in v1 (there's no way
for the MCP server to know whose repo it's looking at) - it's a judgment
call baked into the workflow, and this doc names it as one instead of
leaving it implicit.

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
  Redis Stream, trimmed on write - `XADD findings MAXLEN ~ 10000 * ...`
  - rather than a List or a per-id Hash - Streams are the right primitive
  here specifically because this is an append-only log meant to be read
  back in order later (unlike the counters, which only ever need their
  latest value). The approximate `MAXLEN` bounds growth on what's
  realistically a free/low-tier Upstash instance without needing a
  separate cleanup job; unlike the counters (which must never lose data),
  losing the oldest, already-curated-or-ignored findings once the stream
  is huge is an acceptable tradeoff, not a correctness bug.
- **Requires a shared-secret bearer token, unlike the counters route.**
  `POST /patterns/:id/:event` only ever increments an integer behind a
  strict id/event validation - a free-text findings-ingestion endpoint is
  a meaningfully bigger attack surface than a counter increment: anyone
  who discovers the URL could otherwise POST unbounded arbitrary content
  into the stream, not just bump a number. For v1 (genuinely
  single-submitter), a single shared secret is proportionate - a new env
  var (e.g. `WORK_LEDGER_FINDINGS_TOKEN`) set on both the backend and
  wherever `work-ledger-mcp` runs, checked via `Authorization: Bearer
  <token>`, rejecting unauthenticated requests with 401. This is a
  different mechanism from the counters' `install_id`, which is a
  self-reported dedup key, not a credential - it doesn't gate access on
  its own and shouldn't be mistaken for auth. v2, with real multiple
  submitters, replaces this with a real per-submitter identity/token
  system rather than one shared secret - not designed here.
- **Server-side validation even with auth in place**: cap the number of
  findings accepted per request (e.g. 50), cap total request body size,
  and length-limit each field (e.g. `summary` under ~300 characters,
  `failure_scenario` under ~1000) - defense in depth against an
  authorized-but-buggy or compromised client, not just unauthenticated
  abuse.
- **No dedup for retries, acknowledged rather than solved.** The counters
  route has a real dedup key (`install_id:pattern_id:event`, a 60s
  window) specifically because retries are expected there. A findings
  submission has no equivalent natural identity, so a client-side retry
  would silently double-append to the stream. Low-stakes given curation
  is manual and a human will notice near-duplicate entries when reading
  the stream - worth a client-generated idempotency key (a UUID per
  submission call, checked against a short-TTL marker key the same way
  the counters route already does) as a cheap follow-up if double-appends
  turn out to be annoying in practice, not required to ship v1.
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

None of this blocks v1, which only ever has one *submitter* (the repo
owner) reporting to their own backend - but v1's implementation should
avoid decisions that would make bolting these on later harder than
necessary (e.g. the Stream-per-submission shape and the reused
install_id concept both carry forward cleanly; a bespoke v1-only format
wouldn't).

## Open questions

1. **Reframed, per review feedback.** Not "should `file` paths be left
   raw since v1 is personal-only" - whether a path is safe to forward
   doesn't depend on who's submitting, it depends on whose codebase it
   names (see "Whose codebase is this, actually" above). The real
   question: should `submit_review_findings` (or its caller) be expected
   to confirm the reviewed repo is actually the reviewer's to forward
   before paths/summaries go out unredacted, or is the per-call human
   instruction already the confirmation (see Mechanism)? Leaning toward
   the latter - the instruction to submit *is* the confirmation, made
   explicit in this doc rather than assumed - but this is a real v1
   decision now, not a deferred v2 one.
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
