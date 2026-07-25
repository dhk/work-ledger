from work_ledger.chapters import Chapter, Section
from work_ledger.transcript import TranscriptTailer, Turn, Unit
from work_ledger.waste import (
    REPEATED_READ,
    REPEATED_SUBAGENT,
    UNCHAPTERED_SCOPE,
    find_repeated_reads,
    find_repeated_subagents,
    find_waste_patterns,
)

from .conftest import assistant_lines, user_entry, write_jsonl


def _build_tailer(path, turn_specs):
    """turn_specs: list of (prompt_id, [(model, usage, blocks), ...]) - one
    entry per Unit within that turn. Mirrors test_recommend.py's helper."""
    entries = []
    for i, (pid, units) in enumerate(turn_specs):
        entries.append(user_entry(pid, f"turn {i}"))
        for j, (model, usage, blocks) in enumerate(units):
            entries.extend(assistant_lines(f"msg-{i}-{j}", model, usage, blocks))
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()
    return tailer


def _tailer_from_turns(turns: list[Turn]) -> TranscriptTailer:
    """Build a TranscriptTailer directly from already-constructed Turns,
    bypassing JSONL parsing entirely - used for the one case here
    (subagent_agent_type) that's only ever populated asynchronously from a
    subagent's sidecar `.meta.json` file (see transcript.py's
    _poll_subagents), which isn't worth standing up just to test waste.py's
    grouping key."""
    tailer = TranscriptTailer.__new__(TranscriptTailer)
    tailer.turns = {}
    tailer.turn_order = []
    for turn in turns:
        tailer.turns[turn.prompt_id] = turn
        tailer.turn_order.append(turn.prompt_id)
    return tailer


def _read_unit(path, cost_tokens=(1000, 500)):
    return (
        "claude-haiku-4-5",
        {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]},
        [{"type": "tool_use", "name": "Read", "input": {"file_path": path}, "id": "t"}],
    )


def _subagent_unit(desc, cost_tokens=(1000, 500)):
    return (
        "claude-haiku-4-5",
        {"input_tokens": cost_tokens[0], "output_tokens": cost_tokens[1]},
        [{"type": "tool_use", "name": "Task", "input": {"description": desc}, "id": "t"}],
    )


def test_repeated_read_flagged_across_turns(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_read_unit("/repo/foo.py")]),
            ("p2", [_read_unit("/repo/foo.py")]),
            ("p3", [_read_unit("/repo/bar.py")]),
        ],
    )
    patterns = find_repeated_reads(tailer)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.kind == REPEATED_READ
    assert p.label == "/repo/foo.py"
    assert p.occurrences == 2
    assert p.scope == UNCHAPTERED_SCOPE
    assert p.cost_usd > 0


def test_single_read_not_flagged(tmp_path):
    tailer = _build_tailer(tmp_path / "s.jsonl", [("p1", [_read_unit("/repo/foo.py")])])
    assert find_repeated_reads(tailer) == []


def test_read_repeated_within_one_unit_counts_once_not_double_cost(tmp_path):
    """A single message that Reads the same file twice shouldn't fabricate
    a repeat out of one LLM call - occurrences/cost are Unit-scoped, not
    raw tool_use-call-scoped (see module docstring). Only one Unit exists
    at all here, so a real repeat (2+ distinct Units) never happened."""
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            (
                "p1",
                [
                    (
                        "claude-haiku-4-5",
                        {"input_tokens": 1000, "output_tokens": 500},
                        [
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t1"},
                            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t2"},
                        ],
                    )
                ],
            )
        ],
    )
    assert find_repeated_reads(tailer) == []


def test_repeated_reads_scoped_per_chapter_not_across_chapters(tmp_path):
    """The same file read once in each of two different chapters is not a
    within-chapter repeat - #5 is explicitly within-session/chapter only,
    cross-session/chapter correlation is out of scope (depends on #3)."""
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_read_unit("/repo/foo.py")]),
            ("p2", [_read_unit("/repo/foo.py")]),
        ],
    )
    chapters = [
        Chapter(title="Chapter A", category="other", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="Chapter B", category="other", sections=[Section(title="s", prompt_ids=["p2"])]),
    ]
    assert find_repeated_reads(tailer, chapters) == []


def test_repeated_reads_scoped_within_same_chapter_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_read_unit("/repo/foo.py")]),
            ("p2", [_read_unit("/repo/foo.py")]),
        ],
    )
    chapters = [
        Chapter(title="Chapter A", category="other", sections=[Section(title="s", prompt_ids=["p1", "p2"])]),
    ]
    patterns = find_repeated_reads(tailer, chapters)
    assert len(patterns) == 1
    assert patterns[0].scope == "Chapter A"
    assert patterns[0].occurrences == 2


def test_repeated_subagent_same_description_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_subagent_unit("research the API")]),
            ("p2", [_subagent_unit("research the API")]),
        ],
    )
    patterns = find_repeated_subagents(tailer)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.kind == REPEATED_SUBAGENT
    assert "research the API" in p.label
    assert p.occurrences == 2


def test_repeated_subagent_near_identical_whitespace_and_case_matches(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_subagent_unit("Research the API")]),
            ("p2", [_subagent_unit("  research   the api  ")]),
        ],
    )
    patterns = find_repeated_subagents(tailer)
    assert len(patterns) == 1
    assert patterns[0].occurrences == 2


def test_different_subagent_descriptions_not_flagged(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_subagent_unit("research the API")]),
            ("p2", [_subagent_unit("fix the failing test")]),
        ],
    )
    assert find_repeated_subagents(tailer) == []


def test_different_agent_types_same_description_not_flagged():
    """Same wording dispatched to two different agent types isn't the same
    recurring pattern - agent type is part of the match key. subagent_
    agent_type only ever comes from the subagent's sidecar .meta.json (see
    transcript.py's _poll_subagents), so these Units are built directly
    rather than via a full transcript + sidecar fixture."""
    turn1 = Turn(prompt_id="p1", prompt_snippet="t1", timestamp="")
    turn1.units.append(
        Unit(
            timestamp="",
            subagent_desc="research the API",
            subagent_agent_type="Explore",
            own_cost_usd=0.01,
        )
    )
    turn2 = Turn(prompt_id="p2", prompt_snippet="t2", timestamp="")
    turn2.units.append(
        Unit(
            timestamp="",
            subagent_desc="research the API",
            subagent_agent_type="general-purpose",
            own_cost_usd=0.01,
        )
    )
    tailer = _tailer_from_turns([turn1, turn2])
    assert find_repeated_subagents(tailer) == []


def test_same_agent_type_and_description_from_different_units_flagged():
    turn1 = Turn(prompt_id="p1", prompt_snippet="t1", timestamp="")
    turn1.units.append(
        Unit(
            timestamp="",
            subagent_desc="research the API",
            subagent_agent_type="Explore",
            own_cost_usd=0.01,
        )
    )
    turn2 = Turn(prompt_id="p2", prompt_snippet="t2", timestamp="")
    turn2.units.append(
        Unit(
            timestamp="",
            subagent_desc="research the API",
            subagent_agent_type="Explore",
            own_cost_usd=0.02,
        )
    )
    tailer = _tailer_from_turns([turn1, turn2])
    patterns = find_repeated_subagents(tailer)
    assert len(patterns) == 1
    assert patterns[0].label == "Explore: research the API"
    assert abs(patterns[0].cost_usd - 0.03) < 1e-9


def test_find_waste_patterns_combines_and_sorts_by_cost_descending(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [
            ("p1", [_read_unit("/repo/foo.py", (100, 50))]),
            ("p2", [_read_unit("/repo/foo.py", (100, 50))]),
            ("p3", [_subagent_unit("research the API", cost_tokens=(1_000_000, 1_000_000))]),
            ("p4", [_subagent_unit("research the API", cost_tokens=(1_000_000, 1_000_000))]),
        ],
    )
    patterns = find_waste_patterns(tailer)
    assert len(patterns) == 2
    costs = [p.cost_usd for p in patterns]
    assert costs == sorted(costs, reverse=True)
    assert patterns[0].kind == REPEATED_SUBAGENT


def test_find_waste_patterns_empty_session(tmp_path):
    tailer = _build_tailer(tmp_path / "s.jsonl", [("p1", [_read_unit("/repo/foo.py")])])
    assert find_waste_patterns(tailer) == []


def test_find_waste_patterns_no_chapters_still_detects_with_whole_session_scope(tmp_path):
    tailer = _build_tailer(
        tmp_path / "s.jsonl",
        [("p1", [_read_unit("/repo/foo.py")]), ("p2", [_read_unit("/repo/foo.py")])],
    )
    patterns = find_waste_patterns(tailer, chapters=[])
    assert len(patterns) == 1
    assert patterns[0].scope == UNCHAPTERED_SCOPE
