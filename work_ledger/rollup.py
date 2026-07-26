"""Cross-session rollup: cluster the same recurring initiative's chapters
across every session it touched, and report total cost per cluster -
issue #3.

`chapters --all` (added in #2) already lists every session side-by-side
with its own chapters, but each session's chapters stay siloed there -
there's no way to answer "how much has 'Fix the double-counting bug'
cost in total" without manually adding up matching rows yourself. This
module answers exactly that, by clustering chapter titles that recur
(exactly or near-exactly) across sessions and summing cost per cluster.

Deliberately only reads whatever chapters are already cached
(chapters.cached_chapters) - never a new Haiku pass, same invariant
timeline.py/waste.py already rely on (a Show-stage command must never
have a surprise API cost - see CLAUDE.md). A session with no cached
chapters at all just contributes nothing to any cluster; run `chapters`
(or `chapters --all`) on it first to have it reflected here - this
module never re-chapters or forces a chaptering pass itself, per issue
#3's acceptance criteria.

## Matching mechanism: deterministic title normalization, not LLM/embeddings

The issue leaves the clustering mechanism as an open, undesigned question
between "another small LLM pass" and "embedding similarity." v1 uses
neither: chapter titles are normalized (lowercased, punctuation/
whitespace collapsed, a short stopword list stripped, a light
plural-only stem) and clustered by exact match on the normalized string.
This is the same call waste.py's `_normalize` made for issue #5's
near-identical subagent-prompt matching: avoid a second paid API surface
(beyond chaptering's own Haiku pass) before simple matching is actually
proven too weak. See test_rollup.py for the false-positive/false-negative
tradeoffs found validating this against realistic titles - genuinely
reworded titles ("Fix the double-counting bug" vs "resolve the cost
overcount issue") won't match, which is an accepted false-negative
tradeoff for staying local/free/deterministic (same tradeoff waste.py's
docstring already accepts for its own normalization). If that turns out
to hide real recurring cost in practice, that's the signal a v2 (LLM or
embedding clustering) is worth designing - not something to build
speculatively ahead of that evidence.

`chapters.UNSORTED_TITLE` chapters (the fallback chapters.py uses when a
chaptering pass failed/had no credentials) are deliberately excluded
from clustering: "Unsorted" isn't a real initiative, and matching two
sessions' unrelated fallback chapters together under one cluster would
be a pure false positive - the title collision is an artifact of the
fallback, not a recurring initiative.

## Why a separate `rollup` command, not `chapters --rollup`

The issue's own suggested shape was `chapters --rollup`, but `chapters`
already juggles --all/--detail/--only/--report/--since/--until with a
fair amount of mutual-exclusion logic in cli.py, and a rollup is
*inherently* a cross-session view - there's no single-session meaning
for it the way --detail/--only have one. Modeled instead on `trend`/
`waste`: its own top-level subcommand, reusing the same
find_all_transcripts() + --since/--until sweep `chapters --all`/`trend`/
`timeline` all already use, rather than another flag branch on an
already-branchy command.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from work_ledger.chapters import UNSORTED_TITLE, cached_chapters
from work_ledger.transcript import TranscriptTailer

# Small, closed list - stripped so trivial phrasing differences ("Fix the
# bug" vs "Fix bug") don't hide a real match. Deliberately short: a longer
# list risks stripping a word that's actually load-bearing for some
# initiative's meaning - over-normalizing (and over-merging unrelated
# titles as a result) is the failure mode this module cares about most,
# per issue #3's own "without over-merging unrelated titles" framing.
_STOPWORDS = frozenset({"a", "an", "the", "of", "for", "to", "in", "on", "and", "with"})

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _stem(word: str) -> str:
    """Bare-minimum plural stripping ("bugs" -> "bug") - not a real
    stemmer. No -ing/-ed handling: those are riskier (e.g. "used" -> "us"
    would be a real, wrong word collision), so left alone. Skips short
    words and words already ending in a double-s (e.g. "process") where
    stripping one trailing s would change the word's meaning rather than
    just depluralizing it."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize_title(title: str) -> str:
    """Lowercase, collapse punctuation/whitespace to single spaces, drop a
    short stopword list, and lightly stem each remaining word - two
    titles that reduce to the same string are treated as the same
    initiative. Word order is preserved (this is not a sorted bag-of-
    words match): that's deliberate, to catch reworded-but-same-structure
    titles without also catching two unrelated titles that merely happen
    to share the same words in a different order."""
    text = _PUNCT_RE.sub(" ", title.lower()).strip()
    words = [_stem(w) for w in text.split() if w not in _STOPWORDS]
    return " ".join(words)


@dataclass
class RollupCluster:
    normalized_key: str
    display_title: str  # the first-seen original chapter title, across all matched sessions
    sessions: list[str] = field(default_factory=list)  # transcript stems, first-seen order, deduped
    num_chapters: int = 0
    cost_usd: float = 0.0
    unknown_model_cost: bool = False

    @property
    def num_sessions(self) -> int:
        return len(self.sessions)


def build_rollup(transcripts: list[Path]) -> list[RollupCluster]:
    """Cluster every already-cached chapter across `transcripts` by
    normalized title, and sum cost per cluster - most expensive first.
    Never triggers a chaptering pass (see module docstring); callers pick
    the transcript list the same way chapters --all/trend/timeline
    already do (find_all_transcripts() + a date-range mtime filter)."""
    clusters: dict[str, RollupCluster] = {}

    for path in transcripts:
        chapters = cached_chapters(path)
        if not chapters:
            continue
        tailer = TranscriptTailer(path)
        tailer.poll()

        for chapter in chapters:
            if chapter.title == UNSORTED_TITLE:
                continue
            key = normalize_title(chapter.title)
            if not key:
                continue
            turns = chapter.turns(tailer)

            cluster = clusters.get(key)
            if cluster is None:
                cluster = RollupCluster(normalized_key=key, display_title=chapter.title)
                clusters[key] = cluster

            cluster.num_chapters += 1
            cluster.cost_usd += sum(t.cost_usd for t in turns)
            if any(t.unknown_model_cost for t in turns):
                cluster.unknown_model_cost = True
            if path.stem not in cluster.sessions:
                cluster.sessions.append(path.stem)

    return sorted(clusters.values(), key=lambda c: -c.cost_usd)
