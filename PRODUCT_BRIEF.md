# Product Brief

## What this is

work-ledger is a lightweight usage analytics tool for **individual Claude
Code users** — the person watching their own $20/month or $100/month
subscription, not a team with an observability stack. It reads Claude
Code's own local session transcripts and turns them into near-real-time
visibility into what a session or automation is costing, why, and — as
the tool matures — what to do about it.

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
- **No data leaves this machine without an explicit action.** `export`
  writes a local file and stops — there is no submit/upload flag, and
  there never automatically will be. The one exception (the `chapters`
  Haiku call) is disclosed, costed, and requires the user's own API
  credentials — never silent, never bundled into another action.
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
