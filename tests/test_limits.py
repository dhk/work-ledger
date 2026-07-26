import os
import time
from datetime import datetime, timedelta, timezone

from work_ledger.limits import compute_rate_limit_history, compute_window_usage, load_threshold_tokens, save_threshold_tokens

from .conftest import assistant_lines, user_entry, write_jsonl


def test_threshold_round_trip(isolated_config_dir):
    assert load_threshold_tokens() is None
    save_threshold_tokens(500_000)
    assert load_threshold_tokens() == 500_000


def test_threshold_missing_file_returns_none(isolated_config_dir):
    assert load_threshold_tokens() is None


def test_threshold_corrupt_file_returns_none(isolated_config_dir):
    isolated_config_dir.mkdir(parents=True)
    (isolated_config_dir / "limits_threshold.json").write_text("not json", encoding="utf-8")
    assert load_threshold_tokens() is None


def _write_session(proj_dir, name, prompt_id, timestamp, tokens=(100, 50)):
    entries = [
        user_entry(prompt_id, "hi", timestamp=timestamp),
        *assistant_lines(
            f"{name}-msg",
            "claude-haiku-4-5",
            {"input_tokens": tokens[0], "output_tokens": tokens[1]},
            [{"type": "text", "text": "x"}],
            timestamp=timestamp,
        ),
    ]
    write_jsonl(proj_dir / f"{name}.jsonl", entries)


def test_compute_window_usage_includes_only_turns_inside_window(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    now = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    inside = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    outside = (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z")

    _write_session(proj, "recent", "p1", inside, tokens=(1000, 500))
    path = proj / "recent.jsonl"
    os.utime(path, (now.timestamp(), now.timestamp()))

    usage = compute_window_usage(window_hours=5.0, now=now)
    assert usage.total_tokens == 1500

    # A turn timestamped outside the window, in a file whose mtime is
    # still recent enough to be scanned, must not be counted.
    _write_session(proj, "mixed", "p2", outside, tokens=(999, 999))
    os.utime(proj / "mixed.jsonl", (now.timestamp(), now.timestamp()))
    usage2 = compute_window_usage(window_hours=5.0, now=now)
    assert usage2.total_tokens == 1500  # unchanged - the new session's only turn is outside the window


def test_compute_window_usage_skips_old_files_via_mtime_short_circuit(isolated_transcripts_root):
    """A file whose mtime is already older than the window is skipped
    without even being opened (the newest-first early-break optimization)."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    now = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    old_time = (now - timedelta(hours=48)).timestamp()

    _write_session(proj, "ancient", "p1", now.isoformat().replace("+00:00", "Z"), tokens=(1000, 1000))
    os.utime(proj / "ancient.jsonl", (old_time, old_time))

    usage = compute_window_usage(window_hours=5.0, now=now)
    assert usage.total_tokens == 0


def test_compute_window_usage_no_sessions(isolated_transcripts_root):
    usage = compute_window_usage(window_hours=5.0)
    assert usage.total_tokens == 0
    assert usage.sessions == []


def _rate_limit_entry(timestamp: str, reset_label: str) -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "error": "rate_limit",
        "apiErrorStatus": 429,
        "message": {
            "model": "",
            "content": [{"type": "text", "text": f"You've hit your session limit · resets {reset_label}"}],
        },
    }


def test_compute_rate_limit_history_dedupes_and_respects_window(isolated_transcripts_root):
    """The cross-session companion to compute_window_usage - factual hit
    history (docs/recommend-workflow-efficiency-design.md Open Question 2),
    deduped by reset time same as TranscriptTailer.deduped_rate_limit_events,
    and scoped to the same rolling window as everything else in this module."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    now = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    inside_ts = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    inside_ts_earlier = (now - timedelta(hours=1, minutes=30)).isoformat().replace("+00:00", "Z")
    outside_ts = (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z")

    entries = [
        user_entry("p1", "hi", timestamp=inside_ts),
        _rate_limit_entry(inside_ts, "11:40pm (UTC)"),
        _rate_limit_entry(inside_ts_earlier, "11:40pm (UTC)"),  # same reset - dedupes with the hit above
        _rate_limit_entry(outside_ts, "different (UTC)"),  # outside the window - must be excluded
    ]
    path = proj / "s.jsonl"
    write_jsonl(path, entries)
    os.utime(path, (now.timestamp(), now.timestamp()))

    history = compute_rate_limit_history(window_hours=5.0, now=now)
    assert len(history) == 1
    assert history[0].transcript == path
    assert history[0].hit.reset_label == "11:40pm (UTC)"
    assert history[0].hit.timestamp == inside_ts_earlier  # earliest of the two sharing this reset time


def test_compute_rate_limit_history_no_sessions(isolated_transcripts_root):
    assert compute_rate_limit_history(window_hours=5.0) == []
