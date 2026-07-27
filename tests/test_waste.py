from work_ledger.chapters import Chapter, Section, UNSORTED_TITLE, _save_cache
from work_ledger.rollup import build_rollup_result
from work_ledger.rollup_semantic import ROLLUP_MATCHING_ENV_VAR, SemanticMergeResult
from work_ledger.transcript import TranscriptTailer, Turn, Unit
from work_ledger.waste import (
    REPEATED_READ,
    REPEATED_SUBAGENT,
    UNCHAPTERED_SCOPE,
    find_cross_session_waste_patterns,
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


# --- Cross-session waste mining (the #5 half that depends on #3) ----------


def _write_cross_session(path, prompt_id, blocks, timestamp="2026-07-01T10:00:00Z"):
    entries = [user_entry(prompt_id, "do work", timestamp)]
    entries += assistant_lines(
        f"m-{prompt_id}",
        "claude-haiku-4-5",
        {"input_tokens": 1000, "output_tokens": 500},
        blocks,
        timestamp,
    )
    write_jsonl(path, entries)


def _read_blocks(file_path):
    return [{"type": "tool_use", "name": "Read", "input": {"file_path": file_path}, "id": "t1"}]


def test_cross_session_repeated_read_flagged_across_sessions_of_same_initiative(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the double-counting bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="fix double counting bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    patterns = find_cross_session_waste_patterns([path_a, path_b])
    assert len(patterns) == 1
    p = patterns[0]
    assert p.kind == REPEATED_READ
    assert p.initiative == "Fix the double-counting bug"
    assert p.label == "/repo/foo.py"
    assert p.occurrences == 2
    assert p.num_sessions == 2
    assert p.cost_usd > 0


def test_cross_session_single_session_repeat_not_flagged(tmp_path):
    """A file read twice within one session is already fully covered by
    find_waste_patterns - surfacing it again here (spanning only 1 session)
    would be a duplicate, not new information."""
    path_a = tmp_path / "session-a.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    assert find_cross_session_waste_patterns([path_a]) == []


def test_cross_session_unrelated_initiatives_not_merged(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the login bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="Build the v1 dashboard", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    assert find_cross_session_waste_patterns([path_a, path_b]) == []


def test_cross_session_uncached_session_contributes_nothing(tmp_path):
    """A session with no cached chapters at all can't be attributed to any
    initiative - matches rollup.py's own "run chapters first" precedent."""
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    # path_b deliberately never chaptered.

    assert find_cross_session_waste_patterns([path_a, path_b]) == []


def test_cross_session_unsorted_chapters_excluded(tmp_path):
    """UNSORTED_TITLE is chaptering's own fallback label, not a real
    initiative - two sessions' unrelated Unsorted chapters must not be
    treated as the same recurring pattern, same exclusion rollup.py makes."""
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title=UNSORTED_TITLE, sections=[Section(title=UNSORTED_TITLE, prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title=UNSORTED_TITLE, sections=[Section(title=UNSORTED_TITLE, prompt_ids=["p2"])])],
    )

    assert find_cross_session_waste_patterns([path_a, path_b]) == []


def test_cross_session_repeated_subagent_across_sessions(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    subagent_blocks = [{"type": "tool_use", "name": "Task", "input": {"description": "research the API"}, "id": "t1"}]
    _write_cross_session(path_a, "p1", subagent_blocks)
    _write_cross_session(path_b, "p2", subagent_blocks)

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Research the widget API", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="research widget api", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    patterns = find_cross_session_waste_patterns([path_a, path_b])
    assert len(patterns) == 1
    p = patterns[0]
    assert p.kind == REPEATED_SUBAGENT
    assert p.num_sessions == 2
    assert p.occurrences == 2


def test_cross_session_no_transcripts_returns_empty():
    assert find_cross_session_waste_patterns([]) == []


def test_cross_session_sorted_by_cost_descending(tmp_path):
    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    path_c = tmp_path / "session-c.jsonl"
    path_d = tmp_path / "session-d.jsonl"

    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))
    subagent_blocks = [
        {
            "type": "tool_use",
            "name": "Task",
            "input": {"description": "research the API"},
            "id": "t1",
        }
    ]
    _write_cross_session(path_c, "p3", subagent_blocks)
    _write_cross_session(path_d, "p4", subagent_blocks)

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="fix bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )
    _save_cache(
        path_c,
        chaptered_ids=["p3"],
        chapters=[Chapter(title="Research the API", sections=[Section(title="s", prompt_ids=["p3"])])],
    )
    _save_cache(
        path_d,
        chaptered_ids=["p4"],
        chapters=[Chapter(title="research api", sections=[Section(title="s", prompt_ids=["p4"])])],
    )

    patterns = find_cross_session_waste_patterns([path_a, path_b, path_c, path_d])
    assert len(patterns) == 2
    costs = [p.cost_usd for p in patterns]
    assert costs == sorted(costs, reverse=True)


# --- #68: waste --cross-session shares rollup's clustering -----------------
#
# The requirement most likely to have a subtle bug (per issue #68's own
# testing guidance): enabling WORK_LEDGER_ROLLUP_MATCHING=semantic must
# change what `rollup` and `waste --cross-session` each consider "the same
# initiative" identically, from one shared computation - not two
# independent ones that happen to usually agree.


def test_cross_session_default_deterministic_mode_reworded_titles_stay_unmerged(tmp_path, monkeypatch):
    """Regression guard: with the env var unset (the default), two
    genuinely reworded titles must NOT cluster, and the same file read once
    in each session must NOT be flagged as a cross-session repeat - byte-
    for-byte the same as before #68 existed."""
    monkeypatch.delenv(ROLLUP_MATCHING_ENV_VAR, raising=False)

    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Execute reading-list-builder daily flow", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="Initialize reading list builder daily flow", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    assert find_cross_session_waste_patterns([path_a, path_b]) == []


def test_cross_session_semantic_matching_shares_clusters_with_rollup(tmp_path, monkeypatch):
    """The core shared-mechanism assertion: with semantic matching on and a
    mocked merge of two reworded titles, both `find_cross_session_waste_patterns`
    and `build_rollup_result` must agree the two sessions are one initiative
    - same display title, same session membership - computed from the same
    underlying clustering, not two independently-arrived-at answers."""
    monkeypatch.setenv(ROLLUP_MATCHING_ENV_VAR, "semantic")

    title_a = "Execute reading-list-builder daily flow"
    title_b = "Initialize reading list builder daily flow"

    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))

    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title=title_a, sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title=title_b, sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    def fake_propose_merges(titles):
        assert set(titles) == {title_a, title_b}
        return SemanticMergeResult(groups=[[title_a, title_b]])

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", fake_propose_merges)

    # Without the merge, this would be two separate single-session clusters
    # and the shared file-read wouldn't qualify as a cross-session repeat at
    # all - so a non-empty result here already proves the merge was picked
    # up; the identity assertions below prove it's the *same* merge rollup
    # itself computes, not a coincidentally-matching one.
    patterns = find_cross_session_waste_patterns([path_a, path_b])
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.kind == REPEATED_READ
    assert pattern.num_sessions == 2

    rollup_result = build_rollup_result([path_a, path_b])
    assert len(rollup_result.clusters) == 1
    cluster = rollup_result.clusters[0]
    assert sorted(cluster.sessions) == [path_a.stem, path_b.stem]

    # The exact "same initiative" agreement: waste's pattern.initiative is
    # the identical string rollup's own cluster.display_title is.
    assert pattern.initiative == cluster.display_title


def test_cross_session_semantic_matching_disabled_does_not_call_model(tmp_path, monkeypatch):
    """A cheap but important regression check: with the env var unset,
    find_cross_session_waste_patterns's route through build_rollup_result
    must never even attempt the semantic call."""
    monkeypatch.delenv(ROLLUP_MATCHING_ENV_VAR, raising=False)

    def boom(titles):
        raise AssertionError("propose_merges must not be called when matching mode is deterministic")

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", boom)

    path_a = tmp_path / "session-a.jsonl"
    path_b = tmp_path / "session-b.jsonl"
    _write_cross_session(path_a, "p1", _read_blocks("/repo/foo.py"))
    _write_cross_session(path_b, "p2", _read_blocks("/repo/foo.py"))
    _save_cache(
        path_a,
        chaptered_ids=["p1"],
        chapters=[Chapter(title="Fix the login bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        chaptered_ids=["p2"],
        chapters=[Chapter(title="Fix the checkout bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    find_cross_session_waste_patterns([path_a, path_b])  # must not raise
