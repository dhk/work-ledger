# Product Brief

## What this is

work-ledger is a personal work-analytics tool for **individual Claude Code
users**, not teams with observability stacks. It reads Claude Code's own
local session transcripts and turns them into attributable usage, a view of
how work changes over time, recurring initiatives, and evidence for improving
how someone works. Its strongest surfaces currently Show; Tell is early and
Do remains deliberately immature.

## Who it's for

One person, on their own machine, watching their own usage. Not a team
lead watching a roster of engineers. Not an org rolling out governance
across many seats. If a feature only makes sense once there's a "team" or
"org" concept, it doesn't belong here — see Non-goals.

## The thesis: show, tell, do

Everything in this project sits at one of three stages, and work should
stay honest about which one it's at rather than blurring them:

1. **Show** — expose what's actually going on. Read local transcripts,
   report cost/tokens/activity. No interpretation beyond grouping and
   labeling.
2. **Tell** — turn what's shown into a recommendation a person can act on
   themselves. Still no side effects.
3. **Do** — build and deploy something that implements a recommendation
   without a human re-typing it by hand.

Full rubric and the reversibility rule that gates stage-3 work:
`CLAUDE.md`. Full rationale and a stage-by-stage audit of the codebase:
`docs/show-tell-do-model.md`.

## Non-goals (explicit — check new work against these)

- **Not a team/org observability stack.** Not competing with an
  OTEL-based team tool. No multi-seat concept, no org-wide rollout, no
  governance dashboard.
- **Not a Prometheus/Grafana stack to stand up and maintain.** Something
  you open and read, not infrastructure you operate.
- **Not a raw log dump.** Every view is a deliberate grouping (turn, unit,
  chapter, activity type) over the raw transcript, not the transcript
  itself reformatted.
- **No undisclosed network behavior.** Most analysis is local and `export`
  writes a local file only. The adopted architecture has exactly five network
  paths: hosted Haiku chaptering; optional local Ollama chaptering; opt-in
  pattern counters; separately credentialed, explicit findings submission;
  and opt-in hosted semantic rollup matching. Content leaves the machine in
  the hosted chaptering and semantic-rollup paths, and findings text leaves
  only on explicit submission. The exhaustive contract is
  [`docs/architecture.md`](docs/architecture.md#network-calls-the-exhaustive-list).
- **Not a generic pattern-matching DSL.** The shared pattern library
  matches only against `recommend`'s existing fixed rule ids — there's no
  independent matching engine against raw transcript data.
- **Not a big speculative rule engine.** `recommend` stays a small,
  curated, defensible set of checks, each tracing to a concrete,
  inspectable signal — never a vague "you could be more efficient."
- **Doesn't auto-apply recommendations.** Editing `settings.json`,
  installing a skill, retiring a skill — all human-applied, at least
  until a specific piece of Do-stage work explicitly earns an exception
  under `CLAUDE.md`'s reversibility rule.
- **Doesn't automate ahead of evidence.** A Do-stage automation doesn't
  get built on a Tell-stage rule that's only been checked against one
  session. Real, recurring, multi-session evidence comes first.
- **The community/pattern-library layer stays personal-only until the
  actual multi-user questions are solved** — consent separate from the
  existing opt-in gate, redaction, abuse/volume handling. Not solved by
  wishing it were simpler; not shipped open until it's solved.

## Success shape

Not a single metric — the project succeeds if someone can open it,
immediately understand what their usage is costing and why, and over time
trust it enough to let a Tell-stage recommendation change how they work,
without ever having to wonder what it's doing with their data in the
background.
