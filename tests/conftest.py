"""Shared fixtures for building synthetic Claude Code transcripts on disk,
matching the real ~/.claude/projects/<project>/<session>.jsonl format that
transcript.py parses (see that module's docstring for the format notes this
mirrors: one JSONL line per content block, usage repeated per line for the
same message.id, subagents in a sibling `<session>/subagents/` directory).

No test in this suite touches the real ~/.claude/projects or
~/.config/work-ledger directories - anything that reads them is pointed at
a tmp_path fixture instead.
"""

import json

import pytest


def user_entry(prompt_id: str, text: str, timestamp: str = "2026-07-12T10:00:00Z") -> dict:
    return {
        "type": "user",
        "promptId": prompt_id,
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


def assistant_lines(
    message_id: str,
    model: str,
    usage: dict,
    blocks: list[dict],
    timestamp: str = "2026-07-12T10:00:01Z",
) -> list[dict]:
    """Real transcripts write one JSONL line per content block, repeating
    `usage` verbatim on every line for the same message.id - this is the
    behavior that caused the original double-counting bug, and every line
    this helper emits deliberately repeats `usage` the same way."""
    return [
        {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {"id": message_id, "model": model, "usage": usage, "content": [block]},
        }
        for block in blocks
    ]


def write_jsonl(path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


@pytest.fixture
def transcript_path(tmp_path):
    return tmp_path / "session-a.jsonl"


@pytest.fixture
def isolated_transcripts_root(tmp_path, monkeypatch):
    """Point find_active_transcript()/find_all_transcripts() at an empty
    tmp directory instead of the real ~/.claude/projects, so tests never
    read or depend on whatever real sessions happen to exist on the
    machine running them."""
    import work_ledger.transcript as transcript_mod

    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(transcript_mod, "TRANSCRIPTS_ROOT", root)
    return root


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    """Point limits.py's threshold file at a tmp path instead of the real
    ~/.config/work-ledger/limits_threshold.json."""
    import work_ledger.limits as limits_mod

    config_dir = tmp_path / "config"
    monkeypatch.setattr(limits_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(limits_mod, "THRESHOLD_PATH", config_dir / "limits_threshold.json")
    return config_dir
