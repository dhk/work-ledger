import os
import time

from work_ledger.transcript import TranscriptTailer, find_active_transcript, find_all_transcripts

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
