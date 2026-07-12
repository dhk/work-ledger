# Installing work-ledger

## Requirements

- Python 3.10+
- `pip`
- An existing Claude Code install with at least one session under
  `~/.claude/projects/` (work-ledger reads those transcripts directly — if
  you've never run Claude Code, there's nothing for it to show you yet)

Two subcommands additionally call the Anthropic API directly, separate
from your Claude Code session, and need their own credentials:

- `work-ledger chapters` — groups prompts into initiatives via a small
  Claude Haiku call
- `work-ledger limits` — no API call itself, but shares the same optional
  config as `chapters`

Either `ANTHROPIC_API_KEY` set in your environment, or an
[`ant auth login`](https://platform.claude.com/docs/en/api/sdks/cli)
profile, works. `work-ledger --once` and `work-ledger --detail` (the
default dashboard) need neither — they only read local transcripts.

## Option A: the one-liner

```sh
curl -fsSL https://raw.githubusercontent.com/dhk/work-ledger/main/scripts/install.sh | bash
```

This is a `pip install` from this repo plus some printed next-steps — read
[`scripts/install.sh`](scripts/install.sh) yourself first if you'd rather
not pipe a script straight into your shell. It's a reasonable thing to want
to check, for this or any install one-liner.

## Option B: pip install directly

```sh
pip install --user "git+https://github.com/dhk/work-ledger.git"
```

Does the same thing as the one-liner, minus the printed next-steps below.

## Option C: clone and install editable (for reading/modifying the code)

```sh
git clone https://github.com/dhk/work-ledger.git
cd work-ledger
pip install --user -e .
```

`-e` (editable) means changes to the source under `work_ledger/` take
effect immediately without reinstalling — the right choice if you plan to
read the code or send a PR, not just run the tool.

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

## Setting up chapters and limits

Both call the Anthropic API directly. Pick one:

```sh
# Option 1: API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Option 2: the Anthropic CLI, if you have it
ant auth login
```

Then:

```sh
work-ledger chapters              # first run chapters your active session
work-ledger limits --once         # rolling-window token snapshot
```

`chapters` costs a small amount of real money per session (Haiku, usually
a fraction of a cent to a few cents) — it prints what each pass cost. If
credentials aren't set, `chapters` doesn't crash; it falls back to a single
"Unsorted" chapter and says so explicitly. `limits` makes no model call at
all — it just re-sums token data your local transcripts already contain.

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

See the main [README](README.md) for the full command reference, and
[`docs/session-chaptering-design.md`](docs/session-chaptering-design.md)
for the design rationale behind `chapters` if you're curious how it works
under the hood.
