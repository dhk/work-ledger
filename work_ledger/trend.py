"""Day/week-bucketed view of *cost* over time - "is my spend going up or
down" (issue #4), a different axis than timeline.py's "how has my practice
changed" (issue #44, deliberately not about cost - see its own module
docstring). `chapters --all` already lists per-session totals, but that's a
flat list, not a time series: there's no way to eyeball a trend across many
sessions from it. This module re-slices the same per-turn cost data by
calendar period instead.

Needs no chaptering and no ANTHROPIC_API_KEY - every field it reads
(Turn.cost_usd, Turn.timestamp) is already parsed locally from the
transcript by transcript.py, same as activity.py. Unlike timeline.py's
category-mix panel, there's nothing here that can ever be "partially
cached" - a session's cost is either known or flagged unknown
(unknown_model_cost), never dependent on a separate Haiku pass.

Per-turn timestamps (Turn.timestamp) are used for bucketing, not the
transcript file's mtime that --since/--until filtering elsewhere in this
tool uses to select *which sessions* to scan - same distinction
timeline.py's own module docstring draws between the two.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from work_ledger.transcript import TranscriptTailer

BUCKET_SIZES = ("day", "week")
DEFAULT_WINDOW_DAYS = 30


def _parse_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _period_key(ts: datetime, bucket: str) -> str:
    """The bucket label a turn's timestamp rolls up under: its own date for
    'day', or the Monday that starts its ISO week for 'week' - so every day
    in the same week shares one label, sorted the same way day labels are
    (plain YYYY-MM-DD string comparison)."""
    d = ts.date()
    if bucket == "week":
        d = d - timedelta(days=d.weekday())
    return d.isoformat()


@dataclass
class CostBucket:
    period: str  # YYYY-MM-DD - a day, or the Monday starting a week
    cost_usd: float = 0.0
    num_turns: int = 0
    unknown_model_cost: bool = False


@dataclass
class TrendResult:
    buckets: list[CostBucket] = field(default_factory=list)
    bucket_size: str = "day"
    total_sessions: int = 0

    @property
    def total_cost_usd(self) -> float:
        return sum(b.cost_usd for b in self.buckets)


def build_trend(transcripts: list[Path], bucket: str = "day") -> TrendResult:
    """Build the period-bucketed cost trend over an already-filtered list of
    transcript paths (callers pick the list, e.g. via find_all_transcripts()
    + a date-range filter on file mtime - same pattern chapters --all/
    timeline/sessions/export already use)."""
    if bucket not in BUCKET_SIZES:
        raise ValueError(f"bucket must be one of {BUCKET_SIZES}, got {bucket!r}")

    buckets: dict[str, CostBucket] = {}
    total_sessions = 0

    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        turns = tailer.ordered_turns()
        if not turns:
            continue
        total_sessions += 1

        for turn in turns:
            ts = _parse_timestamp(turn.timestamp)
            if ts is None:
                continue
            key = _period_key(ts, bucket)
            b = buckets.setdefault(key, CostBucket(period=key))
            b.cost_usd += turn.cost_usd
            b.num_turns += 1
            if turn.unknown_model_cost:
                b.unknown_model_cost = True

    ordered = sorted(buckets.values(), key=lambda b: b.period)
    return TrendResult(buckets=ordered, bucket_size=bucket, total_sessions=total_sessions)
