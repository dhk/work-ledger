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
those entries are just ignored rather than guessed at.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from work_ledger.pricing import estimate_cost_usd

TRANSCRIPTS_ROOT = Path.home() / ".claude" / "projects"

SUBAGENT_TOOL_NAMES = {"Agent", "Task"}
SKILL_TOOL_NAME = "Skill"


def find_active_transcript() -> Path | None:
    """Return the most recently modified transcript file, or None if none exist."""
    if not TRANSCRIPTS_ROOT.is_dir():
        return None
    candidates = list(TRANSCRIPTS_ROOT.glob("*/*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


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
            return False

        if entry_type == "user":
            prompt_id = obj.get("promptId")
            message = obj.get("message") or {}
            if prompt_id and message.get("role") == "user":
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
                    if name == SKILL_TOOL_NAME and unit.skill_name is None:
                        unit.skill_name = (block.get("input") or {}).get("skill", "unknown")
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
