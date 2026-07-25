"""Within-session waste mining: flag recurring patterns of likely-redundant
work inside a single session - the same file `Read` more than once, or the
same subagent dispatched more than once with a near-identical prompt/
description - along with their combined cost.

This is a Show-stage feature (see CLAUDE.md's rubric): it surfaces "this
pattern happened N times, costing $X total" and stops there. It is
deliberately not prescriptive about what to do about a flagged pattern -
that's issue #6, which is explicitly blocked on this module producing real,
recurring evidence first (see ROADMAP.md's Automation theme).

Cross-session correlation - comparing "the same pattern" across separate
sessions - depends on #3's cross-session clustering and isn't attempted
here; see issue #5's own scoping ("within-session mining ... could ship
independently"). Everything below only ever looks within one session's own
Turn/Unit data, exactly like activity.py - no chaptering, no
ANTHROPIC_API_KEY, no network call of any kind.

Optionally, if this session already has cached chapters (never triggers a
paid chaptering pass as a side effect - see chapters.cached_chapters), a
pattern's scope is reported as the chapter it fell in rather than just
"this session", which is a more actionable "where did this happen" answer.
A session with no cached chapters still gets full detection, just with a
single whole-session scope label.
"""

from dataclasses import dataclass

from work_ledger.chapters import Chapter
from work_ledger.transcript import TranscriptTailer, Unit

# "More than once" - two occurrences is already a repeat worth surfacing;
# this isn't a noise-reduction knob like recommend.py's MIN_SKILL_REPEATS; a
# single re-read/re-dispatch is exactly the shape of waste this module
# exists to catch, so the threshold stays at the lowest meaningful value.
MIN_REPEATS = 2

UNCHAPTERED_SCOPE = "(whole session - not yet chaptered)"

REPEATED_READ = "repeated-read"
REPEATED_SUBAGENT = "repeated-subagent"


@dataclass
class WastePattern:
    kind: str  # REPEATED_READ | REPEATED_SUBAGENT
    scope: str  # chapter title, or UNCHAPTERED_SCOPE
    label: str  # file path, or subagent type + description
    occurrences: int
    cost_usd: float


def _normalize(text: str) -> str:
    """Collapse whitespace and case so trivial formatting differences
    (trailing punctuation, extra spaces, capitalization) don't hide a
    same-prompt repeat. Deliberately not fuzzier than this - no
    embedding/LLM call, per issue #5's "no new paid dependency" guidance;
    genuinely-reworded-but-same-intent prompts won't match, which is an
    accepted false-negative tradeoff for staying local/free/deterministic."""
    return " ".join(text.split()).strip().lower()


def _prompt_id_to_chapter_title(chapters: list[Chapter]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for chapter in chapters:
        for prompt_id in chapter.prompt_ids:
            mapping[prompt_id] = chapter.title
    return mapping


def find_repeated_reads(
    tailer: TranscriptTailer, chapters: list[Chapter] | None = None
) -> list[WastePattern]:
    """Same file path Read by more than one Unit within the same scope
    (chapter if cached, else the whole session). A single Unit that reads
    the same path more than once in one message is deduped to one
    occurrence for that Unit - repeats are counted per LLM call, matching
    how every other cost figure in this codebase is Unit-scoped, not per
    raw tool_use block."""
    prompt_to_scope = _prompt_id_to_chapter_title(chapters) if chapters else {}
    groups: dict[tuple[str, str], list[Unit]] = {}

    for turn in tailer.ordered_turns():
        scope = prompt_to_scope.get(turn.prompt_id, UNCHAPTERED_SCOPE)
        for unit in turn.units:
            for path in set(unit.read_paths):
                groups.setdefault((scope, path), []).append(unit)

    patterns = []
    for (scope, path), units in groups.items():
        if len(units) < MIN_REPEATS:
            continue
        patterns.append(
            WastePattern(
                kind=REPEATED_READ,
                scope=scope,
                label=path,
                occurrences=len(units),
                cost_usd=sum(u.cost_usd for u in units),
            )
        )
    return patterns


def find_repeated_subagents(
    tailer: TranscriptTailer, chapters: list[Chapter] | None = None
) -> list[WastePattern]:
    """Same subagent (agent type) dispatched more than once with a
    near-identical description within the same scope. "Near-identical"
    is normalized-exact string equality on subagent_desc (see
    _normalize) - simple and deterministic, not a semantic match."""
    prompt_to_scope = _prompt_id_to_chapter_title(chapters) if chapters else {}
    groups: dict[tuple[str, str, str], list[Unit]] = {}

    for turn in tailer.ordered_turns():
        scope = prompt_to_scope.get(turn.prompt_id, UNCHAPTERED_SCOPE)
        for unit in turn.units:
            if unit.kind != "subagent" or not unit.subagent_desc:
                continue
            key = (scope, unit.subagent_agent_type or "", _normalize(unit.subagent_desc))
            groups.setdefault(key, []).append(unit)

    patterns = []
    for (scope, agent_type, _norm_desc), units in groups.items():
        if len(units) < MIN_REPEATS:
            continue
        desc = units[0].subagent_desc
        label = f"{agent_type}: {desc}" if agent_type else desc
        patterns.append(
            WastePattern(
                kind=REPEATED_SUBAGENT,
                scope=scope,
                label=label,
                occurrences=len(units),
                cost_usd=sum(u.cost_usd for u in units),
            )
        )
    return patterns


def find_waste_patterns(
    tailer: TranscriptTailer, chapters: list[Chapter] | None = None
) -> list[WastePattern]:
    """Every detected pattern, most expensive first. `chapters` is optional
    and, if given, expected to already be cached (see module docstring) -
    passing freshly-fetched, uncached chapters would silently make this
    module the reason a paid chaptering pass ran, which is not this
    Show-stage feature's job."""
    patterns = find_repeated_reads(tailer, chapters) + find_repeated_subagents(tailer, chapters)
    patterns.sort(key=lambda p: -p.cost_usd)
    return patterns
