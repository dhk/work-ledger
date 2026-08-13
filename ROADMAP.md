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

**Current focus:** the practice-visibility theme is now fully shipped (#44 timeline, #43 web UI), the cost/usage theme picked up a time-series view (#4 trend), an end-to-end orchestration command (#35 `miso`), cross-session initiative rollup (#3, `work-ledger rollup`), and waste mining is now fully shipped both within-session and cross-session (#5, `work-ledger waste`/`waste --cross-session`) - the cross-session half reuses #3's clustering to compare "the same pattern" across every session of a recurring initiative. The quality/infra batch (#45-48) is closed out, and #42's local session history store shipped as additive infrastructure. #16 and #19 are both **backlogged** - #16's backend half shipped but its unfreeze-policy half is parked pending the repo owner's call; #19 shipped 3 of 4 categories, the remaining two parked on an unvalidated signal. Next up: #66 (timeline narrative summary), then back to #19's parked categories if a real signal turns up. #6 stays blocked on #5 accumulating real usage evidence.

## Cost/usage reporting — Show, core shipped

`chapters`, `activity`, `limits`, `export`. This is the mature part of the
tool: per-prompt and per-unit cost, grouped by initiative or by activity
type, plus a self-calibrated read on the Pro/Max session limit. Everything
below in this theme extends that core rather than replacing it.

| Issue | What | Depends on |
|---|---|---|
| [#3](https://github.com/dhk/work-ledger/issues/3) ✅ | **Cross-session rollup** — cluster the same initiative across sessions by deterministic title normalization, total cost per cluster (`work-ledger rollup`); v1 deliberately skips an LLM/embedding matching pass, see rollup.py | Shipped; did not block on #42 |
| [#68](https://github.com/dhk/work-ledger/issues/68) ✅ | **Semantic matching v2 for rollup/waste --cross-session** — real evidence from #3's v1 (near-all-singleton clusters against real usage) justified moving past deterministic-only matching; shipped as an opt-in, batched Haiku call over still-singleton titles (`WORK_LEDGER_ROLLUP_MATCHING=semantic`, default unchanged), not embeddings - one shared clustering entrypoint (`rollup.build_rollup_result`) so `rollup`/`waste --cross-session` always agree; no merge-decision caching/versioning by design | Shipped; extends #3, also changes #5's cross-session clustering (shared mechanism) |
| [#93](https://github.com/dhk/work-ledger/issues/93) ✅ | **`rollup` cumulative spend, "All other" collapsing, CSV, `--preview`** — cumulative $/% shown everywhere clusters are listed (one shared `rollup.with_cumulative`); `--other-threshold` ports `activity --report`'s residual-bucket mechanism to `RollupCluster` (opt-in, no default, distinct from the existing session-scoping `--top`); `--format csv` third `--report` output alongside html/png; `--preview` renders the table alongside `--report` instead of only writing a file | Shipped; extends #3/#88's `rollup`/`serve --merge-sessions` neighborhood |
| [#4](https://github.com/dhk/work-ledger/issues/4) ✅ | **Trend view** — cost bucketed by day/week across all sessions (`work-ledger trend`) | Shipped; did not block on #42 |
| [#5](https://github.com/dhk/work-ledger/issues/5) ✅ | **Recurring-pattern/waste mining** — repeated file reads, repeated near-identical subagent dispatches, within one session/chapter (`work-ledger waste`) and across every session of the same recurring initiative (`work-ledger waste --cross-session`, via #3's clustering) | Shipped, both halves |
| [#16](https://github.com/dhk/work-ledger/issues/16) | Pluggable local-model chaptering backend (Ollama) + unfreeze chapters | **Backlogged.** Backend half shipped: `ChapterBackend`/`AnthropicBackend`/`OllamaBackend`, `WORK_LEDGER_CHAPTER_BACKEND` config; frozen-prefix cache deliberately untouched for either backend. Unfreeze-policy half parked — needs the repo owner's call on Option A/B/C in `docs/local-model-chaptering-design.md` before it's implemented |
| [#35](https://github.com/dhk/work-ledger/issues/35) ✅ | `miso` — run chapters + reports end-to-end in one command, with `--check-status` and graceful degradation | — |
| [#86](https://github.com/dhk/work-ledger/issues/86) | **MCP session-aware tools** — `work-ledger-mcp` gains `list_sessions`/`render_report` (straightforward, existing code paths) plus an opt-in `--allow-session-credentials` flag for in-session-credential chaptering (two-tool handoff, since MCP sampling is confirmed unimplemented upstream — [anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785)). Own-session identity explicitly out of scope - not solvable precisely today, see the design doc | Proposed, not built - see `docs/mcp-session-tools-design.md`. Extends #16's backend split conceptually (a third path to a chapter), but implemented outside `ChapterBackend` entirely, not a fourth backend |

## Practice visibility — Show, shipped

Reframes "what did this cost" as "how has the way I work actually
changed" — tool selection, delegation, approach mix, browsable rather than
flag-driven.

| Issue | What | Depends on |
|---|---|---|
| [#44](https://github.com/dhk/work-ledger/issues/44) ✅ | **Timeline view** — tool/skill/subagent/approach mix over time (`work-ledger timeline`/`timeline backfill`) | Shipped; did not block on #42 |
| [#43](https://github.com/dhk/work-ledger/issues/43) ✅ | **Local web UI** — `work-ledger serve`, browse sessions/chapters as a page | Shipped; reused `report.py`'s visual system |
| [#42](https://github.com/dhk/work-ledger/issues/42) ✅ | **Local session history store** — sqlite store with incremental, mtime-gated sync (`history.py`) | Shipped; additive infrastructure for future cross-session features, not yet read by #3/#4/#5/#44/#43 |
| [#66](https://github.com/dhk/work-ledger/issues/66) ✅ (Part 1) | **Timeline narrative summary** ("you used to X, now Y") — Part 1 (deterministic narrative, `timeline --summary`/`timeline --report`) shipped; Part 2 (maturity correlation via #3's rollup clustering) still proposed, not built | Extends #44; Part 2 explicitly not scoped for a real-codebase signal (see design doc) |
| [#87](https://github.com/dhk/work-ledger/issues/87) ✅ (Tier 1) | **Commit correlation on `serve`** — "Commits during this session" panel, correlating a session's own `cwd` to local `git log` output in its time window (`git_activity.py`); PR numbers recovered from commit subjects, zero new network calls. Tier 2 (real PR titles/description/review state via the GitHub API, needs its own opt-in gate) tracked on the same issue, not built - deliberate: "live with Tier 1 for a while" | Extends #43's `serve`; reuses #86-adjacent references.py's PR-ref extraction |
| [#88](https://github.com/dhk/work-ledger/issues/88) ✅ | **`serve --merge-sessions`** — one combined chapters → turns → units tree spanning every session in scope, chronologically interleaved, *not* clustered by title (explicitly distinct from `rollup`, which totals cost per initiative - an earlier round of the same design conversation initially conflated the two before this split them apart) | Extends #43's `serve`; reuses #87's block-rendering refactor (`_chapter_block` etc. factored to module level) |

## Recommendations — Tell, started, thin

Turns what's shown into something a person can act on themselves. Still
report-only everywhere — none of these propose automating a fix.

| Issue | What | Depends on |
|---|---|---|
| [#19](https://github.com/dhk/work-ledger/issues/19) | Widen `recommend` beyond cost — user actions, config, new skills, new tools | **Backlogged.** 3 of 4 categories shipped (session-limit hits, interruption counts, recurring-tool-sequence skill candidates); "configuration" and "new tools" categories parked — no validated signal found for either yet |
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

## Quality/Infra — cross-cutting, not staged

Correctness and process gaps found auditing the codebase, plus standing
`CLAUDE.md` requirements (CLI/MCP command conventions) that apply across
every entry point. These don't sit on the show/tell/do axis — they're not
feature work, they cut across whichever stage touches the affected code —
so they're tracked here without a stage label.

| Issue | What |
|---|---|
| [#45](https://github.com/dhk/work-ledger/issues/45) ✅ | `backend/` has no test coverage and isn't part of CI |
| [#46](https://github.com/dhk/work-ledger/issues/46) ✅ | Silent cost loss: `isSidechain` subagents and skill follow-on work aren't attributed |
| [#47](https://github.com/dhk/work-ledger/issues/47) ✅ | Sonnet 5 introductory pricing isn't modeled, nothing forces a fix after it expires |
| [#48](https://github.com/dhk/work-ledger/issues/48) ✅ | No coverage threshold enforced in CI |
| [#73](https://github.com/dhk/work-ledger/issues/73) ✅ | `work-ledger cycle` — the upgrade/restart command `CLAUDE.md`'s CLI/MCP conventions section already required but nothing implemented; detects editable-vs-published automatically |
| [#75](https://github.com/dhk/work-ledger/issues/75) ✅ | The "about" block — same convention section's third requirement (description/version/last-updated/commit/author across every CLI command, the MCP server, `serve`, and generated reports); one shared `about.py` computation, reuses #73's install-mode detection |
| [#91](https://github.com/dhk/work-ledger/issues/91) ✅ | A chaptering call that never got a response (auth rejected, network error, backend unavailable) froze into the cache exactly like a real decision — permanently skipping retry even after the underlying failure was fixed. Distinguished from a real (paid) response that was refused/malformed, which still freezes as before |

#45-48 shipped together in one pass (#51).

## Using this as a guardrail

Before filing a new issue or starting a design doc: check it against
`PRODUCT_BRIEF.md`'s non-goals and `docs/architecture.md`'s constraints,
then place it in (or add) a theme here. If it's Do-stage, check it has
real Tell-stage evidence behind it first — not just a design opinion.
