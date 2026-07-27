from work_ledger.chapters import Chapter, Section, _save_cache
from work_ledger.timeline import DayBucket, build_timeline, summarize_timeline, top_activity_labels, top_category_labels
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


# --- summarize_timeline ------------------------------------------------


def test_summarize_timeline_narrates_a_clear_shift():
    # First half (3 days): mostly "debugging", some "design-planning".
    # Second half (3 days): mostly "refactor", some "docs". Both category
    # counts and day counts comfortably clear the MIN_* guards.
    days = [
        DayBucket(day="2026-07-01", category_counts={"debugging": 3, "design-planning": 2}),
        DayBucket(day="2026-07-02", category_counts={"debugging": 4}),
        DayBucket(day="2026-07-03", category_counts={"debugging": 3, "design-planning": 2}),
        DayBucket(day="2026-07-04", category_counts={"refactor": 4}),
        DayBucket(day="2026-07-05", category_counts={"refactor": 3, "docs": 2}),
        DayBucket(day="2026-07-06", category_counts={"refactor": 3, "docs": 2}),
    ]
    # first half totals: debugging=10, design-planning=4 -> 71%/29%
    # second half totals: refactor=10, docs=4 -> 71%/29%
    narrative = summarize_timeline(days)

    assert narrative is not None
    assert "Early in this range" in narrative
    assert "debugging (71%)" in narrative
    assert "design-planning (29%)" in narrative
    assert "More recently" in narrative
    assert "refactor (71%)" in narrative
    assert "docs (29%)" in narrative


def test_summarize_timeline_too_few_populated_days_returns_none():
    # Only 3 populated days - below MIN_POPULATED_DAYS_FOR_SUMMARY (4), even
    # though the category mix below would otherwise be a clear shift.
    days = [
        DayBucket(day="2026-07-01", category_counts={"debugging": 10}),
        DayBucket(day="2026-07-02", category_counts={"debugging": 10}),
        DayBucket(day="2026-07-03", category_counts={"refactor": 10}),
    ]
    assert summarize_timeline(days) is None


def test_summarize_timeline_too_few_turns_returns_none():
    # 4 populated days (clears the day-count guard) but only 4 categorized
    # turns total - below MIN_CATEGORIZED_TURNS_FOR_SUMMARY (10).
    days = [
        DayBucket(day="2026-07-01", category_counts={"debugging": 1}),
        DayBucket(day="2026-07-02", category_counts={"debugging": 1}),
        DayBucket(day="2026-07-03", category_counts={"refactor": 1}),
        DayBucket(day="2026-07-04", category_counts={"refactor": 1}),
    ]
    assert summarize_timeline(days) is None


def test_summarize_timeline_no_populated_days_returns_none():
    days = [DayBucket(day="2026-07-01"), DayBucket(day="2026-07-02")]
    assert summarize_timeline(days) is None


def test_summarize_timeline_omits_category_below_swing_threshold():
    # "stable" holds the same 25% share in both windows (0-point swing) and
    # must not be mentioned; "big" (75% -> 25%) and "new" (0% -> 50%) both
    # clear SWING_THRESHOLD_POINTS and must be.
    days = [
        DayBucket(day="2026-07-01", category_counts={"big": 10, "stable": 3}),
        DayBucket(day="2026-07-02", category_counts={"big": 5, "stable": 2}),
        DayBucket(day="2026-07-03", category_counts={"big": 3, "stable": 3, "new": 6}),
        DayBucket(day="2026-07-04", category_counts={"big": 2, "stable": 2, "new": 4}),
    ]
    # first half: big=15, stable=5 -> total 20 -> 75%/25%
    # second half: big=5, stable=5, new=10 -> total 20 -> 25%/25%/50%
    narrative = summarize_timeline(days)

    assert narrative is not None
    assert "big (75%)" in narrative
    assert "new (50%)" in narrative
    assert "stable" not in narrative
