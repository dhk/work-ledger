from dataclasses import dataclass

from work_ledger.chapters import (
    CATEGORIES,
    DEFAULT_CATEGORY,
    Chapter,
    Section,
    UNSORTED_TITLE,
    _ChapterOut,
    _ChaptersOut,
    _load_cache,
    _save_cache,
    _SectionOut,
    _validate_partition,
    get_chapters,
)
from work_ledger.transcript import TranscriptTailer

from .conftest import assistant_lines, user_entry, write_jsonl


def _make_turns_transcript(path, prompt_ids):
    entries = []
    for i, pid in enumerate(prompt_ids):
        entries.append(user_entry(pid, f"turn {i}", timestamp=f"2026-07-12T10:0{i}:00Z"))
        entries.extend(
            assistant_lines(
                f"msg-{i}",
                "claude-haiku-4-5",
                {"input_tokens": 10, "output_tokens": 5},
                [{"type": "text", "text": f"response {i}"}],
                timestamp=f"2026-07-12T10:0{i}:01Z",
            )
        )
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()
    return tailer


# --- _validate_partition -----------------------------------------------


def test_validate_partition_drops_unknown_prompt_ids():
    parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(
                title="A",
                category="bug-fix",
                sections=[_SectionOut(title="s1", prompt_ids=["p1", "not-a-real-id"])],
            )
        ]
    )
    cleaned = _validate_partition(parsed, expected_ids={"p1"})
    assert len(cleaned) == 1
    assert cleaned[0].sections[0].prompt_ids == ["p1"]


def test_validate_partition_drops_duplicate_prompt_id_keeps_first():
    parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(title="A", category="bug-fix", sections=[_SectionOut(title="s1", prompt_ids=["p1"])]),
            _ChapterOut(title="B", category="refactor", sections=[_SectionOut(title="s2", prompt_ids=["p1", "p2"])]),
        ]
    )
    cleaned = _validate_partition(parsed, expected_ids={"p1", "p2"})
    assert cleaned[0].sections[0].prompt_ids == ["p1"]
    assert cleaned[1].sections[0].prompt_ids == ["p2"]  # p1 already claimed by chapter A


def test_validate_partition_drops_empty_chapters():
    parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(title="Empty", category="other", sections=[_SectionOut(title="s", prompt_ids=["unknown-id"])]),
        ]
    )
    assert _validate_partition(parsed, expected_ids={"p1"}) == []


# --- cache round-trip ----------------------------------------------------


def test_cache_round_trip_preserves_category(tmp_path):
    transcript_path = tmp_path / "s.jsonl"
    chapters = [Chapter(title="Fix bug", category="bug-fix", sections=[Section(title="sec", prompt_ids=["p1"])])]
    _save_cache(transcript_path, ["p1"], chapters)

    chaptered_ids, loaded = _load_cache(transcript_path)
    assert chaptered_ids == ["p1"]
    assert loaded[0].title == "Fix bug"
    assert loaded[0].category == "bug-fix"
    assert loaded[0].sections[0].prompt_ids == ["p1"]


def test_cache_missing_category_defaults(tmp_path):
    """Cache files written before the category field existed must still
    load - defaulting to "other" rather than crashing or losing data."""
    transcript_path = tmp_path / "s.jsonl"
    cache_path = transcript_path.parent / f"{transcript_path.stem}.chapters.json"
    cache_path.write_text(
        '{"chaptered_prompt_ids": ["p1"], "chapters": '
        '[{"title": "Old chapter", "sections": [{"title": "sec", "prompt_ids": ["p1"]}]}]}',
        encoding="utf-8",
    )
    _, loaded = _load_cache(transcript_path)
    assert loaded[0].category == DEFAULT_CATEGORY


def test_load_cache_missing_file_returns_empty(tmp_path):
    assert _load_cache(tmp_path / "nope.jsonl") == ([], [])


def test_save_cache_survives_write_failure(tmp_path, monkeypatch):
    """_save_cache is documented best-effort - a write failure must not
    raise, since get_chapters already has its in-memory result to return."""
    transcript_path = tmp_path / "s.jsonl"

    def boom(*a, **kw):
        raise OSError("disk full")

    import pathlib

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    _save_cache(transcript_path, ["p1"], [Chapter(title="X", category="other", sections=[])])  # must not raise


# --- get_chapters, with the model call mocked ----------------------------


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50

    def model_dump(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass
class FakeResponse:
    parsed_output: _ChaptersOut | None
    stop_reason: str = "end_turn"
    model: str = "claude-haiku-4-5"
    usage: FakeUsage | None = None


def test_get_chapters_success_builds_chapters_and_cost(tmp_path, monkeypatch):
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1", "p2"])

    fake_parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(
                title="Build the thing",
                category="feature-build",
                sections=[_SectionOut(title="step 1", prompt_ids=["p1", "p2"])],
            )
        ]
    )
    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: FakeResponse(parsed_output=fake_parsed, usage=FakeUsage()),
    )

    result = get_chapters(tailer, transcript_path)

    assert result.fallback_reason is None
    assert len(result.chapters) == 1
    assert result.chapters[0].title == "Build the thing"
    assert result.chapters[0].category == "feature-build"
    assert result.pass_cost_usd > 0

    # Cached to disk, and category survives a fresh load.
    _, cached = _load_cache(transcript_path)
    assert cached[0].category == "feature-build"


def test_get_chapters_already_fully_cached_skips_model_call(tmp_path, monkeypatch):
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1"])
    _save_cache(
        transcript_path,
        ["p1"],
        [Chapter(title="Cached", category="other", sections=[Section(title="s", prompt_ids=["p1"])])],
    )

    def fail_if_called(*a, **kw):
        raise AssertionError("_call_model should not be called when nothing new needs chaptering")

    monkeypatch.setattr("work_ledger.chapters._call_model", fail_if_called)

    result = get_chapters(tailer, transcript_path)
    assert result.pass_cost_usd == 0.0
    assert result.chapters[0].title == "Cached"


def test_get_chapters_model_exception_falls_back_to_unsorted(tmp_path, monkeypatch):
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1"])

    def boom(outline, prior_titles):
        raise RuntimeError("network error")

    monkeypatch.setattr("work_ledger.chapters._call_model", boom)

    result = get_chapters(tailer, transcript_path)
    assert result.fallback_reason is not None
    assert result.chapters[0].title == UNSORTED_TITLE
    assert result.chapters[0].category == DEFAULT_CATEGORY
    assert result.chapters[0].prompt_ids == ["p1"]


def test_get_chapters_refusal_falls_back_to_unsorted(tmp_path, monkeypatch):
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1"])

    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: FakeResponse(parsed_output=None, stop_reason="refusal", usage=FakeUsage()),
    )

    result = get_chapters(tailer, transcript_path)
    assert "refused" in result.fallback_reason
    assert result.chapters[0].title == UNSORTED_TITLE


def test_get_chapters_malformed_shape_falls_back_to_unsorted(tmp_path, monkeypatch):
    """Regression test: a response that comes back (not an exception) but
    with parsed_output=None and a non-refusal stop_reason used to set
    fallback_reason without ever building the Unsorted chapter, silently
    dropping the affected turns from the result entirely."""
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1"])

    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: FakeResponse(parsed_output=None, stop_reason="max_tokens", usage=FakeUsage()),
    )

    result = get_chapters(tailer, transcript_path)
    assert result.fallback_reason is not None
    assert len(result.chapters) == 1
    assert result.chapters[0].title == UNSORTED_TITLE
    assert result.chapters[0].prompt_ids == ["p1"]


def test_get_chapters_missing_prompt_ids_become_unsorted(tmp_path, monkeypatch):
    """The model only covering some of the given turns must not silently
    drop the rest - leftover turns get their own Unsorted chapter."""
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1", "p2"])

    fake_parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(title="Only p1", category="bug-fix", sections=[_SectionOut(title="s", prompt_ids=["p1"])])
        ]
    )
    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: FakeResponse(parsed_output=fake_parsed, usage=FakeUsage()),
    )

    result = get_chapters(tailer, transcript_path)
    titles = [c.title for c in result.chapters]
    assert "Only p1" in titles
    assert UNSORTED_TITLE in titles
    unsorted = next(c for c in result.chapters if c.title == UNSORTED_TITLE)
    assert unsorted.prompt_ids == ["p2"]


def test_get_chapters_continuation_merges_into_last_cached_chapter(tmp_path, monkeypatch):
    transcript_path = tmp_path / "s.jsonl"
    tailer = _make_turns_transcript(transcript_path, ["p1", "p2"])
    _save_cache(
        transcript_path,
        ["p1"],
        [Chapter(title="Ongoing work", category="feature-build", sections=[Section(title="step 1", prompt_ids=["p1"])])],
    )

    fake_parsed = _ChaptersOut(
        chapters=[
            _ChapterOut(
                title="Ongoing work",  # same title as the cached chapter -> continuation, not a new one
                category="feature-build",
                sections=[_SectionOut(title="step 2", prompt_ids=["p2"])],
            )
        ]
    )
    monkeypatch.setattr(
        "work_ledger.chapters._call_model",
        lambda outline, prior_titles: FakeResponse(parsed_output=fake_parsed, usage=FakeUsage()),
    )

    result = get_chapters(tailer, transcript_path)
    assert len(result.chapters) == 1
    assert len(result.chapters[0].sections) == 2
    assert result.chapters[0].prompt_ids == ["p1", "p2"]


def test_categories_are_all_valid_pydantic_choices():
    for cat in CATEGORIES:
        _ChapterOut(title="t", category=cat, sections=[])
