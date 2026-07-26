import os
from datetime import datetime, timezone

from work_ledger.history import get_record, get_status, sync_history

from .conftest import assistant_lines, user_entry, write_jsonl


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
    path = proj_dir / f"{name}.jsonl"
    write_jsonl(path, entries)
    return path


def test_sync_history_no_transcripts(isolated_transcripts_root, isolated_history_db):
    result = sync_history()
    assert result.total_transcripts == 0
    assert result.updated == 0
    assert result.unchanged == 0

    status = get_status()
    assert status.row_count == 0


def test_sync_history_writes_one_row_per_session(isolated_transcripts_root, isolated_history_db):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj, "session-a", "p1", "2026-07-12T10:00:00Z", tokens=(1000, 500))
    _write_session(proj, "session-b", "p1", "2026-07-12T11:00:00Z", tokens=(200, 100))

    result = sync_history()
    assert result.total_transcripts == 2
    assert result.updated == 2
    assert result.unchanged == 0

    status = get_status()
    assert status.row_count == 2

    record_a = get_record("session-a")
    assert record_a is not None
    assert record_a.num_turns == 1
    assert record_a.cost_usd > 0
    assert record_a.project == "proj"
    assert record_a.num_chapters == 0  # no .chapters.json cache written for this session


def test_second_sync_is_a_noop_when_nothing_changed(isolated_transcripts_root, isolated_history_db):
    """The actual point of #42: a re-sync of an untouched transcript must
    not re-open it or rewrite its row - verified here by checking the
    stored synced_at timestamp is byte-identical across both syncs, not
    just checking counts."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj, "session-a", "p1", "2026-07-12T10:00:00Z")

    first = sync_history(now=datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc))
    assert first.updated == 1
    record_after_first = get_record("session-a")
    assert record_after_first is not None

    # A later wall-clock "now" for the second sync proves the unchanged
    # synced_at isn't just an artifact of passing the same `now` twice.
    second = sync_history(now=datetime(2026, 7, 12, 13, 0, 0, tzinfo=timezone.utc))
    assert second.total_transcripts == 1
    assert second.updated == 0
    assert second.unchanged == 1

    record_after_second = get_record("session-a")
    assert record_after_second is not None
    assert record_after_second.synced_at == record_after_first.synced_at
    assert record_after_second.transcript_mtime == record_after_first.transcript_mtime


def test_modified_transcript_is_resynced(isolated_transcripts_root, isolated_history_db):
    """A transcript whose mtime advances past what's stored must be
    re-read and its row updated - the other half of the incremental
    contract (skip unchanged, but never miss something new)."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = _write_session(proj, "session-a", "p1", "2026-07-12T10:00:00Z", tokens=(100, 50))

    first = sync_history(now=datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc))
    assert first.updated == 1
    record_after_first = get_record("session-a")
    mtime_after_first = path.stat().st_mtime

    # Append a second turn and bump the file's mtime forward (relative to
    # its own real mtime after the first sync, not an absolute date guess -
    # the incremental check compares raw file mtimes, not the injected
    # `now` used only for the synced_at bookkeeping field) so the
    # incremental check picks it up as changed.
    extra_entries = [
        user_entry("p2", "more", timestamp="2026-07-12T10:05:00Z"),
        *assistant_lines(
            "session-a-msg-2",
            "claude-haiku-4-5",
            {"input_tokens": 300, "output_tokens": 150},
            [{"type": "text", "text": "y"}],
            timestamp="2026-07-12T10:05:01Z",
        ),
    ]
    with open(path, "a", encoding="utf-8") as f:
        import json

        for e in extra_entries:
            f.write(json.dumps(e) + "\n")
    future_mtime = mtime_after_first + 1000
    os.utime(path, (future_mtime, future_mtime))

    second = sync_history(now=datetime(2026, 7, 12, 15, 0, 0, tzinfo=timezone.utc))
    assert second.updated == 1
    assert second.unchanged == 0

    record_after_second = get_record("session-a")
    assert record_after_second.num_turns == 2
    assert record_after_second.cost_usd > record_after_first.cost_usd
    assert record_after_second.synced_at != record_after_first.synced_at


def test_get_record_missing_returns_none(isolated_transcripts_root, isolated_history_db):
    assert get_record("nonexistent-uuid") is None


def test_sync_history_explicit_transcript_list(isolated_transcripts_root, isolated_history_db):
    """sync_history() also accepts an explicit transcript list instead of
    always calling find_all_transcripts() itself - useful for callers that
    already have a filtered list (mirrors the pattern build_timeline()
    already uses)."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = _write_session(proj, "session-a", "p1", "2026-07-12T10:00:00Z")

    result = sync_history(transcripts=[path])
    assert result.total_transcripts == 1
    assert result.updated == 1
    assert get_record("session-a") is not None
