"""Day-bucketed view of how someone's *practice* has changed over time -
not "what did this cost" (chapters.py/activity.py already answer that) but
"how did I work": which tools/skills/subagents show up more or less over
time, and how the mix of chapter categories (feature-build, debugging,
etc.) has shifted. See docs/show-tell-do-model.md's "timeline" direction
and issue #44.

Deliberately reuses activity.py's existing bucket_key() rather than a
second categorization scheme - the only new thing here is slicing that
same categorization by day instead of summing it once per session.

Chapter-category data is read from whatever's already cached
(chapters.cached_chapters) and never triggers a new Haiku pass on its own
- a Show-stage command shouldn't have a surprise API cost. Sessions with
uncached turns just don't contribute category data for those turns;
`uncached_sessions` on the result says how many were incomplete so a
caller (cli.py's `timeline` command) can point at `timeline backfill`
instead of silently showing a partial mix.

Per-turn timestamps (Turn.timestamp) are used directly for day-bucketing,
not the transcript file's mtime that --since/--until filtering elsewhere
in this tool uses to select *which sessions* to scan - that mtime filter
is only ever a coarse pre-filter for file inclusion, real bucketing here
is exact.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from work_ledger.activity import bucket_key
from work_ledger.chapters import cached_chapters, has_uncached_turns
from work_ledger.transcript import TranscriptTailer

DEFAULT_WINDOW_DAYS = 30


def _parse_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class DayBucket:
    day: str  # YYYY-MM-DD
    activity_counts: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_units(self) -> int:
        return sum(self.activity_counts.values())


@dataclass
class TimelineResult:
    days: list[DayBucket]
    total_sessions: int
    uncached_sessions: int


def _prompt_id_to_category(transcript_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for chapter in cached_chapters(transcript_path):
        for prompt_id in chapter.prompt_ids:
            mapping[prompt_id] = chapter.category
    return mapping


def build_timeline(transcripts: list[Path]) -> TimelineResult:
    """Build the day-bucketed timeline over an already-filtered list of
    transcript paths (callers pick the list, e.g. via find_all_transcripts()
    + a date-range filter on file mtime - same pattern chapters --all/
    sessions/export already use)."""
    buckets: dict[str, DayBucket] = {}
    uncached_sessions = 0
    total_sessions = 0

    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        turns = tailer.ordered_turns()
        if not turns:
            continue

        total_sessions += 1
        if has_uncached_turns(tailer, path):
            uncached_sessions += 1

        category_map = _prompt_id_to_category(path)

        for turn in turns:
            ts = _parse_timestamp(turn.timestamp)
            if ts is None:
                continue
            day = ts.date().isoformat()
            bucket = buckets.setdefault(day, DayBucket(day=day))

            category = category_map.get(turn.prompt_id)
            if category:
                bucket.category_counts[category] = bucket.category_counts.get(category, 0) + 1

            for unit in turn.units:
                key = bucket_key(unit)
                bucket.activity_counts[key] = bucket.activity_counts.get(key, 0) + 1

    ordered_days = sorted(buckets.values(), key=lambda b: b.day)
    return TimelineResult(days=ordered_days, total_sessions=total_sessions, uncached_sessions=uncached_sessions)


def top_activity_labels(days: list[DayBucket], n: int = 6) -> list[str]:
    """The n activity labels with the highest total count across the whole
    range, most-total-first - used to pick a stable, consistent set of
    series to plot/color across every day, rather than each day choosing
    its own top labels independently."""
    totals: dict[str, int] = {}
    for bucket in days:
        for label, count in bucket.activity_counts.items():
            totals[label] = totals.get(label, 0) + count
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return [label for label, _ in ranked[:n]]


def top_category_labels(days: list[DayBucket], n: int = 8) -> list[str]:
    """Same idea as top_activity_labels but for chapter categories - in
    practice this rarely needs truncating since CATEGORIES is a small
    fixed taxonomy (see chapters.py), but kept consistent with the
    activity-label helper rather than assuming every category appears."""
    totals: dict[str, int] = {}
    for bucket in days:
        for label, count in bucket.category_counts.items():
            totals[label] = totals.get(label, 0) + count
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return [label for label, _ in ranked[:n]]


# Minimum populated (has-category-data) days before summarize_timeline() will
# narrate anything. Splitting into two windows needs at least 2 days per
# window to be a "window" rather than one day's noise pretending to be a
# trend, so 4 is the floor, not an arbitrary round number.
MIN_POPULATED_DAYS_FOR_SUMMARY = 4

# Minimum total categorized turns across all populated days. A handful of
# turns split into two "halves" can swing 20+ points by pure chance (e.g. 3
# turns vs 2 turns is already a coin flip's worth of noise) - this floor
# keeps summarize_timeline() from narrating a shift that's really just a
# small sample.
MIN_CATEGORIZED_TURNS_FOR_SUMMARY = 10

# A category only gets mentioned in the narrative if its share of turns
# moved by at least this many percentage points between the two windows.
# 10 points is large enough that it reads as a real change in what
# dominated (not a category going from, say, 24% to 31%), while still
# being reachable well before someone has months of history - matches the
# design doc's own example (42% -> ~0%, 18% -> 0%, 0% -> 35%, 0% -> 20%).
SWING_THRESHOLD_POINTS = 10.0

# At most this many categories get named on each side of the sentence -
# matches the design doc's own two-and-two example and keeps the sentence
# readable instead of listing every category that crossed the threshold.
_MAX_CATEGORIES_PER_CLAUSE = 2


def _category_proportions(half: list[DayBucket]) -> dict[str, float]:
    """Each category's share (0-100) of all categorized turns across the
    given half of populated days."""
    totals: dict[str, int] = {}
    for bucket in half:
        for category, count in bucket.category_counts.items():
            totals[category] = totals.get(category, 0) + count
    grand_total = sum(totals.values())
    if not grand_total:
        return {}
    return {category: count / grand_total * 100 for category, count in totals.items()}


def _join_with_and(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return " and ".join(parts)


def summarize_timeline(days: list[DayBucket]) -> str | None:
    """Narrate how the chapter-category mix has shifted between the first
    and second half of the *populated* days in range - see
    docs/timeline-narrative-and-maturity-design.md's Part 1. Deterministic,
    pure computation over already-collected category_counts: no LLM call,
    no new data source, matches every other Show-stage narrative precedent
    in this codebase (e.g. cli.py's per-session _session_summary()).

    Splits by count of days that actually have category data, not
    calendar halves, since usage is bursty - a burst of 8 populated days
    trailing 20 empty ones should compare its own first half against its
    own second half, not get diluted by the empty days.

    Returns None (mirrors uncached_sessions's existing "don't silently
    show a misleading picture" precedent) rather than narrating noise
    from a handful of data points, when:
    - there are fewer than MIN_POPULATED_DAYS_FOR_SUMMARY populated days,
    - there are fewer than MIN_CATEGORIZED_TURNS_FOR_SUMMARY categorized
      turns total across those days, or
    - no category's share moved by at least SWING_THRESHOLD_POINTS
      percentage points between the two windows (nothing worth saying).
    """
    populated = [d for d in days if d.category_counts]
    if len(populated) < MIN_POPULATED_DAYS_FOR_SUMMARY:
        return None

    total_turns = sum(sum(d.category_counts.values()) for d in populated)
    if total_turns < MIN_CATEGORIZED_TURNS_FOR_SUMMARY:
        return None

    midpoint = len(populated) // 2
    first_half, second_half = populated[:midpoint], populated[midpoint:]

    first_props = _category_proportions(first_half)
    second_props = _category_proportions(second_half)
    if not first_props or not second_props:
        return None

    categories = set(first_props) | set(second_props)
    swings = {category: second_props.get(category, 0.0) - first_props.get(category, 0.0) for category in categories}

    # Categories that lost share (most-negative swing first) and categories
    # that gained share (most-positive swing first); ties broken
    # alphabetically for determinism.
    shrank = sorted(
        (c for c in categories if swings[c] <= -SWING_THRESHOLD_POINTS),
        key=lambda c: (swings[c], c),
    )[:_MAX_CATEGORIES_PER_CLAUSE]
    grew = sorted(
        (c for c in categories if swings[c] >= SWING_THRESHOLD_POINTS),
        key=lambda c: (-swings[c], c),
    )[:_MAX_CATEGORIES_PER_CLAUSE]

    if not shrank and not grew:
        return None

    sentences = []
    if shrank:
        early = _join_with_and([f"{c} ({first_props[c]:.0f}%)" for c in shrank])
        sentences.append(f"Early in this range, {early} dominated.")
    if grew:
        recent = _join_with_and([f"{c} ({second_props[c]:.0f}%)" for c in grew])
        sentences.append(f"More recently, that's shifted toward {recent}.")
    return " ".join(sentences)
