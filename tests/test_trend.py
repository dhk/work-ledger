from work_ledger.trend import CostBucket, TrendResult, build_trend

from .conftest import assistant_lines, user_entry, write_jsonl


def test_build_trend_buckets_by_day(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "fix the bug", "2026-07-01T10:00:00Z"),
        *assistant_lines(
            "m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-01T10:00:01Z",
        ),
        user_entry("p2", "another one", "2026-07-02T11:00:00Z"),
        *assistant_lines(
            "m2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-02T11:00:01Z",
        ),
        user_entry("p3", "same day, second turn", "2026-07-02T12:00:00Z"),
        *assistant_lines(
            "m3", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-02T12:00:01Z",
        ),
    ]
    write_jsonl(path, entries)

    result = build_trend([path])

    assert [b.period for b in result.buckets] == ["2026-07-01", "2026-07-02"]
    assert result.buckets[0].num_turns == 1
    assert result.buckets[1].num_turns == 2
    assert result.bucket_size == "day"
    assert result.total_sessions == 1
    # Every bucket's cost should be strictly positive given nonzero usage.
    assert all(b.cost_usd > 0 for b in result.buckets)
    assert result.total_cost_usd == sum(b.cost_usd for b in result.buckets)


def test_build_trend_buckets_by_week(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        # 2026-06-29 is a Monday - both of these land in the same ISO week.
        user_entry("p1", "monday turn", "2026-06-29T09:00:00Z"),
        *assistant_lines(
            "m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-06-29T09:00:01Z",
        ),
        user_entry("p2", "sunday turn, same week", "2026-07-05T09:00:00Z"),
        *assistant_lines(
            "m2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-05T09:00:01Z",
        ),
        # 2026-07-06 is the next Monday - a new week bucket.
        user_entry("p3", "next monday", "2026-07-06T09:00:00Z"),
        *assistant_lines(
            "m3", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-06T09:00:01Z",
        ),
    ]
    write_jsonl(path, entries)

    result = build_trend([path], bucket="week")

    assert [b.period for b in result.buckets] == ["2026-06-29", "2026-07-06"]
    assert result.buckets[0].num_turns == 2
    assert result.buckets[1].num_turns == 1
    assert result.bucket_size == "week"


def test_build_trend_rejects_invalid_bucket_size(tmp_path):
    path = tmp_path / "s.jsonl"
    write_jsonl(path, [])
    try:
        build_trend([path], bucket="month")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "month" in str(e)


def test_build_trend_skips_empty_transcript(tmp_path):
    path = tmp_path / "empty.jsonl"
    write_jsonl(path, [])
    result = build_trend([path])
    assert result.buckets == []
    assert result.total_sessions == 0
    assert result.total_cost_usd == 0.0


def test_build_trend_multiple_sessions_same_day(tmp_path):
    path_a = tmp_path / "a.jsonl"
    path_b = tmp_path / "b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "first", "2026-07-01T09:00:00Z"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 500, "output_tokens": 100},
                [{"type": "text", "text": "x"}], "2026-07-01T09:00:01Z",
            ),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "second", "2026-07-01T14:00:00Z"),
            *assistant_lines(
                "m2", "claude-haiku-4-5", {"input_tokens": 500, "output_tokens": 100},
                [{"type": "text", "text": "y"}], "2026-07-01T14:00:01Z",
            ),
        ],
    )

    result = build_trend([path_a, path_b])

    assert len(result.buckets) == 1
    assert result.buckets[0].num_turns == 2
    assert result.total_sessions == 2


def test_build_trend_flags_unknown_model_cost(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "unpriced model", "2026-07-01T10:00:00Z"),
        *assistant_lines(
            "m1", "some-future-model-not-in-rates", {"input_tokens": 1000, "output_tokens": 200},
            [{"type": "text", "text": "done"}], "2026-07-01T10:00:01Z",
        ),
    ]
    write_jsonl(path, entries)

    result = build_trend([path])

    assert result.buckets[0].unknown_model_cost is True
    assert result.buckets[0].cost_usd == 0.0
    # #104: a run of "?" periods is exactly where "which model is missing a
    # rate?" gets asked, so the bucket names it rather than only flagging it.
    assert result.buckets[0].unpriced_models == {"some-future-model-not-in-rates"}
    assert result.unpriced_models == ["some-future-model-not-in-rates"]


def test_cost_bucket_and_trend_result_defaults():
    b = CostBucket(period="2026-07-01")
    assert b.cost_usd == 0.0
    assert b.num_turns == 0
    assert b.unknown_model_cost is False

    result = TrendResult()
    assert result.buckets == []
    assert result.bucket_size == "day"
    assert result.total_sessions == 0
    assert result.total_cost_usd == 0.0
