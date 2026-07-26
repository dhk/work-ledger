"""Local-only, rule-based recommendations - no corpus, no extra API call
beyond chaptering itself, just heuristics over the same Turn/Unit/Chapter
data everything else in this tool already computes. This is a first cut: a
small number of concrete, defensible checks, not a big speculative rule
engine. A later, corpus-relative dimension ("your bug-fix chapters cost
more than the median across users who opted into the export corpus")
isn't attempted here - see README's Recommendations section.

The first three checks below are cost-based (outlier chapter cost,
subagent-heavy chapters, repeated skill invocation). The rest widen
`recommend` to workflow-efficiency signals beyond cost, per issue #19 and
docs/recommend-workflow-efficiency-design.md:

- Session-limit hits and interruption count (category 1, "user actions") -
  both signals the design doc validated directly against a real transcript.
- Recurring tool-call sequence (category 3, "new skills") - a same-shape,
  multi-step tool sequence repeating enough times in one session to be a
  named-skill candidate.

Categories 2 ("configuration") and 4 ("new tools") from the design doc are
deliberately NOT implemented here - the doc's own validation found
"repeated manual permission approval" may not be recoverable from
`~/.claude/projects` transcripts at all (Open Question 5: this needs
`.claude/settings.json`/`settings.local.json`, a data source this module
doesn't read), and "new tools" had no validated signal either way. Per this
module's own philosophy above, an unvalidated category doesn't get a rule
just to fill out the taxonomy - they stay open questions (see the design
doc) until there's a real signal to build against.
"""

from dataclasses import dataclass
from statistics import median

from work_ledger.chapters import Chapter
from work_ledger.transcript import TranscriptTailer

MIN_FLAGGED_COST_USD = 0.01  # ignore noise on trivially cheap chapters/skills
OUTLIER_MULTIPLE = 2.0
SUBAGENT_SHARE_THRESHOLD = 0.5
MIN_SUBAGENT_CALLS = 2
MIN_SKILL_REPEATS = 3

# A single interruption is often just steering the model mid-task - normal
# iterative use, not a workflow problem. Only surface it once it recurs
# enough in one session to look like a pattern (requests underspecified up
# front), same repeat-count-guard shape as MIN_SKILL_REPEATS above.
MIN_INTERRUPTION_COUNT = 2

# The design doc's own validated example (10 near-identical branch/commit/
# push/PR/review-request instances in one session) was, in its own words,
# "obviously non-borderline" - the doc leans toward a fairly low threshold
# rather than requiring something that extreme to fire. 3 matches
# MIN_SKILL_REPEATS's existing bar in this file: enough to rule out
# coincidence, not so high it only fires on the doc's own outlier case.
MIN_SEQUENCE_REPEATS = 3
# A repeating 1-2 step sequence is usually just a common idiom (e.g. Read
# then Edit), not a distinct enough "procedure" to be worth naming as a
# skill - require at least 3 steps before considering it a candidate.
MIN_SEQUENCE_STEPS = 3


@dataclass
class Recommendation:
    rule_id: str
    title: str
    detail: str
    cost_usd: float


def _chapter_cost(chapter: Chapter, tailer: TranscriptTailer) -> float:
    return sum(t.cost_usd for t in chapter.turns(tailer))


def _check_outlier_chapters(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    if len(chapters) < 3:
        return []
    costs = [_chapter_cost(c, tailer) for c in chapters]
    typical = median(costs)
    if typical <= 0:
        return []
    out = []
    for chapter, cost in zip(chapters, costs):
        if cost < MIN_FLAGGED_COST_USD:
            continue
        multiple = cost / typical
        if multiple >= OUTLIER_MULTIPLE:
            out.append(
                Recommendation(
                    rule_id="outlier-chapter-cost",
                    title=f'"{chapter.title}" cost {multiple:.1f}x this session\'s typical chapter',
                    detail=(
                        f"${cost:.4f} vs a ${typical:.4f} median across {len(chapters)} chapters - "
                        "worth a look at what drove it (chapters --detail on this one)."
                    ),
                    cost_usd=cost,
                )
            )
    return out


def _check_subagent_heavy(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    out = []
    for chapter in chapters:
        turns = chapter.turns(tailer)
        chapter_cost = sum(t.cost_usd for t in turns)
        if chapter_cost < MIN_FLAGGED_COST_USD:
            continue
        subagent_units = [u for t in turns for u in t.units if u.kind == "subagent"]
        if len(subagent_units) < MIN_SUBAGENT_CALLS:
            continue
        subagent_cost = sum(u.cost_usd for u in subagent_units)
        share = subagent_cost / chapter_cost if chapter_cost else 0.0
        if share >= SUBAGENT_SHARE_THRESHOLD:
            out.append(
                Recommendation(
                    rule_id="subagent-heavy-chapter",
                    title=(
                        f'"{chapter.title}" spent {share * 100:.0f}% of its cost on '
                        f"{len(subagent_units)} subagent calls"
                    ),
                    detail=(
                        f"${subagent_cost:.4f} of ${chapter_cost:.4f} - check whether that fan-out "
                        "was necessary or could've been done inline."
                    ),
                    cost_usd=subagent_cost,
                )
            )
    return out


def _check_repeated_skill(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    out = []
    for chapter in chapters:
        turns = chapter.turns(tailer)
        by_skill: dict[str, list] = {}
        for t in turns:
            for u in t.units:
                if u.kind == "skill" and u.skill_name:
                    by_skill.setdefault(u.skill_name, []).append(u)
        for skill_name, units in by_skill.items():
            if len(units) < MIN_SKILL_REPEATS:
                continue
            cost = sum(u.cost_usd for u in units)
            if cost < MIN_FLAGGED_COST_USD:
                continue
            out.append(
                Recommendation(
                    rule_id="repeated-skill-invocation",
                    title=f'Skill "{skill_name}" ran {len(units)} times in "{chapter.title}" (${cost:.4f})',
                    detail=(
                        "If the same steps run every time, a plain script or deterministic tool might "
                        "do this for a fraction of the cost (see issue #6)."
                    ),
                    cost_usd=cost,
                )
            )
    return out


def _format_hit_clock(timestamp: str) -> str:
    """"2026-07-11T23:15:14.228Z" -> "23:15 UTC" - best-effort, falls back to
    the raw timestamp if it doesn't parse (never crashes a recommendation
    over a display detail)."""
    try:
        _, _, rest = timestamp.partition("T")
        return f"{rest[:5]} UTC" if rest else timestamp
    except Exception:
        return timestamp


def _check_session_limit_hits(tailer: TranscriptTailer) -> list[Recommendation]:
    """Category 1 ("user actions"), the doc's most-validated signal: Claude
    Code's own synthetic `error: "rate_limit"` transcript entry, deduped by
    reset time (see TranscriptTailer.deduped_rate_limit_events - a retry
    storm against one limit window isn't N separate hits). Doesn't require
    cross-session data - a single session with multiple hits is already
    actionable, per the design doc's proposed sequencing."""
    events = tailer.deduped_rate_limit_events()
    if not events:
        return []
    n = len(events)
    when = "; ".join(f"{_format_hit_clock(e.timestamp)} (resets {e.reset_label or 'unknown'})" for e in events)
    return [
        Recommendation(
            rule_id="session-limit-hits",
            title=f"Hit your session limit {n} time{'s' if n != 1 else ''} this session",
            detail=(
                f"{when} - each already deduped from any retry-storm entries sharing the same "
                "reset time. Consider spacing out heavy work, or this may be a signal your "
                "current plan tier doesn't match your usage (see `work-ledger limits` for "
                "the rolling-window usage behind it)."
            ),
            cost_usd=0.0,
        )
    ]


def _check_interruptions(tailer: TranscriptTailer) -> list[Recommendation]:
    """Category 1 ("user actions"), the precise half of the doc's
    interruption signal: a literal `[Request interrupted by user]` marker
    inside genuine user-message content (TranscriptTailer.interruption_count
    - already scoped to avoid the false-positive risk the doc's own
    validation ran into). The doc's fuzzier "short turn then long
    clarifying turn" heuristic is deliberately NOT built here - it flagged
    its own false-positive risk as the hardest part of this category to get
    right, and recommended shipping only the precise marker-count version
    first (Open Question 1)."""
    n = tailer.interruption_count
    if n < MIN_INTERRUPTION_COUNT:
        return []
    return [
        Recommendation(
            rule_id="session-interruptions",
            title=f"You interrupted Claude {n} times this session",
            detail=(
                "Repeated interruptions can mean a request was underspecified up front - "
                "consider giving more context/constraints before the first attempt, or "
                "breaking a large ask into smaller steps."
            ),
            cost_usd=0.0,
        )
    ]


def _turn_tool_shape(turn) -> tuple[str, ...]:
    """The ordered sequence of tool-call tokens across a turn's units
    (Unit.tool_call_signature - "ToolName" or "Bash:<verb>"), with
    consecutive duplicates collapsed so a retried identical call doesn't
    inflate the step count. This is the unit `_check_recurring_tool_sequence`
    compares across turns to find a repeating multi-step procedure."""
    tokens = [tok for u in turn.units for tok in u.tool_call_signature]
    shape: list[str] = []
    for tok in tokens:
        if not shape or shape[-1] != tok:
            shape.append(tok)
    return tuple(shape)


def _check_recurring_tool_sequence(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    """Category 3 ("new skills"), the doc's other strongly-validated signal:
    a same-shape, multi-step tool-call sequence (e.g. "Bash:git checkout",
    "Bash:git commit", "Bash:git push", "Bash:gh pr create" - a
    branch/commit/push/PR/review-request cycle) recurring across a whole
    session's turns often enough to be a named-skill candidate rather than
    a one-off. Session-wide rather than per-chapter (`chapters` is accepted
    only for signature symmetry with the other checks) since the doc's own
    validated example - 10 instances - was a whole-session pattern, not
    confined to one chapter."""
    del chapters  # unused - this check is deliberately session-wide, see docstring
    by_shape: dict[tuple[str, ...], list] = {}
    for turn in tailer.ordered_turns():
        shape = _turn_tool_shape(turn)
        if len(shape) < MIN_SEQUENCE_STEPS:
            continue
        by_shape.setdefault(shape, []).append(turn)

    out = []
    for shape, matching_turns in by_shape.items():
        if len(matching_turns) < MIN_SEQUENCE_REPEATS:
            continue
        cost = sum(t.cost_usd for t in matching_turns)
        shape_str = " → ".join(shape)
        out.append(
            Recommendation(
                rule_id="recurring-tool-sequence",
                title=(
                    f"Same {len(shape)}-step tool sequence repeated {len(matching_turns)} times "
                    "this session"
                ),
                detail=(
                    f"{shape_str} - recurring closely enough to be a named-skill candidate instead "
                    "of re-run by hand every time (the design doc's own validated example was a "
                    '"ship a scoped PR" branch/commit/push/PR/review-request cycle - see issue #6 '
                    "for the deterministic-tool-substitution angle on non-skill-shaped repeats)."
                ),
                cost_usd=cost,
            )
        )
    return out


def generate_recommendations(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    recs: list[Recommendation] = []
    recs.extend(_check_outlier_chapters(chapters, tailer))
    recs.extend(_check_subagent_heavy(chapters, tailer))
    recs.extend(_check_repeated_skill(chapters, tailer))
    recs.extend(_check_session_limit_hits(tailer))
    recs.extend(_check_interruptions(tailer))
    recs.extend(_check_recurring_tool_sequence(chapters, tailer))
    recs.sort(key=lambda r: r.cost_usd, reverse=True)
    return recs
