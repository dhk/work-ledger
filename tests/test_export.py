from work_ledger.chapters import Chapter, ChapterResult, Section
from work_ledger.export import CATEGORIES, build_export_payload

from .conftest import assistant_lines, user_entry, write_jsonl


def _make_session(proj_dir, name, prompt_ids):
    entries = []
    for i, pid in enumerate(prompt_ids):
        entries.append(user_entry(pid, f"turn {i}"))
        entries.extend(
            assistant_lines(f"{name}-msg-{i}", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 50}, [{"type": "text", "text": "x"}])
        )
    write_jsonl(proj_dir / f"{name}.jsonl", entries)


def test_export_payload_shape_and_no_identifying_content(isolated_transcripts_root, monkeypatch):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _make_session(proj, "session-1", ["p1", "p2"])

    fake_chapters = [
        Chapter(title="Secret project name", category="feature-build", sections=[Section(title="s", prompt_ids=["p1"])]),
        Chapter(title="Fix the thing", category="bug-fix", sections=[Section(title="s", prompt_ids=["p2"])]),
    ]
    monkeypatch.setattr(
        "work_ledger.export.get_chapters",
        lambda tailer, path: ChapterResult(chapters=fake_chapters, pass_cost_usd=0.001),
    )

    result = build_export_payload()

    assert result.num_sessions == 1
    payload = result.payload
    assert payload["schema_version"] == 1
    assert payload["totals"]["sessions"] == 1
    assert payload["totals"]["chapters"] == 2
    assert payload["totals"]["input_tokens"] == 200
    assert payload["totals"]["output_tokens"] == 100

    # Every known category present, even at zero - stable shape across runs.
    assert set(payload["by_category"].keys()) == set(CATEGORIES)
    assert payload["by_category"]["feature-build"]["chapters"] == 1
    assert payload["by_category"]["bug-fix"]["chapters"] == 1
    assert payload["by_category"]["refactor"]["chapters"] == 0

    # The whole point: no chapter titles, transcript paths, or session ids.
    dumped = str(payload)
    assert "Secret project name" not in dumped
    assert "Fix the thing" not in dumped
    assert "session-1" not in dumped


def test_export_clamps_unrecognized_category_into_other(isolated_transcripts_root, monkeypatch):
    """Regression test: a category value outside the known taxonomy (e.g.
    from a stale/hand-edited cache) must not silently create a new bucket
    in by_category, which would break the payload's fixed-shape guarantee."""
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _make_session(proj, "session-1", ["p1"])

    weird_chapter = Chapter(title="Weird", category="not-a-real-category", sections=[Section(title="s", prompt_ids=["p1"])])
    monkeypatch.setattr(
        "work_ledger.export.get_chapters",
        lambda tailer, path: ChapterResult(chapters=[weird_chapter], pass_cost_usd=0.0),
    )

    payload = build_export_payload().payload
    assert set(payload["by_category"].keys()) == set(CATEGORIES)
    assert payload["by_category"]["other"]["chapters"] == 1


def test_export_no_sessions_found(isolated_transcripts_root):
    result = build_export_payload()
    assert result.num_sessions == 0
    assert result.payload["totals"]["sessions"] == 0


def test_export_date_range_filters_sessions(isolated_transcripts_root, monkeypatch):
    import datetime
    import os
    import time

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _make_session(proj, "old", ["p1"])
    _make_session(proj, "new", ["p2"])

    old_time = time.time() - 20 * 86400
    os.utime(proj / "old.jsonl", (old_time, old_time))

    monkeypatch.setattr(
        "work_ledger.export.get_chapters",
        lambda tailer, path: ChapterResult(
            chapters=[Chapter(title="c", category="other", sections=[Section(title="s", prompt_ids=[t.prompt_id for t in tailer.ordered_turns()])])],
            pass_cost_usd=0.0,
        ),
    )

    since = (datetime.datetime.now() - datetime.timedelta(days=5)).date()
    result = build_export_payload(since=since)
    assert result.num_sessions == 1  # only "new" is within the last 5 days
