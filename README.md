# work-ledger

A lightweight usage analytics tool for individual Claude Code users — the
person watching their own $20/month or $100/month subscription, not a team
with an observability stack.

**Goals:**
- Near-real-time visibility into what a session or automation is costing
- Something you can open and read, not a raw log dump or a Prometheus/Grafana
  stack to stand up and maintain
- Attribute cost back to what caused it — a slash command, a skill
  invocation, a subagent call, a block of work — so it can say "this cost
  $X" and then "here's what to cut"

Design and scope are being worked out in
[dhk/adventures-in-ai#34](https://github.com/dhk/adventures-in-ai/issues/34),
including prior art already checked (OTEL-based team tools, a macOS
rate-limit widget) and open questions on data source (session transcripts vs.
a local OTEL sink) and real-time mechanism.

## Usage

```
work-ledger              # live dashboard, watching the most recently active session
work-ledger --once       # print current totals once and exit
work-ledger --detail     # break each prompt down into its underlying units of work
work-ledger --transcript path/to/session.jsonl   # watch a specific transcript
```

By default, cost/tokens are shown per prompt turn (one row per message you
send). `--detail` expands each turn into its underlying **units of work** —
one row per actual LLM call (one `message.id`) — and specifically labels
`Skill:` and `Subagent:` calls so fan-out cost is visible instead of folded
into the turn total.

**Known limitation on subagent attribution**: this environment writes
subagent transcripts to a separate `<session>/subagents/agent-<id>.jsonl`
file with a `.meta.json` sidecar naming the exact `toolUseId` that spawned
it, which `work-ledger` uses for exact correlation. Claude Code's transcript
format is internal/undocumented and can differ by install or version — an
older or different setup that instead inlines subagent activity as
`isSidechain` entries in the main transcript file is not specifically
handled; those entries are currently just ignored rather than guessed at,
so subagent cost may not roll up on such installs. Skill invocations run
inline in the main chain, so only the invoking call itself is labeled — any
follow-on work the skill drives isn't currently bounded as belonging to that
skill (transcripts don't mark a clear skill-scope boundary).

**Bug fixed in this pass**: Claude Code writes one JSONL line per content
block (thinking/text/tool_use) rather than one line per full LLM response,
but repeats the complete `usage` block on every line belonging to the same
message. The original version summed `usage` per line, overcounting cost by
roughly 2-4x on any multi-block response. Costs are now deduped by
`message.id` so each real API call is counted exactly once — cost estimates
from before this fix should be treated as inflated.

## Status

v1 built: near-real-time terminal dashboard reading Claude Code's own
session transcripts, no telemetry setup required. Cost/token attribution
works at both the per-prompt-turn level (default) and per-unit-of-work level
(`--detail`), with skill and subagent calls specifically labeled.

Not yet done: cross-session/historical rollup (only watches one transcript
at a time); Sonnet 5 introductory pricing isn't modeled (runs a little high
until 2026-08-31); no automated tests yet.
