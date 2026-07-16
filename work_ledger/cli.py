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

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from work_ledger.activity import collapse_to_other, group_by_activity, top_n
from work_ledger.chapters import Chapter, get_chapters
from work_ledger.export import build_export_payload
from work_ledger.limits import (
    DEFAULT_WINDOW_HOURS,
    WindowUsage,
    compute_window_usage,
    load_threshold_tokens,
    save_threshold_tokens,
)
from work_ledger import pattern_client
from work_ledger.patterns import DEFAULT_PATTERNS_DIR, load_patterns, patterns_for_rule
from work_ledger.recommend import generate_recommendations
from work_ledger.transcript import (
    Turn,
    TranscriptTailer,
    find_active_transcript,
    find_all_transcripts,
    find_transcripts_by_session_prefix,
)

POLL_INTERVAL_S = 1.0
LIMITS_POLL_INTERVAL_S = 5.0

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


def run_chapters(
    transcript_path=None,
    detail: bool = False,
    only: str | None = None,
    as_json: bool = False,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
):
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

    if report:
        from work_ledger.report import ReportRenderError, build_report_html, render_png

        out_path = Path(report_out) if report_out else Path(f"work-ledger-chapters-{path.stem}.{report_format}")
        html = build_report_html(path.name, tailer, chapters, result.pass_cost_usd)

        if report_format == "html":
            out_path.write_text(html, encoding="utf-8")
        else:
            try:
                render_png(html, out_path)
            except ReportRenderError as e:
                console.print(f"[red]{e}[/red]")
                sys.exit(1)

        console.print(f"[green]Wrote {report_format.upper()} report to {out_path}[/green]")
        return

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


def run_activity(
    transcript_path=None,
    as_json: bool = False,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
    other_threshold: float = 0.8,
    top: int | None = None,
):
    """Cost grouped by activity type (tool/skill/subagent/direct-reply),
    not by initiative - unlike `chapters`, this makes no API call and
    needs no ANTHROPIC_API_KEY, since everything it reads is already
    parsed locally from the transcript."""
    console = Console()
    path = transcript_path or find_active_transcript()
    if path is None:
        console.print(
            "[red]No Claude Code session transcripts found under "
            "~/.claude/projects/. Run a session first, or pass --transcript.[/red]"
        )
        sys.exit(1)

    console.print(f"[dim]Watching:[/dim] {path}")

    tailer = TranscriptTailer(path)
    tailer.poll()

    buckets = group_by_activity(tailer)
    if not buckets:
        console.print("[yellow]No units found in this transcript.[/yellow]")
        return

    if report:
        from work_ledger.report import ReportRenderError, build_activity_report_html, render_png

        collapsed = top_n(buckets, top) if top is not None else collapse_to_other(buckets, threshold=other_threshold)
        out_path = Path(report_out) if report_out else Path(f"work-ledger-activity-{path.stem}.{report_format}")
        html = build_activity_report_html(path.name, collapsed, len(buckets))

        if report_format == "html":
            out_path.write_text(html, encoding="utf-8")
        else:
            try:
                render_png(html, out_path)
            except ReportRenderError as e:
                console.print(f"[red]{e}[/red]")
                sys.exit(1)

        console.print(f"[green]Wrote {report_format.upper()} report to {out_path}[/green]")
        return

    grand_total = sum(b.cost_usd for b in buckets) or 1e-9

    if as_json:
        import json

        data = [
            {"label": b.label, "cost_usd": b.cost_usd, "pct": b.cost_usd / grand_total * 100} for b in buckets
        ]
        console.print_json(json.dumps(data))
        return

    table = Table(title=f"work-ledger activity — {path.name}", expand=True)
    table.add_column("activity type", ratio=3)
    table.add_column("cost (est.)", justify="right", width=14)
    table.add_column("% of total", justify="right", width=10)
    for b in buckets:
        table.add_row(b.label, f"${b.cost_usd:.4f}", f"{b.cost_usd / grand_total * 100:.1f}%")
    console.print()
    console.print(table)


def _parse_date_arg(value: str, flag: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        print(f"error: {flag} must be YYYY-MM-DD, got {value!r}", file=sys.stderr)
        sys.exit(2)


def _validate_other_threshold(value: float) -> None:
    if not 0 <= value <= 1:
        print(
            f"error: --other-threshold must be between 0 and 1 (a fraction), got {value}",
            file=sys.stderr,
        )
        sys.exit(2)


def _validate_top(value: int | None) -> None:
    if value is not None and value <= 0:
        print(f"error: --top must be a positive integer, got {value}", file=sys.stderr)
        sys.exit(2)


def _resolve_transcript_arg(transcript: str | None, session: str | None) -> Path | None:
    """Turn --transcript/--session into a concrete Path (or None, meaning
    "fall back to find_active_transcript()") - shared by every subcommand
    that accepts either flag, so the mutual-exclusion and no-match/
    ambiguous-match errors are worded identically everywhere.

    --session takes a session's local transcript UUID (or a prefix of
    one, like a short git commit hash) and searches for it under
    ~/.claude/projects/ - it has nothing to do with a claude.ai/code
    `session_...` URL id, which isn't recorded anywhere transcript.py can
    read (see find_transcripts_by_session_prefix's docstring)."""
    if transcript and session:
        print("error: --transcript and --session are mutually exclusive", file=sys.stderr)
        sys.exit(2)
    if not session:
        return Path(transcript) if transcript else None

    matches = find_transcripts_by_session_prefix(session)
    if not matches:
        print(f"error: no transcript found with session id starting with {session!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"error: {session!r} matches {len(matches)} transcripts - be more specific:", file=sys.stderr)
        for p in matches[:10]:
            print(f"  {p.stem}", file=sys.stderr)
        if len(matches) > 10:
            print(f"  ... and {len(matches) - 10} more", file=sys.stderr)
        sys.exit(2)
    return matches[0]


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


def build_limits_table(usage: WindowUsage) -> Table:
    table = Table(title=f"work-ledger limits — rolling {usage.window_hours:g}h window", expand=True)
    table.add_column("Session", ratio=3, overflow="ellipsis")
    table.add_column("Last activity", width=13)
    table.add_column("Tokens", justify="right", width=14)
    table.add_column("Cost (est.)", justify="right", width=12)

    for s in usage.sessions:
        last = s.last_activity.astimezone().strftime("%H:%M:%S") if s.last_activity else ""
        table.add_row(
            Path(s.transcript).stem,
            last,
            f"{s.total_tokens:,}",
            f"${s.cost_usd:.4f}",
        )

    table.add_section()
    table.add_row(
        "",
        Text("TOTAL", style="bold"),
        Text(f"{usage.total_tokens:,}", style="bold green"),
        Text(f"${usage.total_cost_usd:.4f}", style="bold"),
    )
    return table


def _threshold_note(usage: WindowUsage, threshold_tokens: int | None) -> str | None:
    if not threshold_tokens:
        return None
    pct = usage.total_tokens / threshold_tokens * 100
    return f"{pct:.0f}% of your {threshold_tokens:,}-token threshold for this window"


def run_limits(
    window_hours: float = DEFAULT_WINDOW_HOURS,
    once: bool = False,
    set_threshold: int | None = None,
    as_json: bool = False,
):
    console = Console()

    if set_threshold is not None:
        save_threshold_tokens(set_threshold)
        console.print(f"[green]Saved personal threshold: {set_threshold:,} tokens for a {window_hours:g}h window.[/green]")
        return

    threshold = load_threshold_tokens()
    console.print(f"[dim]Rolling {window_hours:g}-hour window across every session under ~/.claude/projects/.[/dim]")
    console.print(
        "[dim]This is a self-calibrated estimate, not an official number - Anthropic doesn't publish "
        "the exact session-limit threshold, and Claude Code's own /status is local-display-only. "
        "Set yours with --set-threshold once you know it (check this command's total the next time "
        "Claude Code tells you you've hit your limit).[/dim]\n"
    )
    if threshold is None:
        console.print(
            "[yellow]No threshold set yet - showing raw totals only. "
            "Use --set-threshold TOKENS to calibrate.[/yellow]\n"
        )

    if as_json:
        usage = compute_window_usage(window_hours=window_hours)
        import json

        data = {
            "window_hours": window_hours,
            "threshold_tokens": threshold,
            "total_tokens": usage.total_tokens,
            "total_cost_usd": usage.total_cost_usd,
            "sessions": [
                {
                    "transcript": str(s.transcript),
                    "tokens": s.total_tokens,
                    "cost_usd": s.cost_usd,
                    "last_activity": s.last_activity.isoformat() if s.last_activity else None,
                }
                for s in usage.sessions
            ],
        }
        console.print_json(json.dumps(data))
        return

    def render():
        usage = compute_window_usage(window_hours=window_hours)
        renderables = [build_limits_table(usage)]
        note = _threshold_note(usage, threshold)
        if note:
            renderables.append(Text(note, style="bold"))
        return Group(*renderables)

    if once:
        console.print(render())
        return

    with Live(render(), console=console, refresh_per_second=1) as live:
        try:
            while True:
                time.sleep(LIMITS_POLL_INTERVAL_S)
                live.update(render())
        except KeyboardInterrupt:
            pass


def run_export(since: date | None = None, until: date | None = None, out: str | None = None):
    console = Console()
    console.print(
        "[dim]Building an anonymized export - aggregate totals and chapter-category rollups only, "
        "no chapter titles, transcript paths, or session ids. Sessions not yet chaptered will be "
        "chaptered now (same small Anthropic API cost as `chapters --all`).[/dim]\n"
    )

    result = build_export_payload(since=since, until=until)
    if result.num_sessions == 0:
        range_note = " in that date range" if (since or until) else ""
        console.print(f"[red]No session transcripts found{range_note}.[/red]")
        sys.exit(1)

    import json

    out_path = Path(out) if out else Path(f"work-ledger-export-{date.today().isoformat()}.json")
    out_path.write_text(json.dumps(result.payload, indent=2), encoding="utf-8")

    totals = result.payload["totals"]
    console.print(
        f"[green]Wrote {out_path}[/green] ({totals['sessions']} session(s), "
        f"{totals['chapters']} chapters, ${totals['cost_usd']:.4f} total)"
    )
    if result.pass_cost_usd:
        console.print(f"[dim]Chaptering newly-seen sessions for this export cost ${result.pass_cost_usd:.4f}.[/dim]")
    console.print(
        "[bold yellow]This file was not sent anywhere.[/bold yellow] Review it, then share it "
        "yourself if you want to contribute it - work-ledger never makes this call for you."
    )


def run_recommend(transcript_path=None, as_json: bool = False, mark_used: str | None = None):
    console = Console()

    if mark_used:
        sent = pattern_client.report_event(mark_used, "used")
        if sent:
            console.print(f"[green]Marked {mark_used!r} as used.[/green] Thanks - this updates the shared count.")
        elif not pattern_client.is_enabled():
            console.print(
                "[yellow]Not reported: the pattern library isn't enabled.[/yellow] "
                "Run [bold]work-ledger patterns enable[/bold] first."
            )
        else:
            console.print(
                "[yellow]Not reported: no backend configured or it was unreachable.[/yellow] "
                f"Set {pattern_client.BACKEND_URL_ENV} to report real usage - see "
                "docs/pattern-library-design.md."
            )
        return

    path = transcript_path or find_active_transcript()
    if path is None:
        console.print(
            "[red]No Claude Code session transcripts found under "
            "~/.claude/projects/. Run a session first, or pass --transcript.[/red]"
        )
        sys.exit(1)

    console.print(f"[dim]Watching:[/dim] {path}")
    console.print(
        "[dim]Recommendations are local-only heuristics over this session's own Turn/Unit/Chapter "
        "data - no corpus, no extra API call beyond chaptering itself.[/dim]\n"
    )

    tailer = TranscriptTailer(path)
    tailer.poll()
    result = get_chapters(tailer, path)
    if result.fallback_reason:
        console.print(f"[yellow]Note: {result.fallback_reason}[/yellow]")
    if result.pass_cost_usd:
        console.print(f"[dim]This chaptering pass cost ${result.pass_cost_usd:.4f}[/dim]")

    recs = generate_recommendations(result.chapters, tailer)

    # Pattern-library augmentation is entirely opt-in (work-ledger patterns
    # enable) - until then recommend's output is unchanged from before this
    # existed. Matching is the v1 mechanism from
    # docs/pattern-library-design.md: a library entry only ever gets
    # attached to a local rule that actually fired with the same rule_id,
    # never independent matching against raw transcript data.
    library_matches: dict[str, list] = {}
    if pattern_client.is_enabled():
        entries = load_patterns(DEFAULT_PATTERNS_DIR)
        for r in recs:
            matches = patterns_for_rule(entries, r.rule_id)
            if matches:
                library_matches[r.rule_id] = matches
                for m in matches:
                    pattern_client.report_event(m.id, "recommended")

    if as_json:
        import json

        data = [
            {
                "rule_id": r.rule_id,
                "title": r.title,
                "detail": r.detail,
                "cost_usd": r.cost_usd,
                "library_matches": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "fix": m.fix,
                        "recommended_count": m.recommended_count,
                        "used_count": m.used_count,
                    }
                    for m in library_matches.get(r.rule_id, [])
                ],
            }
            for r in recs
        ]
        console.print_json(json.dumps(data))
        return

    console.print()
    if not recs:
        console.print("[green]No recommendations - nothing matched the current heuristics.[/green]")
        return

    table = Table(title=f"work-ledger recommend — {path.name}", expand=True)
    table.add_column("At stake", justify="right", width=12)
    table.add_column("Recommendation", ratio=3, overflow="fold")

    for r in recs:
        detail_text = Text()
        detail_text.append(r.title, style="bold")
        detail_text.append(f"\n{r.detail}", style="dim")
        for m in library_matches.get(r.rule_id, []):
            detail_text.append(
                f"\n★ Community pattern: {m.title} "
                f"(recommended {m.recommended_count}x, used {m.used_count}x)\n  {m.fix}",
                style="cyan",
            )
        table.add_row(f"${r.cost_usd:.4f}", detail_text)

    console.print(table)


def run_patterns(action: str):
    console = Console()

    if action == "enable":
        pattern_client.enable()
        console.print("[green]Pattern library enabled.[/green]")
        console.print(
            "[dim]`recommend` will now show matching community patterns alongside its own "
            "findings, and report anonymous recommended/used counts if a backend is "
            f"configured ({pattern_client.BACKEND_URL_ENV}). Without one configured, matching "
            "still works locally - there's just nowhere to report counts to yet, since no "
            "backend is hosted by this project (see docs/pattern-library-design.md).[/dim]"
        )
        return

    if action == "disable":
        pattern_client.disable()
        console.print("[green]Pattern library disabled.[/green] `recommend` is unchanged from before it existed.")
        return

    if action == "status":
        enabled = pattern_client.is_enabled()
        console.print(f"Pattern library: {'[green]enabled[/green]' if enabled else '[yellow]disabled[/yellow]'}")
        if enabled:
            install_id = pattern_client.get_or_create_install_id()
            console.print(f"Install id: {install_id}")
            url = pattern_client.backend_url()
            console.print(f"Backend: {url or '[yellow]not configured[/yellow] (' + pattern_client.BACKEND_URL_ENV + ' unset)'}")
        return

    if action == "list":
        entries = load_patterns(DEFAULT_PATTERNS_DIR)
        if not entries:
            console.print(f"[dim]No pattern entries found under {DEFAULT_PATTERNS_DIR}[/dim]")
            return
        table = Table(title="work-ledger pattern library", expand=True)
        table.add_column("id", ratio=2)
        table.add_column("category", width=14)
        table.add_column("maps_to", ratio=1)
        table.add_column("rec.", justify="right", width=6)
        table.add_column("used", justify="right", width=6)
        for e in entries:
            table.add_row(e.id, e.category, e.maps_to_rule_id or "", str(e.recommended_count), str(e.used_count))
        console.print(table)
        return


def _add_transcript_args(parser: argparse.ArgumentParser) -> None:
    """--transcript and --session are two ways to pick a specific
    session, added identically to every subcommand that needs one - see
    _resolve_transcript_arg for how they're reconciled."""
    parser.add_argument(
        "--transcript",
        type=str,
        default=None,
        help="Path to a specific transcript .jsonl file (default: most recently modified session)",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        metavar="UUID_OR_PREFIX",
        help="Pick a session by its local transcript UUID (or a prefix of one, like a short git "
        "commit hash) instead of a full --transcript path. Searches ~/.claude/projects/ for a "
        "matching filename. Mutually exclusive with --transcript. Not the same id as a "
        "claude.ai/code session_... URL - there's no local mapping from that id to a transcript.",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Watch Claude Code session cost/token usage in near-real-time."
    )
    _add_transcript_args(parser)
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
    _add_transcript_args(chapters_parser)
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
    chapters_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a visual report (HTML or PNG) to a file instead of a terminal table. "
        "Not yet supported with --all.",
    )
    chapters_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png"],
        default="html",
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium",
    )
    chapters_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-chapters-<session>.<format>)",
    )

    activity_parser = subparsers.add_parser(
        "activity",
        help="Cost grouped by activity type (tool/skill/subagent/direct-reply) instead of "
        "initiative - unlike `chapters`, needs no ANTHROPIC_API_KEY and makes no API call",
    )
    _add_transcript_args(activity_parser)
    activity_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    activity_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a visual report (HTML or PNG) to a file instead of a terminal table",
    )
    activity_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png"],
        default="html",
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium",
    )
    activity_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-activity-<session>.<format>)",
    )
    activity_parser.add_argument(
        "--other-threshold",
        type=float,
        default=0.8,
        metavar="FRACTION",
        help="With --report: show activity types individually until their running cost "
        "crosses this fraction of the total (default: 0.8, i.e. 80%%), then fold the rest "
        "into one residual bucket. Ignored if --top is given. Only affects --report, not "
        "the table/--json views, which always show every activity type.",
    )
    activity_parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="With --report: show only the N costliest activity types individually, folding "
        "everything else into one residual bucket - a hard count cutoff instead of "
        "--other-threshold's percentage cutoff. Takes precedence over --other-threshold "
        "if both are given.",
    )

    limits_parser = subparsers.add_parser(
        "limits",
        help="Track rolling-window token usage across all sessions, as a self-calibrated proxy "
        "for the Claude Pro/Max session limit (not an official number - see the command's own note)",
    )
    limits_parser.add_argument(
        "--once",
        action="store_true",
        help="Print a snapshot once and exit, instead of watching live",
    )
    limits_parser.add_argument(
        "--window-hours",
        type=float,
        default=DEFAULT_WINDOW_HOURS,
        help=f"Rolling window size in hours (default: {DEFAULT_WINDOW_HOURS:g}, matching Claude's "
        "session window; use e.g. 168 for a rough weekly view)",
    )
    limits_parser.add_argument(
        "--set-threshold",
        type=int,
        default=None,
        metavar="TOKENS",
        help="Save your own calibrated token threshold for this window size, then exit",
    )
    limits_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Write an anonymized, manual usage export (aggregates + chapter-category rollups "
        "only) to a local JSON file - never sent anywhere automatically",
    )
    export_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include sessions last modified on/after this date (YYYY-MM-DD)",
    )
    export_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only include sessions last modified on/before this date (YYYY-MM-DD)",
    )
    export_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path (default: work-ledger-export-<date>.json)",
    )

    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Local-only, rule-based recommendations over one session's Turn/Unit/Chapter data "
        "(no corpus, no extra API call beyond chaptering itself)",
    )
    _add_transcript_args(recommend_parser)
    recommend_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    recommend_parser.add_argument(
        "--mark-used",
        type=str,
        default=None,
        metavar="ID",
        help="Confirm you applied a pattern-library entry's fix, incrementing its shared "
        "used count. Requires `work-ledger patterns enable` first.",
    )

    patterns_parser = subparsers.add_parser(
        "patterns",
        help="Manage the shared pattern library (see docs/pattern-library-design.md) - "
        "opt-in, off by default",
    )
    patterns_parser.add_argument(
        "action",
        choices=["enable", "disable", "status", "list"],
        help="enable/disable the pattern library, show its current status, or list "
        "locally-available entries",
    )

    args = parser.parse_args()

    if args.command == "limits":
        run_limits(
            window_hours=args.window_hours,
            once=args.once,
            set_threshold=args.set_threshold,
            as_json=args.json,
        )
        return

    if args.command == "export":
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        run_export(since=since, until=until, out=args.out)
        return

    if args.command == "recommend":
        transcript_path = _resolve_transcript_arg(args.transcript, args.session)
        run_recommend(transcript_path=transcript_path, as_json=args.json, mark_used=args.mark_used)
        return

    if args.command == "patterns":
        run_patterns(args.action)
        return

    if args.command == "activity":
        if args.report and args.json:
            print("error: --report and --json are mutually exclusive", file=sys.stderr)
            sys.exit(2)
        _validate_top(args.top)
        if args.top is None:
            _validate_other_threshold(args.other_threshold)
        transcript_path = _resolve_transcript_arg(args.transcript, args.session)
        run_activity(
            transcript_path=transcript_path,
            as_json=args.json,
            report=args.report,
            report_format=args.format,
            report_out=args.out,
            other_threshold=args.other_threshold,
            top=args.top,
        )
        return

    if args.command == "chapters":
        if args.all:
            if args.transcript or args.session or args.detail or args.only:
                print(
                    "error: --all can't be combined with --transcript, --session, --detail, or --only",
                    file=sys.stderr,
                )
                sys.exit(2)
            if args.report:
                print("error: --report doesn't support --all yet (see issue #4/#7)", file=sys.stderr)
                sys.exit(2)
            since = _parse_date_arg(args.since, "--since") if args.since else None
            until = _parse_date_arg(args.until, "--until") if args.until else None
            run_chapters_all(since=since, until=until, as_json=args.json)
            return
        if args.since or args.until:
            print("error: --since/--until only apply with --all", file=sys.stderr)
            sys.exit(2)
        if args.report and args.json:
            print("error: --report and --json are mutually exclusive", file=sys.stderr)
            sys.exit(2)
        transcript_path = _resolve_transcript_arg(args.transcript, args.session)
        run_chapters(
            transcript_path=transcript_path,
            detail=args.detail,
            only=args.only,
            as_json=args.json,
            report=args.report,
            report_format=args.format,
            report_out=args.out,
        )
        return

    transcript_path = _resolve_transcript_arg(args.transcript, args.session)
    run(transcript_path=transcript_path, once=args.once, detail=args.detail)


if __name__ == "__main__":
    main()
