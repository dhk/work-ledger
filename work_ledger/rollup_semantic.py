"""Optional second clustering pass for `rollup.py`: a batched Haiku call
that proposes merges among chapter titles that `normalize_title()`'s
deterministic matching left as singletons - issue #68, see
`docs/rollup-semantic-matching-design.md` for the full design and
rationale (that doc's decisions are final; this module implements them).

## Why this exists

`rollup.py`'s v1 clustering is deterministic-only: two titles cluster
together only if they normalize to the same string. Run against real
usage, that came back almost entirely singletons - chapters describing
the same obviously-recurring work, worded differently each time (e.g.
"Execute reading-list-builder daily flow for 2026-06-23" vs. "Initialize
reading list builder daily flow"), never clustered at all. Fuzzy string
matching was evaluated and rejected (see the design doc's Investigation
section - there's no threshold that recovers those true positives
without also merging cases the existing test suite exists to keep
separate). A small Haiku pass, reusing `chapters.py`'s already-built
enforced-structured-output machinery, was chosen over embeddings for
that reason: it's not a new provider integration, just a second call
through infrastructure already proven out by `chapters.py`.

## Trigger: WORK_LEDGER_ROLLUP_MATCHING, read fresh every call

Off (`deterministic`, the default) unless explicitly opted into
(`semantic`) - mirrors `chapters.py`'s `WORK_LEDGER_CHAPTER_BACKEND`
exactly, including reading the env var fresh on every call rather than
caching it at import time, for the same reason: so changing it takes
effect without restarting anything, and so tests can monkeypatch
os.environ per-test without import-order games. No CLI flag - this is a
persistent, "fire and forget" setting by explicit design decision (see
the design doc's Architecture section), not a per-invocation choice.

## Failure handling

Mirrors `chapters.py`'s `get_chapters()` shape: any failure (no
credentials, a rejected key, a refusal, a malformed/schema-mismatched
response, any other exception) returns an empty-groups result with a
distinguishable `fallback_reason` rather than raising - `rollup.py`
folds that straight into "deterministic-only result, plus a note",
never a crash and never a silent difference between "nothing new to
merge" (empty groups, no fallback_reason) and "the pass couldn't run at
all" (empty groups, fallback_reason set).

## No caching, no versioning

Deliberately not designed here - see the design doc's Non-goals. Every
call re-proposes merges fresh from whatever's still singleton; cluster
membership can drift run to run, which is an accepted consequence of a
similarity judgment call, not a defect.
"""

import os
from dataclasses import dataclass, field

from pydantic import BaseModel

from work_ledger.chapters import CHAPTER_MODEL
from work_ledger.pricing import estimate_cost_usd

ROLLUP_MATCHING_ENV_VAR = "WORK_LEDGER_ROLLUP_MATCHING"
DETERMINISTIC_MATCHING = "deterministic"
SEMANTIC_MATCHING = "semantic"

# Same wording shape as chapters.NO_CREDENTIALS_MESSAGE, adapted for this
# pass - factored out so it's asserted against by name in tests rather than
# re-typed, same reasoning chapters.py gives for its own constant.
NO_CREDENTIALS_MESSAGE = (
    "No ANTHROPIC_API_KEY found in this environment; semantic matching skipped, "
    "falling back to deterministic-only clustering. Set ANTHROPIC_API_KEY, or run "
    "`ant auth login` if you have the Anthropic CLI."
)

# A batch of short titles - generous but bounded, same non-streaming-HTTP-
# timeout reasoning chapters.py's MAX_TOKENS documents. No batch-size
# chunking (see the design doc's Open Questions #2): one call regardless of
# how many singleton titles there are, untested at very large counts.
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are given a numbered list of initiative titles, each summarizing a \
distinct coding-session chapter (an initiative or task, e.g. "Build the v1 dashboard", \
not a single turn/prompt). Every title in the list currently failed to match any other \
title by exact/normalized-string comparison, but some of them may still describe the \
same recurring initiative in different words (different verbs, an embedded date or \
version number, a reworded description).

Your job: group titles that describe the SAME recurring initiative, even if reworded.

Rules:
- Only return a group when 2 or more titles genuinely describe the same recurring work.
- Titles describing genuinely different work must NOT be grouped, even if they share \
words or structure (e.g. "Fix the login bug" and "Fix the checkout bug" are different \
initiatives; "Build the v1 dashboard" and "Build the v2 dashboard" are different \
initiatives).
- A title with no genuine match should simply not appear in any group - that is not an \
error, most titles will have no match.
- Only use the exact title strings you were given. Do not invent, paraphrase, \
abbreviate, or correct a title - copy it verbatim into a group.
- A title must appear in at most one group."""


class _MergeGroup(BaseModel):
    titles: list[str]


class _MergesOut(BaseModel):
    groups: list[_MergeGroup]


@dataclass
class SemanticMergeResult:
    """What `propose_merges` returns. `groups` is always a list of
    validated, 2+-title groups drawn only from the input batch (see
    `_validate_groups`) - empty when nothing merged, whether that's
    because the model found nothing to merge or because the call failed
    outright; `fallback_reason` is the only thing that distinguishes
    those two cases (None for the former, set for the latter)."""

    groups: list[list[str]] = field(default_factory=list)
    fallback_reason: str | None = None
    cost_usd: float = 0.0


def matching_mode() -> str:
    """The configured mode, read fresh from the environment every call -
    see module docstring for why this isn't cached at import time."""
    return os.environ.get(ROLLUP_MATCHING_ENV_VAR, DETERMINISTIC_MATCHING).strip().lower()


def is_semantic_enabled() -> bool:
    return matching_mode() == SEMANTIC_MATCHING


def _build_prompt(titles: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return (
        f"Here are {len(titles)} initiative titles that didn't match anything else via "
        f"exact/normalized-string comparison:\n\n{numbered}\n\n"
        "Group any that describe the same recurring initiative, per the rules above."
    )


def _validate_groups(parsed: _MergesOut, input_titles: list[str]) -> list[list[str]]:
    """Drop any title the model wasn't actually given (it must not invent
    titles), and drop a title from a later group if it already appeared in
    an earlier one (a title can only belong to one merge) - the same
    "never trust the model's output blindly" discipline
    `chapters._validate_partition` applies to prompt_ids, applied here to
    titles. A group that has fewer than 2 valid titles left after that is
    dropped entirely - a merge needs at least two things to merge."""
    allowed = set(input_titles)
    seen: set[str] = set()
    cleaned: list[list[str]] = []
    for group in parsed.groups:
        kept = []
        for title in group.titles:
            if title not in allowed or title in seen:
                continue
            seen.add(title)
            kept.append(title)
        if len(kept) >= 2:
            cleaned.append(kept)
    return cleaned


def propose_merges(titles: list[str]) -> SemanticMergeResult:
    """Batch ALL of `titles` into one structured-output Haiku call
    proposing merges among them - never one call per title (see module
    docstring). Any failure mode (no credentials, a rejected key, a
    refusal, a malformed response, any other exception) falls back
    silently to an empty-groups result with a distinguishable
    `fallback_reason`, mirroring `chapters.get_chapters`'s exception
    handling shape - never raises."""
    if len(titles) < 2:
        return SemanticMergeResult(groups=[])

    try:
        import anthropic  # imported lazily - only needed when semantic matching actually runs
    except ImportError as e:
        # issue #99: a broken/incomplete environment (missing or
        # mismatched anthropic install) must degrade the same as every
        # other failure mode this function already handles, not crash
        # before ever reaching the try/except below - which can't even
        # be entered if the import itself is what failed, since its
        # except clauses reference `anthropic.AuthenticationError` etc.
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                f"the `anthropic` package failed to import ({e}); semantic matching skipped, "
                "falling back to deterministic-only clustering"
            ),
        )

    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=CHAPTER_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(titles)}],
            output_format=_MergesOut,
        )
    except anthropic.AuthenticationError as e:
        # A real 401 - a key was sent and rejected, distinct from no key
        # being present at all (the TypeError branch below) - same
        # distinction chapters.get_chapters draws.
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                f"ANTHROPIC_API_KEY was rejected by the server ({e}); semantic matching "
                "skipped, falling back to deterministic-only clustering. Check the key is "
                "still valid at console.anthropic.com."
            ),
        )
    except TypeError as e:
        # The SDK raises a plain TypeError, not an AnthropicError subclass,
        # when it can't find any credential at all - verified against the
        # installed anthropic SDK, same as chapters.get_chapters.
        if "Could not resolve authentication method" in str(e):
            return SemanticMergeResult(groups=[], fallback_reason=NO_CREDENTIALS_MESSAGE)
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                f"semantic matching call failed ({e}); falling back to deterministic-only "
                "clustering"
            ),
        )
    except Exception as e:  # noqa: BLE001 - any other failure here falls back, never crashes
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                f"semantic matching call failed ({e}); falling back to deterministic-only "
                "clustering"
            ),
        )

    cost = 0.0
    if response.usage:
        c = estimate_cost_usd(response.model, response.usage.model_dump())
        cost = c if c is not None else 0.0

    if response.stop_reason == "refusal":
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                "semantic matching call was refused; falling back to deterministic-only "
                "clustering"
            ),
            cost_usd=cost,
        )
    if response.parsed_output is None:
        return SemanticMergeResult(
            groups=[],
            fallback_reason=(
                "semantic matching response didn't match the expected shape "
                f"(stop_reason={response.stop_reason!r}); falling back to "
                "deterministic-only clustering"
            ),
            cost_usd=cost,
        )

    groups = _validate_groups(response.parsed_output, titles)
    return SemanticMergeResult(groups=groups, cost_usd=cost)
