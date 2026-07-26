import os
import time

from work_ledger.transcript import (
    TranscriptTailer,
    find_active_transcript,
    find_all_transcripts,
    find_transcripts_by_session_prefix,
)

from .conftest import assistant_lines, user_entry, write_jsonl


def test_dedup_by_message_id_prevents_overcounting(transcript_path):
    """Regression test for the original double-counting bug: Claude Code
    writes one JSONL line per content block but repeats the full usage
    block on every line for the same message.id. Summing usage per line
    would count this single real API call 3x."""
    usage = {"input_tokens": 100, "output_tokens": 50}
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            usage,
            [
                {"type": "text", "text": "thinking..."},
                {"type": "tool_use", "name": "Bash", "input": {}, "id": "tool-1"},
                {"type": "text", "text": "done"},
            ],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    turns = tailer.ordered_turns()
    assert len(turns) == 1
    assert len(turns[0].units) == 1  # 3 lines, same message.id -> one Unit
    assert turns[0].input_tokens == 100
    assert turns[0].output_tokens == 50


def test_two_distinct_messages_in_one_turn_both_counted(transcript_path):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
        *assistant_lines("msg-2", "claude-haiku-4-5", {"input_tokens": 20, "output_tokens": 8}, [{"type": "text", "text": "b"}]),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    turn = tailer.ordered_turns()[0]
    assert len(turn.units) == 2
    assert turn.input_tokens == 30
    assert turn.output_tokens == 13


def test_skill_invocation_labeled(transcript_path):
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

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.kind == "skill"
    assert unit.label == "Skill: dataviz"


def test_subagent_dispatch_labeled_and_tool_use_id_tracked(transcript_path):
    entries = [
        user_entry("p1", "spawn a subagent"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Task", "input": {"description": "research X"}, "id": "tool-abc"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.kind == "subagent"
    assert unit.subagent_tool_use_id == "tool-abc"
    assert "research X" in unit.label


def test_read_tool_use_captures_file_path(transcript_path):
    entries = [
        user_entry("p1", "read a file"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.py"}, "id": "t1"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.read_paths == ["/a/b.py"]


def test_read_tool_use_without_file_path_is_not_recorded(transcript_path):
    """A malformed/unexpected Read input (no file_path) is skipped rather
    than recording a None/empty placeholder that would look like a real
    repeated path to waste.py's detection."""
    entries = [
        user_entry("p1", "read a file"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Read", "input": {}, "id": "t1"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.read_paths == []


def test_multiple_reads_in_one_unit_all_captured(transcript_path):
    entries = [
        user_entry("p1", "read two files"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}, "id": "t1"},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/b.py"}, "id": "t2"},
            ],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.read_paths == ["/a.py", "/b.py"]


def test_subagent_transcript_usage_rolls_up_into_dispatching_unit(transcript_path):
    entries = [
        user_entry("p1", "spawn a subagent"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 10, "output_tokens": 5},
            [{"type": "tool_use", "name": "Task", "input": {"description": "research X"}, "id": "tool-abc"}],
        ),
    ]
    write_jsonl(transcript_path, entries)

    subagents_dir = transcript_path.parent / transcript_path.stem / "subagents"
    subagents_dir.mkdir(parents=True)
    (subagents_dir / "agent-1.meta.json").write_text(
        '{"toolUseId": "tool-abc", "agentType": "Explore", "description": "research X"}',
        encoding="utf-8",
    )
    sub_entries = [
        {
            "type": "assistant",
            "timestamp": "2026-07-12T10:00:02Z",
            "message": {
                "id": "sub-msg-1",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 200, "output_tokens": 100},
                "content": [{"type": "text", "text": "subagent output"}],
            },
        }
    ]
    write_jsonl(subagents_dir / "agent-1.jsonl", sub_entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()
    tailer.poll()  # subagent files are picked up on a subsequent poll pass

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.subagent_agent_type == "Explore"
    assert unit.input_tokens == 10 + 200
    assert unit.output_tokens == 5 + 100


def test_issidechain_entries_are_skipped_not_guessed_at(transcript_path):
    """Inline isSidechain entries (a different transcript format than this
    environment's separate-file subagent layout) are deliberately ignored
    rather than correlated - see transcript.py's module docstring."""
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

    turns = tailer.ordered_turns()
    assert len(turns) == 1
    assert turns[0].units == []


def test_issidechain_entries_are_counted_for_46(transcript_path):
    """A skipped isSidechain entry isn't silently invisible (#46) - it's
    counted so a caller can warn the session's cost may be an undercount."""
    entries = [
        user_entry("p1", "do something"),
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:01Z",
            "message": {
                "id": "sidechain-msg-1",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999},
                "content": [{"type": "text", "text": "sidechain"}],
            },
        },
        {
            "type": "assistant",
            "isSidechain": True,
            "timestamp": "2026-07-12T10:00:02Z",
            "message": {
                "id": "sidechain-msg-2",
                "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [{"type": "text", "text": "sidechain 2"}],
            },
        },
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    assert tailer.skipped_sidechain_count == 2
    assert tailer.has_skipped_sidechain() is True


def test_no_sidechain_entries_count_stays_zero(transcript_path):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    assert tailer.skipped_sidechain_count == 0
    assert tailer.has_skipped_sidechain() is False


def test_unknown_model_flagged_not_silently_zero(transcript_path):
    entries = [
        user_entry("p1", "do something"),
        *assistant_lines("msg-1", "some-brand-new-model", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "a"}]),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    turn = tailer.ordered_turns()[0]
    assert turn.unknown_model_cost is True
    assert turn.cost_usd == 0.0


def _rate_limit_entry(timestamp: str, reset_label: str) -> dict:
    """The exact synthetic rate_limit shape from
    docs/recommend-workflow-efficiency-design.md's Validation section - no
    message.id, no usage block, so conftest's assistant_lines() (which
    always builds a usage-bearing, message.id-bearing entry) doesn't fit
    here; this is deliberately a raw dict matching the non-standard shape."""
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


def test_rate_limit_hits_recorded_but_not_turned_into_a_unit(transcript_path):
    """A rate_limit entry carries no usage/message.id - it's not a real LLM
    call, so it must not silently become a (free, model-less) Unit on the
    current turn."""
    entries = [
        user_entry("p1", "do something"),
        _rate_limit_entry("2026-07-11T23:15:14.228Z", "11:40pm (UTC)"),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    assert len(tailer.rate_limit_hits) == 1
    assert tailer.rate_limit_hits[0].reset_label == "11:40pm (UTC)"
    assert tailer.ordered_turns()[0].units == []


def test_rate_limit_hits_deduped_by_reset_time(transcript_path):
    """Mirrors the design doc's own validation: 5 raw hits, but 4 of them
    share one reset time (a retry storm against the same limit window) -
    that collapses to 2 distinct events, not 5."""
    entries = [
        user_entry("p1", "do something"),
        _rate_limit_entry("2026-07-11T23:15:14.228Z", "11:40pm (UTC)"),
        _rate_limit_entry("2026-07-12T03:22:00.000Z", "4:40am (UTC)"),
        _rate_limit_entry("2026-07-12T03:30:00.000Z", "4:40am (UTC)"),
        _rate_limit_entry("2026-07-12T04:00:00.000Z", "4:40am (UTC)"),
        _rate_limit_entry("2026-07-12T04:15:00.000Z", "4:40am (UTC)"),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    assert len(tailer.rate_limit_hits) == 5
    events = tailer.deduped_rate_limit_events()
    assert [(e.timestamp, e.reset_label) for e in events] == [
        ("2026-07-11T23:15:14.228Z", "11:40pm (UTC)"),
        ("2026-07-12T03:22:00.000Z", "4:40am (UTC)"),  # earliest of the 4 sharing this reset time
    ]


def test_interruption_marker_counted_only_in_genuine_user_text(transcript_path):
    """The literal marker only counts when it's the actual text content of
    a `type: "user"` message - not when it shows up inside a tool_use input
    (an assistant message, not a user one) or a tool_result block (a user
    entry, but not text content) - see INTERRUPTION_MARKER's docstring for
    why a blind substring search overcounts in practice."""
    entries = [
        user_entry("p1", "first prompt"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 1, "output_tokens": 1},
            [{"type": "tool_use", "name": "Bash", "input": {"command": "echo '[Request interrupted by user]'"}, "id": "t1"}],
        ),
        {
            "type": "user",
            "promptId": "p1",
            "timestamp": "2026-07-12T10:05:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "[Request interrupted by user]"}],
            },
        },
        {
            "type": "user",
            "promptId": "p1",
            "timestamp": "2026-07-12T10:06:00Z",
            "message": {"role": "user", "content": "[Request interrupted by user]"},
        },
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    assert tailer.interruption_count == 1


def test_bash_tool_call_signature_distinguishes_subcommands(transcript_path):
    """A single leading word ("git") isn't enough to tell `git checkout`
    apart from `git commit`/`git push` - tool_call_signature keeps up to 3
    words so a recurring git/gh workflow stays distinguishable, without
    capturing branch names, commit messages, or PR bodies."""
    entries = [
        user_entry("p1", "ship it"),
        *assistant_lines(
            "msg-1",
            "claude-haiku-4-5",
            {"input_tokens": 1, "output_tokens": 1},
            [
                {"type": "tool_use", "name": "Bash", "input": {"command": "git checkout -b my-branch-name"}, "id": "t1"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m 'a secret message'"}, "id": "t2"},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}, "id": "t3"},
            ],
        ),
    ]
    write_jsonl(transcript_path, entries)

    tailer = TranscriptTailer(transcript_path)
    tailer.poll()

    unit = tailer.ordered_turns()[0].units[0]
    assert unit.tool_call_signature == ["Bash:git checkout -b", "Bash:git commit -m", "Read"]
    assert "my-branch-name" not in unit.tool_call_signature[0]
    assert "secret message" not in unit.tool_call_signature[1]


def test_find_active_transcript_picks_most_recent(isolated_transcripts_root):
    import os
    import time

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    older = proj / "older.jsonl"
    newer = proj / "newer.jsonl"
    older.write_text("", encoding="utf-8")
    newer.write_text("", encoding="utf-8")
    now = time.time()
    os.utime(older, (now - 100, now - 100))
    os.utime(newer, (now, now))

    assert find_active_transcript() == newer


def test_find_active_transcript_none_when_no_projects_dir(tmp_path, monkeypatch):
    import work_ledger.transcript as transcript_mod

    monkeypatch.setattr(transcript_mod, "TRANSCRIPTS_ROOT", tmp_path / "does-not-exist")
    assert find_active_transcript() is None


def test_find_all_transcripts_newest_first(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    a = proj / "a.jsonl"
    b = proj / "b.jsonl"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    now = time.time()
    os.utime(a, (now - 100, now - 100))
    os.utime(b, (now, now))

    result = find_all_transcripts()
    assert result == [b, a]


def test_find_all_transcripts_skips_vanished_file(isolated_transcripts_root, monkeypatch):
    """A file that disappears between the glob and the stat call is
    skipped rather than raising - see find_all_transcripts' docstring."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    (proj / "a.jsonl").write_text("", encoding="utf-8")

    import pathlib

    real_stat = pathlib.Path.stat

    def flaky_stat(self, *a, **kw):
        if self.name == "a.jsonl":
            raise OSError("vanished")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "stat", flaky_stat)
    assert find_all_transcripts() == []


def test_find_transcripts_by_session_prefix_exact_and_prefix_match(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    target = proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl"
    other = proj / "1111aaaa-0000-0000-0000-000000000000.jsonl"
    target.write_text("", encoding="utf-8")
    other.write_text("", encoding="utf-8")

    assert find_transcripts_by_session_prefix("0daf9882-076e-53aa-84a0-0db25e6d57a2") == [target]
    assert find_transcripts_by_session_prefix("0daf9882") == [target]
    assert find_transcripts_by_session_prefix("0daf") == [target]


def test_find_transcripts_by_session_prefix_ambiguous_returns_all_matches(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    a = proj / "0daf1111-0000-0000-0000-000000000000.jsonl"
    b = proj / "0daf2222-0000-0000-0000-000000000000.jsonl"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")

    matches = find_transcripts_by_session_prefix("0daf")
    assert set(matches) == {a, b}


def test_find_transcripts_by_session_prefix_no_match(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    (proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl").write_text("", encoding="utf-8")

    assert find_transcripts_by_session_prefix("zzzz") == []


def test_find_transcripts_by_session_prefix_no_projects_dir(tmp_path, monkeypatch):
    import work_ledger.transcript as transcript_mod

    monkeypatch.setattr(transcript_mod, "TRANSCRIPTS_ROOT", tmp_path / "does-not-exist")
    assert find_transcripts_by_session_prefix("anything") == []
