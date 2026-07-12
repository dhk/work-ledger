"""Local-only, rule-based recommendations - no corpus, no extra API call
beyond chaptering itself, just heuristics over the same Turn/Unit/Chapter
data everything else in this tool already computes. This is a first cut: a
small number of concrete, defensible checks, not a big speculative rule
engine. A later, corpus-relative dimension ("your bug-fix chapters cost
more than the median across users who opted into the export corpus")
isn't attempted here - see README's Recommendations section.

These checks are all cost-based. See
docs/recommend-workflow-efficiency-design.md for a proposed, not-yet-built
widening of this module to workflow-efficiency signals beyond cost - user
actions, configuration, candidate skills, and candidate tools.
"""

from dataclasses import dataclass
from statistics import median

from work_ledger.chapters import Chapter
from work_ledger.transcript import TranscriptTailer

MIN_FLAGGED_COST_USD = 0.01  # ignore noise on trivially cheap chapters/skills
OUTLIER_MULTIPLE = 2.0
SUBAGENT_SHARE_THRESHOLD = 0.5
MIN_SUBAGENT_CALLS = 2
MIN_SKILL_REPEATS = 3


@dataclass
class Recommendation:
    rule_id: str
    title: str
    detail: str
    cost_usd: float


def _chapter_cost(chapter: Chapter, tailer: TranscriptTailer) -> float:
    return sum(t.cost_usd for t in chapter.turns(tailer))


def _check_outlier_chapters(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    if len(chapters) < 3:
        return []
    costs = [_chapter_cost(c, tailer) for c in chapters]
    typical = median(costs)
    if typical <= 0:
        return []
    out = []
    for chapter, cost in zip(chapters, costs):
        if cost < MIN_FLAGGED_COST_USD:
            continue
        multiple = cost / typical
        if multiple >= OUTLIER_MULTIPLE:
            out.append(
                Recommendation(
                    rule_id="outlier-chapter-cost",
                    title=f'"{chapter.title}" cost {multiple:.1f}x this session\'s typical chapter',
                    detail=(
                        f"${cost:.4f} vs a ${typical:.4f} median across {len(chapters)} chapters - "
                        "worth a look at what drove it (chapters --detail on this one)."
                    ),
                    cost_usd=cost,
                )
            )
    return out


def _check_subagent_heavy(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    out = []
    for chapter in chapters:
        turns = chapter.turns(tailer)
        chapter_cost = sum(t.cost_usd for t in turns)
        if chapter_cost < MIN_FLAGGED_COST_USD:
            continue
        subagent_units = [u for t in turns for u in t.units if u.kind == "subagent"]
        if len(subagent_units) < MIN_SUBAGENT_CALLS:
            continue
        subagent_cost = sum(u.cost_usd for u in subagent_units)
        share = subagent_cost / chapter_cost if chapter_cost else 0.0
        if share >= SUBAGENT_SHARE_THRESHOLD:
            out.append(
                Recommendation(
                    rule_id="subagent-heavy-chapter",
                    title=(
                        f'"{chapter.title}" spent {share * 100:.0f}% of its cost on '
                        f"{len(subagent_units)} subagent calls"
                    ),
                    detail=(
                        f"${subagent_cost:.4f} of ${chapter_cost:.4f} - check whether that fan-out "
                        "was necessary or could've been done inline."
                    ),
                    cost_usd=subagent_cost,
                )
            )
    return out


def _check_repeated_skill(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    out = []
    for chapter in chapters:
        turns = chapter.turns(tailer)
        by_skill: dict[str, list] = {}
        for t in turns:
            for u in t.units:
                if u.kind == "skill" and u.skill_name:
                    by_skill.setdefault(u.skill_name, []).append(u)
        for skill_name, units in by_skill.items():
            if len(units) < MIN_SKILL_REPEATS:
                continue
            cost = sum(u.cost_usd for u in units)
            if cost < MIN_FLAGGED_COST_USD:
                continue
            out.append(
                Recommendation(
                    rule_id="repeated-skill-invocation",
                    title=f'Skill "{skill_name}" ran {len(units)} times in "{chapter.title}" (${cost:.4f})',
                    detail=(
                        "If the same steps run every time, a plain script or deterministic tool might "
                        "do this for a fraction of the cost (see issue #6)."
                    ),
                    cost_usd=cost,
                )
            )
    return out


def generate_recommendations(chapters: list[Chapter], tailer: TranscriptTailer) -> list[Recommendation]:
    recs: list[Recommendation] = []
    recs.extend(_check_outlier_chapters(chapters, tailer))
    recs.extend(_check_subagent_heavy(chapters, tailer))
    recs.extend(_check_repeated_skill(chapters, tailer))
    recs.sort(key=lambda r: r.cost_usd, reverse=True)
    return recs
