# Installing work-ledger

## Requirements

- Python 3.10+
- `pip`
- An existing Claude Code install with at least one session under
  `~/.claude/projects/` (work-ledger reads those transcripts directly — if
  you've never run Claude Code, there's nothing for it to show you yet)

Two features can call the Anthropic API directly, separate from your Claude
Code session, and need their own credentials:

- `work-ledger chapters` — groups prompt and unit snippets into initiatives
  via Claude Haiku by default; an optional Ollama backend is local instead
- semantic `rollup`/`waste --cross-session` matching — sends unmatched
  initiative titles to Haiku only when
  `WORK_LEDGER_ROLLUP_MATCHING=semantic` is set

Either `ANTHROPIC_API_KEY` set in your environment, or an
[`ant auth login`](https://platform.claude.com/docs/en/api/sdks/cli)
profile, works. `work-ledger --once` and `work-ledger --detail` (the
default dashboard) need neither — they only read local transcripts.

## Option A: the one-liner

```sh
curl -fsSL https://raw.githubusercontent.com/dhk/work-ledger/main/scripts/install.sh | bash
```

This is a `pip install` from PyPI plus some printed next-steps — read
[`scripts/install.sh`](scripts/install.sh) yourself first if you'd rather
not pipe a script straight into your shell. It's a reasonable thing to want
to check, for this or any install one-liner.

## Option B: pip install directly

```sh
pip install --user work-ledger
```

Does the same thing as the one-liner, minus the printed next-steps below.
Want the unreleased tip of `main` instead of the latest release?

```sh
pip install --user "git+https://github.com/dhk/work-ledger.git"
```

**Check what you got:** `work-ledger about` reports the installed version.
The full command set documented here needs **0.2.0 or newer** — `0.1.0`
predates `serve`, `activity`, `timeline`, `trend`, `sessions`, `waste`,
`rollup`, `miso`, `history`, `session`, `cycle`, and `about`, most of
which need no credentials at all. If PyPI still has only the older
release, use the git URL above or Option C until the next release lands
(see [RELEASING.md](RELEASING.md)).

## Option C: clone and install editable (for reading/modifying the code)

```sh
git clone https://github.com/dhk/work-ledger.git
cd work-ledger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

`-e` (editable) means changes to the source under `work_ledger/` take
effect immediately without reinstalling — the right choice if you plan to
read the code or send a PR, not just run the tool.

The virtual environment keeps work-ledger and its dependencies isolated from
your system Python. Reactivate it with `source .venv/bin/activate` whenever
you return to this checkout.

## Verify it worked

```sh
work-ledger --once
```

You should see a table of prompt turns from your most recently active
Claude Code session, with token counts and an estimated cost. If you get
`No Claude Code session transcripts found`, either Claude Code hasn't
written any transcripts yet on this machine, or they're somewhere other
than `~/.claude/projects/` — pass `--transcript path/to/session.jsonl`
directly if you know where yours are.

## Setting up hosted model features

For hosted chaptering or opt-in semantic rollup matching, pick one:

```sh
# Option 1: API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Option 2: the Anthropic CLI, if you have it
ant auth login
```

Then:

```sh
work-ledger chapters              # first run chapters your active session
```

`chapters` costs a small amount of real money per session (Haiku, usually
a fraction of a cent to a few cents) — it prints what each pass cost. If
credentials aren't set, `chapters` doesn't crash; it falls back to a single
"Unsorted" chapter and says so explicitly.

`limits` needs no credentials and makes no model call. It only re-sums token
data in local transcripts:

```sh
work-ledger limits --once
```

### Calibrating `limits`

`limits` tracks Claude Pro/Max's rolling session-limit window as an
estimate — Anthropic doesn't publish the exact threshold. Calibrate your
own:

```sh
work-ledger limits --once   # note the total the next time Claude Code
                             # tells you you've hit your limit
work-ledger limits --set-threshold 500000   # save that number
```

The threshold is stored in `~/.config/work-ledger/limits_threshold.json`,
separate from any per-session cache.

## Optional: the visual PNG report

`work-ledger chapters --report --format html` needs nothing extra. The PNG
variant screenshots that HTML via a headless browser and needs the
optional `report` extra:

```sh
pip install --user "work-ledger[report]"
playwright install chromium
```

Without this, `--format png` fails with a clear error telling you to run
the two commands above — it never silently falls back to HTML.

## Using work-ledger inside Claude (MCP)

`work-ledger-mcp` runs work-ledger's **pattern-library** mechanism as an
MCP server, so a live Claude Code session can consult it directly instead
of only seeing it after the fact via `work-ledger recommend`. Needs the
optional `patterns` extra:

```sh
pip install --user "work-ledger[patterns]"
```

Then register it. For Claude Code:

```sh
claude mcp add work-ledger -- work-ledger-mcp
```

For Claude Desktop, add the equivalent block to its MCP config instead:

```json
{
  "mcpServers": {
    "work-ledger": { "command": "work-ledger-mcp" }
  }
}
```

Restart/reconnect the client so it picks up the new server, then confirm
it connected with `claude mcp list` (Claude Code) or the client's own
MCP/tools indicator.

**Scope — read this before expecting more than it does.** This server
exposes exactly five tools: `list_patterns`, `report_recommended`,
`report_used`, `submit_review_findings`, and `about`. It does **not**
expose `chapters`/`activity`/`sessions`/`trend`/`rollup`/`waste`/`limits`
— there is currently no way for Claude itself to ask "what did I spend
this week" through MCP; that's still CLI-only. See
[docs/commands.md](docs/commands.md#pattern-library-opt-in-experimental)
for what each of the five tools does.

It's also inert by default: `list_patterns` works immediately (reads
local pattern files), but `report_recommended`/`report_used`/
`submit_review_findings` no-op — honestly, not silently — until you run
`work-ledger patterns enable` and point `WORK_LEDGER_PATTERN_BACKEND_URL`
at a real deployed backend (see [`backend/README.md`](backend/README.md)).
Nothing here stands that backend up for you.

## Upgrading

```sh
work-ledger cycle
```

Detects how this install actually happened and does the matching thing:

- **Editable clone** (Option C above): `git pull` in the repo root. Stops
  with a clear message first if you have uncommitted local changes,
  rather than risking a confusing `git pull` failure.
- **pipx/uv-tool/pip install** (Options A/B above): runs the matching
  upgrade command (`pipx upgrade work-ledger`, `uv tool upgrade
  work-ledger`, or `pip install --upgrade work-ledger`/the same git URL
  you originally installed from).

```sh
work-ledger cycle --check-status
```

Reports the detected install mode and exactly what plain `work-ledger
cycle` would run, without running it — no `git`/`pip`/`pipx`/`uv` command
executes, nothing changes.

Either way, if something looks like it's listening on `work-ledger
serve`'s port (default 8765), `cycle` says so and asks you to stop/restart
it yourself — it never sends a signal to another process, since it has no
reliable way to know that whatever's listening there is actually the
`serve` instance you meant.

## Uninstalling

```sh
pip uninstall work-ledger
```

This doesn't touch anything work-ledger wrote outside its own package:
- Per-session chapter caches: `~/.claude/projects/**/*.chapters.json`
- The `limits` threshold: `~/.config/work-ledger/limits_threshold.json`

Remove those too if you want a completely clean uninstall.

## Troubleshooting

**`No Claude Code session transcripts found under ~/.claude/projects/`**
Either Claude Code hasn't been run on this machine, or its transcripts
live somewhere else. Pass `--transcript path/to/session.jsonl` explicitly
to point at a specific file.

**`chapters` always shows "Unsorted"**
Credentials aren't being picked up. Check `echo $ANTHROPIC_API_KEY`, or
run `ant auth status` if you're using an `ant` profile. The note printed
above the table will say why the call failed.

**`--format png` fails with a Playwright/Chromium error**
Run `pip install "work-ledger[report]"` followed by
`playwright install chromium`, then try again.

**Permission errors writing to `~/.config/work-ledger/` or next to a
transcript under `~/.claude/projects/`**
work-ledger degrades gracefully here rather than crashing — a chapter
cache or threshold write failure just means the next run redoes that work
instead of reusing it. If you're seeing this constantly, check the
directory's permissions.

## What's next

See the [command reference](docs/commands.md) for full CLI detail, and
[`docs/session-chaptering-design.md`](docs/session-chaptering-design.md)
for the design rationale behind `chapters` if you're curious how it works
under the hood.
