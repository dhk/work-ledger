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

Nothing built yet — this repo exists so the tool has its own home from day
one instead of outgrowing a bigger repo later.
