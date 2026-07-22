import pytest

from work_ledger.chapters import Chapter, Section
from pathlib import Path

from work_ledger.cli import (
    _check_transcript_flag_placement,
    _filter_only,
    _in_date_range,
    _parse_date_arg,
    _resolve_transcript_arg,
    _threshold_note,
    _turns_cost,
    _turns_unknown,
    _validate_other_threshold,
    _validate_top,
)
from work_ledger.limits import SessionWindowUsage, WindowUsage
from work_ledger.transcript import Turn, Unit


def _turn(prompt_id, cost=1.0, unknown=False):
    unit = Unit(timestamp="2026-07-12T10:00:00Z", own_cost_usd=cost, own_unknown_model=unknown)
    return Turn(prompt_id=prompt_id, prompt_snippet="x", timestamp="2026-07-12T10:00:00Z", units=[unit])


def test_turns_cost_sums_all_turns():
    turns = [_turn("p1", 1.5), _turn("p2", 2.5)]
    assert _turns_cost(turns) == 4.0


def test_turns_unknown_true_if_any_turn_unknown():
    turns = [_turn("p1", 0.0, unknown=True), _turn("p2", 1.0)]
    assert _turns_unknown(turns) is True


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


@pytest.mark.parametrize("command", ["chapters", "activity", "recommend"])
def test_check_transcript_flag_placement_rejects_session_before_subcommand(command, capsys):
    argv = ["--session", "abc123", command]
    with pytest.raises(SystemExit) as exc_info:
        _check_transcript_flag_placement(argv, command)
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "--session" in err
    assert command in err


@pytest.mark.parametrize("command", ["chapters", "activity", "recommend"])
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
