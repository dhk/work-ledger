# Roadmap

This is a map, not a duplicate issue tracker — it groups work into themes
and shows where each theme sits relative to the others. For the reasoning
behind any individual item, follow its issue link; this file doesn't
restate rationale that already lives there, since the two would drift.

Staging follows the show/tell/do rubric in `CLAUDE.md` (full writeup:
`docs/show-tell-do-model.md`). Issues carry a `stage:show` / `stage:tell`
/ `stage:do` label so they're filterable directly on GitHub; this file is
the narrative synthesis on top, refreshed when a theme's shape actually
changes — not mechanically re-synced on every issue edit.

**Current focus:** the practice-visibility theme is now fully shipped (#44 timeline, #43 web UI), the cost/usage theme picked up a time-series view (#4 trend), and the quality/infra batch (#45-48) is closed out. Nothing designated as current focus yet - next candidate is whichever of #42 (history store) or the Tell-stage work (#19/#21/#22-23) gets picked up.

## Cost/usage reporting — Show, core shipped

`chapters`, `activity`, `limits`, `export`. This is the mature part of the
tool: per-prompt and per-unit cost, grouped by initiative or by activity
type, plus a self-calibrated read on the Pro/Max session limit. Everything
below in this theme extends that core rather than replacing it.

| Issue | What | Depends on |
|---|---|---|
| [#3](https://github.com/dhk/work-ledger/issues/3) | Cross-session rollup — cluster the same initiative across sessions | — |
| [#4](https://github.com/dhk/work-ledger/issues/4) ✅ | **Trend view** — cost bucketed by day/week across all sessions (`work-ledger trend`) | Shipped; did not block on #42 |
| [#5](https://github.com/dhk/work-ledger/issues/5) | Recurring-pattern/waste mining across chapters and sessions | — |
| [#16](https://github.com/dhk/work-ledger/issues/16) | Pluggable local-model chaptering backend (Ollama) + unfreeze chapters | — |
| [#35](https://github.com/dhk/work-ledger/issues/35) | `miso` — run chapters + reports end-to-end in one command | — |

## Practice visibility — Show, shipped

Reframes "what did this cost" as "how has the way I work actually
changed" — tool selection, delegation, approach mix, browsable rather than
flag-driven.

| Issue | What | Depends on |
|---|---|---|
| [#44](https://github.com/dhk/work-ledger/issues/44) ✅ | **Timeline view** — tool/skill/subagent/approach mix over time (`work-ledger timeline`/`timeline backfill`) | Shipped; did not block on #42 |
| [#43](https://github.com/dhk/work-ledger/issues/43) ✅ | **Local web UI** — `work-ledger serve`, browse sessions/chapters as a page | Shipped; reused `report.py`'s visual system |
| [#42](https://github.com/dhk/work-ledger/issues/42) | Local session history store | Backs #3/#4/#5 and periodic runs — still open, not needed by #44/#43 |

## Recommendations — Tell, started, thin

Turns what's shown into something a person can act on themselves. Still
report-only everywhere — none of these propose automating a fix.

| Issue | What | Depends on |
|---|---|---|
| [#19](https://github.com/dhk/work-ledger/issues/19) | Widen `recommend` beyond cost — user actions, config, new skills, new tools | — |
| [#21](https://github.com/dhk/work-ledger/issues/21) | Shared pattern library ("the mother ship") with popularity scoring | — |
| [#22](https://github.com/dhk/work-ledger/issues/22) | Detect and resolve skill rot (overlapping/redundant skills) | — |
| [#23](https://github.com/dhk/work-ledger/issues/23) | Research backing #22 (published prior art on skill/agent overlap) | Backs #22 |

## Community/findings layer — Tell, personal-only v1

A narrower slice of Tell: forwarding code-review findings across sessions
into the shared pattern library, so recurring mistakes get curated once
instead of rediscovered per-session. Deliberately scoped to
single-person-use before any of the consent/redaction/abuse questions a
multi-user version would raise get solved.

| Issue | What | Depends on |
|---|---|---|
| [#30](https://github.com/dhk/work-ledger/issues/30) | Harvest code-review findings into the pattern library (v1: personal-only) | Reuses #21's opt-in gate |

## Automation — Do, deliberately empty

Nothing here builds or deploys something that changes a person's setup on
its own — and that's not an oversight. Per `CLAUDE.md`'s rule: don't
automate a Tell-stage recommendation until it's been validated against a
real recurring pattern, not just one session's data.

| Issue | What | Depends on |
|---|---|---|
| [#6](https://github.com/dhk/work-ledger/issues/6) | Deterministic-tool substitution for recurring expensive patterns | **Blocked on #5** surfacing a real pattern first — do not start design work ahead of that data |

## Quality/Infra — cross-cutting, not staged, closed out

Correctness and process gaps found auditing the codebase. These don't sit
on the show/tell/do axis — they're not feature work, they cut across
whichever stage touches the affected code — so they're tracked here
without a stage label.

| Issue | What |
|---|---|
| [#45](https://github.com/dhk/work-ledger/issues/45) ✅ | `backend/` has no test coverage and isn't part of CI |
| [#46](https://github.com/dhk/work-ledger/issues/46) ✅ | Silent cost loss: `isSidechain` subagents and skill follow-on work aren't attributed |
| [#47](https://github.com/dhk/work-ledger/issues/47) ✅ | Sonnet 5 introductory pricing isn't modeled, nothing forces a fix after it expires |
| [#48](https://github.com/dhk/work-ledger/issues/48) ✅ | No coverage threshold enforced in CI |

All four shipped together in one pass (#51).

## Using this as a guardrail

Before filing a new issue or starting a design doc: check it against
`PRODUCT_BRIEF.md`'s non-goals and `docs/architecture.md`'s constraints,
then place it in (or add) a theme here. If it's Do-stage, check it has
real Tell-stage evidence behind it first — not just a design opinion.
