"""Anonymized, manual, opt-in usage export.

This module never sends anything anywhere - it only builds a JSON payload
and the CLI writes it to a local file. If a user wants to contribute it to
a shared corpus, that's a separate, manual step they take themselves (see
README's Export section). Nothing in work-ledger makes a network call on
its own initiative.

What's included: session/chapter counts and token/cost totals, rolled up
by the fixed chapter category taxonomy (chapters.CATEGORIES) - never by
free-text chapter title. What's deliberately excluded: chapter titles,
prompt/tool content, transcript paths, session identifiers - anything that
identifies the work itself rather than just its shape. Getting the
category for each chapter still requires chaptering to have run (same
Haiku pass `chapters --all` already makes), so exporting un-chaptered
sessions incurs the same small, disclosed API cost.
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from work_ledger.chapters import CATEGORIES, get_chapters
from work_ledger.transcript import TranscriptTailer, find_all_transcripts

SCHEMA_VERSION = 1


def _in_date_range(path: Path, since: date | None, until: date | None) -> bool:
    """Same approximation as `chapters --all --since/--until`: filtered by
    the transcript file's mtime, not the session's exact start/end."""
    if since is None and until is None:
        return True
    mtime_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    if since and mtime_date < since:
        return False
    if until and mtime_date > until:
        return False
    return True


def _empty_bucket() -> dict:
    return {"chapters": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


@dataclass
class ExportResult:
    payload: dict
    pass_cost_usd: float
    num_sessions: int


def build_export_payload(since: date | None = None, until: date | None = None) -> ExportResult:
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]

    totals = _empty_bucket()
    # Pre-seed every known category so the payload shape is stable across
    # users/runs even when a bucket is empty - easier to aggregate later.
    by_category = {cat: _empty_bucket() for cat in CATEGORIES}
    pass_cost_usd = 0.0
    num_sessions = 0

    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        if not tailer.ordered_turns():
            continue

        result = get_chapters(tailer, path)
        pass_cost_usd += result.pass_cost_usd
        num_sessions += 1

        for chapter in result.chapters:
            turns = chapter.turns(tailer)
            in_tok = sum(t.input_tokens for t in turns)
            out_tok = sum(t.output_tokens for t in turns)
            cost = sum(t.cost_usd for t in turns)

            totals["chapters"] += 1
            totals["input_tokens"] += in_tok
            totals["output_tokens"] += out_tok
            totals["cost_usd"] += cost

            bucket = by_category.setdefault(chapter.category, _empty_bucket())
            bucket["chapters"] += 1
            bucket["input_tokens"] += in_tok
            bucket["output_tokens"] += out_tok
            bucket["cost_usd"] += cost

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().date().isoformat(),
        "range": {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "totals": {**totals, "sessions": num_sessions},
        "by_category": by_category,
    }
    return ExportResult(payload=payload, pass_cost_usd=pass_cost_usd, num_sessions=num_sessions)
