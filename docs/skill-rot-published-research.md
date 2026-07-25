# Research notes: published prior art on skill/agent overlap and consolidation

Status: reference notes, not a build proposal - captures a research pass
requested alongside `docs/skill-rot-consolidation-design.md`, kept as a
separate file since it's landscape research rather than a design for this
repo specifically.
Related: `docs/skill-rot-consolidation-design.md` (the actual proposal for
work-ledger; this doc is its supporting prior-art survey).

## Why this is a separate file from the design doc

The design doc proposes a specific mechanism for this repo. This doc
answers a different question - "is anyone else already solving this, and
what did they build" - so the two can be read independently and this one
can be updated as new prior art surfaces without touching the proposal
itself.

## Three registers this problem shows up in, and they don't yet cite each other

**1. Academic agent-skill research (mostly 2026, all pre-product).** A
cluster of papers names this "skill evolution" directly:

- **SkillNet** builds a skill-similarity graph across a growing library -
  the graph is what tells you whether two skills should be reused as-is or
  merged.
- **SkillX** does the fuller lifecycle: merges similar skills, decomposes
  overly-broad ones back apart, and evaluates generalization after each
  change.
- **SkillReducer** reframes the problem as content cleanup rather than
  graph-matching - prunes bloated descriptions, reorganizes a skill's
  content into "rules" vs. "references." Closer to compression than to
  merge/delete.
- **SkillsVote** proposes lifecycle governance end to end: collection to
  recommendation to evolution - a skill's whole life gets tracked, not
  just its creation.
- **SkillResolve-Bench** benchmarks the retrieval-time version of this
  failure: two skills that do the same thing, and an agent that can't
  tell them apart when choosing which to use ("same-capability
  ambiguity").

None of these are shipped products - they're benchmarks/frameworks, which
means this is a recognized open problem in the research community, not a
solved one anywhere yet.

**2. Enterprise/industry framing - "agent sprawl," a different scale of
the same shape.** Instead of one project's skills overlapping, whole teams
stand up near-identical agents independently (Workato and CIO.com both
describe redundant "lead follow-up"-style agents built by different
departments with no shared data model). The proposed fix is organizational
- identify overlaps, consolidate, centralize under one platform with audit
trails - closer to a governance/procurement problem than a technical
merge algorithm. Relevant context, but a different-scale problem than one
repo's skill directory; worth not conflating the two.

**3. What Anthropic has actually shipped - narrower than either of the
above.** Two real, current mechanisms in Claude Code:

- **Exact-name collision resolution.** Same-named skills at different
  levels (enterprise/personal/project/plugin/bundled) resolve via a
  defined precedence, and same-named skills at different directory depths
  get disambiguated automatically (e.g. `apps/web:deploy` vs. root
  `deploy`). This solves *identical names*, not *semantic overlap between
  differently-named skills* - the harder case this repo's design doc is
  actually about.
- **An authoring principle, not a detection mechanism.** The official
  best-practices guidance warns against a skill "restating what Claude
  would do by default," and frames skill creation as justified when
  something "keeps getting pasted into chat" or a `CLAUDE.md` section "has
  grown into a procedure." That's a *creation* gate, symmetric with this
  repo's "move into workflow" outcome - but there's no published
  equivalent *retirement* gate. Nothing in the current product looks at an
  existing skill library and asks whether any two entries should collapse
  into one.

## The most operationally mature template, and it isn't agent research

Knowledge-base/documentation management has fought duplicate-content rot
for years, well before agent skills existed, and its practices are further
along than anything the agent-skill papers above have operationalized:

- A **content registry** tracking every article's owner, lifecycle status
  (`active` / `merge-candidate` / `deprecated`), and canonical purpose.
- **Scheduled similarity scans** (weekly cadence, ~90%+ similarity
  threshold is a commonly cited starting point) rather than one-off
  audits.
- **Merge execution as a defined action**, not just a flag: retire the
  losing article, replace it with a pointer/redirect to the canonical one,
  update anything that referenced it.
- **Mandatory ownership** - every piece of content has a named owner
  responsible for noticing when it's gone stale or been superseded.

This maps close to one-to-one onto the merge/subsume/move-into-workflow
split in `skill-rot-consolidation-design.md`, and is the strongest
candidate to borrow a concrete mechanism from rather than inventing one
from scratch.

## Takeaways folded into the design doc's direction

- A lightweight **status field per skill** (`active` /
  `merge-candidate` / `superseded-by:<id>`) is a cheaper v1 than a full
  similarity graph (SkillNet's approach) - graph-based matching is a
  reasonable v2 once a library is large enough that manual review gets
  painful.
- **"Move into workflow" should leave a redirect, not a silent deletion** -
  same pattern the KB world uses, so an old `/skill-name` habit or
  reference doesn't just start failing quietly.
- **Rot isn't only cross-skill overlap.** SkillReducer's framing matters:
  a single skill can rot on its own axis (bloat, staleness) independent of
  any sibling - worth treating as a second, cheaper-to-detect category
  alongside cross-skill overlap.
- **Keep project-scale and org-scale explicitly separate.** One project's
  skill directory (SkillNet/SkillReducer-scale, solvable with a local
  audit) and an organization running many teams' worth of agents ("agent
  sprawl," a governance problem) are different problems with different
  fixes - worth not conflating if this ever grows past a single project.

## Sources

- [Agent Skill Evaluation and Evolution: Frameworks and Benchmarks](https://arxiv.org/pdf/2606.11435)
- [SkillOpt: Executive Strategy for Self-Evolving Agent Skills](https://arxiv.org/pdf/2605.23904)
- [SkillsVote: Lifecycle Governance of Agent Skills](https://arxiv.org/pdf/2605.18401)
- [SkillResolve-Bench: Measuring and Resolving Same-Capability Ambiguity in Agent Skill Retrieval](https://arxiv.org/pdf/2606.10388)
- [Harnessing Agent Skills: Architectural Patterns and a Reference Architecture for Skill-Mediated LLM Agents](https://arxiv.org/pdf/2606.20631)
- [Contain the Chaos: Why AI Sprawl is the Next Big Security Challenge](https://www.workato.com/the-connector/contain-ai-sprawl/)
- [New agentic AI tools bring new threat: agent sprawl | CIO](https://www.cio.com/article/3987692/new-agentic-ai-tools-bring-new-threat-agent-sprawl.html)
- [How to Avoid Agent Sprawl While Enabling AI Innovation With MuleSoft](https://blogs.mulesoft.com/automation/how-to-avoid-agent-sprawl/)
- [Skill authoring best practices - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Extend Claude with skills - Claude Code Docs](https://code.claude.com/docs/en/skills)
- [Why Knowledge Base Duplication Is Hurting Your Customer Experience - Ariglad](https://www.ariglad.com/blogs/knowledge-base-duplication)
- [KB Content Deduplication Strategies](https://www.supportbench.com/prevent-kb-content-duplication-across-products-versions/)
