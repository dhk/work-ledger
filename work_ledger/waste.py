"""Waste mining: flag recurring patterns of likely-redundant work - the
same file `Read` more than once, or the same subagent dispatched more than
once with a near-identical prompt/description - along with their combined
cost. Two halves, both issue #5:

- **Within-session** (`find_waste_patterns`) - looks at one session's own
  Turn/Unit data, exactly like activity.py. No chaptering, no
  ANTHROPIC_API_KEY, no network call of any kind. Ships independently per
  the issue's own scoping.
- **Cross-session** (`find_cross_session_waste_patterns`) - the same two
  pattern kinds, but comparing across every session belonging to the same
  recurring initiative, using #3's cross-session clustering
  (`rollup.normalize_title`) to decide what counts as "the same initiative"
  in the first place. This is why it depends on #3: without a stable
  initiative grouping, there's no principled way to say a file re-read in
  session A and a file re-read in unrelated session B are "the same
  pattern" rather than a coincidence. Only reads already-cached chapters
  (never triggers a paid chaptering pass, same invariant as rollup.py) and
  only reports a pattern once it spans 2+ distinct sessions - a repeat
  confined to one session is already fully covered by the within-session
  half above, so surfacing it again here would be a duplicate, not new
  information.

Both halves are Show-stage (see CLAUDE.md's rubric): each surfaces "this
pattern happened N times, costing $X total" and stops there. Deliberately
not prescriptive about what to do about a flagged pattern - that's issue
#6, which is explicitly blocked on this module producing real, recurring
evidence first (see ROADMAP.md's Automation theme).

Optionally, if a session already has cached chapters (never triggers a
paid chaptering pass as a side effect - see chapters.cached_chapters), a
within-session pattern's scope is reported as the chapter it fell in
rather than just "this session", which is a more actionable "where did
this happen" answer. A session with no cached chapters still gets full
within-session detection, just with a single whole-session scope label -
but contributes nothing to cross-session mining, which can only compare
sessions that are chaptered (see cross-session docstring below).
"""

from dataclasses import dataclass
from pathlib import Path

from work_ledger.chapters import Chapter, UNSORTED_TITLE, cached_chapters
from work_ledger.rollup import normalize_title
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


# --- Cross-session waste mining (the #5 half that depends on #3) ----------


@dataclass
class CrossSessionWastePattern:
    kind: str  # REPEATED_READ | REPEATED_SUBAGENT
    initiative: str  # the rollup cluster's display title - see rollup.RollupCluster
    label: str  # file path, or subagent type + description
    occurrences: int
    num_sessions: int
    cost_usd: float


def _chapter_cluster_map(transcripts: list[Path]) -> dict[Path, dict[str, str]]:
    """For each transcript, a {prompt_id: normalized_cluster_key} map built
    from its already-cached chapters only (UNSORTED_TITLE chapters and
    unresolvable/empty-after-normalization titles excluded - same
    exclusions rollup.build_rollup makes, so a prompt only ever gets a
    cluster key when rollup would also count it toward a real initiative).
    A transcript with no cached chapters maps to {} and so never
    contributes to cross-session mining - matching rollup.py's own
    "run chapters first" precedent."""
    result: dict[Path, dict[str, str]] = {}
    for path in transcripts:
        chapters = cached_chapters(path)
        prompt_to_key: dict[str, str] = {}
        for chapter in chapters or []:
            if chapter.title == UNSORTED_TITLE:
                continue
            key = normalize_title(chapter.title)
            if not key:
                continue
            for prompt_id in chapter.prompt_ids:
                prompt_to_key[prompt_id] = key
        result[path] = prompt_to_key
    return result


def _cluster_display_titles(transcripts: list[Path]) -> dict[str, str]:
    """First-seen original chapter title per normalized cluster key, across
    all transcripts - mirrors RollupCluster.display_title so the same
    initiative is named identically in `rollup` and here."""
    titles: dict[str, str] = {}
    for path in transcripts:
        for chapter in cached_chapters(path) or []:
            if chapter.title == UNSORTED_TITLE:
                continue
            key = normalize_title(chapter.title)
            if key and key not in titles:
                titles[key] = chapter.title
    return titles


def find_cross_session_waste_patterns(transcripts: list[Path]) -> list[CrossSessionWastePattern]:
    """The same two pattern kinds as `find_waste_patterns`, but scoped to a
    recurring initiative (a rollup cluster) across every session it
    touched, instead of one chapter/session. Only reads chapters already
    cached on disk - never triggers a chaptering pass (see module
    docstring) - and only reports a pattern once it spans 2+ distinct
    sessions, since a single-session repeat is already fully covered by
    `find_waste_patterns`."""
    display_titles = _cluster_display_titles(transcripts)
    cluster_maps = _chapter_cluster_map(transcripts)

    read_groups: dict[tuple[str, str], list[Unit]] = {}
    read_sessions: dict[tuple[str, str], set[str]] = {}
    subagent_groups: dict[tuple[str, str, str], list[Unit]] = {}
    subagent_sessions: dict[tuple[str, str, str], set[str]] = {}

    for path in transcripts:
        prompt_to_key = cluster_maps[path]
        if not prompt_to_key:
            continue
        tailer = TranscriptTailer(path)
        tailer.poll()

        for turn in tailer.ordered_turns():
            key = prompt_to_key.get(turn.prompt_id)
            if key is None:
                continue
            for unit in turn.units:
                for read_path in set(unit.read_paths):
                    gkey = (key, read_path)
                    read_groups.setdefault(gkey, []).append(unit)
                    read_sessions.setdefault(gkey, set()).add(path.stem)

                if unit.kind == "subagent" and unit.subagent_desc:
                    skey = (key, unit.subagent_agent_type or "", _normalize(unit.subagent_desc))
                    subagent_groups.setdefault(skey, []).append(unit)
                    subagent_sessions.setdefault(skey, set()).add(path.stem)

    patterns: list[CrossSessionWastePattern] = []

    for (key, read_path), units in read_groups.items():
        sessions = read_sessions[(key, read_path)]
        if len(sessions) < 2 or len(units) < MIN_REPEATS:
            continue
        patterns.append(
            CrossSessionWastePattern(
                kind=REPEATED_READ,
                initiative=display_titles[key],
                label=read_path,
                occurrences=len(units),
                num_sessions=len(sessions),
                cost_usd=sum(u.cost_usd for u in units),
            )
        )

    for (key, agent_type, _norm_desc), units in subagent_groups.items():
        sessions = subagent_sessions[(key, agent_type, _norm_desc)]
        if len(sessions) < 2 or len(units) < MIN_REPEATS:
            continue
        desc = units[0].subagent_desc
        label = f"{agent_type}: {desc}" if agent_type else desc
        patterns.append(
            CrossSessionWastePattern(
                kind=REPEATED_SUBAGENT,
                initiative=display_titles[key],
                label=label,
                occurrences=len(units),
                num_sessions=len(sessions),
                cost_usd=sum(u.cost_usd for u in units),
            )
        )

    patterns.sort(key=lambda p: -p.cost_usd)
    return patterns
