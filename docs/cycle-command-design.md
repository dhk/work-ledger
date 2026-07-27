# Design: `work-ledger cycle`

Status: decided, implemented in the same PR as this doc. Small enough in
scope not to need a separate proposal/decision split - one pass.
Author: written by Claude, from a conversation with the repo owner.
Related: issue #73, `CLAUDE.md`'s "CLI/MCP command conventions" section
(the "cycle"/upgrade-path requirement this implements), `docs/local-model
-chaptering-design.md`'s env-var precedent (unrelated mechanism, same
"detect and report before acting" spirit as `--check-status` here),
`INSTALL.md` (the manual steps this automates).

## Problem

`CLAUDE.md` already commits this project to a rule: every CLI/MCP command
gets a "cycle"/upgrade path in two variants (local editable-clone vs.
cycle-from-last-published), and if a command's own upgrade story is more
than "git pull, done" - a background/daemon process in particular -
"build the actual cycle command, don't just describe the steps and leave
them manual." `work-ledger serve` and `work-ledger-mcp` are exactly that
case, and no such command exists yet. `INSTALL.md` documents the manual
steps; nothing runs them.

## Goals

- One command, `work-ledger cycle`, that does the right upgrade step for
  however this install actually happened - editable clone vs. pipx/uv
  tool/pip - without the person needing to remember which one applies to
  them.
- `--check-status` (mirroring `miso --check-status`'s existing shape):
  report what `cycle` would do and what it currently detects, without
  changing anything - a dry run, not a guess.
- Never silently clobber uncommitted local work in an editable checkout.

## Non-goals (for this pass)

- **Auto-detecting and killing a running `work-ledger serve` process.**
  `cycle` checks whether something is listening on `serve`'s configured
  port and tells the person to stop/restart it themselves - it does not
  guess a PID from a port number and send it a signal. This codebase has
  no existing PID-tracking infrastructure for `serve` (it's designed to
  run in the foreground until Ctrl-C, same as the plain live dashboard),
  and guessing wrong would mean killing a process this command was never
  told to touch. Building real PID tracking for `serve` is a separate,
  larger piece of work if it's ever wanted - not bundled into this pass.
- **Auto-restarting `serve`/`work-ledger-mcp` after upgrading.** Same
  reasoning - `cycle` doesn't know what arguments the person originally
  ran `serve` with (custom `--port`, `--since`/`--until`), and respawning
  a detached background process on someone's behalf carries real
  surprise-factor risk (wrong working directory, an orphaned process, an
  unclear place for its output to go). `cycle` reports what it detects
  and reminds the person to restart manually.
- **A generic process-management framework.** This is one command
  solving one documented gap, not infrastructure other commands are
  expected to build on.

## Architecture

### Install-mode detection

Via `importlib.metadata.distribution("work-ledger")` and PEP 610's
`direct_url.json` (which `pip`/`pipx`/`uv` all write on install):

- **Editable**: `direct_url.json` has `"dir_info": {"editable": true}`.
  The `url` field (a `file://` URL) gives the repo's on-disk path.
- **Published, from a git ref**: `direct_url.json` present, not editable,
  with a `"vcs_info"` block - the original `git+https://...` URL is
  preserved there so the same ref can be re-installed on upgrade.
- **Published, from PyPI**: no `direct_url.json` at all (or one with
  neither `dir_info.editable` nor `vcs_info`) - a normal index install.

Installer (which upgrade command to run) is a heuristic over
`sys.executable`'s path: contains `pipx` → `pipx upgrade work-ledger`;
contains `uv/tools` or `uv\tools` → `uv tool upgrade work-ledger`;
otherwise → plain `pip install --upgrade` (using the git ref URL if this
was a git install, else the bare package name for a PyPI install).
Degrades to printing the plain-pip command as a suggestion (not a guess
it silently runs) if the heuristic can't tell.

### `serve` port check

A local, best-effort TCP connect attempt to `127.0.0.1:<port>` (default
8765, same default `serve` itself uses, overridable with `--port` to
match a non-default `serve --port`). A successful connect means
*something* is listening there - reported as "serve looks like it's
running," not asserted as fact (another process could coincidentally
hold that port). No signal is ever sent to whatever's listening.

### The actual cycle

- **Editable**: `git status --porcelain` first - if there are uncommitted
  changes, stop and tell the person to commit/stash first rather than
  risk a confusing `git pull` failure. Otherwise `git pull` in the repo
  root, reporting the commit SHA before and after (identical SHA means
  "already up to date," reported as such, not as an error).
- **Published**: run the detected upgrade command, reporting old/new
  version from `importlib.metadata` before and after.
- Either path, if the port check found something listening: print a
  reminder to stop and restart it after the upgrade completes.

### `--check-status`

Runs every detection step above and prints what's found and what plain
`work-ledger cycle` would do - no `git pull`, no upgrade command, no
prompts, no state changes. Matches `miso --check-status`'s existing
"dry-run readiness check" shape and wording style.

## Migration/compatibility

Purely additive - a new subcommand, no changes to any existing command's
behavior or output.
