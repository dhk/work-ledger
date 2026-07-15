"""Group a session's cost by activity type - which tool, skill, subagent,
or plain reply produced it - rather than by initiative (see chapters.py).

Unlike `chapters`, this needs no Anthropic API call and no ANTHROPIC_API_KEY:
every field it reads (Unit.kind, skill_name, subagent_agent_type, tool_names)
is already parsed locally from the transcript. That makes it a useful
fallback view when chaptering isn't set up, and a different lens even when
it is - "what kind of work cost the money" instead of "which initiative."
"""

from dataclasses import dataclass

from work_ledger.transcript import TranscriptTailer, Unit


@dataclass
class ActivityBucket:
    label: str
    cost_usd: float


def bucket_key(unit: Unit) -> str:
    """The activity-type label a unit's cost rolls up under. Mirrors
    Unit.kind's own subagent/skill priority order, but falls back to the
    first tool called (or a plain-reply label) instead of a raw text
    snippet - unlike Unit.label, this is meant to be a category shared by
    many units, not a one-off description of a single message."""
    if unit.kind == "subagent":
        return f"Subagent: {unit.subagent_agent_type or unit.subagent_desc}"
    if unit.kind == "skill":
        return f"Skill: {unit.skill_name}"
    if unit.tool_names:
        name = unit.tool_names[0]
        if name.startswith("mcp__"):
            parts = name.split("__")
            return f"MCP: {parts[1]}" if len(parts) > 1 else "MCP call"
        return f"Tool: {name}"
    return "Direct response (no tool call)"


def group_by_activity(tailer: TranscriptTailer) -> list[ActivityBucket]:
    """Every unit's cost, summed by bucket_key(), sorted most expensive
    first."""
    totals: dict[str, float] = {}
    for turn in tailer.ordered_turns():
        for unit in turn.units:
            key = bucket_key(unit)
            totals[key] = totals.get(key, 0.0) + unit.cost_usd
    buckets = [ActivityBucket(label=label, cost_usd=cost) for label, cost in totals.items()]
    buckets.sort(key=lambda b: -b.cost_usd)
    return buckets


def collapse_to_other(buckets: list[ActivityBucket], threshold: float = 0.8) -> list[ActivityBucket]:
    """Keep buckets individually until their running total crosses
    `threshold` (a fraction of the grand total, e.g. 0.8 for 80%), then
    fold everything after that into one residual bucket. `buckets` must
    already be sorted most expensive first (group_by_activity's contract).

    The residual bucket is deliberately not part of the descending sort -
    it can be (and often is) bigger than any single kept bucket, since
    it's a sum of many small ones, not one activity type. Callers that
    render this should treat it as visually distinct (see report.py),
    not just the next bar in the sequence."""
    total = sum(b.cost_usd for b in buckets)
    if total <= 0 or not buckets:
        return list(buckets)

    kept: list[ActivityBucket] = []
    running = 0.0
    for i, b in enumerate(buckets):
        running += b.cost_usd
        kept.append(b)
        if running / total >= threshold:
            rest = buckets[i + 1 :]
            if rest:
                rest_cost = sum(r.cost_usd for r in rest)
                pct = int(round(threshold * 100))
                kept.append(
                    ActivityBucket(label=f"Other/final {100 - pct}% ({len(rest)} categories)", cost_usd=rest_cost)
                )
            return kept
    return kept
