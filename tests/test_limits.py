import os
import time
from datetime import datetime, timedelta, timezone

from work_ledger.limits import compute_window_usage, load_threshold_tokens, save_threshold_tokens

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
