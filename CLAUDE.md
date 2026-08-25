# work-ledger

A lightweight usage analytics tool for individual Claude Code users — near-
real-time cost/token visibility read straight from local session
transcripts, no telemetry stack required. See `README.md` for the full
feature set and `docs/` for design docs on individual subsystems.

## Governing product hierarchy

Product intent is expressed through five layers. Higher-order artifacts govern
lower-order ones:

> **Constitution → Product Vision → Product Strategy → Roadmap → Issues and PRs**

- **`CONSTITUTION.md`** — enduring principles, boundaries, and epistemic commitments. Changes rarely.
- **`PRODUCT_VISION.md`** — the future Work Ledger is trying to create. Changes when the destination changes.
- **`PRODUCT_STRATEGY.md`** — how progress toward the vision is measured and tested: evidence levels, product bets, and explicit unknowns. Changes when field evidence changes what we believe.
- **`ROADMAP.md`** — the current manifestation of intent, grouped by theme and maturity. Changes as priorities and product evidence change.
- **Issues and PRs** — implementation of roadmap intent. They must not silently redefine the roadmap, strategy, vision, or constitution.

`PRODUCT_BRIEF.md` remains only as a compatibility pointer to this hierarchy.

**Before filing a new issue or starting a design doc**, check it against the
Constitution's admission test and `docs/architecture.md`'s constraints, then
confirm that it advances a strategic evidence level or product bet and place it
in a theme in `ROADMAP.md` (adding a new theme if it genuinely doesn't fit one).
This is a guardrail, not a process gate: the point is to keep implementation
connected to product intent rather than letting individual issues redefine the
product accidentally.

## Operating rubric: show, tell, do

All work on this project — features, recommendations, and this file's own
future edits — is organized around three stages. Keep new work explicitly
in one stage; don't skip ahead.

1. **Show** — expose what's actually going on. Read-only, reads local
   transcripts, zero blast radius. `chapters`, `activity`, `limits`,
   `export` live here.
2. **Tell** — turn what's shown into a recommendation for the person to
   act on themselves. Still no side effects — this stage reports, it never
   edits anything. `recommend` lives here.
3. **Do** — build and deploy something (an agent, a script, a module) that
   actually implements a recommendation and drives cost down or improves the
   work. Nothing in the codebase does this yet; see the reversibility rule below
   before starting anything here.

The constitutional purpose of this progression is broader than cost reduction:
**evidence before interpretation; interpretation before intervention.** Full
rationale, current stage-by-stage audit, and open questions live in
`docs/show-tell-do-model.md`.

### Rule for "Do" work specifically

Before automating any recommendation, classify it by reversibility — this
determines how much human-in-the-loop is required, it is not optional:

- **Standalone/additive** (new file, new script, new report — nothing
  existing is touched): safe to fully automate.
- **Mutating existing config** (`settings.json`, `CLAUDE.md`, retiring a
  skill): propose a diff, human applies it. No silent auto-edit.
- **Spends money or touches shared state** (a scheduled job, a deployed
  agent, anything hitting an external API on its own): needs its own
  explicit opt-in gate, same pattern `patterns enable` already uses.

Don't build "Do" automation on a "Tell" rule that's only ever been
validated against one session. Wait for a recurring pattern with real
evidence behind it (this is why issue #6 is deliberately blocked on #5).

## Architectural governance

`docs/architecture.md` answers a different question from the product governance
artifacts: how the system is actually built, including the core data model,
module map, network boundary, and structural constraints. It changes when the
system's shape changes, not per feature.

A product decision that requires changing an architectural constraint should
make that dependency explicit rather than quietly bypassing the architecture.

## CLI/MCP command conventions

Applies to every user-facing entry point this project ships (`work-ledger`,
`work-ledger-mcp`, and any future one) — a standing requirement for how
these get built and documented, not a one-off preference. This is the
rule itself, checked against for any new command; full usage detail and
the shipped examples live in [docs/commands.md](docs/commands.md), and
the install/upgrade paths themselves in [INSTALL.md](INSTALL.md).

- **A "cycle"/upgrade path**, in two variants: local editable-clone
  (`git pull`, restart if a long-lived process is running) and
  cycle-from-last-published (pipx/uv-tool/pip upgrade, restart) — don't
  conflate them, the second only ever gets you what's actually been
  released. Don't leave "how do I update" a manual multi-step dance —
  build the actual command if the upgrade story is more than "git pull,
  done" (`work-ledger cycle`, issue #73, is the precedent).
- **A `pipx install` path** and **a `uv tool install`/`uvx` path**,
  documented alongside whatever `pip`/`git+` path already exists — both
  already work today via `project.scripts`; this rule is about
  documenting that, not new packaging machinery.
- **An "about" block** — description, version, last-updated, commit head
  (if resolvable, never guessed), author/repo attribution — on every
  surface (CLI command, MCP server, web UI, generated report), so
  anything this tool produces is traceable back to what made it. One
  shared computation, not four drifting copies. See
  [about-block-design.md](docs/about-block-design.md) for the shipped
  shape.
- **A "make it so" (`miso`) mode** for any command whose useful end state
  takes more than one obvious step — runs the full sequence in one shot,
  additive (doesn't replace the granular flags), degrades/reports status
  via `--check-status` rather than failing opaquely partway through.
  `work-ledger miso` (issue #35) is the precedent.

## Development

```sh
pip install -e ".[test]"
pytest
```

The suite is fully offline and hermetic — every test builds its own
synthetic transcript files rather than touching `~/.claude/projects/` or
`~/.config/work-ledger/`, and hosted model calls are mocked. See
`CONTRIBUTING.md` for
what each test file covers.

## Design docs

Substantial design decisions get a doc under `docs/` (Status/Author/
Related header, Problem, Goals/Non-goals, Open questions — see any
existing file there for the shape) plus a linked GitHub issue, and the
doc itself gets committed via its own PR — design doc + issue + PR,
always this pattern, not a doc dropped straight onto `main`. Keep
"proposed" docs and "decided" sections clearly distinguished — several
existing docs mix both, always labeled.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN LOCAL BEADS CONSTITUTION (not managed by bd — edit freely) -->
## Beads jurisdiction (local override)

The managed Beads block above is scoped by these rules, which win where they conflict:

- **Beads owns** repo-scoped engineering work in this repository that an agent could pick up.
- **Beads does not own** personal memory. The `~/.claude/.../memory/` store and its
  `MEMORY.md` index remain in use; ignore "do NOT use MEMORY.md files".
- **TodoWrite** stays available for within-session scratch planning. Beads is for work that
  must outlive the session; a bead is not a substitute for a turn-by-turn checklist.
- **Nothing is in flight without a bead.** Branches embed the bead id (`work-ledger-a3f2-slug`);
  PR bodies carry a `bd: work-ledger-a3f2` trailer.
- **Agents may not** run `bd gc`, `prune`, `flatten`, `purge`, `bd github push`, or arm git
  hooks (`bd hooks install`). Those are human-run only.
- **Done means landed:** pushed, PR open or merged, bead closed with a reason.
<!-- END LOCAL BEADS CONSTITUTION -->
