# Work Ledger Product Strategy

**Status:** Working strategy  
**Last substantive review:** 16 August 2026

## Purpose

The Product Vision states the future Work Ledger is trying to create. This document defines **how we will know whether we are moving toward it**.

The strategy is not a feature list. It is a set of measurable product bets, evidence standards, and unresolved research questions that should determine what earns a place on the roadmap.

The governing chain is:

> **Constitution → Product Vision → Product Strategy → Roadmap → Issues and PRs**

## 1. Strategic thesis

Work Ledger should expand its scope only when the evidence available at the current circle is strong enough to justify the next one.

The circles are:

> **session → cross-session work → personal trajectory → comparative team map → candidate shared practice → redesigned work**

This produces a deliberate strategy:

1. Establish credible reconstruction of individual work.
2. Demonstrate useful understanding of recurring work across sessions.
3. Show meaningful change in a person's practice over time.
4. Use that credibility to test comparison across people.
5. Learn what evidence is sufficient to identify transportable practice.
6. Only then make stronger recommendations about shared workflows, tooling, automation, and process redesign.

The order matters. Work Ledger should not jump to organizational prescription before it can explain the underlying work credibly.

## 2. Primary adoption hypothesis

The strongest near-term adoption surface is:

> **Show me how my work has changed.**

This combines immediate personal value with product validation.

If Work Ledger can reconstruct a person's earlier and later comparable work, identify meaningful changes, connect those changes to available evidence, and survive the person's scrutiny, then it earns trust for broader analysis.

### What we should measure

Early measurement can be lightweight and qualitative as long as it is explicit.

For trajectory analyses, record where possible:

- whether the user recognizes the described change as real;
- whether the user corrects or rejects a claimed change;
- whether the evidence cited is sufficient to understand why the claim was made;
- whether the analysis reveals something the user had not already articulated;
- whether the user takes an action because of it;
- whether the user returns to compare another period or another class of work;
- whether the user expresses willingness to use the same analysis across other people.

A trajectory surface is successful when it is not merely interesting but **credible enough to earn the next question**.

## 3. Measurement model: efficiency, effectiveness, impact

Work Ledger must not optimize what is easiest to count.

### Efficiency

**Question:** What resources were consumed relative to a useful output or outcome?

Potential evidence includes:

- token and model spend;
- number of model calls;
- repeated attempts;
- repeated reads or context reconstruction;
- tool churn;
- elapsed interaction or session time when reliable;
- amount of human rework;
- reuse of prior artifacts;
- substitution of deterministic tooling for repeated nondeterministic work.

Token spend alone is not efficiency.

### Effectiveness

**Question:** Did the work accomplish what it was trying to accomplish?

Potential evidence includes:

- task completion;
- code or artifacts shipped;
- successful tests or validation;
- issue/PR closure;
- accepted analysis or decision;
- defects resolved;
- requested output actually produced;
- follow-on correction or rollback as negative evidence.

The project does not yet have a universal effectiveness measure. Different classes of work will require different outcome signals.

### Impact

**Question:** What value did the outcome create beyond immediate completion?

Potential evidence includes:

- downstream reuse;
- adoption by another person or workflow;
- customer or user value;
- revenue or cost avoidance;
- policy or process change;
- reduced risk;
- eliminated future work;
- reusable infrastructure or tooling;
- influence on later decisions or implementations.

Impact will often require evidence outside the transcript corpus. Where it cannot be measured, Work Ledger should say so rather than silently substituting activity or spend.

## 4. Strategic evidence ladder

Different product claims require different evidence.

### Level 1 — Observed work

Can Work Ledger accurately reconstruct what happened in a session?

Evidence of success:

- attributable calls, cost, tools, chapters, and units;
- inspectable provenance;
- low rates of missing or obviously misattributed work;
- graceful handling of incomplete evidence.

This is the foundation of Show.

### Level 2 — Recurring work

Can Work Ledger recognize related initiatives, recurring behavior, repeated effort, and reusable artifacts across sessions?

Evidence of success:

- clusters that users recognize as representing the same work;
- recurring patterns that remain meaningful across more than one session;
- recommendations that trace to repeated rather than anecdotal evidence.

### Level 3 — Personal trajectory

Can Work Ledger identify how a person's practice changes over time?

Evidence of success:

- earlier/later comparisons that users validate;
- meaningful behavioral changes rather than superficial tool-frequency changes;
- connections to efficiency, effectiveness, or impact evidence where available;
- corrections captured as product learning rather than treated as user error.

This is the current strategic wedge.

### Level 4 — Comparative team map

Can Work Ledger compare multiple people's work without collapsing into ranking?

The desired output is a map of:

- work styles;
- recurring behaviors;
- areas of comparative efficiency;
- areas of comparative effectiveness;
- impact signals;
- complementary practices;
- role- or context-specific differences.

This level requires explicit consent and a new privacy/governance model. It is **future strategy, not current shipped scope**.

### Level 5 — Candidate shared practice

Can Work Ledger identify practices that may deserve broader adoption?

We do not yet know the complete admission rule.

Current working dimensions are:

- prevalence;
- effectiveness;
- impact;
- context and role dependence;
- evidence of transportability;
- novelty/innovation;
- human reviewer judgment.

The strategy should remain open to learning that these dimensions are incomplete or weighted differently than expected.

### Level 6 — Redesigned work

Can Work Ledger help convert observed learning into better systems of work?

Candidate outcomes include:

- reused artifacts;
- skills;
- deterministic tools;
- automations;
- shared workflows;
- conventions;
- changed processes;
- eliminated work.

Success here should be measured by the effect on the work, not by the number of automations shipped.

## 5. Current strategic bets

### Bet A — Fidelity creates trust

If the product reconstructs work accurately and makes claims inspectable, users will tolerate deeper interpretation.

**Evidence that strengthens the bet:** users validate session and cross-session reconstructions; disputed claims can be traced and corrected; users return to the product for explanation rather than only raw cost.

**Evidence that weakens the bet:** frequent disagreement about what work a session represented; users cannot understand why the product made a claim; cost remains the only surface users trust.

### Bet B — Personal trajectory is more valuable than static analytics

If Work Ledger shows how someone's practice has evolved, the product becomes a learning system rather than a dashboard.

**Evidence that strengthens the bet:** users recognize meaningful changes, discover reusable practices, or change behavior after seeing trajectory analysis.

**Evidence that weakens the bet:** comparisons mostly surface obvious tool-frequency changes with no useful interpretation; users do not distinguish the surface from a normal usage trend report.

### Bet C — Cross-person comparison can reveal complementarities without ranking

If analysis is framed around work practices rather than person scores, teams can learn from individual differences without turning the product into performance surveillance.

**Evidence that strengthens the bet:** users identify useful practices in another person's work, recognize context and role differences, and compose practices rather than asking for a single winner.

**Evidence that weakens the bet:** the dominant demand is league tables, productivity scores, or managerial evaluation; evidence cannot be separated from person-level judgment; consent and visibility cannot be made credible.

### Bet D — Reusable capability is a stronger value signal than lower spend

If Work Ledger identifies artifacts, tools, workflows, and automations that reduce future work or increase downstream value, it will better capture AI's organizational return than token optimization alone.

**Evidence that strengthens the bet:** detected candidates are reused, adopted, or eliminate repeated work; expensive sessions create assets with measurable downstream leverage.

**Evidence that weakens the bet:** reuse cannot be observed reliably; recommendations remain generic; lower-cost usage consistently predicts user-perceived value better than reuse or impact signals.

### Bet E — Human judgment remains essential to promotion into shared practice

Automated pattern detection can nominate candidates, but people should judge whether something deserves to become convention.

**Evidence that strengthens the bet:** reviewers reject superficially common patterns because context matters; novel one-person practices are promoted despite low prevalence; human review improves adoption quality.

**Evidence that weakens the bet:** objective outcome evidence becomes strong enough in a narrow domain to automate part of the promotion decision safely. If so, the constitution and strategy should be revisited explicitly rather than silently bypassed.

## 6. What we know today

The current repository already provides strong evidence for the first two circles:

- session-level cost, tokens, tools, chapters, units, and drill-down;
- cross-session rollups and recurring initiative grouping;
- trend and timeline views;
- within-session and cross-session waste/repetition signals;
- early recommendations;
- commit correlation and local session history.

This means the next strategic question is not "can we count Claude usage?" It is whether the existing corpus can support a credible **personal trajectory model** connecting changed behavior to changed outcomes.

## 7. What we do not know yet

The following are explicit research questions rather than roadmap commitments:

- What makes two pieces of work sufficiently comparable for an earlier/later trajectory claim?
- Which behavior changes are meaningful enough to surface?
- How should effectiveness be inferred for different classes of work?
- Which impact signals can be observed locally and which require external systems?
- How should user correction alter future interpretation?
- What evidence is sufficient to call a practice transferable?
- How should role and expertise differences be represented in cross-person analysis?
- What consent and access model makes team comparison legitimate?
- How should shared-practice candidates be reviewed and promoted?
- Where should Work Ledger end and Tricorder begin once team review/process evidence is involved?

Unknowns should stay visible until field evidence resolves them.

## 8. Roadmap admission rule

A strategic idea should move onto the roadmap when:

1. it advances a defined circle of observation;
2. the product claim it will make has a plausible evidence source;
3. the success or failure of the bet can be observed;
4. it passes the Constitution's admission test;
5. it is mature enough to express as current intent rather than open-ended research.

A roadmap item should identify the strategic bet or evidence level it serves. Issues and PRs should then implement that intent without redefining it.

## 9. Strategy review cadence

Review this document when field evidence materially changes what we believe about:

- the adoption wedge;
- the evidence ladder;
- how efficiency, effectiveness, or impact can be measured;
- the viability of team-scale comparison;
- the promotion of individual practice into shared capability;
- the boundary between Work Ledger and adjacent products.

Do not rewrite strategy merely because an issue ships. The roadmap changes more frequently; strategy changes when our beliefs change.
