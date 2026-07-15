from work_ledger.activity import ActivityBucket, bucket_key, collapse_to_other, group_by_activity
from work_ledger.transcript import TranscriptTailer

from .conftest import assistant_lines, user_entry, write_jsonl


def test_bucket_key_direct_response(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "hi"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10}, [{"type": "text", "text": "hello"}]),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    unit = tailer.ordered_turns()[0].units[0]
    assert bucket_key(unit) == "Direct response (no tool call)"


def test_bucket_key_tool(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "run it"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
                [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t1"}],
            ),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    unit = tailer.ordered_turns()[0].units[0]
    assert bucket_key(unit) == "Tool: Bash"


def test_bucket_key_mcp_tool(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "check the PR"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
                [{"type": "tool_use", "name": "mcp__github__pull_request_read", "input": {}, "id": "t1"}],
            ),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    unit = tailer.ordered_turns()[0].units[0]
    assert bucket_key(unit) == "MCP: github"


def test_bucket_key_skill(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "make a chart"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
                [{"type": "tool_use", "name": "Skill", "input": {"skill": "dataviz"}, "id": "t1"}],
            ),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    unit = tailer.ordered_turns()[0].units[0]
    assert bucket_key(unit) == "Skill: dataviz"


def test_bucket_key_subagent(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "research this"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 10},
                [{"type": "tool_use", "name": "Task", "input": {"description": "research X"}, "id": "t1"}],
            ),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    unit = tailer.ordered_turns()[0].units[0]
    assert bucket_key(unit) == "Subagent: research X"


def test_group_by_activity_aggregates_across_turns_and_sorts_descending(transcript_path):
    write_jsonl(
        transcript_path,
        [
            user_entry("p1", "first"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 100},
                [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t1"}],
            ),
            user_entry("p2", "second"),
            *assistant_lines(
                "m2", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 100},
                [{"type": "tool_use", "name": "Bash", "input": {}, "id": "t2"}],
            ),
            user_entry("p3", "third"),
            *assistant_lines(
                "m3", "claude-haiku-4-5", {"input_tokens": 1, "output_tokens": 1},
                [{"type": "text", "text": "ok"}],
            ),
        ],
    )
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    buckets = group_by_activity(tailer)

    assert [b.label for b in buckets][0] == "Tool: Bash"
    bash_bucket = next(b for b in buckets if b.label == "Tool: Bash")
    direct_bucket = next(b for b in buckets if b.label == "Direct response (no tool call)")
    assert bash_bucket.cost_usd > direct_bucket.cost_usd
    # Two Bash-labeled turns must roll up into one bucket, not two.
    assert sum(1 for b in buckets if b.label == "Tool: Bash") == 1
    assert abs(sum(b.cost_usd for b in buckets) - tailer.total_cost_usd()) < 1e-9


def test_group_by_activity_empty_transcript(transcript_path):
    write_jsonl(transcript_path, [])
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    assert group_by_activity(tailer) == []


def test_collapse_to_other_folds_the_tail():
    buckets = [
        ActivityBucket("A", 50),
        ActivityBucket("B", 30),
        ActivityBucket("C", 10),
        ActivityBucket("D", 5),
        ActivityBucket("E", 5),
    ]
    collapsed = collapse_to_other(buckets, threshold=0.8)
    labels = [b.label for b in collapsed]
    assert labels == ["A", "B", "Other/final 20% (3 categories)"]
    other = collapsed[-1]
    assert other.cost_usd == 20


def test_collapse_to_other_no_residual_when_threshold_never_crossed_early():
    """If the very first bucket alone already crosses the threshold, there
    may still be nothing left in the tail (single-bucket input) - no
    residual bucket should be invented out of zero remaining cost."""
    buckets = [ActivityBucket("A", 100)]
    collapsed = collapse_to_other(buckets, threshold=0.8)
    assert [b.label for b in collapsed] == ["A"]


def test_collapse_to_other_empty_list():
    assert collapse_to_other([], threshold=0.8) == []


def test_collapse_to_other_keeps_everything_when_threshold_is_one():
    buckets = [ActivityBucket("A", 50), ActivityBucket("B", 30), ActivityBucket("C", 20)]
    collapsed = collapse_to_other(buckets, threshold=1.0)
    assert [b.label for b in collapsed] == ["A", "B", "C"]
