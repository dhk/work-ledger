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
