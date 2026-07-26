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
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from work_ledger.pricing import estimate_cost_usd
from work_ledger.transcript import TranscriptTailer, Turn

CHAPTER_MODEL = "claude-haiku-4-5"
# The exact wording get_chapters uses when no credential can be found at
# all - factored out so check_credentials() (used by `miso --check-status`
# and `miso`'s own up-front status notice) reports the identical fact in
# the identical words, rather than drifting into a second phrasing of the
# same thing over time.
NO_CREDENTIALS_MESSAGE = (
    "No ANTHROPIC_API_KEY found in this environment; new turns grouped as "
    "Unsorted. Set ANTHROPIC_API_KEY, or run `ant auth login` if you have the "
    "Anthropic CLI."
)
# 16000 is the safe non-streaming ceiling for this API (higher risks HTTP
# timeouts without switching to streaming). Output scales with turn count
# (every prompt_id must be enumerated at least once), so a very long
# retroactively-chaptered session can still hit this - it falls back to
# "Unsorted" for whatever's left over rather than crashing (see
# get_chapters), but the result is worse than a shorter session's.
MAX_TOKENS = 16000
UNSORTED_TITLE = "Unsorted"

# --- Backend configuration (see docs/local-model-chaptering-design.md) ----
#
# Environment-variable driven, not CLI flags: backend choice is a one-time
# setup decision (like ANTHROPIC_API_KEY itself), not a per-invocation one.
DEFAULT_BACKEND = "anthropic"
OLLAMA_DEFAULT_HOST = "http://localhost:11434"
# A local model generating MAX_TOKENS's worth of output (16000, tuned for
# the hosted API's non-streaming HTTP timeout) could take minutes on modest
# hardware rather than seconds - see the design doc's "Latency
# implications". Kept as its own, separately-configurable ceiling rather
# than shared with MAX_TOKENS above; deliberately conservative default,
# trading a higher chance of Unsorted fallback on long sessions for a
# bounded wait.
OLLAMA_DEFAULT_MAX_TOKENS = 4096

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
    # Wall-clock time the model call itself took this run - 0.0 when
    # nothing new was chaptered (cache hit) or the call failed before
    # producing a response. Always 0.0 for the Anthropic backend too
    # (cost is the meaningful number there); only OllamaBackend populates
    # this with something worth showing, since its cost_usd is always 0.0
    # (see BackendResponse/OllamaBackend below) - see format_pass_note.
    wall_clock_s: float = 0.0


def format_pass_note(result: ChapterResult) -> str | None:
    """One-liner describing what this chaptering pass's own model call
    cost - dollars for a hosted backend, wall-clock time in its place for
    a local backend (whose cost_usd is always $0.0, but which still isn't
    free of overhead - see docs/local-model-chaptering-design.md's "Cost"
    note). Returns None when nothing was actually called this run (a full
    cache hit, or a failed call - fallback_reason already covers that
    case)."""
    if result.pass_cost_usd:
        return f"cost ${result.pass_cost_usd:.4f}"
    if result.wall_clock_s:
        return f"took {result.wall_clock_s:.1f}s locally (no API cost)"
    return None


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


def _build_context(prior_chapter_titles: list[str]) -> str:
    """Shared between every backend: the "here's what came before" preamble
    prepended to the outline so a fresh model call knows not to re-list an
    already-cached turn. Backend-agnostic - factored out of the old
    Anthropic-only `_call_model` rather than duplicated in OllamaBackend."""
    if not prior_chapter_titles:
        return ""
    titled = "; ".join(prior_chapter_titles)
    return (
        f"Turns before this point were already grouped into these chapters "
        f"(in order): {titled}. Only assign chapters/sections for the NEW "
        f"turns below - do not re-list any earlier turn.\n\n"
    )


@dataclass
class BackendResponse:
    """What every ChapterBackend.call() returns - backend-agnostic shape
    that get_chapters works with from here on (_validate_partition, the
    Unsorted fallback, and cache read/write never look at a backend-specific
    response type). See docs/local-model-chaptering-design.md's
    Architecture section."""

    parsed: "_ChaptersOut | None"
    stop_reason: str
    cost_usd: float  # always 0.0 for a local backend
    wall_clock_s: float


class ChapterBackend(Protocol):
    """A pluggable chaptering model call. `AnthropicBackend` (today's
    hosted default) and `OllamaBackend` (local, optional) both implement
    this - see docs/local-model-chaptering-design.md."""

    def call(self, outline: str, prior_chapter_titles: list[str]) -> BackendResponse: ...


class BackendUnavailableError(Exception):
    """Raised by a backend's call() for an anticipated, nameable failure
    mode - a missing optional dependency, an unreachable local server, a
    local response that doesn't match the expected schema - as opposed to
    a genuinely unexpected exception. The message is already user-facing;
    get_chapters uses it verbatim as fallback_reason rather than wrapping
    it in the generic "chaptering call failed (...)" phrasing reserved for
    truly unexpected errors. Never triggers a switch to a different
    backend - a backend failure always falls back to a single "Unsorted"
    chapter, exactly like today's Anthropic-only failure handling, per the
    design doc's explicit no-auto-fallback-between-backends non-goal."""


class AnthropicBackend:
    """The hosted, default backend - today's `_call_model` body, moved here
    unchanged in behavior. Deliberately does NOT catch/wrap
    anthropic.AuthenticationError or the credential-missing TypeError into
    BackendUnavailableError: get_chapters already has specific, tested
    handling for exactly those two shapes (see its docstring), and letting
    them propagate as-is preserves that handling verbatim rather than
    duplicating the same distinction inside this class."""

    def __init__(self, model: str | None = None, max_tokens: int = MAX_TOKENS):
        self.model = model or CHAPTER_MODEL
        self.max_tokens = max_tokens

    def call(self, outline: str, prior_chapter_titles: list[str]) -> BackendResponse:
        import anthropic  # imported lazily - only needed for `chapters`, not the live dashboard

        client = anthropic.Anthropic()
        context = _build_context(prior_chapter_titles)
        start = time.monotonic()
        response = client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context + outline}],
            output_format=_ChaptersOut,
        )
        elapsed = time.monotonic() - start

        cost = 0.0
        if response.usage:
            c = estimate_cost_usd(response.model, response.usage.model_dump())
            cost = c if c is not None else 0.0

        return BackendResponse(
            parsed=response.parsed_output,
            stop_reason=response.stop_reason,
            cost_usd=cost,
            wall_clock_s=elapsed,
        )


class OllamaBackend:
    """Local-inference backend - talks to a local Ollama server and never
    sends session content over the network. Uses Ollama's `format` field
    (a JSON schema, not the string "json") to constrain decoding to
    `_ChaptersOut`'s shape server-side - the local equivalent of the
    Anthropic SDK's `output_format=`, and the load-bearing property this
    backend exists to preserve: enforced structured output, not a prompted
    "return JSON" convention. See
    docs/local-model-chaptering-design.md's "OllamaBackend specifics".

    Requires the optional `ollama` PyPI package (`pip install
    "work-ledger[local-chapters]"`) and a running local server - both
    checked lazily inside call(), never at import time, so importing
    chapters.py never requires either.
    """

    def __init__(
        self,
        model: str | None,
        host: str = OLLAMA_DEFAULT_HOST,
        max_tokens: int = OLLAMA_DEFAULT_MAX_TOKENS,
    ):
        self.model = model
        self.host = host
        self.max_tokens = max_tokens

    def call(self, outline: str, prior_chapter_titles: list[str]) -> BackendResponse:
        if not self.model:
            raise BackendUnavailableError(
                "WORK_LEDGER_CHAPTER_BACKEND=ollama requires WORK_LEDGER_CHAPTER_MODEL to name "
                "a model pulled into your local Ollama server (e.g. `qwen2.5:14b`); new turns "
                "grouped as Unsorted."
            )
        try:
            import ollama
        except ImportError as e:
            raise BackendUnavailableError(
                "the `ollama` package isn't installed; new turns grouped as Unsorted. Run "
                '`pip install "work-ledger[local-chapters]"`, or unset '
                "WORK_LEDGER_CHAPTER_BACKEND to use the Anthropic backend instead."
            ) from e

        context = _build_context(prior_chapter_titles)
        schema = _ChaptersOut.model_json_schema()
        client = ollama.Client(host=self.host)

        start = time.monotonic()
        try:
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context + outline},
                ],
                format=schema,
                options={"num_predict": self.max_tokens},
            )
        except ollama.ResponseError as e:
            # A structured error response *from* the server - e.g. the
            # named model isn't pulled locally - distinct from the server
            # not being reachable at all (below).
            raise BackendUnavailableError(
                f"the Ollama server rejected the request ({e}); new turns grouped as "
                f"Unsorted. Check `ollama list` includes {self.model!r}, or pull it with "
                f"`ollama pull {self.model}`."
            ) from e
        except Exception as e:  # noqa: BLE001 - anything else here means we couldn't talk to it at all
            raise BackendUnavailableError(
                f"could not reach the local Ollama server at {self.host} ({e}); new turns "
                "grouped as Unsorted. Make sure `ollama serve` is running, or set OLLAMA_HOST "
                "if it's listening somewhere else."
            ) from e
        elapsed = time.monotonic() - start

        try:
            content = response["message"]["content"]
            parsed = _ChaptersOut.model_validate_json(content)
        except Exception as e:  # noqa: BLE001 - malformed/truncated local output, not a crash
            raise BackendUnavailableError(
                f"the local model's response didn't match the expected schema ({e}); new turns "
                "grouped as Unsorted. This is more likely with a smaller local model - see "
                "docs/local-model-chaptering-design.md's 'Reliability implications'."
            ) from e

        stop_reason = "max_tokens" if response.get("done_reason") == "length" else "end_turn"
        return BackendResponse(
            parsed=parsed,
            stop_reason=stop_reason,
            cost_usd=0.0,
            wall_clock_s=elapsed,
        )


def _select_backend() -> ChapterBackend:
    """Choose and instantiate a backend from environment configuration -
    the "thin dispatcher" the design doc describes `_call_model` becoming.
    Re-read fresh on every call (not cached at import time) so changing
    WORK_LEDGER_CHAPTER_BACKEND/WORK_LEDGER_CHAPTER_MODEL/OLLAMA_HOST takes
    effect without restarting anything - and so tests can monkeypatch
    os.environ per-test without import-order games."""
    backend_name = os.environ.get("WORK_LEDGER_CHAPTER_BACKEND", DEFAULT_BACKEND).strip().lower()
    model = os.environ.get("WORK_LEDGER_CHAPTER_MODEL") or None

    if backend_name == "anthropic":
        return AnthropicBackend(model=model)
    if backend_name == "ollama":
        host = os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
        max_tokens_str = os.environ.get("WORK_LEDGER_OLLAMA_MAX_TOKENS")
        max_tokens = int(max_tokens_str) if max_tokens_str else OLLAMA_DEFAULT_MAX_TOKENS
        return OllamaBackend(model=model, host=host, max_tokens=max_tokens)
    raise BackendUnavailableError(
        f"unknown WORK_LEDGER_CHAPTER_BACKEND={backend_name!r} (expected 'anthropic' or "
        "'ollama'); new turns grouped as Unsorted."
    )


def _call_model(outline: str, prior_chapter_titles: list[str]) -> BackendResponse:
    """Thin dispatcher: pick a backend from config, call it, return its
    BackendResponse. Everything downstream in get_chapters
    (_validate_partition, the Unsorted fallback, cache read/write) is
    backend-agnostic and unchanged by which backend actually ran."""
    return _select_backend().call(outline, prior_chapter_titles)


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


def cached_chapters(transcript_path: Path) -> list[Chapter]:
    """Read only whatever chapters are already cached for this transcript,
    without calling the model for anything new. For callers (e.g.
    timeline.py) that want category data if it exists but must never
    trigger a paid Haiku pass as a side effect of an unrelated command."""
    _, chapters = _load_cache(transcript_path)
    return chapters


def has_uncached_turns(tailer: TranscriptTailer, transcript_path: Path) -> bool:
    """Whether this transcript has any turns not yet covered by its
    chapters cache - used by `timeline backfill` to decide which sessions
    are worth an actual chaptering pass, and by plain `timeline` to warn
    that its category mix is incomplete without running one."""
    chaptered_ids, _ = _load_cache(transcript_path)
    chaptered_id_set = set(chaptered_ids)
    return any(t.prompt_id not in chaptered_id_set for t in tailer.ordered_turns())


def _check_ollama_credentials() -> tuple[bool, str]:
    """The Ollama-backend analog of the Anthropic check below: cheap,
    no-network. Only verifies the optional `ollama` package is importable -
    it deliberately does NOT try to reach the local server (that would be
    a real network call from a status check, which the Anthropic check
    above also avoids), so a "credentials found" result here still doesn't
    guarantee a chaptering pass will succeed if `ollama serve` isn't
    actually running - same limitation the Anthropic check has for an
    invalid-but-present key."""
    try:
        import ollama  # noqa: F401
    except ImportError:
        return False, (
            "the `ollama` package isn't installed; new turns will fall back to Unsorted. Run "
            '`pip install "work-ledger[local-chapters]"`, or unset WORK_LEDGER_CHAPTER_BACKEND '
            "to use the Anthropic backend instead."
        )
    return True, (
        "ollama package installed (this doesn't confirm the local server is running - a "
        "chaptering pass will still fail distinctly if it isn't)"
    )


def check_credentials() -> tuple[bool, str]:
    """Cheap, no-network check for whether the *configured* backend
    (`WORK_LEDGER_CHAPTER_BACKEND`, default "anthropic") looks usable.

    For the Anthropic backend: whether the SDK can resolve *some*
    credential (`ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` env var, or an
    `ant auth login` profile on disk) - not whether it's actually valid,
    which only a real API call can prove. That's a deliberate limit, not
    an oversight: validating for real would mean a second network call on
    top of the one chaptering pass already makes (see
    docs/architecture.md's "Network calls" - never a silent extra one), and
    get_chapters's own AuthenticationError handling already surfaces an
    invalid-but-present key distinctly once a real chaptering pass is
    attempted.

    Constructing `anthropic.Anthropic()` runs the SDK's full credential
    resolution chain (env vars, `ANTHROPIC_PROFILE`, workload identity
    federation, the active on-disk profile `ant auth login` writes) but
    never issues a request itself - verified against the installed SDK
    (see its docstring's precedence list), so this is safe to call from a
    status check with no cost and no risk of tripping over network access.

    For the Ollama backend: see _check_ollama_credentials above.

    Used by `miso --check-status` and `miso`'s own up-front notice (see
    cli.py) - returns the exact wording get_chapters uses for the
    no-credential fallback so the same fact is never phrased two ways."""
    backend_name = os.environ.get("WORK_LEDGER_CHAPTER_BACKEND", DEFAULT_BACKEND).strip().lower()
    if backend_name == "ollama":
        return _check_ollama_credentials()

    import anthropic  # imported lazily - only needed for `chapters`/`miso`, not the live dashboard

    client = anthropic.Anthropic()
    if client.api_key or client.auth_token or client.credentials:
        return True, "Anthropic credentials found (env var or `ant auth login` profile)"
    return False, NO_CREDENTIALS_MESSAGE


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
    wall_clock_s = 0.0
    fallback_reason = None
    new_chapter_dicts: list[_ChapterOut] = []

    import anthropic  # imported lazily - only needed for `chapters`, not the live dashboard

    try:
        response = _call_model(outline, prior_titles)
    except anthropic.AuthenticationError as e:
        # A real 401 from the server - a key was sent and rejected (invalid,
        # revoked, or malformed), distinct from no key being present at all
        # (see the TypeError branch below) - worth flagging differently
        # since the fix is "check the key," not "set a key." Only ever
        # raised by AnthropicBackend, but harmless to catch regardless of
        # which backend is configured.
        fallback_reason = (
            f"ANTHROPIC_API_KEY was rejected by the server ({e}); new turns grouped as "
            "Unsorted. Check the key is still valid at console.anthropic.com."
        )
        response = None
    except TypeError as e:
        # The SDK raises a plain TypeError, not an AnthropicError subclass,
        # when it can't find any credential at all (verified against the
        # installed anthropic SDK, not guessed) - client-side, before any
        # network call, so this costs nothing to check.
        if "Could not resolve authentication method" in str(e):
            fallback_reason = NO_CREDENTIALS_MESSAGE
        else:
            fallback_reason = f"chaptering call failed ({e}); new turns grouped as Unsorted"
        response = None
    except BackendUnavailableError as e:
        # A backend-specific, anticipated failure mode (e.g. OllamaBackend's
        # missing package / unreachable server / schema mismatch) - the
        # message is already user-facing, so it's used verbatim rather than
        # wrapped in the generic "chaptering call failed (...)" phrasing
        # below. Never falls back to a different backend - just Unsorted,
        # same as every other failure mode here.
        fallback_reason = str(e)
        response = None
    except Exception as e:  # noqa: BLE001 - any other failure here falls back, never crashes
        fallback_reason = f"chaptering call failed ({e}); new turns grouped as Unsorted"
        response = None

    def _all_unsorted() -> list[_ChapterOut]:
        return [
            _ChapterOut(
                title=UNSORTED_TITLE,
                category=DEFAULT_CATEGORY,
                sections=[_SectionOut(title=UNSORTED_TITLE, prompt_ids=[t.prompt_id for t in new_turns])],
            )
        ]

    if response is not None:
        cost = response.cost_usd
        wall_clock_s = response.wall_clock_s
        parsed = response.parsed
        if response.stop_reason == "refusal":
            fallback_reason = "chaptering call was refused; new turns grouped as Unsorted"
            new_chapter_dicts = _all_unsorted()
        elif parsed is None:
            fallback_reason = (
                "chaptering response didn't match the expected shape "
                f"(stop_reason={response.stop_reason!r}); new turns grouped as Unsorted"
            )
            new_chapter_dicts = _all_unsorted()
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
    else:
        new_chapter_dicts = _all_unsorted()

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

    return ChapterResult(
        chapters=merged_chapters,
        pass_cost_usd=cost,
        fallback_reason=fallback_reason,
        wall_clock_s=wall_clock_s,
    )
