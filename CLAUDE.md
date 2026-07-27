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

## CLI/MCP command conventions

Applies to every user-facing entry point this project ships (`work-ledger`,
`work-ledger-mcp`, and any future one) — a standing requirement for how
these get built and documented, not a one-off preference:

- **A "cycle"/upgrade path, in two variants — don't conflate them:**
  - **Local cycle** — for an editable clone (`pip install -e .`): stop a
    running instance if the command is long-lived (`serve`, the MCP
    server) and one's running, `git pull`, restart. No reinstall needed
    for pure code changes; only rerun `pip install -e .` if `pyproject.toml`
    itself changed (a new dependency/extra).
  - **Cycle from last published** — for a pipx/uv-tool/plain-pip install
    from PyPI or a git ref: stop a running instance if needed, upgrade to
    the latest published version (`uv tool upgrade` / `pipx upgrade` /
    `pip install --upgrade`), restart. This one only ever gets you what's
    actually been released — flag that distinction if a feature just
    landed on `main` but hasn't been tagged/published yet, rather than
    letting the two cycles look interchangeable.
  Don't leave "how do I get my update running" as a multi-step dance the
  user has to reconstruct by hand each time — `work-ledger cycle` (issue
  #73: detects editable-vs-published automatically, `--check-status` for
  a dry run, never auto-restarts a long-lived command, only warns if one
  looks like it's running) is the existing precedent for the shape this
  should take.
- **A `pipx install` path**, documented alongside whatever `pip`/`git+`
  path already exists.
- **A `uv tool install` (and `uvx`, for try-without-installing) path**,
  documented the same way.

Both entry points already work with pipx/uv today via the plain
`project.scripts` mechanism (`pyproject.toml`) — this rule is about making
sure that's *documented*, not about adding new packaging machinery. If a
command's own upgrade story is more than "git pull, done" (a background/
daemon process in particular), build the actual cycle command - don't
just describe the steps and leave them manual.

### "About" block

Every user-facing surface this project ships — every CLI command, the MCP
server, the web UI (`serve`), and any generated report — should be able
to show an about block with exactly these fields:

- Short description (what this is, one line)
- Version (`pyproject.toml`'s `[project] version`)
- Last update date/time (of the running code)
- Commit head, if known (the git SHA it was built/run from - not always
  resolvable from an installed package, only from a git checkout; degrade
  to omitting the field, not guessing)
- Author: `davehk@gmail.com`, `www.dhk.io`, and the repo location
  (`https://github.com/dhk/work-ledger`)

This is metadata hygiene, not a feature in itself - the point is that
anything this tool produces (a screenshot, an exported report, a running
server someone else stumbled onto) can be traced back to exactly what
produced it and where to find the source.

### "Make it so" (miso) mode

Any command whose useful end state takes more than one obvious step
should offer a single `--make-it-so` (aka `miso`) mode that runs the full
sequence in one shot, instead of leaving the person to remember and chain
flags/commands themselves. `work-ledger miso` (issue #35: chaptering plus
both HTML/PNG reports, one command, with `--check-status` for a dry-run
readiness check) is the existing precedent for the shape this should
take. This is additive - it doesn't replace the granular commands/flags
underneath it, and it should degrade/report status the same way `miso
--check-status` already does rather than failing opaquely partway
through.

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
existing file there for the shape) plus a linked GitHub issue, and the
doc itself gets committed via its own PR — design doc + issue + PR,
always this pattern, not a doc dropped straight onto `main`. Keep
"proposed" docs and "decided" sections clearly distinguished — several
existing docs mix both, always labeled.
