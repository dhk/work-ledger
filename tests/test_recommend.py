from work_ledger.chapters import Chapter, Section
from work_ledger.recommend import generate_recommendations
from work_ledger.transcript import TranscriptTailer

from .conftest import assistant_lines, user_entry, write_jsonl


def _build_tailer(path, turn_specs):
    """turn_specs: list of (prompt_id, [(model, usage, blocks), ...]) - one
    entry per Unit within that turn."""
    entries = []
    for i, (pid, units) in enumerate(turn_specs):
        entries.append(user_entry(pid, f"turn {i}"))
        for j, (model, usage, blocks) in enumerate(units):
            entries.extend(assistant_lines(f"msg-{i}-{j}", model, usage, blocks))
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()
    return tailer


def _text_unit(cost_tokens=(10, 5)):
    return ("claude-haiku-4-5", {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]}, [{"type": "text", "text": "x"}])


def _skill_unit(name, cost_tokens=(10, 5)):
    return (
        "claude-haiku-4-5",
        {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]},
        [{"type": "tool_use", "name": "Skill", "input": {"skill": name}, "id": "t"}],
    )


def _subagent_unit(cost_tokens=(1_000_000, 1_000_000)):
    return (
        "claude-haiku-4-5",
        {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]},
        [{"type": "tool_use", "name": "Task", "input": {"description": "research"}, "id": "t"}],
    )


def test_no_recommendations_on_uniform_cheap_session(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [("p1", [_text_unit()]), ("p2", [_text_unit()]), ("p3", [_text_unit()])],
    )
    chapters = [
        Chapter(title="A", category="other", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="B", category="other", sections=[Section(title="s", prompt_ids=["p2"])]),
        Chapter(title="C", category="other", sections=[Section(title="s", prompt_ids=["p3"])]),
    ]
    assert generate_recommendations(chapters, tailer) == []


def test_outlier_chapter_cost_flagged(tmp_path):
    # Two cheap chapters, one dramatically more expensive.
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_text_unit((10_000, 5_000))]),
            ("p2", [_text_unit((10_000, 5_000))]),
            ("p3", [_text_unit((1_000_000, 1_000_000))]),
        ],
    )
    chapters = [
        Chapter(title="Cheap A", category="other", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="Cheap B", category="other", sections=[Section(title="s", prompt_ids=["p2"])]),
        Chapter(title="Expensive", category="other", sections=[Section(title="s", prompt_ids=["p3"])]),
    ]
    recs = generate_recommendations(chapters, tailer)
    assert any(r.rule_id == "outlier-chapter-cost" and "Expensive" in r.title for r in recs)


def test_subagent_heavy_chapter_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [("p1", [_subagent_unit(), _subagent_unit()])],
    )
    chapters = [Chapter(title="Research spree", category="other", sections=[Section(title="s", prompt_ids=["p1"])])]
    recs = generate_recommendations(chapters, tailer)
    assert any(r.rule_id == "subagent-heavy-chapter" for r in recs)


def test_subagent_heavy_requires_minimum_call_count(tmp_path):
    """A single subagent call, even an expensive one, doesn't trigger the
    rule - MIN_SUBAGENT_CALLS guards against flagging one legitimate call."""
    tailer = _build_tailer(tmp_path / "s.jsonl", [("p1", [_subagent_unit()])])
    chapters = [Chapter(title="One call", category="other", sections=[Section(title="s", prompt_ids=["p1"])])]
    recs = generate_recommendations(chapters, tailer)
    assert not any(r.rule_id == "subagent-heavy-chapter" for r in recs)


def test_repeated_skill_invocation_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_skill_unit("dataviz", (50_000, 50_000))]),
            ("p2", [_skill_unit("dataviz", (50_000, 50_000))]),
            ("p3", [_skill_unit("dataviz", (50_000, 50_000))]),
        ],
    )
    chapters = [
        Chapter(
            title="Charting work",
            category="other",
            sections=[Section(title="s", prompt_ids=["p1", "p2", "p3"])],
        )
    ]
    recs = generate_recommendations(chapters, tailer)
    assert any(r.rule_id == "repeated-skill-invocation" and "dataviz" in r.title for r in recs)


def test_repeated_skill_below_threshold_not_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [("p1", [_skill_unit("dataviz", (50_000, 50_000))]), ("p2", [_skill_unit("dataviz", (50_000, 50_000))])],
    )
    chapters = [Chapter(title="Charting work", category="other", sections=[Section(title="s", prompt_ids=["p1", "p2"])])]
    recs = generate_recommendations(chapters, tailer)
    assert not any(r.rule_id == "repeated-skill-invocation" for r in recs)


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


def test_session_limit_hits_flagged(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "ok"}]),
        _rate_limit_entry("2026-07-11T23:15:14.228Z", "11:40pm (UTC)"),
        _rate_limit_entry("2026-07-12T03:22:00.000Z", "4:40am (UTC)"),
        _rate_limit_entry("2026-07-12T03:30:00.000Z", "4:40am (UTC)"),  # dupe reset time - deduped away
    ]
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()

    recs = generate_recommendations([], tailer)
    matches = [r for r in recs if r.rule_id == "session-limit-hits"]
    assert len(matches) == 1
    assert "2 times" in matches[0].title  # 3 raw hits dedupe to 2 distinct reset windows


def test_no_session_limit_recommendation_without_hits(tmp_path):
    tailer = _build_tailer(tmp_path / "s.jsonl", [("p1", [_text_unit()])])
    recs = generate_recommendations([], tailer)
    assert not any(r.rule_id == "session-limit-hits" for r in recs)


def _interruption_entries(prompt_id: str, count: int, start_ts: str = "2026-07-12T10:00:00Z") -> list[dict]:
    return [
        {
            "type": "user",
            "promptId": prompt_id,
            "timestamp": start_ts,
            "message": {"role": "user", "content": "[Request interrupted by user]"},
        }
        for _ in range(count)
    ]


def test_interruptions_flagged_at_threshold(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [user_entry("p1", "first"), *_interruption_entries("p1", 2)]
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()

    recs = generate_recommendations([], tailer)
    assert any(r.rule_id == "session-interruptions" and "2 times" in r.title for r in recs)


def test_single_interruption_not_flagged(tmp_path):
    """A lone interruption is normal course-correction, not a pattern -
    MIN_INTERRUPTION_COUNT guards against flagging on just one."""
    path = tmp_path / "s.jsonl"
    entries = [user_entry("p1", "first"), *_interruption_entries("p1", 1)]
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()

    recs = generate_recommendations([], tailer)
    assert not any(r.rule_id == "session-interruptions" for r in recs)


def _git_workflow_blocks() -> list[dict]:
    """A 3-step Bash sequence shaped like the design doc's own validated
    example (branch/commit/push/PR cycle, abbreviated to 3 steps here)."""
    return [
        {"type": "tool_use", "name": "Bash", "input": {"command": "git checkout -b feature"}, "id": "t1"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m msg"}, "id": "t2"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "gh pr create"}, "id": "t3"},
    ]


def test_recurring_tool_sequence_flagged_at_threshold(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, _git_workflow_blocks())]),
            ("p2", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, _git_workflow_blocks())]),
            ("p3", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, _git_workflow_blocks())]),
        ],
    )
    recs = generate_recommendations([], tailer)
    matches = [r for r in recs if r.rule_id == "recurring-tool-sequence"]
    assert len(matches) == 1
    assert "3 times" in matches[0].title
    assert "git checkout" in matches[0].detail


def test_recurring_tool_sequence_below_threshold_not_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, _git_workflow_blocks())]),
            ("p2", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, _git_workflow_blocks())]),
        ],
    )
    recs = generate_recommendations([], tailer)
    assert not any(r.rule_id == "recurring-tool-sequence" for r in recs)


def test_recurring_short_sequence_not_flagged(tmp_path):
    """Fewer than MIN_SEQUENCE_STEPS steps isn't a "procedure" worth naming,
    even if it repeats often - e.g. a plain Read then Edit."""
    short_blocks = [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}, "id": "t1"},
        {"type": "tool_use", "name": "Edit", "input": {}, "id": "t2"},
    ]
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, short_blocks)]),
            ("p2", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, short_blocks)]),
            ("p3", [("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, short_blocks)]),
        ],
    )
    recs = generate_recommendations([], tailer)
    assert not any(r.rule_id == "recurring-tool-sequence" for r in recs)


def test_recommendations_sorted_by_cost_descending(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_text_unit((1_000, 500))]),
            ("p2", [_text_unit((1_000, 500))]),
            ("p3", [_text_unit((500_000, 500_000))]),
            ("p4", [_text_unit((2_000_000, 2_000_000))]),
        ],
    )
    chapters = [
        Chapter(title="A", category="other", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="B", category="other", sections=[Section(title="s", prompt_ids=["p2"])]),
        Chapter(title="Mid", category="other", sections=[Section(title="s", prompt_ids=["p3"])]),
        Chapter(title="Biggest", category="other", sections=[Section(title="s", prompt_ids=["p4"])]),
    ]
    recs = generate_recommendations(chapters, tailer)
    costs = [r.cost_usd for r in recs]
    assert costs == sorted(costs, reverse=True)
