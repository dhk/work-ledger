"""Locate and tail Claude Code session transcripts (~/.claude/projects/**/*.jsonl).

No telemetry setup needed - these files already exist for every session.
Each assistant message carries a `usage` block (tokens) and `model`; each
user message carries a `promptId` that groups all activity back to the
prompt that triggered it. We use that grouping as the outer "Turn" unit.

Within a turn, each individual assistant *message* (one LLM call - one
`message.id`) is a finer "Unit" of work: the commentary plus whatever tool
calls came with it. Important quirk verified against real transcripts:
Claude Code writes one JSONL line per content block (thinking/text/tool_use)
rather than one line per API response, and repeats the full `usage` block
on every one of those lines for the same `message.id`. Naively summing
`usage` per JSONL line (as this file's first version did) overcounts cost
by 2-4x on any multi-block response - this version dedupes by `message.id`
so each real LLM call is counted exactly once.

Skill and subagent (Agent/Task) tool calls are labeled specifically.
Subagent transcripts live in a separate `<session>/subagents/agent-<id>.jsonl`
file with a `.meta.json` sidecar that names the exact `toolUseId` that
spawned it - we use that to roll the subagent's own token usage into the
Unit that dispatched it. This correlation is verified against this
environment's transcripts; Claude Code's transcript format is internal and
undocumented, so older/other installs that instead inline subagent activity
as `isSidechain` entries in the main file are not specifically handled -
those entries are just ignored rather than guessed at. They *are* counted
(`TranscriptTailer.skipped_sidechain_count`), so a caller can at least warn
that a session's cost may be an undercount instead of looking complete when
it isn't - see #46.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from work_ledger.pricing import estimate_cost_usd

TRANSCRIPTS_ROOT = Path.home() / ".claude" / "projects"

SUBAGENT_TOOL_NAMES = {"Agent", "Task"}
SKILL_TOOL_NAME = "Skill"
READ_TOOL_NAME = "Read"
BASH_TOOL_NAME = "Bash"

# Claude Code writes this exact synthetic assistant entry (no message.id, no
# usage block) when a request is rejected for hitting the Pro/Max session
# limit - verified against a real transcript, see
# docs/recommend-workflow-efficiency-design.md's "Validation" section:
#   {"type": "assistant", "error": "rate_limit", "apiErrorStatus": 429,
#    "message": {"model": "", "content": [{"type": "text",
#    "text": "You've hit your session limit · resets 11:40pm (UTC)"}]}}
RATE_LIMIT_ERROR = "rate_limit"

# Claude Code writes this literal string as the entire content of a genuine
# `type: "user"` message when the user interrupts a running turn. The design
# doc's validation found this precise and worth shipping - but only when the
# search is scoped to actual user-message text blocks, never a blind
# substring search over the whole transcript: a naive full-text search also
# matches the tool's own prior Bash output echoing this same marker text back
# (e.g. this file's own docstring, or a previous run's terminal output),
# which inflated the doc's own trial count from 2 real interruptions to 8
# false-inclusive hits.
INTERRUPTION_MARKER = "[Request interrupted by user]"


def find_active_transcript() -> Path | None:
    """Return the most recently modified transcript file, or None if none exist."""
    if not TRANSCRIPTS_ROOT.is_dir():
        return None
    candidates = list(TRANSCRIPTS_ROOT.glob("*/*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_all_transcripts() -> list[Path]:
    """Return every session transcript found, newest (by mtime) first.
    Skips any file that disappears or becomes unreadable between the glob
    and the stat call (e.g. deleted/moved concurrently) rather than raising."""
    if not TRANSCRIPTS_ROOT.is_dir():
        return []
    dated = []
    for p in TRANSCRIPTS_ROOT.glob("*/*.jsonl"):
        try:
            dated.append((p, p.stat().st_mtime))
        except OSError:
            continue
    dated.sort(key=lambda pair: pair[1], reverse=True)
    return [p for p, _mtime in dated]


def find_transcripts_by_session_prefix(prefix: str) -> list[Path]:
    """Every transcript whose filename (the session's own local UUID, not
    to be confused with a claude.ai/code `session_...` URL id - those are
    a different, unrelated identifier with no mapping to this one) starts
    with `prefix`, newest first. Lets `--session` take a short prefix
    instead of the full UUID, same convention as `git rev-parse` accepting
    a short commit hash."""
    return [p for p in find_all_transcripts() if p.stem.startswith(prefix)]


def _shorten(text: str, max_len: int = 60) -> str:
    text = " ".join(text.split())  # collapse whitespace/newlines
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def extract_prompt_snippet(message: dict, max_len: int = 60) -> str:
    """Best-effort short text summary of a user message for display."""
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = " ".join(parts)
    else:
        text = ""
    return _shorten(text, max_len) or "(no text - tool result or non-text turn)"


def extract_full_user_text(message: dict) -> str:
    """Same content extraction as extract_prompt_snippet (plain string
    content, or only `type: "text"` blocks from a list - never tool_use/
    tool_result blocks) but untruncated. Used where a display-length
    snippet isn't enough - e.g. recommend.py's interruption-marker check,
    which needs to search the literal user-authored text, not a 60-char
    preview of it, while still staying scoped to genuine user content
    rather than a blind substring search over the whole transcript."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


_RESET_LABEL_RE = re.compile(r"resets\s+(.+)$", re.IGNORECASE)


def _parse_reset_label(text: str) -> str:
    """Pull the "resets HH:MM(am/pm) (TZ)" tail off a rate-limit message,
    e.g. "You've hit your session limit · resets 11:40pm (UTC)" -> "11:40pm (UTC)".
    Used as the dedup key for retry-storm rate-limit hits (see RateLimitHit
    and TranscriptTailer.deduped_rate_limit_events): multiple raw hits that
    share the same reset time are the same limit window hit repeatedly on
    retry, not distinct events - see docs/recommend-workflow-efficiency-design.md's
    Validation section (5 raw entries collapsed to 2 real events)."""
    match = _RESET_LABEL_RE.search(text)
    return match.group(1).strip() if match else ""


@dataclass
class RateLimitHit:
    """One raw `error: "rate_limit"` transcript entry - the session-limit hit
    signal validated in docs/recommend-workflow-efficiency-design.md. Several
    raw hits can share one `reset_label` (a retry storm against the same
    limit window); see TranscriptTailer.deduped_rate_limit_events for the
    dedup this doc's validation found necessary."""

    timestamp: str
    reset_label: str
    text: str


def _aggregate_subagent_usage(jsonl_path: Path) -> tuple[int, int, float, bool]:
    """Sum token usage/cost across every distinct assistant message in a
    subagent transcript (deduping by message.id for the same reason as the
    main transcript - see module docstring)."""
    seen_message_ids: set[str] = set()
    input_tokens = output_tokens = 0
    cost = 0.0
    unknown = False
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        # Can't read the subagent transcript - its cost is unknown, not $0.
        # Flagging unknown=True surfaces "?" in the UI instead of silently
        # under-reporting (same philosophy as pricing.py's unpriced-model case).
        return 0, 0, 0.0, True
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        message = obj.get("message") or {}
        usage = message.get("usage") or {}
        if not usage:
            continue
        mid = message.get("id")
        if mid:
            if mid in seen_message_ids:
                continue
            seen_message_ids.add(mid)
        model = message.get("model", "")
        c = estimate_cost_usd(model, usage)
        if c is None:
            unknown = True
        else:
            cost += c
        input_tokens += usage.get("input_tokens", 0) or 0
        output_tokens += usage.get("output_tokens", 0) or 0
    return input_tokens, output_tokens, cost, unknown


@dataclass
class Unit:
    """One assistant message (one LLM call) - commentary plus its tool calls.

    Content (text/tool_use) is derived incrementally as JSONL lines for this
    message.id arrive, since Claude Code splits one message across multiple
    lines. Fields are first-wins so ordering across lines doesn't matter.
    """

    timestamp: str
    text_snippet: str = ""
    tool_names: list[str] = field(default_factory=list)
    skill_name: str | None = None
    # Target path of every Read tool_use call this unit made (in call order,
    # duplicates included) - narrowly scoped to just what waste.py's
    # repeated-file-read detection needs (#5), rather than a generic
    # capture-every-tool-input field: a Write/Edit input can carry a whole
    # file's contents, which would bloat every Unit for no reason nothing
    # here reads. The path itself isn't a new privacy exposure - it's
    # already visible elsewhere in the same transcript (the Read's result).
    read_paths: list[str] = field(default_factory=list)
    # One token per tool_use call this unit made, in call order - "ToolName"
    # for most tools, or "Bash:<up to first 3 words of the command>" for
    # Bash (e.g. "Bash:git checkout -b", "Bash:git commit -m",
    # "Bash:gh pr create") so a Bash-heavy sequence (branch/commit/push/PR/
    # review-request) doesn't collapse into indistinguishable "Bash"
    # entries - a single leading word ("git") wasn't enough to tell `git
    # checkout` apart from `git commit`/`git push`. Still deliberately just
    # the command+subcommand, never the full command text (no branch
    # names, commit messages, or PR bodies) - narrowly scoped to what
    # recommend.py's recurring-tool-sequence check needs (issue #19), same
    # "capture only what's needed, not a generic tool-input dump" precedent
    # as read_paths above.
    tool_call_signature: list[str] = field(default_factory=list)
    subagent_desc: str | None = None
    subagent_tool_use_id: str | None = None
    subagent_agent_type: str | None = None
    own_input_tokens: int = 0
    own_output_tokens: int = 0
    own_cost_usd: float = 0.0
    own_unknown_model: bool = False
    # Populated later (async) once a matching subagent transcript is found.
    subagent_input_tokens: int = 0
    subagent_output_tokens: int = 0
    subagent_cost_usd: float = 0.0
    subagent_unknown_model: bool = False

    @property
    def kind(self) -> str:
        if self.subagent_desc is not None:
            return "subagent"
        if self.skill_name is not None:
            return "skill"
        return "text"

    @property
    def label(self) -> str:
        if self.kind == "subagent":
            return f"Subagent: {self.subagent_agent_type or self.subagent_desc}"
        if self.kind == "skill":
            return f"Skill: {self.skill_name}"
        if self.text_snippet:
            return self.text_snippet
        if self.tool_names:
            return self.tool_names[0]
        return "(no content)"

    @property
    def input_tokens(self) -> int:
        return self.own_input_tokens + self.subagent_input_tokens

    @property
    def output_tokens(self) -> int:
        return self.own_output_tokens + self.subagent_output_tokens

    @property
    def cost_usd(self) -> float:
        return self.own_cost_usd + self.subagent_cost_usd

    @property
    def unknown_model_cost(self) -> bool:
        return self.own_unknown_model or self.subagent_unknown_model


@dataclass
class Turn:
    prompt_id: str
    prompt_snippet: str
    timestamp: str
    units: list[Unit] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.units)

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.units)

    @property
    def cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.units)

    @property
    def unknown_model_cost(self) -> bool:
        return any(u.unknown_model_cost for u in self.units)

    @property
    def num_assistant_messages(self) -> int:
        return len(self.units)


class TranscriptTailer:
    """Tails a transcript file and aggregates cost/tokens per user-prompt turn,
    broken down further into per-unit-of-work rows within each turn."""

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        self.turns: dict[str, Turn] = {}
        self.turn_order: list[str] = []
        self._current_prompt_id: str | None = None
        self._unit_by_message_id: dict[str, Unit] = {}
        self._subagents_dir = path.parent / path.stem / "subagents"
        self._unit_by_tool_use_id: dict[str, Unit] = {}
        self._subagent_mtimes: dict[str, float] = {}
        # Count (not parse - see module docstring and #46) of inline
        # isSidechain entries skipped in the main transcript. A nonzero
        # count means this session's cost is a silent undercount on an
        # install that uses that older/different transcript format -
        # surfaced by callers (see cli.py) rather than left invisible.
        self.skipped_sidechain_count = 0
        # Raw session-limit hits and genuine-user-message interruptions -
        # both validated signals from docs/recommend-workflow-efficiency-design.md,
        # surfaced to recommend.py (and limits.py) rather than folded into
        # Turn/Unit, since neither carries usage/cost data of its own.
        self.rate_limit_hits: list[RateLimitHit] = []
        self.interruption_count = 0

    def poll(self) -> bool:
        """Read any new lines/subagent data since last poll. Returns True if changed."""
        changed_main = self._poll_main()
        changed_sub = self._poll_subagents()
        return changed_main or changed_sub

    def _poll_main(self) -> bool:
        changed = False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                new_lines = f.readlines()
                self._offset = f.tell()
        except FileNotFoundError:
            return False

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if self._handle_entry(obj):
                changed = True
        return changed

    def _handle_entry(self, obj: dict) -> bool:
        entry_type = obj.get("type")

        if obj.get("isSidechain"):
            # This environment writes subagent activity to a separate file
            # (see _poll_subagents); inline sidechain entries from other
            # transcript formats aren't correlated here - skip rather than guess.
            self.skipped_sidechain_count += 1
            return False

        if entry_type == "user":
            message = obj.get("message") or {}
            is_user_message = message.get("role") == "user"
            if is_user_message and INTERRUPTION_MARKER in extract_full_user_text(message):
                # Scoped to genuine user-message text only (never tool_use/
                # tool_result content) - see INTERRUPTION_MARKER's docstring
                # for why a blind substring search overcounts.
                self.interruption_count += 1

            prompt_id = obj.get("promptId")
            if prompt_id and is_user_message:
                if prompt_id not in self.turns:
                    self.turns[prompt_id] = Turn(
                        prompt_id=prompt_id,
                        prompt_snippet=extract_prompt_snippet(message),
                        timestamp=obj.get("timestamp", ""),
                    )
                    self.turn_order.append(prompt_id)
                self._current_prompt_id = prompt_id
                return True
            return False

        if entry_type == "assistant":
            message = obj.get("message") or {}

            if obj.get("error") == RATE_LIMIT_ERROR:
                # The synthetic rate-limit entry (see RATE_LIMIT_ERROR's
                # docstring) has no message.id/usage - it isn't a real LLM
                # call, so it's recorded separately rather than forced into
                # the Unit/Turn model that Turn.cost_usd etc. depend on.
                text = ""
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
                self.rate_limit_hits.append(
                    RateLimitHit(
                        timestamp=obj.get("timestamp", ""),
                        reset_label=_parse_reset_label(text),
                        text=text,
                    )
                )
                return True

            usage = message.get("usage") or {}
            model = message.get("model", "")
            if not usage or not self._current_prompt_id:
                return False
            turn = self.turns.get(self._current_prompt_id)
            if turn is None:
                return False

            mid = message.get("id")
            unit = self._unit_by_message_id.get(mid) if mid else None
            is_new_unit = unit is None
            if is_new_unit:
                unit = Unit(timestamp=obj.get("timestamp", ""))
                turn.units.append(unit)
                if mid:
                    self._unit_by_message_id[mid] = unit

            # usage is duplicated verbatim across every line for this message.id;
            # overwrite (not accumulate) so re-seeing it is always safe.
            unit.own_input_tokens = usage.get("input_tokens", 0) or 0
            unit.own_output_tokens = usage.get("output_tokens", 0) or 0
            cost = estimate_cost_usd(model, usage)
            if cost is None:
                unit.own_unknown_model = True
            else:
                unit.own_cost_usd = cost
                unit.own_unknown_model = False

            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and not unit.text_snippet:
                    unit.text_snippet = _shorten(block.get("text", ""))
                elif btype == "tool_use":
                    name = block.get("name", "")
                    unit.tool_names.append(name)
                    if name == BASH_TOOL_NAME:
                        command = ((block.get("input") or {}).get("command") or "").strip()
                        # Up to the first 3 words (command + subcommand,
                        # e.g. "git checkout", "gh pr create") - enough to
                        # tell different git/gh steps apart, never enough
                        # to include a branch name, commit message, or PR
                        # body (see tool_call_signature's docstring).
                        head = " ".join(command.split()[:3])
                        unit.tool_call_signature.append(f"{name}:{head}" if head else name)
                    else:
                        unit.tool_call_signature.append(name)
                    if name == SKILL_TOOL_NAME and unit.skill_name is None:
                        unit.skill_name = (block.get("input") or {}).get("skill", "unknown")
                    elif name == READ_TOOL_NAME:
                        path = (block.get("input") or {}).get("file_path")
                        if path:
                            unit.read_paths.append(path)
                    elif name in SUBAGENT_TOOL_NAMES and unit.subagent_desc is None:
                        inp = block.get("input") or {}
                        unit.subagent_desc = (
                            inp.get("description") or inp.get("subagent_type") or "subagent"
                        )
                        unit.subagent_tool_use_id = block.get("id")
                        if unit.subagent_tool_use_id:
                            self._unit_by_tool_use_id[unit.subagent_tool_use_id] = unit

            return True

        return False

    def _poll_subagents(self) -> bool:
        if not self._subagents_dir.is_dir():
            return False
        changed = False
        for meta_path in self._subagents_dir.glob("agent-*.meta.json"):
            jsonl_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl"))
            if not jsonl_path.exists():
                continue
            try:
                mtime = jsonl_path.stat().st_mtime
            except OSError:
                continue
            key = str(jsonl_path)
            if self._subagent_mtimes.get(key) == mtime:
                continue
            self._subagent_mtimes[key] = mtime

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            tool_use_id = meta.get("toolUseId")
            unit = self._unit_by_tool_use_id.get(tool_use_id)
            if unit is None:
                continue  # dispatching message not seen yet, or a stale/unrelated file

            input_tok, output_tok, cost, unknown = _aggregate_subagent_usage(jsonl_path)
            unit.subagent_input_tokens = input_tok
            unit.subagent_output_tokens = output_tok
            unit.subagent_cost_usd = cost
            unit.subagent_unknown_model = unknown
            agent_type = meta.get("agentType")
            if agent_type:
                unit.subagent_agent_type = agent_type
            changed = True
        return changed

    def ordered_turns(self) -> list[Turn]:
        return [self.turns[pid] for pid in self.turn_order]

    def total_cost_usd(self) -> float:
        return sum(t.cost_usd for t in self.turns.values())

    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns.values())

    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns.values())

    def has_unknown_model(self) -> bool:
        return any(t.unknown_model_cost for t in self.turns.values())

    def has_skipped_sidechain(self) -> bool:
        """True if any inline isSidechain entry was seen and skipped (see
        skipped_sidechain_count) - a signal this session's cost may be an
        undercount on an install that uses that transcript format."""
        return self.skipped_sidechain_count > 0

    def deduped_rate_limit_events(self) -> list[RateLimitHit]:
        """Collapse raw rate_limit hits (self.rate_limit_hits) by reset
        label. A retry storm against the same limit window produces several
        raw entries that all share one reset time - docs/recommend-workflow-
        efficiency-design.md's validation found 5 raw entries collapsing to
        2 real events this way. Returns one hit per distinct reset label
        (the earliest-timestamped raw hit for that label), oldest first. A
        hit whose reset time couldn't be parsed keys on its own timestamp
        instead, so it's never silently merged with an unrelated hit."""
        by_reset: dict[str, RateLimitHit] = {}
        for hit in self.rate_limit_hits:
            key = hit.reset_label or f"unparsed:{hit.timestamp}"
            existing = by_reset.get(key)
            if existing is None or hit.timestamp < existing.timestamp:
                by_reset[key] = hit
        return sorted(by_reset.values(), key=lambda h: h.timestamp)
