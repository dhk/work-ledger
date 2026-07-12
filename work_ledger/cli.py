"""Terminal dashboard: tails the active Claude Code session transcript and
shows running cost/token usage per prompt, updating in near-real-time.

No telemetry setup, no server, no browser - just run it in a terminal next
to your session. The `chapters` subcommand adds a separate, on-demand
semantic layer on top (see docs/session-chaptering-design.md): it groups
prompts into initiatives via a small Haiku pass and links back into this
same per-unit rendering for drill-down (`chapters --detail`).
"""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from work_ledger.chapters import Chapter, get_chapters
from work_ledger.transcript import Turn, TranscriptTailer, find_active_transcript, find_all_transcripts

POLL_INTERVAL_S = 1.0

UNIT_KIND_STYLE = {
    "skill": "cyan",
    "subagent": "magenta",
    "text": "dim",
}

TABLE_COLUMNS = ("Time", "Prompt / task", "Calls", "In tok", "Out tok", "Cost (est.)")


def _unit_cost_str(unit) -> str:
    return "?" if unit.unknown_model_cost and unit.cost_usd == 0 else f"${unit.cost_usd:.4f}"


def _turn_cost_str(turn_or_turns_cost: float, unknown: bool) -> str:
    return "?" if unknown and turn_or_turns_cost == 0 else f"${turn_or_turns_cost:.4f}"


def _new_table(title: str) -> Table:
    table = Table(title=title, expand=True)
    table.add_column("Time", style="dim", width=8)
    table.add_column("Prompt / task", ratio=3, overflow="ellipsis")
    table.add_column("Calls", justify="right", width=6)
    table.add_column("In tok", justify="right", width=8)
    table.add_column("Out tok", justify="right", width=8)
    table.add_column("Cost (est.)", justify="right", width=12)
    return table


def add_turn_rows(table: Table, turns: list[Turn], detail: bool = False, indent: str = "") -> None:
    """Render one row per turn (and, if detail, one row per unit within it).
    Shared by the live dashboard and the `chapters --detail` drill-down so
    there is exactly one code path that renders a turn's units."""
    for turn in turns:
        time_str = turn.timestamp[11:19] if len(turn.timestamp) >= 19 else turn.timestamp
        table.add_row(
            time_str,
            Text(indent + turn.prompt_snippet, style="bold"),
            str(turn.num_assistant_messages),
            f"{turn.input_tokens:,}",
            f"{turn.output_tokens:,}",
            _turn_cost_str(turn.cost_usd, turn.unknown_model_cost),
        )
        if detail:
            for unit in turn.units:
                style = UNIT_KIND_STYLE.get(unit.kind, "")
                prefix = {"skill": "  ↳ ", "subagent": "  ↳ ", "text": "    "}[unit.kind]
                table.add_row(
                    "",
                    Text(indent + prefix + unit.label, style=style),
                    "",
                    f"{unit.input_tokens:,}",
                    f"{unit.output_tokens:,}",
                    _unit_cost_str(unit),
                )


def build_table(tailer: TranscriptTailer, transcript_name: str, detail: bool = False) -> Table:
    table = _new_table(f"work-ledger — watching {transcript_name}")
    add_turn_rows(table, tailer.ordered_turns(), detail=detail)

    total_cost = tailer.total_cost_usd()
    unknown_note = " (some models unpriced)" if tailer.has_unknown_model() else ""
    table.add_section()
    table.add_row(
        "",
        Text("TOTAL", style="bold"),
        "",
        f"{tailer.total_input_tokens():,}",
        f"{tailer.total_output_tokens():,}",
        Text(f"${total_cost:.4f}{unknown_note}", style="bold green"),
    )
    return table


def run(transcript_path=None, once: bool = False, detail: bool = False):
    console = Console()
    path = transcript_path or find_active_transcript()
    if path is None:
        console.print(
            "[red]No Claude Code session transcripts found under "
            "~/.claude/projects/. Run a session first, or pass --transcript.[/red]"
        )
        sys.exit(1)

    console.print(f"[dim]Watching:[/dim] {path}")
    console.print("[dim]Cost is an estimate from token pricing, not itemized billing "
                   "(plan-included usage still has no per-run $ from Anthropic).[/dim]\n")

    tailer = TranscriptTailer(path)
    tailer.poll()

    if once:
        console.print(build_table(tailer, path.name, detail=detail))
        return

    with Live(build_table(tailer, path.name, detail=detail), console=console, refresh_per_second=2) as live:
        try:
            while True:
                time.sleep(POLL_INTERVAL_S)
                if tailer.poll():
                    live.update(build_table(tailer, path.name, detail=detail))
        except KeyboardInterrupt:
            pass


def _turns_cost(turns: list[Turn]) -> float:
    return sum(t.cost_usd for t in turns)


def _turns_unknown(turns: list[Turn]) -> bool:
    return any(t.unknown_model_cost for t in turns)


def _sorted_by_cost(tailer: TranscriptTailer, chapters: list[Chapter]) -> list[Chapter]:
    scored = [(c, _turns_cost(c.turns(tailer))) for c in chapters]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _ in scored]


def _filter_only(chapters: list[Chapter], only: str) -> list[Chapter]:
    try:
        idx = int(only)
        if 1 <= idx <= len(chapters):
            return [chapters[idx - 1]]
        return []
    except ValueError:
        pass
    exact = [c for c in chapters if c.title == only]
    if exact:
        return exact
    return [c for c in chapters if only.lower() in c.title.lower()]


def build_chapters_table(
    tailer: TranscriptTailer,
    transcript_name: str,
    chapters: list[Chapter],
    grand_total_cost: float,
    detail: bool = False,
) -> Table:
    table = _new_table(f"work-ledger chapters — {transcript_name}")

    total_cost = 0.0
    total_in = 0
    total_out = 0
    any_unknown = False

    for i, chapter in enumerate(chapters, start=1):
        turns = chapter.turns(tailer)
        cost = _turns_cost(turns)
        unknown = _turns_unknown(turns)
        pct = (cost / grand_total_cost * 100) if grand_total_cost else 0.0
        total_cost += cost
        total_in += sum(t.input_tokens for t in turns)
        total_out += sum(t.output_tokens for t in turns)
        any_unknown = any_unknown or unknown

        table.add_row(
            "",
            Text(f"▾ {i}. {chapter.title}", style="bold cyan"),
            str(len(turns)),
            f"{sum(t.input_tokens for t in turns):,}",
            f"{sum(t.output_tokens for t in turns):,}",
            Text(f"{_turn_cost_str(cost, unknown)}  ({pct:.0f}%)", style="bold"),
        )

        for section in chapter.sections:
            sec_turns = section.turns(tailer)
            sec_cost = _turns_cost(sec_turns)
            table.add_row(
                "",
                Text(f"    {section.title}"),
                str(len(sec_turns)),
                f"{sum(t.input_tokens for t in sec_turns):,}",
                f"{sum(t.output_tokens for t in sec_turns):,}",
                _turn_cost_str(sec_cost, _turns_unknown(sec_turns)),
            )
            if detail:
                add_turn_rows(table, sec_turns, detail=True, indent="      ")

        table.add_section()

    unknown_note = " (some models unpriced)" if any_unknown else ""
    table.add_row(
        "",
        Text("TOTAL (shown)", style="bold"),
        "",
        f"{total_in:,}",
        f"{total_out:,}",
        Text(f"${total_cost:.4f}{unknown_note}", style="bold green"),
    )
    return table


def run_chapters(transcript_path=None, detail: bool = False, only: str | None = None, as_json: bool = False):
    console = Console()
    path = transcript_path or find_active_transcript()
    if path is None:
        console.print(
            "[red]No Claude Code session transcripts found under "
            "~/.claude/projects/. Run a session first, or pass --transcript.[/red]"
        )
        sys.exit(1)

    console.print(f"[dim]Watching:[/dim] {path}")
    console.print(
        "[dim]Chaptering makes a separate Claude API call (Haiku) to group prompts "
        "into initiatives - distinct from the token-pricing estimate below, and "
        "billed to your Anthropic API account, not your Claude Code session.[/dim]\n"
    )

    tailer = TranscriptTailer(path)
    tailer.poll()

    result = get_chapters(tailer, path)

    if result.fallback_reason:
        console.print(f"[yellow]Note: {result.fallback_reason}[/yellow]")
    if result.pass_cost_usd:
        console.print(f"[dim]This chaptering pass cost ${result.pass_cost_usd:.4f}[/dim]")

    chapters = _sorted_by_cost(tailer, result.chapters)
    if only:
        chapters = _filter_only(chapters, only)
        if not chapters:
            console.print(f"[red]No chapter matching {only!r}.[/red]")
            sys.exit(1)

    if as_json:
        import json

        data = [
            {
                "title": c.title,
                "cost_usd": _turns_cost(c.turns(tailer)),
                "sections": [
                    {
                        "title": s.title,
                        "prompt_ids": s.prompt_ids,
                        "cost_usd": _turns_cost(s.turns(tailer)),
                    }
                    for s in c.sections
                ],
            }
            for c in chapters
        ]
        console.print_json(json.dumps(data))
        return

    console.print()
    console.print(
        build_chapters_table(
            tailer, path.name, chapters, grand_total_cost=tailer.total_cost_usd(), detail=detail
        )
    )


def _parse_date_arg(value: str, flag: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        print(f"error: {flag} must be YYYY-MM-DD, got {value!r}", file=sys.stderr)
        sys.exit(2)


def _in_date_range(path: Path, since: date | None, until: date | None) -> bool:
    """Filter by the transcript file's mtime - an approximation of when the
    session happened, not its exact start/end (see README). Cheap: doesn't
    require opening the file."""
    if since is None and until is None:
        return True
    mtime_date = datetime.fromtimestamp(path.stat().st_mtime).date()
    if since and mtime_date < since:
        return False
    if until and mtime_date > until:
        return False
    return True


def run_chapters_all(since: date | None = None, until: date | None = None, as_json: bool = False):
    console = Console()
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not transcripts:
        range_note = " in that date range" if (since or until) else ""
        console.print(f"[red]No session transcripts found{range_note}.[/red]")
        sys.exit(1)

    console.print(f"[dim]Chaptering {len(transcripts)} session(s) found under ~/.claude/projects/ "
                  "(retroactive - each session's own cache means already-chaptered sessions cost "
                  "nothing to re-run).[/dim]\n")

    rows = []
    grand_total_cost = 0.0
    grand_pass_cost = 0.0

    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()

        if not tailer.ordered_turns():
            # Still represent this session in the summary (a truly empty
            # transcript is rare but real - a session that never got past
            # its first prompt) rather than silently dropping it, which
            # would make the "N session(s)" count above inaccurate and
            # break the "one row per session" contract of --json.
            rows.append(
                {
                    "transcript": str(path),
                    "session_date": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
                    "num_chapters": 0,
                    "top_chapter": None,
                    "cost_usd": 0.0,
                    "unknown_model_cost": False,
                }
            )
            continue

        result = get_chapters(tailer, path)
        session_cost = tailer.total_cost_usd()
        grand_total_cost += session_cost
        grand_pass_cost += result.pass_cost_usd

        if result.fallback_reason:
            console.print(f"[yellow]{path.name}: {result.fallback_reason}[/yellow]")

        top_chapter = max(result.chapters, key=lambda c: _turns_cost(c.turns(tailer)), default=None)
        rows.append(
            {
                "transcript": str(path),
                "session_date": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
                "num_chapters": len(result.chapters),
                "top_chapter": top_chapter.title if top_chapter else None,
                "cost_usd": session_cost,
                "unknown_model_cost": tailer.has_unknown_model(),
            }
        )

    if as_json:
        import json

        console.print_json(json.dumps(rows))
        return

    table = Table(title="work-ledger chapters --all", expand=True)
    table.add_column("Date", width=11)
    table.add_column("Session", ratio=2, overflow="ellipsis")
    table.add_column("Chapters", justify="right", width=9)
    table.add_column("Top chapter", ratio=2, overflow="ellipsis")
    table.add_column("Cost (est.)", justify="right", width=12)

    any_unknown = False
    for row in rows:
        any_unknown = any_unknown or row["unknown_model_cost"]
        cost_str = _turn_cost_str(row["cost_usd"], row["unknown_model_cost"])
        table.add_row(
            row["session_date"],
            Path(row["transcript"]).stem,
            str(row["num_chapters"]),
            row["top_chapter"] or "",
            cost_str,
        )

    unknown_note = " (some models unpriced)" if any_unknown else ""
    table.add_section()
    table.add_row(
        "",
        "",
        "",
        Text("GRAND TOTAL", style="bold"),
        Text(f"${grand_total_cost:.4f}{unknown_note}", style="bold green"),
    )
    console.print(table)
    if grand_pass_cost:
        console.print(f"[dim]Chaptering across all sessions cost ${grand_pass_cost:.4f} this run.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Watch Claude Code session cost/token usage in near-real-time."
    )
    parser.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Path to a specific transcript .jsonl file (default: most recently modified session)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print current totals once and exit, instead of watching live",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Break each prompt down into its underlying units of work "
        "(one row per assistant turn), flagging skill and subagent calls",
    )

    subparsers = parser.add_subparsers(dest="command")
    chapters_parser = subparsers.add_parser(
        "chapters",
        help="Group prompts into semantic initiatives via a Haiku pass, with cost rollup per initiative",
    )
    chapters_parser.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Path to a specific transcript .jsonl file (default: most recently modified session)",
    )
    chapters_parser.add_argument(
        "--detail",
        action="store_true",
        help="Drill into each chapter/section's underlying turn/unit rows",
    )
    chapters_parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Show only one chapter, matched by title (substring ok) or 1-based index",
    )
    chapters_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    chapters_parser.add_argument(
        "--all",
        action="store_true",
        help="Chapter every session transcript found under ~/.claude/projects/, "
        "not just the active one - for applying chaptering retroactively. "
        "Each session's own cache still applies, so already-chaptered "
        "sessions cost nothing to re-run. Incompatible with --transcript/--detail/--only.",
    )
    chapters_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="With --all: only include sessions last modified on/after this date (YYYY-MM-DD). "
        "Approximate - based on the transcript file's mtime, not exact session start/end.",
    )
    chapters_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="With --all: only include sessions last modified on/before this date (YYYY-MM-DD). "
        "Approximate - based on the transcript file's mtime, not exact session start/end.",
    )

    args = parser.parse_args()

    if args.command == "chapters":
        if args.all:
            if args.transcript or args.detail or args.only:
                print("error: --all can't be combined with --transcript, --detail, or --only", file=sys.stderr)
                sys.exit(2)
            since = _parse_date_arg(args.since, "--since") if args.since else None
            until = _parse_date_arg(args.until, "--until") if args.until else None
            run_chapters_all(since=since, until=until, as_json=args.json)
            return
        if args.since or args.until:
            print("error: --since/--until only apply with --all", file=sys.stderr)
            sys.exit(2)
        transcript_path = Path(args.transcript) if args.transcript else None
        run_chapters(transcript_path=transcript_path, detail=args.detail, only=args.only, as_json=args.json)
        return

    transcript_path = Path(args.transcript) if args.transcript else None
    run(transcript_path=transcript_path, once=args.once, detail=args.detail)


if __name__ == "__main__":
    main()
