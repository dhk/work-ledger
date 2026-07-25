# work-ledger

A lightweight usage analytics tool for individual Claude Code users — near-
real-time cost/token visibility read straight from local session
transcripts, no telemetry stack required. See `README.md` for the full
feature set and `docs/` for design docs on individual subsystems.

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
   actually implements a recommendation and drives cost down. Nothing in
   the codebase does this yet; see the reversibility rule below before
   starting anything here.

Full rationale, current stage-by-stage audit, and open questions:
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

## Governance artifacts

Three durable, project-level artifacts, each answering a different
question and changing at a different rate — don't merge them:

- **`PRODUCT_BRIEF.md`** — what this is, who it's for, and an explicit
  non-goals list. Changes rarely.
- **`ROADMAP.md`** — where things stand right now, grouped by theme, not
  a restated issue list. Changes when a theme's shape changes.
- **`docs/architecture.md`** — how the system is actually built: the
  core data model, module map, and structural constraints. Changes when
  the system's shape changes, not per-feature.

**Before filing a new issue or starting a design doc**, check it against
`PRODUCT_BRIEF.md`'s non-goals and `docs/architecture.md`'s constraints,
then place it in a theme in `ROADMAP.md` (adding a new theme if it
genuinely doesn't fit one). This is a guardrail, not a gate — the point is
making sure new work doesn't quietly drift the product's intent, not
blocking work on process.

## Development

```sh
pip install -e ".[test]"
pytest
```

The suite is fully offline and hermetic — every test builds its own
synthetic transcript files rather than touching `~/.claude/projects/` or
`~/.config/work-ledger/`, and the one call that costs real money
(`chapters`' Haiku pass) is mocked. See README's "Development" section for
what each test file covers.

## Design docs

Substantial design decisions get a doc under `docs/` (Status/Author/
Related header, Problem, Goals/Non-goals, Open questions — see any
existing file there for the shape) plus a linked GitHub issue. Keep
"proposed" docs and "decided" sections clearly distinguished — several
existing docs mix both, always labeled.
