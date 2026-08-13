import types

import pytest

from work_ledger.chapters import Chapter, Section
from pathlib import Path

from work_ledger import cli
from work_ledger.cli import (
    _check_transcript_flag_placement,
    _cost_bar,
    _filter_only,
    _has_skill_units,
    _in_date_range,
    _parse_date_arg,
    _resolve_rollup_flags,
    _resolve_transcript_arg,
    _session_duration_minutes,
    _sidechain_warning,
    _threshold_note,
    _turns_cost,
    _turns_unknown,
    _validate_min_cost,
    _validate_other_threshold,
    _validate_top,
    _validate_top_initiatives,
    _version_string,
    build_session_rows,
)
from work_ledger.limits import SessionWindowUsage, WindowUsage
from work_ledger.transcript import TranscriptTailer, Turn, Unit

from .conftest import assistant_lines, user_entry, write_jsonl


def _turn(prompt_id, cost=1.0, unknown=False):
    unit = Unit(timestamp="2026-07-12T10:00:00Z", own_cost_usd=cost, own_unknown_model=unknown)
    return Turn(prompt_id=prompt_id, prompt_snippet="x", timestamp="2026-07-12T10:00:00Z", units=[unit])


def test_turns_cost_sums_all_turns():
    turns = [_turn("p1", 1.5), _turn("p2", 2.5)]
    assert _turns_cost(turns) == 4.0


def test_turns_unknown_true_if_any_turn_unknown():
    turns = [_turn("p1", 0.0, unknown=True), _turn("p2", 1.0)]
    assert _turns_unknown(turns) is True


def test_cost_bar_scales_to_own_max():
    assert _cost_bar(5.0, 10.0, width=10) == "█" * 5
    assert _cost_bar(10.0, 10.0, width=10) == "█" * 10
    assert _cost_bar(0.0, 10.0, width=10) == ""


def test_cost_bar_zero_max_returns_empty():
    """A trend where every period has $0 cost (e.g. all unpriced models) must
    not divide by zero - no bar rather than crashing."""
    assert _cost_bar(0.0, 0.0) == ""


def test_cost_bar_never_exceeds_width():
    assert len(_cost_bar(100.0, 1.0, width=10)) == 10


def test_turns_unknown_false_if_none_unknown():
    turns = [_turn("p1"), _turn("p2")]
    assert _turns_unknown(turns) is False


def _chapters():
    return [
        Chapter(title="Fix double-counting bug", category="bug-fix", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="Build the dashboard", category="feature-build", sections=[Section(title="s", prompt_ids=["p2"])]),
    ]


def test_filter_only_by_exact_title():
    result = _filter_only(_chapters(), "Build the dashboard")
    assert len(result) == 1
    assert result[0].title == "Build the dashboard"


def test_filter_only_by_substring():
    result = _filter_only(_chapters(), "double-counting")
    assert len(result) == 1
    assert result[0].title == "Fix double-counting bug"


def test_filter_only_by_one_based_index():
    result = _filter_only(_chapters(), "2")
    assert result[0].title == "Build the dashboard"


def test_filter_only_index_out_of_range_returns_empty():
    assert _filter_only(_chapters(), "99") == []


def test_filter_only_no_match_returns_empty():
    assert _filter_only(_chapters(), "nonexistent") == []


def test_parse_date_arg_valid():
    d = _parse_date_arg("2026-07-01", "--since")
    assert d.isoformat() == "2026-07-01"


def test_parse_date_arg_invalid_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_date_arg("not-a-date", "--since")
    assert exc_info.value.code == 2
    assert "--since" in capsys.readouterr().err


@pytest.mark.parametrize("value", [0.0, 0.5, 0.8, 1.0])
def test_validate_other_threshold_accepts_in_range_values(value):
    _validate_other_threshold(value)  # must not raise/exit


@pytest.mark.parametrize("value", [-0.1, 1.1, 150, -1])
def test_validate_other_threshold_rejects_out_of_range_values(value, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _validate_other_threshold(value)
    assert exc_info.value.code == 2
    assert "--other-threshold" in capsys.readouterr().err


def test_validate_top_accepts_none():
    _validate_top(None)  # must not raise/exit - --top is optional


@pytest.mark.parametrize("value", [1, 5, 100])
def test_validate_top_accepts_positive_values(value):
    _validate_top(value)  # must not raise/exit


@pytest.mark.parametrize("value", [0, -1, -10])
def test_validate_top_rejects_non_positive_values(value, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _validate_top(value)
    assert exc_info.value.code == 2
    assert "--top" in capsys.readouterr().err


def test_validate_top_initiatives_accepts_none():
    _validate_top_initiatives(None)  # must not raise/exit - optional


@pytest.mark.parametrize("value", [1, 5, 100])
def test_validate_top_initiatives_accepts_positive_values(value):
    _validate_top_initiatives(value)  # must not raise/exit


@pytest.mark.parametrize("value", [0, -1, -10])
def test_validate_top_initiatives_rejects_non_positive_values(value, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _validate_top_initiatives(value)
    assert exc_info.value.code == 2
    assert "--top-initiatives" in capsys.readouterr().err


def test_validate_min_cost_accepts_none():
    _validate_min_cost(None)  # must not raise/exit - optional


@pytest.mark.parametrize("value", [0.0, 0.01, 10.0, 1000.0])
def test_validate_min_cost_accepts_non_negative_values(value):
    _validate_min_cost(value)  # must not raise/exit


@pytest.mark.parametrize("value", [-0.01, -1, -100])
def test_validate_min_cost_rejects_negative_values(value, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _validate_min_cost(value)
    assert exc_info.value.code == 2
    assert "--min-cost" in capsys.readouterr().err


def test_in_date_range_no_bounds_always_true(tmp_path):
    p = tmp_path / "f.jsonl"
    p.write_text("", encoding="utf-8")
    assert _in_date_range(p, None, None) is True


def test_in_date_range_since_excludes_older_file(tmp_path):
    import datetime
    import os

    p = tmp_path / "f.jsonl"
    p.write_text("", encoding="utf-8")
    old_time = (datetime.datetime.now() - datetime.timedelta(days=10)).timestamp()
    os.utime(p, (old_time, old_time))

    since = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
    assert _in_date_range(p, since, None) is False


def test_threshold_note_none_when_no_threshold():
    usage = WindowUsage(window_hours=5.0)
    assert _threshold_note(usage, None) is None


def test_threshold_note_formats_percentage():
    from pathlib import Path

    usage = WindowUsage(window_hours=5.0)
    usage.sessions.append(SessionWindowUsage(transcript=Path("x.jsonl"), input_tokens=250_000, output_tokens=0))
    note = _threshold_note(usage, 500_000)
    assert "50%" in note


def test_resolve_transcript_arg_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _resolve_transcript_arg("some/path.jsonl", "0daf9882")
    assert exc_info.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_resolve_transcript_arg_neither_given_returns_none_when_no_pin(tmp_path, monkeypatch):
    import work_ledger.session_pin as session_pin_mod

    monkeypatch.setattr(session_pin_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(session_pin_mod, "PINNED_SESSION_PATH", tmp_path / "pinned_session")
    assert _resolve_transcript_arg(None, None) is None


def test_resolve_transcript_arg_falls_back_to_pinned_session(tmp_path, monkeypatch):
    import work_ledger.session_pin as session_pin_mod

    monkeypatch.setattr(session_pin_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(session_pin_mod, "PINNED_SESSION_PATH", tmp_path / "pinned_session")
    target = tmp_path / "session.jsonl"
    target.write_text("", encoding="utf-8")
    session_pin_mod.set_pinned_session(target)

    assert _resolve_transcript_arg(None, None) == target.resolve()


def test_resolve_transcript_arg_explicit_transcript_overrides_pin(tmp_path, monkeypatch):
    import work_ledger.session_pin as session_pin_mod

    monkeypatch.setattr(session_pin_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(session_pin_mod, "PINNED_SESSION_PATH", tmp_path / "pinned_session")
    pinned = tmp_path / "pinned.jsonl"
    pinned.write_text("", encoding="utf-8")
    session_pin_mod.set_pinned_session(pinned)

    assert _resolve_transcript_arg("explicit.jsonl", None) == Path("explicit.jsonl")


def test_resolve_transcript_arg_transcript_given_returns_path():
    assert _resolve_transcript_arg("some/path.jsonl", None) == Path("some/path.jsonl")


def test_resolve_transcript_arg_session_resolves_unique_match(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    target = proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl"
    target.write_text("", encoding="utf-8")

    assert _resolve_transcript_arg(None, "0daf9882") == target


def test_resolve_transcript_arg_session_no_match_exits(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    (proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _resolve_transcript_arg(None, "zzzz")
    assert exc_info.value.code == 1
    assert "zzzz" in capsys.readouterr().err


def test_resolve_transcript_arg_session_ambiguous_exits_and_lists_candidates(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    (proj / "0daf1111-0000-0000-0000-000000000000.jsonl").write_text("", encoding="utf-8")
    (proj / "0daf2222-0000-0000-0000-000000000000.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _resolve_transcript_arg(None, "0daf")
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "0daf1111-0000-0000-0000-000000000000" in err
    assert "0daf2222-0000-0000-0000-000000000000" in err


@pytest.mark.parametrize("command", ["chapters", "activity", "recommend", "waste"])
def test_check_transcript_flag_placement_rejects_session_before_subcommand(command, capsys):
    argv = ["--session", "abc123", command]
    with pytest.raises(SystemExit) as exc_info:
        _check_transcript_flag_placement(argv, command)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--session" in err
    assert command in err


@pytest.mark.parametrize("command", ["chapters", "activity", "recommend", "waste"])
def test_check_transcript_flag_placement_rejects_transcript_before_subcommand(command, capsys):
    argv = ["--transcript", "x.jsonl", command]
    with pytest.raises(SystemExit) as exc_info:
        _check_transcript_flag_placement(argv, command)
    assert exc_info.value.code == 2
    assert "--transcript" in capsys.readouterr().err


def test_check_transcript_flag_placement_allows_flag_after_subcommand():
    argv = ["chapters", "--session", "abc123"]
    _check_transcript_flag_placement(argv, "chapters")  # must not raise/exit


def test_check_transcript_flag_placement_allows_before_and_after_since_after_wins():
    """Regression coverage for the exact argparse behavior this check is
    built around: if the flag appears both before and after the subcommand,
    argparse's own parsing already lets the after-occurrence win correctly
    - only "before, and not repeated after" is actually broken."""
    argv = ["--session", "wrong", "chapters", "--session", "right"]
    _check_transcript_flag_placement(argv, "chapters")  # must not raise/exit


def test_check_transcript_flag_placement_no_subcommand_is_fine():
    argv = ["--session", "abc123", "--once"]
    _check_transcript_flag_placement(argv, None)  # must not raise/exit


@pytest.mark.parametrize("command", ["limits", "export", "patterns", "sessions"])
def test_check_transcript_flag_placement_ignores_commands_without_transcript_flags(command):
    """limits/export/patterns/sessions never redefine --transcript/--session
    on their own parser, so there's no ambiguity for this check to catch -
    it should be a no-op for these regardless of flag position."""
    argv = ["--session", "abc123", command]
    _check_transcript_flag_placement(argv, command)  # must not raise/exit


def test_check_transcript_flag_placement_handles_flag_equals_form():
    argv = ["--session=abc123", "chapters"]
    with pytest.raises(SystemExit) as exc_info:
        _check_transcript_flag_placement(argv, "chapters")
    assert exc_info.value.code == 2


def test_has_skill_units_true_when_present():
    skill_unit = Unit(timestamp="t", skill_name="dataviz")
    turn = Turn(prompt_id="p1", prompt_snippet="x", timestamp="t", units=[skill_unit])
    assert _has_skill_units([turn]) is True


def test_has_skill_units_false_when_absent():
    plain_unit = Unit(timestamp="t")
    turn = Turn(prompt_id="p1", prompt_snippet="x", timestamp="t", units=[plain_unit])
    assert _has_skill_units([turn]) is False


def test_sidechain_warning_none_when_nothing_skipped(transcript_path):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    assert _sidechain_warning(tailer) is None


def test_sidechain_warning_present_when_entries_skipped(transcript_path):
    entries = [
        user_entry("p1", "do something"),
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:01Z",
            "message": {
                "id": "sidechain-msg",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999},
                "content": [{"type": "text", "text": "sidechain"}],
            },
        },
    ]
    write_jsonl(transcript_path, entries)
    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    warning = _sidechain_warning(tailer)
    assert warning is not None
    assert "1" in warning
    assert "isSidechain" in warning


def test_run_prints_sidechain_warning(transcript_path, capsys):
    """#46: an inline isSidechain entry being skipped shows up as a visible
    CLI warning, not just as a documented caveat in the README."""
    entries = [
        user_entry("p1", "do something"),
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:01Z",
            "message": {
                "id": "sidechain-msg",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999},
                "content": [{"type": "text", "text": "sidechain"}],
            },
        },
    ]
    write_jsonl(transcript_path, entries)

    cli.run(transcript_path=transcript_path, once=True)

    out = capsys.readouterr().out
    assert "Warning" in out
    assert "undercount" in out


def test_run_no_sidechain_warning_when_nothing_skipped(transcript_path, capsys):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    cli.run(transcript_path=transcript_path, once=True)

    out = capsys.readouterr().out
    assert "Warning" not in out


def test_run_detail_prints_skill_followon_note(transcript_path, capsys):
    """#46: a Skill: unit's follow-on work isn't bounded to that skill - the
    CLI now says so in --detail output rather than only in README prose."""
    entries = [
        user_entry("p1", "run the dataviz skill"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Skill", "input": {"skill": "dataviz"}, "id": "t1"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    cli.run(transcript_path=transcript_path, once=True, detail=True)

    out = capsys.readouterr().out
    assert "bounded" in out


def test_run_no_detail_omits_skill_followon_note(transcript_path, capsys):
    entries = [
        user_entry("p1", "run the dataviz skill"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Skill", "input": {"skill": "dataviz"}, "id": "t1"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    cli.run(transcript_path=transcript_path, once=True, detail=False)

    out = capsys.readouterr().out
    assert "bounded" not in out


def test_run_activity_prints_skill_followon_note(transcript_path, capsys):
    entries = [
        user_entry("p1", "run the dataviz skill"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Skill", "input": {"skill": "dataviz"}, "id": "t1"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_activity(transcript_path=transcript_path)

    out = capsys.readouterr().out
    assert "bounded" in out


def test_run_activity_prints_sidechain_warning(transcript_path, capsys):
    entries = [
        user_entry("p1", "do something"),
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:01Z",
            "message": {
                "id": "sidechain-msg",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999},
                "content": [{"type": "text", "text": "sidechain"}],
            },
        },
        *assistant_lines("msg-2", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_activity(transcript_path=transcript_path)

    out = capsys.readouterr().out
    assert "Warning" in out
    assert "undercount" in out


# --- run_waste (#5) ------------------------------------------------------


def test_run_waste_reports_no_patterns_message(transcript_path, capsys):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_waste(transcript_path=transcript_path)

    out = capsys.readouterr().out
    assert "No repeated patterns found" in out


def test_run_waste_table_shows_repeated_read(transcript_path, capsys):
    entries = [
        user_entry("p1", "read a file"),
        *assistant_lines(
            "msg-1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t1"}],
        ),
        user_entry("p2", "read it again"),
        *assistant_lines(
            "msg-2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t2"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_waste(transcript_path=transcript_path)

    out = capsys.readouterr().out
    assert "a.py" in out
    assert "Repeated file read" in out
    assert "not what to do about it" in out


def test_run_waste_json_output(transcript_path, capsys):
    entries = [
        user_entry("p1", "read a file"),
        *assistant_lines(
            "msg-1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t1"}],
        ),
        user_entry("p2", "read it again"),
        *assistant_lines(
            "msg-2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t2"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_waste(transcript_path=transcript_path, as_json=True)

    import json

    out = capsys.readouterr().out
    # The dim "Watching:.../note" preamble is printed unconditionally before
    # --json's output, same as every other subcommand's --json path in this
    # codebase (see run_activity/run_recommend) - not something this test
    # should special-case away, just skip past to find the actual JSON.
    data = json.loads(out[out.index("[") :])
    assert len(data) == 1
    assert data[0]["kind"] == "repeated-read"
    assert data[0]["label"] == "/repo/foo.py"
    assert data[0]["occurrences"] == 2


def test_run_waste_prints_sidechain_warning(transcript_path, capsys):
    entries = [
        user_entry("p1", "do something"),
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:01Z",
            "message": {
                "id": "sidechain-msg",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999},
                "content": [{"type": "text", "text": "sidechain"}],
            },
        },
        *assistant_lines("msg-2", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    cli.run_waste(transcript_path=transcript_path)

    out = capsys.readouterr().out
    assert "Warning" in out
    assert "undercount" in out


def test_run_waste_report_writes_well_formed_html(transcript_path, capsys, tmp_path):
    entries = [
        user_entry("p1", "read a file"),
        *assistant_lines(
            "msg-1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t1"}],
        ),
        user_entry("p2", "read it again"),
        *assistant_lines(
            "msg-2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t2"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    out_path = tmp_path / "waste-report.html"
    cli.run_waste(transcript_path=transcript_path, report=True, report_out=str(out_path))

    assert out_path.exists()
    html = out_path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "/repo/foo.py" in html


# --- run_waste_cross_session: the #5 half that depends on #3 ------------


def test_run_waste_cross_session_no_transcripts_exits(isolated_transcripts_root, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.run_waste_cross_session()
    assert exc_info.value.code == 1
    assert "No session transcripts found" in capsys.readouterr().out


def test_run_waste_cross_session_json_output(isolated_transcripts_root, capsys):
    from work_ledger.chapters import _save_cache

    proj1 = isolated_transcripts_root / "proj1"
    proj1.mkdir()
    proj2 = isolated_transcripts_root / "proj2"
    proj2.mkdir()

    path_a = proj1 / "session-a.jsonl"
    path_b = proj2 / "session-b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "read a file"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t1"}],
            ),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "read it again"),
            *assistant_lines(
                "m2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t2"}],
            ),
        ],
    )
    _save_cache(
        path_a,
        ["p1"],
        [Chapter(title="Fix the double-counting bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        ["p2"],
        [Chapter(title="fix double counting bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    cli.run_waste_cross_session(as_json=True)

    import json

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["kind"] == "repeated-read"
    assert data[0]["label"] == "/repo/foo.py"
    assert data[0]["occurrences"] == 2
    assert data[0]["num_sessions"] == 2
    assert data[0]["cost_usd"] > 0


def test_run_waste_cross_session_table_shows_pattern(isolated_transcripts_root, capsys):
    from work_ledger.chapters import _save_cache

    proj1 = isolated_transcripts_root / "proj1"
    proj1.mkdir()
    proj2 = isolated_transcripts_root / "proj2"
    proj2.mkdir()

    path_a = proj1 / "session-a.jsonl"
    path_b = proj2 / "session-b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "read a file"),
            *assistant_lines(
                "m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t1"}],
            ),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "read it again"),
            *assistant_lines(
                "m2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 500},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t2"}],
            ),
        ],
    )
    _save_cache(
        path_a,
        ["p1"],
        [Chapter(title="Fix the double-counting bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        ["p2"],
        [Chapter(title="fix double counting bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    cli.run_waste_cross_session()

    out = capsys.readouterr().out
    assert "a.py" in out
    assert "TOTAL flagged" in out
    assert "not what to do about it" in out


def test_run_waste_cross_session_no_patterns_message(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    path = proj / "session-a.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "do something"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
        ],
    )

    cli.run_waste_cross_session()

    assert "No repeated patterns found" in capsys.readouterr().out


def test_run_waste_cross_session_uncached_hint_excludes_zero_turn_sessions(isolated_transcripts_root, capsys):
    """Same fix as run_rollup's: a genuinely empty session must never be
    counted toward "N session(s) have no cached chapters yet" - re-running
    `chapters --all` can never resolve it (see run_chapters_all's own
    zero-turn skip), so counting it there is a misleading dead end."""
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    empty_path = proj / "session-empty.jsonl"
    write_jsonl(empty_path, [])

    real_path = proj / "session-real.jsonl"
    write_jsonl(
        real_path,
        [
            user_entry("p1", "do something"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
        ],
    )

    cli.run_waste_cross_session()

    out = capsys.readouterr().out
    assert "1 of 2 session(s) have no cached chapters yet" in out


# --- build_session_rows: duration, tokens, summary ----------------------


def test_session_duration_minutes_multi_turn():
    turns = [
        Turn(prompt_id="p1", prompt_snippet="a", timestamp="2026-07-12T10:00:00Z"),
        Turn(prompt_id="p2", prompt_snippet="b", timestamp="2026-07-12T10:15:00Z"),
    ]
    assert _session_duration_minutes(turns) == 15.0


def test_session_duration_minutes_single_turn_is_zero():
    turns = [Turn(prompt_id="p1", prompt_snippet="a", timestamp="2026-07-12T10:00:00Z")]
    assert _session_duration_minutes(turns) == 0.0


def test_session_duration_minutes_empty_is_zero():
    assert _session_duration_minutes([]) == 0.0


def test_build_session_rows_includes_duration_tokens_and_summary(tmp_path):
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "first ask", timestamp="2026-07-12T10:00:00Z"),
        *assistant_lines(
            "m1", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 50},
            [{"type": "text", "text": "ok"}], timestamp="2026-07-12T10:00:01Z",
        ),
        user_entry("p2", "second ask", timestamp="2026-07-12T10:30:00Z"),
        *assistant_lines(
            "m2", "claude-haiku-4-5", {"input_tokens": 200, "output_tokens": 75},
            [{"type": "text", "text": "ok again"}], timestamp="2026-07-12T10:30:01Z",
        ),
    ]
    write_jsonl(path, entries)

    rows = build_session_rows([path])

    assert len(rows) == 1
    row = rows[0]
    assert row["total_tokens"] == 100 + 50 + 200 + 75
    assert row["duration_minutes"] == 30.0
    assert row["summary"] == "first ask"  # no cached chapters -> falls back to first prompt


def test_build_session_rows_summary_prefers_cached_chapter_titles(tmp_path):
    from work_ledger.chapters import _save_cache

    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "fix the bug"),
        *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
    ]
    write_jsonl(path, entries)
    _save_cache(
        path,
        ["p1"],
        [Chapter(title="Fix the double-counting bug", category="bug-fix", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    rows = build_session_rows([path])

    assert rows[0]["summary"] == "Fix the double-counting bug"


def test_build_session_rows_summary_truncates_long_first_prompt(tmp_path):
    path = tmp_path / "s.jsonl"
    long_prompt = "x" * 200
    entries = [
        user_entry("p1", long_prompt),
        *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
    ]
    write_jsonl(path, entries)

    rows = build_session_rows([path])

    assert rows[0]["summary"].endswith("…")
    assert len(rows[0]["summary"]) <= 141


# --- miso ("make it so" end-to-end mode, issue #35) -------------------------


def test_run_miso_check_status_reports_ok_and_makes_no_side_effect(monkeypatch, capsys):
    """`--check-status` (check_status_only=True) is a pure environment
    diagnostic: no transcript resolution, no TranscriptTailer, no file
    written - failing either of those must fail the test."""
    monkeypatch.setattr("work_ledger.cli.check_credentials", lambda: (True, "Anthropic credentials found (env var or `ant auth login` profile)"))
    monkeypatch.setattr("work_ledger.report.png_available", lambda: (True, "Playwright is installed (the `report` extra is available)"))

    def fail_if_called(*a, **kw):
        raise AssertionError("--check-status must not touch any transcript")

    monkeypatch.setattr("work_ledger.cli.find_active_transcript", fail_if_called)
    monkeypatch.setattr("work_ledger.cli.TranscriptTailer", fail_if_called)

    cli.run_miso(check_status_only=True)

    out = capsys.readouterr().out
    assert "OK" in out
    assert "DEGRADED" not in out
    assert "Both HTML and PNG reports will be generated" in out
    assert "no transcript was read and no API call was" in out


def test_run_miso_check_status_reports_degraded_with_fix_guidance(monkeypatch, capsys):
    from work_ledger.chapters import NO_CREDENTIALS_MESSAGE
    from work_ledger.report import PNG_UNAVAILABLE_MESSAGE

    monkeypatch.setattr("work_ledger.cli.check_credentials", lambda: (False, NO_CREDENTIALS_MESSAGE))
    monkeypatch.setattr("work_ledger.report.png_available", lambda: (False, PNG_UNAVAILABLE_MESSAGE))

    cli.run_miso(check_status_only=True)

    out = capsys.readouterr().out
    assert "DEGRADED" in out
    assert "No ANTHROPIC_API_KEY found" in out
    # Regression check for the rich-markup bug where a literal "[report]"
    # in a message gets silently swallowed as an (invalid) style tag -
    # the pip install command must render intact, brackets and all.
    assert 'work-ledger[report]' in out
    assert "Only HTML reports will be generated" in out


def test_run_miso_single_session_writes_html_reports_and_prints_tables(tmp_path, monkeypatch, capsys):
    """Full (non-check-status) run against one session: chapters get
    labeled (mocked _call_model, never a real API call - see
    tests/test_chapters.py's own convention), both terminal tables print,
    and both chapters/activity HTML reports are written. PNG is mocked
    unavailable here so this test doesn't depend on Playwright/Chromium
    being present in whatever environment runs the suite."""
    from work_ledger.chapters import BackendResponse, _ChapterOut, _ChaptersOut, _SectionOut

    monkeypatch.chdir(tmp_path)
    transcript_path = tmp_path / "session-a.jsonl"
    entries = [
        user_entry("p1", "build the dashboard"),
        *assistant_lines(
            "msg-1",
            "claude-sonnet-4-5",
            {"input_tokens": 100, "output_tokens": 50},
            [{"type": "text", "text": "ok, building it"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    fake_parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(
                title="Build the dashboard",
                category="feature-build",
                sections=[_SectionOut(title="build it", prompt_ids=["p1"])],
            )
        ]
    )
    # _call_model now returns a backend-agnostic BackendResponse (see
    # tests/test_chapters.py's own convention) rather than a raw Anthropic
    # SDK response shape.
    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: BackendResponse(
            parsed=fake_parsed, stop_reason="end_turn", cost_usd=0.0031, wall_clock_s=1.1
        ),
    )
    monkeypatch.setattr("work_ledger.cli.check_credentials", lambda: (True, "Anthropic credentials found"))
    monkeypatch.setattr("work_ledger.report.png_available", lambda: (False, "PNG unavailable for this test"))

    cli.run_miso(transcript_path=transcript_path)

    out = capsys.readouterr().out
    # Not asserting the chapter title appears unbroken in `out`: rich wraps
    # long cell text across lines at whatever width capsys's non-tty
    # Console renders at, which would make this assertion width-dependent -
    # the HTML report (checked below) is the reliable place to confirm the
    # title made it through.
    assert "1 chapter(s) labeled" in out
    assert "Reports:" in out
    assert "PNG skipped" in out

    chapters_html = tmp_path / f"work-ledger-miso-chapters-{transcript_path.stem}.html"
    activity_html = tmp_path / f"work-ledger-miso-activity-{transcript_path.stem}.html"
    assert chapters_html.exists()
    assert activity_html.exists()
    assert "Build the dashboard" in chapters_html.read_text(encoding="utf-8")
    # No Playwright mocked in - PNG must not be attempted at all.
    assert not (tmp_path / f"work-ledger-miso-chapters-{transcript_path.stem}.png").exists()


def test_run_miso_no_session_found_errors_clearly(monkeypatch, capsys):
    monkeypatch.setattr("work_ledger.cli.check_credentials", lambda: (True, "ok"))
    monkeypatch.setattr("work_ledger.report.png_available", lambda: (True, "ok"))
    monkeypatch.setattr("work_ledger.cli.find_active_transcript", lambda: None)

    with pytest.raises(SystemExit) as exc_info:
        cli.run_miso(transcript_path=None)
    assert exc_info.value.code == 1
    assert "No Claude Code session transcripts found" in capsys.readouterr().out


def test_run_miso_all_reuses_chapters_all_and_skips_reports(isolated_transcripts_root, monkeypatch, capsys):
    """--all must not invent per-session report generation - it reuses
    run_chapters_all's existing cross-session sweep as-is (chapters --report
    doesn't support --all yet either - see issue #4/#7) and says clearly
    that reports aren't part of this mode."""
    monkeypatch.setattr("work_ledger.cli.check_credentials", lambda: (True, "ok"))
    monkeypatch.setattr("work_ledger.report.png_available", lambda: (True, "ok"))

    project_dir = isolated_transcripts_root / "proj1"
    project_dir.mkdir()
    path = project_dir / "session-a.jsonl"
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
    ]
    write_jsonl(path, entries)

    cli.run_miso(all_sessions=True)

    out = capsys.readouterr().out
    assert "work-ledger chapters --all" in out
    assert "aren't generated in --all mode" in out


def test_run_sessions_top_sorts_by_cost_descending_and_truncates(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    # Three sessions, deliberately written cheap/expensive/mid so the
    # default (file-order) listing wouldn't already happen to be cost-sorted.
    path_cheap = proj / "session-cheap.jsonl"
    path_expensive = proj / "session-expensive.jsonl"
    path_mid = proj / "session-mid.jsonl"
    write_jsonl(
        path_cheap,
        [
            user_entry("p1", "cheap one"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 20}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_expensive,
        [
            user_entry("p2", "expensive one"),
            *assistant_lines("m2", "claude-opus-4-8", {"input_tokens": 50_000, "output_tokens": 10_000}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_mid,
        [
            user_entry("p3", "mid one"),
            *assistant_lines("m3", "claude-haiku-4-5", {"input_tokens": 10_000, "output_tokens": 2_000}, [{"type": "text", "text": "done"}]),
        ],
    )

    cli.run_sessions(top=2, as_json=True)

    import json

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    assert [row["session"] for row in data] == [path_expensive.stem, path_mid.stem]
    assert data[0]["cost_usd"] > data[1]["cost_usd"] > 0


def test_run_sessions_without_top_keeps_default_order(isolated_transcripts_root, capsys):
    """No --top given -> every session listed, unfiltered - `top` must not
    change behavior for the plain `sessions` call sites."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    path_a = proj / "session-a.jsonl"
    path_b = proj / "session-b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "a"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 20}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "b"),
            *assistant_lines("m2", "claude-haiku-4-5", {"input_tokens": 200, "output_tokens": 40}, [{"type": "text", "text": "done"}]),
        ],
    )

    cli.run_sessions(as_json=True)

    import json

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2


def test_run_rollup_clusters_across_sessions_json(isolated_transcripts_root, capsys):
    from work_ledger.chapters import _save_cache

    proj1 = isolated_transcripts_root / "proj1"
    proj1.mkdir()
    proj2 = isolated_transcripts_root / "proj2"
    proj2.mkdir()

    path_a = proj1 / "session-a.jsonl"
    path_b = proj2 / "session-b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "fix it again"),
            *assistant_lines("m2", "claude-haiku-4-5", {"input_tokens": 2000, "output_tokens": 400}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(
        path_a,
        ["p1"],
        [Chapter(title="Fix the double-counting bug", sections=[Section(title="s", prompt_ids=["p1"])])],
    )
    _save_cache(
        path_b,
        ["p2"],
        [Chapter(title="fix double counting bug", sections=[Section(title="s", prompt_ids=["p2"])])],
    )

    cli.run_rollup(as_json=True)

    out_json = capsys.readouterr().out
    import json

    data = json.loads(out_json)
    assert len(data) == 1
    # Which session's exact-case spelling wins as the display title depends
    # on find_all_transcripts()'s mtime order (both sessions are written in
    # this test at effectively the same instant) - both are valid, only the
    # normalized clustering itself is asserted to be deterministic.
    assert data[0]["title"] in ("Fix the double-counting bug", "fix double counting bug")
    assert data[0]["num_sessions"] == 2
    assert data[0]["num_chapters"] == 2
    assert sorted(data[0]["sessions"]) == sorted([path_a.stem, path_b.stem])
    assert data[0]["cost_usd"] > 0


def test_run_rollup_top_excludes_cheap_sessions_from_clustering(isolated_transcripts_root, capsys):
    """--top scopes the *session pool* before clustering (top_n_transcripts_by_cost,
    same ranking sessions --top/serve --top use) - a cheap session's chapter
    must not appear in the rollup at all when it's excluded."""
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()

    path_cheap = proj / "cheap.jsonl"
    path_expensive = proj / "expensive.jsonl"
    write_jsonl(
        path_cheap,
        [
            user_entry("p1", "cheap"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 20}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_expensive,
        [
            user_entry("p2", "expensive"),
            *assistant_lines("m2", "claude-opus-4-8", {"input_tokens": 50_000, "output_tokens": 10_000}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path_cheap, ["p1"], [Chapter(title="Cheap chapter", sections=[Section(title="s", prompt_ids=["p1"])])])
    _save_cache(path_expensive, ["p2"], [Chapter(title="Expensive chapter", sections=[Section(title="s", prompt_ids=["p2"])])])

    cli.run_rollup(as_json=True, top=1)

    import json

    data = json.loads(capsys.readouterr().out)
    titles = [c["title"] for c in data]
    assert "Expensive chapter" in titles
    assert "Cheap chapter" not in titles


def test_run_rollup_report_writes_html_file(isolated_transcripts_root, capsys, tmp_path, monkeypatch):
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    monkeypatch.chdir(tmp_path)
    cli.run_rollup(report=True, report_format="html")

    out = capsys.readouterr().out
    assert "Wrote HTML report to" in out
    written = list(tmp_path.glob("work-ledger-rollup-*.html"))
    assert len(written) == 1
    assert "Fix the bug" in written[0].read_text()


def test_run_rollup_report_writes_csv_file(isolated_transcripts_root, capsys, tmp_path, monkeypatch):
    """Issue #93: --format csv is a third --report output alongside
    html/png, with the same clusters plus cumulative columns."""
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    monkeypatch.chdir(tmp_path)
    cli.run_rollup(report=True, report_format="csv")

    out = capsys.readouterr().out
    assert "Wrote CSV report to" in out
    written = list(tmp_path.glob("work-ledger-rollup-*.csv"))
    assert len(written) == 1

    import csv as csv_module

    rows = list(csv_module.DictReader(written[0].read_text().splitlines()))
    assert len(rows) == 1
    assert rows[0]["initiative"] == "Fix the bug"
    assert rows[0]["is_other"] == "no"
    assert float(rows[0]["cumulative_pct"]) == 100.0


def _make_costed_session(root, project, name, prompt_id, title, output_tokens):
    from work_ledger.chapters import _save_cache

    proj_dir = root / project
    proj_dir.mkdir(exist_ok=True)
    path = proj_dir / f"{name}.jsonl"
    write_jsonl(
        path,
        [
            user_entry(prompt_id, "do work"),
            *assistant_lines(
                f"m-{prompt_id}", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": output_tokens},
                [{"type": "text", "text": "done"}],
            ),
        ],
    )
    _save_cache(path, [prompt_id], [Chapter(title=title, sections=[Section(title="s", prompt_ids=[prompt_id])])])
    return path


def test_run_rollup_other_threshold_collapses_small_clusters_json(isolated_transcripts_root, capsys):
    """Issue #93: --other-threshold folds initiatives beyond the given
    cumulative-cost fraction into one 'All other' cluster, applied before
    the --json output is built."""
    import json

    proj = "proj"
    # Cost scales with output tokens (input tokens held constant across
    # all four) - widely separated so the 80% crossing point isn't close
    # to any rounding edge: Big ~70%, Big+Medium ~90%, cumulative.
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup(as_json=True)
    full = json.loads(capsys.readouterr().out)
    assert len(full) == 4
    full_by_title = {d["title"]: d["cost_usd"] for d in full}
    small_total = full_by_title["Small initiative one"] + full_by_title["Small initiative two"]

    cli.run_rollup(as_json=True, other_threshold=0.8)
    collapsed = json.loads(capsys.readouterr().out)

    assert len(collapsed) == 3  # Big, Medium, All other
    other = next(d for d in collapsed if d["is_other"])
    assert other["title"].startswith("All other")
    assert round(other["cost_usd"], 6) == round(small_total, 6)
    assert sum(1 for d in collapsed if d["is_other"]) == 1
    assert not any(d["is_other"] for d in collapsed if d is not other)


def test_run_rollup_other_threshold_note_and_row_in_table(isolated_transcripts_root, capsys):
    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup(other_threshold=0.8)

    out = " ".join(capsys.readouterr().out.split())  # collapse rich's line-wrapping
    assert "Big initiative" in out
    assert "Medium initiative" in out
    assert "All other" in out
    assert "Small initiative one" not in out  # folded away, not shown as its own row
    assert "folded into 'All other'" in out


def test_run_rollup_no_other_threshold_shows_every_initiative(isolated_transcripts_root, capsys):
    """Opt-in only (issue #93): without --other-threshold, nothing is
    folded, matching every prior release's behavior exactly."""
    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup()

    out = " ".join(capsys.readouterr().out.split())
    assert "Small initiative one" in out
    assert "Small initiative two" in out
    assert "All other" not in out


def test_run_rollup_top_initiatives_keeps_n_costliest(isolated_transcripts_root, capsys):
    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup(top_initiatives=1)

    out = " ".join(capsys.readouterr().out.split())
    assert "Big initiative" in out
    assert "Medium initiative" not in out
    assert "Small initiative one" not in out
    assert "All other" in out
    assert "folded into 'All other'" in out


def test_run_rollup_min_cost_folds_below_the_floor(isolated_transcripts_root, capsys):
    import json

    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup(as_json=True)
    full = {d["title"]: d["cost_usd"] for d in json.loads(capsys.readouterr().out)}

    # A floor between the Small pair and the Medium initiative's cost.
    floor = (full["Small initiative one"] + full["Medium initiative"]) / 2
    cli.run_rollup(as_json=True, min_cost=floor)
    collapsed = json.loads(capsys.readouterr().out)

    other = next(d for d in collapsed if d["is_other"])
    assert other["title"].startswith("All other")
    assert round(other["cost_usd"], 6) == round(
        full["Small initiative one"] + full["Small initiative two"], 6
    )
    assert not any(d["title"] in ("Big initiative", "Medium initiative") for d in collapsed if d["is_other"])


def test_run_rollup_top_initiatives_takes_precedence_over_other_threshold(isolated_transcripts_root, capsys):
    """Issue #93 follow-up: when more than one collapsing flag is given,
    --top-initiatives wins - matches the documented precedence."""
    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    # other_threshold=0.8 alone would keep Big+Medium (2 individual rows);
    # top_initiatives=1 must win and keep only Big.
    cli.run_rollup(other_threshold=0.8, top_initiatives=1)

    out = " ".join(capsys.readouterr().out.split())
    assert "Big initiative" in out
    assert "Medium initiative" not in out
    assert "--top-initiatives 1" in out  # the folded-note names the flag that actually ran


def test_run_rollup_min_cost_takes_precedence_over_other_threshold(isolated_transcripts_root, capsys):
    proj = "proj"
    _make_costed_session(isolated_transcripts_root, proj, "s-a", "p1", "Big initiative", 7000)
    _make_costed_session(isolated_transcripts_root, proj, "s-b", "p2", "Medium initiative", 2000)
    _make_costed_session(isolated_transcripts_root, proj, "s-c", "p3", "Small initiative one", 600)
    _make_costed_session(isolated_transcripts_root, proj, "s-d", "p4", "Small initiative two", 400)

    cli.run_rollup(other_threshold=0.8, min_cost=1000000.0)  # an absurdly high floor - folds everything

    out = " ".join(capsys.readouterr().out.split())
    assert "--min-cost" in out
    assert "--other-threshold" not in out


# --- issue #97: --semantic, --preset/--miso, _resolve_rollup_flags --------


def _rollup_args(**overrides):
    base = dict(
        json=False,
        confirm=False,
        top=None,
        report=False,
        format=None,
        other_threshold=None,
        top_initiatives=None,
        min_cost=None,
        preview=False,
        semantic=False,
        preset=None,
        save_preset=None,
        list_presets=False,
        delete_preset=None,
        miso=False,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_resolve_rollup_flags_plain_passthrough_no_bundle():
    """No --miso/--preset: every flag passes straight through, --format
    falls back to "html" (its pre-#97 argparse default) rather than None."""
    resolved = _resolve_rollup_flags(_rollup_args(other_threshold=0.5, confirm=True))
    assert resolved["other_threshold"] == 0.5
    assert resolved["confirm"] is True
    assert resolved["report_format"] == "html"
    assert resolved["top"] is None
    assert resolved["semantic"] is False


def test_resolve_rollup_flags_miso_applies_the_built_in_bundle():
    from work_ledger import rollup_presets

    resolved = _resolve_rollup_flags(_rollup_args(miso=True))
    assert resolved["semantic"] is True
    assert resolved["other_threshold"] == rollup_presets.MISO_PRESET["other_threshold"]
    assert resolved["report"] is True
    assert resolved["report_format"] == "html"
    assert resolved["confirm"] is True
    assert resolved["preview"] is True


def test_resolve_rollup_flags_cli_flag_overrides_miso():
    resolved = _resolve_rollup_flags(_rollup_args(miso=True, other_threshold=0.5))
    assert resolved["other_threshold"] == 0.5  # explicit CLI value wins over --miso's 0.8


def test_resolve_rollup_flags_preset_bundle_applies(monkeypatch):
    monkeypatch.setattr(
        "work_ledger.rollup_presets.get_preset",
        lambda name: {"other_threshold": 0.9, "top_initiatives": None, "confirm": True} if name == "x" else None,
    )
    resolved = _resolve_rollup_flags(_rollup_args(preset="x"))
    assert resolved["other_threshold"] == 0.9
    assert resolved["confirm"] is True


def test_resolve_rollup_flags_cli_flag_overrides_preset(monkeypatch):
    monkeypatch.setattr(
        "work_ledger.rollup_presets.get_preset",
        lambda name: {"other_threshold": 0.9} if name == "x" else None,
    )
    resolved = _resolve_rollup_flags(_rollup_args(preset="x", other_threshold=0.5))
    assert resolved["other_threshold"] == 0.5


def test_resolve_rollup_flags_unknown_preset_exits(monkeypatch, capsys):
    monkeypatch.setattr("work_ledger.rollup_presets.get_preset", lambda name: None)
    with pytest.raises(SystemExit) as exc_info:
        _resolve_rollup_flags(_rollup_args(preset="nope"))
    assert exc_info.value.code == 2
    assert "nope" in capsys.readouterr().err


def test_resolve_rollup_flags_store_true_flags_or_with_bundle(monkeypatch):
    """A store_true flag not passed on the CLI (False) still resolves
    True if the bundle asked for it - there's no CLI syntax for
    "explicitly not this," so OR-ing is correct."""
    monkeypatch.setattr(
        "work_ledger.rollup_presets.get_preset",
        lambda name: {"preview": True} if name == "x" else None,
    )
    resolved = _resolve_rollup_flags(_rollup_args(preset="x", preview=False))
    assert resolved["preview"] is True


def test_run_rollup_semantic_sets_env_var_only_for_the_call(isolated_transcripts_root, monkeypatch, capsys):
    from work_ledger import rollup_semantic
    from work_ledger.chapters import _save_cache

    monkeypatch.delenv(rollup_semantic.ROLLUP_MATCHING_ENV_VAR, raising=False)

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    seen_during_call = []

    def fake_build_rollup_result(transcripts):
        import os

        seen_during_call.append(os.environ.get(rollup_semantic.ROLLUP_MATCHING_ENV_VAR))
        from work_ledger.rollup import build_rollup_result as real

        return real(transcripts)

    monkeypatch.setattr("work_ledger.cli.build_rollup_result", fake_build_rollup_result)

    cli.run_rollup(semantic=True)

    assert seen_during_call == [rollup_semantic.SEMANTIC_MATCHING]  # set during the call...
    import os

    assert rollup_semantic.ROLLUP_MATCHING_ENV_VAR not in os.environ  # ...and cleaned up after


def test_run_rollup_semantic_does_not_clobber_already_set_env_var(isolated_transcripts_root, monkeypatch):
    import os

    from work_ledger import rollup_semantic
    from work_ledger.chapters import _save_cache

    monkeypatch.setenv(rollup_semantic.ROLLUP_MATCHING_ENV_VAR, rollup_semantic.SEMANTIC_MATCHING)

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    cli.run_rollup(semantic=True)

    # Still set afterward - run_rollup must never delete an env var it didn't set itself.
    assert os.environ[rollup_semantic.ROLLUP_MATCHING_ENV_VAR] == rollup_semantic.SEMANTIC_MATCHING


def test_run_rollup_table_shows_cumulative_column(isolated_transcripts_root, capsys):
    """Ask #1: cumulative $ and % are shown in the default (no-flags)
    table, not gated behind any new flag."""
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    cli.run_rollup()

    out = " ".join(capsys.readouterr().out.split())
    assert "Cumulative" in out
    assert "100%" in out  # a single cluster is trivially 100% cumulative


def test_run_rollup_preview_shows_table_alongside_report(isolated_transcripts_root, capsys, tmp_path, monkeypatch):
    """--preview works alongside --report - see what the file will
    contain without opening it (issue #93)."""
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    monkeypatch.chdir(tmp_path)
    cli.run_rollup(report=True, report_format="html", preview=True)

    out = capsys.readouterr().out
    assert "Wrote HTML report to" in out  # the file was still written
    assert "Fix the bug" in out  # ...and the table was also printed
    assert "work-ledger rollup" in out


def test_run_rollup_preview_without_report_matches_default_table(isolated_transcripts_root, capsys):
    """Without --report, --preview shows the same table the no-flags
    default already does - it's an explicit alias for that case, not a
    different rendering."""
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    path = proj / "s.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    cli.run_rollup(preview=True)

    out = capsys.readouterr().out
    assert "Fix the bug" in out
    assert "Cumulative" in out


def test_run_rollup_no_transcripts_exits(isolated_transcripts_root, capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.run_rollup()
    assert exc_info.value.code == 1
    assert "No session transcripts found" in capsys.readouterr().out


def test_run_rollup_no_cached_chapters_prints_hint(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    path = proj / "session-a.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "do something"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
        ],
    )
    # No .chapters.json cache written for this session at all.

    cli.run_rollup()

    out = capsys.readouterr().out
    assert "No cached chapters found" in out
    assert "chapters --all" in out


def test_count_sessions_needing_chaptering_excludes_zero_turn_sessions(tmp_path):
    """A genuinely empty (zero-turn) session can never be helped by
    `chapters --all` - it's skipped outright by run_chapters_all, so it
    never gets a cache file and `not cached_chapters(p)` would be True for
    it forever. The real, actionable count only includes sessions that
    have turns but aren't fully cached yet."""
    empty_path = tmp_path / "empty.jsonl"
    write_jsonl(empty_path, [])

    real_path = tmp_path / "real.jsonl"
    write_jsonl(
        real_path,
        [
            user_entry("p1", "do something"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
        ],
    )

    assert cli._count_sessions_needing_chaptering([empty_path, real_path]) == 1
    assert cli._count_sessions_needing_chaptering([empty_path]) == 0


def test_run_rollup_uncached_hint_excludes_zero_turn_sessions(isolated_transcripts_root, capsys):
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()

    # A cluster of 2 cached, matching-title sessions - gives run_rollup a
    # real cluster to print instead of hitting the empty "no clusters" path.
    path_a = proj / "session-a.jsonl"
    path_b = proj / "session-b.jsonl"
    write_jsonl(
        path_a,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "fix it again"),
            *assistant_lines("m2", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path_a, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])
    _save_cache(path_b, ["p2"], [Chapter(title="fix bug", sections=[Section(title="s", prompt_ids=["p2"])])])

    # A genuinely empty session alongside them - must not be counted as
    # "still needs chapters --all" (see issue found against real usage:
    # re-running chapters --all reported 166 sessions chaptered, but a
    # cross-session command still showed sessions as uncached afterward).
    empty_path = proj / "session-empty.jsonl"
    write_jsonl(empty_path, [])

    cli.run_rollup()

    out = capsys.readouterr().out
    assert "have no cached chapters yet" not in out


def test_run_rollup_since_filters_out_older_sessions(isolated_transcripts_root, capsys):
    import os
    from datetime import date, datetime, timedelta

    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    path = proj / "session-a.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "old work"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Old initiative", sections=[Section(title="s", prompt_ids=["p1"])])])

    old_date = date.today() - timedelta(days=30)
    old_time = datetime(old_date.year, old_date.month, old_date.day).timestamp()
    os.utime(path, (old_time, old_time))

    with pytest.raises(SystemExit) as exc_info:
        cli.run_rollup(since=date.today() - timedelta(days=1))
    assert exc_info.value.code == 1
    assert "No session transcripts found in that date range" in capsys.readouterr().out


def test_run_rollup_table_shows_grand_total(isolated_transcripts_root, capsys):
    from work_ledger.chapters import _save_cache

    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    path = proj / "session-a.jsonl"
    write_jsonl(
        path,
        [
            user_entry("p1", "fix it"),
            *assistant_lines("m1", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]),
        ],
    )
    _save_cache(path, ["p1"], [Chapter(title="Fix the bug", sections=[Section(title="s", prompt_ids=["p1"])])])

    cli.run_rollup()

    out = capsys.readouterr().out
    assert "work-ledger rollup" in out
    # rich may wrap "GRAND TOTAL" across two lines in capsys's non-tty
    # narrow rendering (see the same caveat in test_run_miso_* above) -
    # check both words landed rather than the exact joined substring.
    assert "GRAND" in out
    assert "TOTAL" in out
    assert "Fix the bug" in out


# --- #68: WORK_LEDGER_ROLLUP_MATCHING / --confirm ---------------------------


def _norm(out: str) -> str:
    """Collapse rich's non-tty line-wrapping (default 80-col width under
    capsys) so a substring check isn't broken by a wrap landing mid-phrase
    - same caveat test_run_rollup_table_shows_grand_total already works
    around by checking words separately; here it's simpler to just
    collapse all whitespace once."""
    return " ".join(out.split())


def _make_singleton_session(root, project, name, prompt_id, title):
    from work_ledger.chapters import _save_cache

    proj_dir = root / project
    proj_dir.mkdir(exist_ok=True)
    path = proj_dir / f"{name}.jsonl"
    write_jsonl(
        path,
        [
            user_entry(prompt_id, "do work"),
            *assistant_lines(
                f"m-{prompt_id}", "claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 200}, [{"type": "text", "text": "done"}]
            ),
        ],
    )
    _save_cache(path, [prompt_id], [Chapter(title=title, sections=[Section(title="s", prompt_ids=[prompt_id])])])
    return path


def test_run_rollup_default_env_prints_no_semantic_note(isolated_transcripts_root, capsys, monkeypatch):
    """Env var unset (the default): no semantic-matching note of any kind,
    even with --confirm passed - this is the "byte-for-byte unchanged
    default behavior" guarantee, not just "no crash"."""
    monkeypatch.delenv("WORK_LEDGER_ROLLUP_MATCHING", raising=False)

    def boom(titles):
        raise AssertionError("propose_merges must not be called when matching mode is deterministic")

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", boom)

    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", "Fix the bug")

    cli.run_rollup(confirm=True)

    out = capsys.readouterr().out
    assert "semantic" not in out.lower()
    assert "WORK_LEDGER_ROLLUP_MATCHING" not in out


def test_run_rollup_confirm_lists_merged_titles(isolated_transcripts_root, capsys, monkeypatch):
    from work_ledger.rollup_semantic import SemanticMergeResult

    monkeypatch.setenv("WORK_LEDGER_ROLLUP_MATCHING", "semantic")

    title_a = "Execute reading-list-builder daily flow"
    title_b = "Initialize reading list builder daily flow"
    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", title_a)
    _make_singleton_session(isolated_transcripts_root, "proj2", "b", "p2", title_b)

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[[title_a, title_b]]),
    )

    cli.run_rollup(confirm=True)

    out = _norm(capsys.readouterr().out)
    assert "Merged via semantic matching" in out
    assert title_a in out
    assert title_b in out


def test_run_rollup_semantic_merge_without_confirm_omits_title_list(isolated_transcripts_root, capsys, monkeypatch):
    """Without --confirm, a merge still gets a short visibility note (never
    silently identical to "nothing to merge"), but not the full title
    breakdown - that's what --confirm is for."""
    from work_ledger.rollup_semantic import SemanticMergeResult

    monkeypatch.setenv("WORK_LEDGER_ROLLUP_MATCHING", "semantic")

    title_a = "Execute reading-list-builder daily flow"
    title_b = "Initialize reading list builder daily flow"
    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", title_a)
    _make_singleton_session(isolated_transcripts_root, "proj2", "b", "p2", title_b)

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[[title_a, title_b]]),
    )

    cli.run_rollup(confirm=False)

    out = capsys.readouterr().out
    assert "merged" in out.lower()
    assert "Merged via semantic matching" not in out


def test_run_rollup_semantic_fallback_reason_printed(isolated_transcripts_root, capsys, monkeypatch):
    """A degraded semantic pass (no credentials, refusal, etc.) must print
    a distinguishable note even without --confirm - visibility into a
    failure isn't gated behind the opt-in detail flag."""
    from work_ledger.rollup_semantic import SemanticMergeResult

    monkeypatch.setenv("WORK_LEDGER_ROLLUP_MATCHING", "semantic")
    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", "Fix the login bug")
    _make_singleton_session(isolated_transcripts_root, "proj2", "b", "p2", "Fix the checkout bug")

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[], fallback_reason="No ANTHROPIC_API_KEY found in this environment; semantic matching skipped"),
    )

    cli.run_rollup()

    out = capsys.readouterr().out
    assert "No ANTHROPIC_API_KEY found" in out


def test_run_rollup_semantic_nothing_to_merge_note_distinct_from_fallback(isolated_transcripts_root, capsys, monkeypatch):
    """The pass running successfully and finding nothing to merge must be
    worded differently than it failing to run at all - both print
    something, but never the same something."""
    from work_ledger.rollup_semantic import SemanticMergeResult

    monkeypatch.setenv("WORK_LEDGER_ROLLUP_MATCHING", "semantic")
    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", "Fix the login bug")
    _make_singleton_session(isolated_transcripts_root, "proj2", "b", "p2", "Fix the checkout bug")

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[]),
    )

    cli.run_rollup()

    out = _norm(capsys.readouterr().out)
    assert "found nothing new to merge" in out
    assert "Note:" not in out


def test_run_waste_cross_session_confirm_lists_merged_titles(isolated_transcripts_root, capsys, monkeypatch):
    from work_ledger.rollup_semantic import SemanticMergeResult

    monkeypatch.setenv("WORK_LEDGER_ROLLUP_MATCHING", "semantic")

    title_a = "Execute reading-list-builder daily flow"
    title_b = "Initialize reading list builder daily flow"
    path_a = _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", title_a)
    path_b = _make_singleton_session(isolated_transcripts_root, "proj2", "b", "p2", title_b)

    # Give both sessions the same repeated Read so there's an actual
    # cross-session pattern once the two titles are merged into one
    # initiative - otherwise the table-vs-"no patterns" branch differs and
    # the semantic note wouldn't be reachable via the same code path.
    write_jsonl(
        path_a,
        [
            user_entry("p1", "do work"),
            *assistant_lines(
                "m-p1",
                "claude-haiku-4-5",
                {"input_tokens": 1000, "output_tokens": 200},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t1"}],
            ),
        ],
    )
    write_jsonl(
        path_b,
        [
            user_entry("p2", "do work"),
            *assistant_lines(
                "m-p2",
                "claude-haiku-4-5",
                {"input_tokens": 1000, "output_tokens": 200},
                [{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/foo.py"}, "id": "t1"}],
            ),
        ],
    )

    monkeypatch.setattr(
        "work_ledger.rollup_semantic.propose_merges",
        lambda titles: SemanticMergeResult(groups=[[title_a, title_b]]),
    )

    cli.run_waste_cross_session(confirm=True)

    out = _norm(capsys.readouterr().out)
    assert "Merged via semantic matching" in out
    assert title_a in out
    assert title_b in out


def test_run_waste_cross_session_default_env_prints_no_semantic_note(isolated_transcripts_root, capsys, monkeypatch):
    monkeypatch.delenv("WORK_LEDGER_ROLLUP_MATCHING", raising=False)

    def boom(titles):
        raise AssertionError("propose_merges must not be called when matching mode is deterministic")

    monkeypatch.setattr("work_ledger.rollup_semantic.propose_merges", boom)

    _make_singleton_session(isolated_transcripts_root, "proj1", "a", "p1", "Fix the bug")

    cli.run_waste_cross_session(confirm=True)

    out = capsys.readouterr().out
    assert "semantic" not in out.lower()


# --- timeline --summary --------------------------------------------------


def _day_transcript(project_dir, filename: str, day: str, category_counts: dict[str, int]) -> None:
    """Write a single-day transcript under `project_dir` with one user turn
    per categorized unit, then chapter-cache it so build_timeline() picks
    up exactly the requested category_counts for that day - mirrors
    test_build_timeline_uses_cached_chapter_categories's cache-priming
    pattern, just parameterized over several turns/categories at once."""
    from work_ledger.chapters import _save_cache

    entries = []
    prompt_id = 0
    category_prompt_ids: dict[str, list[str]] = {}
    for category, count in category_counts.items():
        for _ in range(count):
            prompt_id += 1
            pid = f"{filename}-p{prompt_id}"
            entries.append(user_entry(pid, "do a thing", f"{day}T10:00:00Z"))
            entries.extend(
                assistant_lines(
                    f"{filename}-m{prompt_id}", "claude-haiku-4-5",
                    {"input_tokens": 5, "output_tokens": 5},
                    [{"type": "text", "text": "done"}], f"{day}T10:00:01Z",
                )
            )
            category_prompt_ids.setdefault(category, []).append(pid)

    path = project_dir / f"{filename}.jsonl"
    write_jsonl(path, entries)
    chapters = [
        Chapter(title=category, category=category, sections=[Section(title=category, prompt_ids=pids)])
        for category, pids in category_prompt_ids.items()
    ]
    _save_cache(path, chaptered_ids=[pid for pids in category_prompt_ids.values() for pid in pids], chapters=chapters)


def test_run_timeline_summary_prints_narrative(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    _day_transcript(proj, "d1", "2026-07-01", {"debugging": 3})
    _day_transcript(proj, "d2", "2026-07-02", {"debugging": 2, "design-planning": 1})
    _day_transcript(proj, "d3", "2026-07-03", {"refactor": 3})
    _day_transcript(proj, "d4", "2026-07-04", {"refactor": 2, "docs": 1})

    cli.run_timeline(summary=True)

    out = capsys.readouterr().out
    # Narrative printed alongside (above) the usual sparkline view, not
    # instead of it - the granular table stays even when --summary is on.
    assert "Summary" in out
    assert "Early in this range" in out
    assert "debugging" in out
    assert "More recently" in out
    assert "refactor" in out
    assert "work-ledger timeline" in out
    assert "Approach mix" in out


def test_run_timeline_without_summary_flag_omits_narrative(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    _day_transcript(proj, "d1", "2026-07-01", {"debugging": 3})
    _day_transcript(proj, "d2", "2026-07-02", {"debugging": 2, "design-planning": 1})
    _day_transcript(proj, "d3", "2026-07-03", {"refactor": 3})
    _day_transcript(proj, "d4", "2026-07-04", {"refactor": 2, "docs": 1})

    cli.run_timeline(summary=False)

    out = capsys.readouterr().out
    assert "Summary" not in out
    assert "work-ledger timeline" in out


def test_run_timeline_summary_reports_not_enough_data(isolated_transcripts_root, capsys):
    proj = isolated_transcripts_root / "proj1"
    proj.mkdir()
    # Only 2 populated days - below summarize_timeline()'s minimum, even
    # though a single day is chaptered and would otherwise render fine.
    _day_transcript(proj, "d1", "2026-07-01", {"debugging": 3})
    _day_transcript(proj, "d2", "2026-07-02", {"refactor": 3})

    cli.run_timeline(summary=True)

    out = capsys.readouterr().out
    assert "not enough day-to-day category data yet" in out
    # Still prints the ordinary sparkline view - --summary never suppresses it.
    assert "Approach mix" in out
    assert "semantic" not in out.lower()


# --- run_cycle_command (issue #73) ---------------------------------------


def test_run_cycle_command_check_status_editable(monkeypatch, tmp_path, capsys):
    from work_ledger import cycle as cycle_mod

    monkeypatch.setattr(
        cycle_mod,
        "detect_install_mode",
        lambda: cycle_mod.InstallInfo(mode=cycle_mod.EDITABLE, version="1.0", repo_root=tmp_path),
    )
    monkeypatch.setattr(cycle_mod, "is_port_in_use", lambda port: False)

    cli.run_cycle_command(check_status=True)

    out = capsys.readouterr().out
    assert "editable clone" in out
    assert str(tmp_path) in out
    assert "would run `git pull`" in out
    assert "Nothing detected listening" in out


def test_run_cycle_command_check_status_published_shows_upgrade_command(monkeypatch, capsys):
    from work_ledger import cycle as cycle_mod

    monkeypatch.setattr(
        cycle_mod, "detect_install_mode", lambda: cycle_mod.InstallInfo(mode=cycle_mod.PUBLISHED_PYPI, version="1.0")
    )
    monkeypatch.setattr(cycle_mod, "is_port_in_use", lambda port: False)
    monkeypatch.setattr(cycle_mod, "detect_installer", lambda: None)

    cli.run_cycle_command(check_status=True)

    out = " ".join(capsys.readouterr().out.split())
    assert "published install (PyPI)" in out
    assert "pip install --upgrade work-ledger" in out


def test_run_cycle_command_warns_when_serve_port_in_use(monkeypatch, capsys):
    from work_ledger import cycle as cycle_mod

    monkeypatch.setattr(
        cycle_mod, "detect_install_mode", lambda: cycle_mod.InstallInfo(mode=cycle_mod.PUBLISHED_PYPI, version="1.0")
    )
    monkeypatch.setattr(cycle_mod, "is_port_in_use", lambda port: True)

    cli.run_cycle_command(check_status=True)

    out = " ".join(capsys.readouterr().out.split())
    assert "may be running" in out
    assert "never signals another process" in out


def test_run_cycle_command_reports_pulled_commits(monkeypatch, capsys):
    from work_ledger import cycle as cycle_mod

    report = cycle_mod.CycleReport(
        install=cycle_mod.InstallInfo(mode=cycle_mod.EDITABLE, version="1.0"),
        serve_port_in_use=False,
        serve_port=8765,
        action="git pull",
        before="aaaaaaaaaaaaaaaaaaaa",
        after="bbbbbbbbbbbbbbbbbbbb",
        changed=True,
    )
    monkeypatch.setattr(cycle_mod, "run_cycle", lambda port: report)

    cli.run_cycle_command(check_status=False)

    out = capsys.readouterr().out
    assert "Pulled new commits" in out
    assert "aaaaaaaaaa" in out and "bbbbbbbbbb" in out


def test_run_cycle_command_reports_already_up_to_date(monkeypatch, capsys):
    from work_ledger import cycle as cycle_mod

    report = cycle_mod.CycleReport(
        install=cycle_mod.InstallInfo(mode=cycle_mod.EDITABLE, version="1.0"),
        serve_port_in_use=False,
        serve_port=8765,
        action="git pull",
        before="aaaaaaaaaaaaaaaaaaaa",
        after="aaaaaaaaaaaaaaaaaaaa",
        changed=False,
    )
    monkeypatch.setattr(cycle_mod, "run_cycle", lambda port: report)

    cli.run_cycle_command(check_status=False)

    assert "Already up to date" in capsys.readouterr().out


def test_run_cycle_command_error_exits_nonzero(monkeypatch, capsys):
    from work_ledger import cycle as cycle_mod

    def _raise(port):
        raise cycle_mod.CycleError("uncommitted changes present")

    monkeypatch.setattr(cycle_mod, "run_cycle", _raise)

    with pytest.raises(SystemExit) as exc_info:
        cli.run_cycle_command(check_status=False)

    assert exc_info.value.code == 1
    assert "uncommitted changes present" in capsys.readouterr().out


# --- _version_string (--version includes commit/date) --------------------


def test_version_string_includes_commit_and_date(monkeypatch):
    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info())

    assert _version_string() == "1.2.3 (commit abc1234, 2026-07-20)"


def test_version_string_no_commit_falls_back_to_date_only(monkeypatch):
    """A published (non-git) install has no resolvable commit - never
    fabricate one, fall back to just the date."""
    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info(commit=None))

    assert _version_string() == "1.2.3 (last updated 2026-07-20)"


def test_version_string_no_date_or_commit_is_bare_version(monkeypatch):
    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info(commit=None, last_updated=""))

    assert _version_string() == "1.2.3"


# --- run_about_command (issue #75) ----------------------------------------


def _fake_about_info(**overrides):
    from work_ledger.about import AboutInfo

    defaults = dict(
        description="Lightweight, near-real-time Claude Code usage/cost tracker for individuals",
        version="1.2.3",
        last_updated="2026-07-20T10:00:00+00:00",
        commit="abc1234",
        author_email="davehk@gmail.com",
        author_url="www.dhk.io",
        repo_url="https://github.com/dhk/work-ledger",
    )
    defaults.update(overrides)
    return AboutInfo(**defaults)


def test_run_about_command_prints_all_fields(monkeypatch, capsys):
    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info())

    cli.run_about_command(as_json=False)
    out = capsys.readouterr().out
    assert "1.2.3" in out
    assert "abc1234" in out
    assert "2026-07-20T10:00:00+00:00" in out
    assert "davehk@gmail.com" in out
    assert "www.dhk.io" in out
    assert "https://github.com/dhk/work-ledger" in out


def test_run_about_command_no_commit_shows_fallback_note(monkeypatch, capsys):
    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info(commit=None))

    cli.run_about_command(as_json=False)
    out = capsys.readouterr().out
    assert "not resolvable" in out


def test_run_about_command_json(monkeypatch, capsys):
    import json

    import work_ledger.about as about_mod

    monkeypatch.setattr(about_mod, "get_about_info", lambda: _fake_about_info())

    cli.run_about_command(as_json=True)
    data = json.loads(capsys.readouterr().out)
    assert data["version"] == "1.2.3"
    assert data["commit"] == "abc1234"
    assert data["repo_url"] == "https://github.com/dhk/work-ledger"
