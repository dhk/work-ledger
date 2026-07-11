"""Locate and tail Claude Code session transcripts (~/.claude/projects/**/*.jsonl).

No telemetry setup needed - these files already exist for every session.
Each assistant message carries a `usage` block (tokens) and `model`; each
user message carries a `promptId` that groups all activity back to the
prompt that triggered it. We use that grouping as the "block of work" unit.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from work_ledger.pricing import estimate_cost_usd

TRANSCRIPTS_ROOT = Path.home() / ".claude" / "projects"


def find_active_transcript() -> Path | None:
    """Return the most recently modified transcript file, or None if none exist."""
    if not TRANSCRIPTS_ROOT.is_dir():
        return None
    candidates = list(TRANSCRIPTS_ROOT.glob("*/*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


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
    text = " ".join(text.split())  # collapse whitespace/newlines
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "(no text - tool result or non-text turn)"


@dataclass
class Turn:
    prompt_id: str
    prompt_snippet: str
    timestamp: str
    cost_usd: float = 0.0
    unknown_model_cost: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    num_assistant_messages: int = 0


class TranscriptTailer:
    """Tails a transcript file and aggregates cost/tokens per user-prompt turn."""

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        self.turns: dict[str, Turn] = {}
        self.turn_order: list[str] = []
        self._current_prompt_id: str | None = None

    def poll(self) -> bool:
        """Read any new lines since last poll. Returns True if anything changed."""
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
            cost = estimate_cost_usd(model, usage)
            if cost is None:
                turn.unknown_model_cost = True
            else:
                turn.cost_usd += cost
            turn.input_tokens += usage.get("input_tokens", 0) or 0
            turn.output_tokens += usage.get("output_tokens", 0) or 0
            turn.num_assistant_messages += 1
            return True

        return False

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
