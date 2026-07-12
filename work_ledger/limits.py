"""Best-effort tracking of the Claude Pro/Max rolling-window usage limit
(the "5-hour session limit" that resets on a rolling basis) - NOT the same
thing as the dollar-cost telemetry the rest of work-ledger tracks, and NOT
an official number. Anthropic doesn't publish the exact token/message
threshold or expose it via any documented, scriptable API; Claude Code's
own `/status` shows a percentage but it's local-display-only.

What this actually does: sums real token usage (the same Turn/Unit data
transcript.py already parses) across every session, in a rolling window
(default 5 hours) ending now. That's a real number, not a guess about what
happened - but turning it into "% of your limit" needs a threshold this
tool can't know on its own. You calibrate it yourself: the next time
Claude Code tells you you've hit your limit, check what this command
reported at that moment and save it with `--set-threshold`.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from work_ledger.transcript import TranscriptTailer, find_all_transcripts

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
THRESHOLD_PATH = CONFIG_DIR / "limits_threshold.json"

DEFAULT_WINDOW_HOURS = 5.0


def _parse_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_threshold_tokens() -> int | None:
    if not THRESHOLD_PATH.exists():
        return None
    try:
        data = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("threshold_tokens")
    return int(value) if isinstance(value, (int, float)) else None


def save_threshold_tokens(threshold_tokens: int) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    THRESHOLD_PATH.write_text(
        json.dumps({"threshold_tokens": threshold_tokens}, indent=2), encoding="utf-8"
    )


@dataclass
class SessionWindowUsage:
    transcript: Path
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    last_activity: datetime | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class WindowUsage:
    window_hours: float
    sessions: list[SessionWindowUsage] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(s.total_tokens for s in self.sessions)

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.sessions)


def compute_window_usage(
    window_hours: float = DEFAULT_WINDOW_HOURS, now: datetime | None = None
) -> WindowUsage:
    """Sum token usage across every session with activity in the rolling
    window ending at `now` (default: current time, UTC)."""
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    result = WindowUsage(window_hours=window_hours)
    for path in find_all_transcripts():
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < window_start:
            # find_all_transcripts() is newest-first by mtime, and a file
            # that hasn't changed since before the window started can't
            # contain any turns inside it either - everything after this
            # one in iteration order is even older, so stop scanning.
            break

        tailer = TranscriptTailer(path)
        tailer.poll()

        session_usage = SessionWindowUsage(transcript=path)
        for turn in tailer.ordered_turns():
            ts = _parse_timestamp(turn.timestamp)
            if ts is None or ts < window_start or ts > now:
                continue
            session_usage.input_tokens += turn.input_tokens
            session_usage.output_tokens += turn.output_tokens
            session_usage.cost_usd += turn.cost_usd
            if session_usage.last_activity is None or ts > session_usage.last_activity:
                session_usage.last_activity = ts

        if session_usage.total_tokens > 0:
            result.sessions.append(session_usage)

    result.sessions.sort(key=lambda s: s.last_activity or now, reverse=True)
    return result
