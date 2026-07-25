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
