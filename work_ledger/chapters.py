"""Group a session's Turns into semantically-labeled Chapters/Sections
(initiatives), on top of the deterministic Turn/Unit telemetry in
transcript.py. See docs/session-chaptering-design.md for the full design
and rationale - this module implements that design.

This is a separate, offline/batch annotation layer: it never changes how
transcript.py parses or how the live dashboard counts cost. The only thing
this module adds is a grouping label; cost/token rollups for a Chapter or
Section are always a plain sum over the Turn objects it references (via
`.turns(tailer)`), never separately stored or invented.

Results are cached to disk next to the transcript and the cached prefix is
frozen: re-running chaptering on a session that has grown new turns only
sends the new turns to the model and never revises/retitles a chapter
that's already cached (see the design doc's "Decided: caching, frozen
prefix").
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from work_ledger.pricing import estimate_cost_usd
from work_ledger.transcript import TranscriptTailer, Turn

CHAPTER_MODEL = "claude-haiku-4-5"
# 16000 is the safe non-streaming ceiling for this API (higher risks HTTP
# timeouts without switching to streaming). Output scales with turn count
# (every prompt_id must be enumerated at least once), so a very long
# retroactively-chaptered session can still hit this - it falls back to
# "Unsorted" for whatever's left over rather than crashing (see
# get_chapters), but the result is worse than a shorter session's.
MAX_TOKENS = 16000
UNSORTED_TITLE = "Unsorted"

# Fixed, closed taxonomy - not free text. This is what lets `export` report
# category rollups without ever transmitting a chapter's actual title (which
# can describe real project/business specifics). Keep this list short and
# stable: it becomes part of the on-disk cache schema and, later, the corpus
# schema (see docs/session-chaptering-design.md and README's Export section).
CATEGORIES: tuple[str, ...] = (
    "feature-build",
    "bug-fix",
    "refactor",
    "design-planning",
    "debugging",
    "docs",
    "review-feedback",
    "tooling-infra",
    "other",
)
DEFAULT_CATEGORY = "other"

SYSTEM_PROMPT = """You group a coding session's prompts into a small number of \
"chapters" (distinct initiatives, e.g. "Build the v1 dashboard", "Fix the \
double-counting bug") each split into "sections" (a step within that \
initiative). You are given a numbered list of turns, each showing the \
prompt_id, timestamp, a short snippet of what the user asked, and short \
labels for what the assistant did in that turn.

Rules:
- Every prompt_id you were given must appear in exactly one section of one \
chapter. Do not invent prompt_ids, and do not assign the same prompt_id to \
more than one section.
- Titles should be short, concrete, and describe the initiative/step, not \
restate the raw prompt text.
- Prefer fewer, larger chapters over many tiny ones, unless the turns are \
genuinely doing unrelated things.
- Each chapter also gets a `category`, chosen from a fixed list (feature-build, \
bug-fix, refactor, design-planning, debugging, docs, review-feedback, \
tooling-infra, other) - pick the closest match, or "other" if none fit.
- If you are told that earlier turns were already grouped into prior \
chapters, only assign chapters/sections to the NEW turns you were given - \
never re-list an earlier turn's prompt_id."""


class _SectionOut(BaseModel):
    title: str
    prompt_ids: list[str]


class _ChapterOut(BaseModel):
    title: str
    category: Literal[CATEGORIES]
    sections: list[_SectionOut]


class _ChaptersOut(BaseModel):
    chapters: list[_ChapterOut]


@dataclass
class Section:
    title: str
    prompt_ids: list[str] = field(default_factory=list)

    def turns(self, tailer: TranscriptTailer) -> list[Turn]:
        wanted = set(self.prompt_ids)
        return [t for t in tailer.ordered_turns() if t.prompt_id in wanted]


@dataclass
class Chapter:
    title: str
    sections: list[Section] = field(default_factory=list)
    category: str = DEFAULT_CATEGORY

    @property
    def prompt_ids(self) -> list[str]:
        return [pid for s in self.sections for pid in s.prompt_ids]

    def turns(self, tailer: TranscriptTailer) -> list[Turn]:
        wanted = set(self.prompt_ids)
        return [t for t in tailer.ordered_turns() if t.prompt_id in wanted]


@dataclass
class ChapterResult:
    chapters: list[Chapter]
    pass_cost_usd: float
    fallback_reason: str | None = None


def _cache_path(transcript_path: Path) -> Path:
    return transcript_path.parent / f"{transcript_path.stem}.chapters.json"


def _load_cache(transcript_path: Path) -> tuple[list[str], list[Chapter]]:
    path = _cache_path(transcript_path)
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []
    chaptered_ids = list(data.get("chaptered_prompt_ids", []))
    chapters = [
        Chapter(
            title=c["title"],
            sections=[
                Section(title=s["title"], prompt_ids=list(s["prompt_ids"]))
                for s in c.get("sections", [])
            ],
            # Older cache files predate the category field - default rather
            # than re-chaptering (the frozen-prefix contract still holds).
            category=c.get("category", DEFAULT_CATEGORY),
        )
        for c in data.get("chapters", [])
    ]
    return chaptered_ids, chapters


def _save_cache(transcript_path: Path, chaptered_ids: list[str], chapters: list[Chapter]) -> None:
    """Best-effort - a write failure (read-only dir, permissions, full disk)
    just means the next run re-chapters these turns instead of using the
    cache. It must not crash `chapters`, which already has its in-memory
    result to return regardless of whether it gets persisted."""
    data = {
        "chaptered_prompt_ids": chaptered_ids,
        "chapters": [
            {
                "title": c.title,
                "category": c.category,
                "sections": [{"title": s.title, "prompt_ids": s.prompt_ids} for s in c.sections],
            }
            for c in chapters
        ],
    }
    try:
        _cache_path(transcript_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _build_outline(turns: list[Turn]) -> str:
    lines = []
    for turn in turns:
        time_str = turn.timestamp[11:19] if len(turn.timestamp) >= 19 else turn.timestamp
        unit_labels = ", ".join(u.label for u in turn.units) or "(no units)"
        lines.append(f'[{turn.prompt_id}] ({time_str}) "{turn.prompt_snippet}"')
        lines.append(f"    units: {unit_labels}")
    return "\n".join(lines)


def _call_model(outline: str, prior_chapter_titles: list[str]):
    import anthropic  # imported lazily - only needed for `chapters`, not the live dashboard

    client = anthropic.Anthropic()
    context = ""
    if prior_chapter_titles:
        titled = "; ".join(prior_chapter_titles)
        context = (
            f"Turns before this point were already grouped into these chapters "
            f"(in order): {titled}. Only assign chapters/sections for the NEW "
            f"turns below - do not re-list any earlier turn.\n\n"
        )
    return client.messages.parse(
        model=CHAPTER_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context + outline}],
        output_format=_ChaptersOut,
    )


def _validate_partition(parsed: _ChaptersOut, expected_ids: set[str]) -> list[_ChapterOut]:
    """Drop prompt_ids the model wasn't given or already assigned elsewhere.
    Does not add an Unsorted chapter for missing ids - the caller does that
    once, after seeing what's left over from all chapters combined."""
    seen: set[str] = set()
    cleaned_chapters = []
    for chapter in parsed.chapters:
        cleaned_sections = []
        for section in chapter.sections:
            kept = []
            for pid in section.prompt_ids:
                if pid not in expected_ids or pid in seen:
                    continue
                seen.add(pid)
                kept.append(pid)
            if kept:
                cleaned_sections.append(_SectionOut(title=section.title, prompt_ids=kept))
        if cleaned_sections:
            cleaned_chapters.append(
                _ChapterOut(title=chapter.title, category=chapter.category, sections=cleaned_sections)
            )
    return cleaned_chapters


def get_chapters(tailer: TranscriptTailer, transcript_path: Path) -> ChapterResult:
    """Return the chaptering for this transcript, calling the model only for
    turns not already in the cache. Cached chapters/sections are frozen -
    never revised or retitled once written (see module docstring)."""
    chaptered_ids, chapters = _load_cache(transcript_path)
    chaptered_id_set = set(chaptered_ids)

    all_turns = tailer.ordered_turns()
    new_turns = [t for t in all_turns if t.prompt_id not in chaptered_id_set]

    if not new_turns:
        return ChapterResult(chapters=chapters, pass_cost_usd=0.0)

    outline = _build_outline(new_turns)
    prior_titles = [c.title for c in chapters]
    new_ids = {t.prompt_id for t in new_turns}

    cost = 0.0
    fallback_reason = None
    new_chapter_dicts: list[_ChapterOut] = []

    try:
        response = _call_model(outline, prior_titles)
    except Exception as e:  # noqa: BLE001 - any failure here falls back, never crashes
        fallback_reason = f"chaptering call failed ({e}); new turns grouped as Unsorted"
        response = None

    if response is not None:
        if response.usage:
            c = estimate_cost_usd(response.model, response.usage.model_dump())
            cost = c if c is not None else 0.0
        parsed = response.parsed_output
        if response.stop_reason == "refusal":
            fallback_reason = "chaptering call was refused; new turns grouped as Unsorted"
        elif parsed is None:
            fallback_reason = (
                "chaptering response didn't match the expected shape "
                f"(stop_reason={response.stop_reason!r}); new turns grouped as Unsorted"
            )
        else:
            new_chapter_dicts = _validate_partition(parsed, new_ids)
            covered = {pid for c in new_chapter_dicts for s in c.sections for pid in s.prompt_ids}
            missing = [t.prompt_id for t in new_turns if t.prompt_id not in covered]
            if missing:
                new_chapter_dicts.append(
                    _ChapterOut(
                        title=UNSORTED_TITLE,
                        category=DEFAULT_CATEGORY,
                        sections=[_SectionOut(title=UNSORTED_TITLE, prompt_ids=missing)],
                    )
                )

    if response is None:
        new_chapter_dicts = [
            _ChapterOut(
                title=UNSORTED_TITLE,
                category=DEFAULT_CATEGORY,
                sections=[_SectionOut(title=UNSORTED_TITLE, prompt_ids=[t.prompt_id for t in new_turns])],
            )
        ]

    new_chapters = [
        Chapter(
            title=c.title,
            sections=[Section(title=s.title, prompt_ids=s.prompt_ids) for s in c.sections],
            category=c.category,
        )
        for c in new_chapter_dicts
    ]

    # Merge: if both the last cached chapter and the first new chapter share
    # a title, treat the new one as a continuation (append its sections)
    # rather than a separate chapter with a duplicate name.
    merged_chapters = list(chapters)
    for new_chapter in new_chapters:
        if merged_chapters and merged_chapters[-1].title == new_chapter.title:
            merged_chapters[-1].sections.extend(new_chapter.sections)
        else:
            merged_chapters.append(new_chapter)

    all_chaptered_ids = chaptered_ids + [t.prompt_id for t in new_turns]
    _save_cache(transcript_path, all_chaptered_ids, merged_chapters)

    return ChapterResult(chapters=merged_chapters, pass_cost_usd=cost, fallback_reason=fallback_reason)
