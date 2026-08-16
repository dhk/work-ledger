# Work Ledger Constitution

**Status:** Governing document  
**Last substantive review:** 16 August 2026

## Purpose

This constitution is the highest-order statement of what Work Ledger is loyal to and how the project should make decisions when product ideas, implementation convenience, measurement, or short-term opportunity pull in different directions.

The governing hierarchy is:

> **Constitution → Product Vision → Product Strategy → Roadmap → Issues and PRs**

Each layer serves the layer above it:

- **The Constitution** defines the project's enduring principles, boundaries, and epistemic commitments.
- **The Product Vision** describes the future we are trying to create.
- **The Product Strategy** defines how we will test progress toward that vision and what evidence should change our minds.
- **The Roadmap** is the current manifestation of intent: the bets and capabilities we choose to pursue now.
- **Issues and PRs** implement that intent.

When they conflict, the higher-order artifact wins. A PR should not quietly redefine the roadmap; the roadmap should not quietly redefine strategy; strategy should not quietly redefine the vision; and none of them may silently violate the constitution.

## 1. Work Ledger is about the work

Work Ledger is work-centric.

Its subject is not the personality, worth, rank, or productivity score of the person doing the work. Its subject is **how work actually happens and how that work might become better**.

Within the broader family of tools:

- **Wingman is about the person.**
- **Work Ledger is about the work.**
- **Tricorder is about team practice: what teams build and how review and collaboration help them get to good.**

The evidence can overlap. The organizing question must not.

Work Ledger asks:

> **What does this evidence tell us about the work and how it could improve?**

## 2. Improve the work, not the bill

Work Ledger is not a token-cost optimization product.

Spend is useful because it makes resource consumption visible and forces a concrete question:

> **What did I get for what I spent?**

But lower spend is not the objective. A more expensive workflow may be better if it produces substantially better outcomes, creates reusable capability, prevents later work, improves reliability, or has greater downstream impact.

Work Ledger should distinguish:

- **Efficiency:** resources consumed relative to useful output or outcome.
- **Effectiveness:** the degree to which the intended outcome was achieved.
- **Impact:** the value created beyond immediate task completion, including reuse, adoption, risk reduction, customer value, policy or process change, and organizational leverage.

Token spend is an input measure. It must never silently become a proxy for value.

## 3. Evidence before interpretation; interpretation before intervention

Work Ledger follows the **Show → Tell → Do** progression.

### Show

Reconstruct and expose what actually happened. Group, attribute, compare, and make the evidence inspectable.

### Tell

Interpret the evidence and make recommendations that a person can assess and act on. Recommendations must trace to concrete, inspectable signals and must communicate uncertainty.

### Do

Implement a recommendation only after the recommendation has earned that right through evidence, validation, and an appropriate human-control model.

The stages may inform one another, but the project must not skip them merely because automation is technically possible.

> **Do not automate ahead of evidence.**

## 4. Practice is a trajectory, not a snapshot

Work changes over time.

A single session is evidence. A person's history across comparable sessions is stronger evidence. Changes in that person's practice over time can reveal learning, improvement, regression, specialization, and the emergence of reusable capability.

Work Ledger should therefore reason across expanding circles of observation:

> **session → cross-session work → personal trajectory → comparative team map → candidate shared practice → redesigned work**

Before confidently comparing people, Work Ledger should demonstrate that it can recognize meaningful change within one person's own work.

A core question is:

> **What do you do differently now that appears to work better than what you did before?**

## 5. Compare to understand, not to rank

Team-scale analysis exists to reveal differences, complementarities, and transferable practice—not to manufacture a productivity leaderboard.

People may exhibit different comparative advantages:

- one may decompose problems particularly well;
- another may converge with less resource consumption;
- another may create unusually reusable artifacts;
- another may identify failure modes early;
- another may turn repeated work into deterministic tooling.

The organizational opportunity is not to force everyone into one person's workflow. It is to understand which elements are effective, which are contextual, which are idiosyncratic, and which can be composed into stronger shared practice.

> **The purpose of team analysis is synthesis, not ranking.**

> **Work Ledger should reveal comparative advantage, not manufacture conformity.**

## 6. Individual practice is evidence; shared practice is discovered

A successful workflow observed in one person's corpus is a **candidate**, not automatically a standard.

Likewise, widespread repetition does not prove that a practice is good. Frequency is evidence, not validation. Novel practice may begin with one person and still be worth adopting.

Today we can reasonably hypothesize a progression such as:

> **individual evidence → overlapping patterns across people → candidate shared practice → demonstrated usefulness → human judgment → possible convention**

But the exact promotion criteria are not yet known.

That uncertainty is part of the constitution rather than a gap to hide. Work Ledger must not encode organizational doctrine where evidence and experience remain immature.

Candidate generalization should consider at least:

- **Prevalence:** isolated or recurring; individual or shared.
- **Effectiveness:** whether there is evidence that the practice improves the work or outcome.
- **Impact:** whether value extends beyond the immediate task.
- **Context:** what role, problem, constraints, expertise, and environment make the practice work.
- **Human judgment:** whether a knowledgeable reviewer believes the practice is appropriate, transportable, and worth institutionalizing.

> **Work Ledger surfaces evidence for generalization; people decide what deserves to become shared practice.**

## 7. Preserve context when generalizing

A pattern is not transportable merely because its surface form repeats.

Work Ledger should distinguish:

- genuine shared need from coincidental similarity;
- domain expertise from generally useful technique;
- role-specific practice from team-wide convention;
- innovation from novelty;
- correlation from evidence of causation;
- consensus from conformity.

When recommending reuse or adoption, the system should preserve enough context to explain **where the practice came from, where it worked, and what assumptions may limit transfer**.

## 8. The person whose work is observed retains agency

Work Ledger may analyze a person's work. It must not quietly turn that person into the product being scored.

The project should not become covert employee surveillance, hidden performance scoring, or automated judgment about a person's worth, promotability, employability, or compensation.

Team analysis should expose work patterns in service of learning and improvement. Material changes in who can see personal evidence, how comparisons are used, and what organizational decisions may be made from them require explicit product and governance decisions; they must not arrive as incidental implementation details.

## 9. Provenance and uncertainty are product features

A consequential claim should be inspectable back to its evidence.

Work Ledger should distinguish among:

- **Observed:** directly present in transcripts, tool traces, artifacts, commits, or other evidence.
- **Derived:** deterministically calculated or grouped from observed evidence.
- **Inferred:** an interpretation or synthesis made from the evidence.
- **Validated:** an interpretation that has been checked against additional evidence or repeated observations.
- **Endorsed:** a conclusion a human has judged useful or appropriate for adoption.

These states must not silently collapse into one another.

Absence of evidence is not evidence of absence. A plausible story is not a fact. A repeated pattern is not automatically a best practice.

## 10. Reversibility determines delegated authority

When Work Ledger reaches the Do stage, the amount of automation permitted should depend on blast radius and reversibility.

- **Standalone or additive work** that does not alter existing state may be highly automated.
- **Mutating existing configuration or practice** should normally be proposed as an inspectable change for human approval.
- **Actions that spend money, affect shared state, deploy ongoing automation, or alter other people's environments** require explicit opt-in and stronger controls.

Human review is not ceremony. It is part of the product model where consequences are meaningful.

## 11. Privacy and network behavior must be legible

Work Ledger begins from unusually sensitive evidence: detailed records of how someone actually works.

Local-first processing remains the default posture. Any content leaving the user's machine must be deliberate, documented, and visible enough that a reasonable user can understand what is being sent and why.

No feature earns exemption from this principle because a hosted service would be convenient.

Team-scale capability will require explicit answers to questions that the current single-person product does not yet need to solve, including consent, visibility, redaction, retention, organizational access, and downstream use. Those questions must be solved before personal evidence is casually pooled.

## 12. Earn broader scope through demonstrated understanding

Work Ledger's first obligation is to understand the user's own work credibly.

A particularly valuable adoption and validation surface is:

> **Show me how my work has changed.**

The experience should reconstruct earlier and later comparable work, surface meaningful changes in behavior or workflow, connect those changes to available efficiency/effectiveness/impact evidence, and allow the person to correct the interpretation.

The trust progression is intentional:

> **understand my work → understand how my work is changing → understand how others work → understand what we can learn from one another → improve how the team works**

Broader claims should be earned through narrower demonstrated competence.

## 13. Optimize for reusable capability and eliminated work

The most valuable outcome is not necessarily a cheaper instance of the same process.

Work Ledger should look for opportunities to:

- reuse an existing artifact rather than recreate it;
- turn recurring practice into a skill, tool, workflow, or convention;
- replace expensive nondeterministic work with deterministic machinery where appropriate;
- remove unnecessary handoffs and repetition;
- redesign a process around new capability;
- eliminate work that no longer needs to exist.

The ultimate question is not merely, "How can this task be done for fewer tokens?"

It is:

> **Given what we now know, should this work be done this way at all?**

## 14. Epistemic humility is mandatory

This project is exploring a new class of evidence about AI-assisted work. We do not yet know the complete model for effectiveness, impact, transferability, or organizational adoption.

The system should say when those things are unknown.

Research questions belong in strategy and design documents until the evidence is strong enough to promote them. Unknowns should not be prematurely converted into scoring formulas, hard thresholds, or governance rules simply to make the product appear finished.

## 15. Admission test for consequential product work

Before a substantial feature moves onto the roadmap, ask:

1. **What does this teach us about the work?**
2. **Which circle of observation does it serve?** Session, cross-session, trajectory, team comparison, shared practice, or redesign?
3. **What evidence supports the claim the feature will make?**
4. **Is it Show, Tell, or Do?** Has the preceding stage earned the next one?
5. **Does it preserve the distinction between efficiency, effectiveness, and impact?**
6. **Does it improve understanding or enable learning rather than ranking people?**
7. **What context could make the apparent pattern non-transferable?**
8. **What human judgment is required?**
9. **What is the privacy, network, and blast-radius consequence?**
10. **Could this help eliminate or redesign the work rather than merely optimize the current form?**

If those questions cannot be answered credibly, the feature may still be a useful experiment—but it should be labeled as such rather than promoted as settled product behavior.

## 16. Amendment

This constitution should change rarely, but it is not sacred text.

Amend it when accumulated evidence demonstrates that a governing principle is wrong, incomplete, or no longer adequate. Constitutional changes should be explicit, reviewed as such, and accompanied by corresponding review of the Product Vision and Product Strategy.

Routine roadmap evolution, implementation decisions, and feature additions are not constitutional amendments.
