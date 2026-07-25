from work_ledger.chapters import Chapter, Section, _save_cache
from work_ledger.timeline import build_timeline, top_activity_labels, top_category_labels
from work_ledger.transcript import TranscriptTailer

from .conftest import assistant_lines, user_entry, write_jsonl


def test_build_timeline_buckets_by_day(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "fix the bug", "2026-07-01T10:00:00Z"),
        *assistant_lines(
            "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
            [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t1"}], "2026-07-01T10:00:01Z",
        ),
        user_entry("p2", "another one", "2026-07-02T11:00:00Z"),
        *assistant_lines(
            "m2", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
            [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t2"}], "2026-07-02T11:00:01Z",
        ),
        user_entry("p3", "make a chart", "2026-07-02T12:00:00Z"),
        *assistant_lines(
            "m3", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
            [{"type": "tool_use", "name": "Skill", "input": {"skill": "dataviz"}, "id": "t3"}], "2026-07-02T12:00:01Z",
        ),
    ]
    write_jsonl(path, entries)

    result = build_timeline([path])

    assert [b.day for b in result.days] == ["2026-07-01", "2026-07-02"]
    assert result.days[0].activity_counts == {"Tool: Bash": 1}
    assert result.days[1].activity_counts == {"Tool: Bash": 1, "Skill: dataviz": 1}
    assert result.total_sessions == 1
    assert result.uncached_sessions == 1  # no .chapters.json written for this session


def test_build_timeline_uses_cached_chapter_categories(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "fix the bug", "2026-07-01T10:00:00Z"),
        *assistant_lines(
            "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
            [{"type": "text", "text": "done"}], "2026-07-01T10:00:01Z",
        ),
    ]
    write_jsonl(path, entries)
    # Simulate an already-chaptered session (what `timeline backfill` would produce)
    # without making a real model call.
    _save_cache(
        path,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the bug", category="bug-fix", sections=[Section(title="Fix", prompt_ids=["p1"])])],
    )

    result = build_timeline([path])

    assert result.uncached_sessions == 0
    assert result.days[0].category_counts == {"bug-fix": 1}


def test_build_timeline_skips_empty_transcript(tmp_path):
    path = tmp_path / "empty.jsonl"
    write_jsonl(path, [])
    result = build_timeline([path])
    assert result.days == []
    assert result.total_sessions == 0
    assert result.uncached_sessions == 0


def test_build_timeline_multiple_sessions_same_day(tmp_path):
    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "first", "2026-07-01T09:00:00Z"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 5, "output_tokens": 5},
                [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t1"}], "2026-07-01T09:00:01Z",
            ),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "second", "2026-07-01T14:00:00Z"),
            *assistant_lines(
                "m2", "claude-haiku-4-5", {"input_tokens": 5, "output_tokens": 5},
                [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t2"}], "2026-07-01T14:00:01Z",
            ),
        ],
    )

    result = build_timeline([path_a, path_b])

    assert len(result.days) == 1
    assert result.days[0].activity_counts == {"Tool: Bash": 2}
    assert result.total_sessions == 2


def test_top_activity_labels_ranks_by_total_count():
    from work_ledger.timeline import DayBucket

    days = [
        DayBucket(day="2026-07-01", activity_counts={"Tool: Bash": 3, "Tool: Edit": 1}),
        DayBucket(day="2026-07-02", activity_counts={"Tool: Bash": 1, "Skill: dataviz": 5}),
    ]
    assert top_activity_labels(days, n=2) == ["Skill: dataviz", "Tool: Bash"]
    assert top_activity_labels(days, n=1) == ["Skill: dataviz"]


def test_top_category_labels_ranks_by_total_count():
    from work_ledger.timeline import DayBucket

    days = [
        DayBucket(day="2026-07-01", category_counts={"bug-fix": 2}),
        DayBucket(day="2026-07-02", category_counts={"bug-fix": 1, "feature-build": 4}),
    ]
    assert top_category_labels(days) == ["feature-build", "bug-fix"]


def test_top_activity_labels_empty_days():
    assert top_activity_labels([]) == []
    assert top_category_labels([]) == []
