"""Terminal dashboard: tails the active Claude Code session transcript and
shows running cost/token usage per prompt, updating in near-real-time.

No telemetry setup, no server, no browser - just run it in a terminal next
to your session. The `chapters` subcommand adds a separate, on-demand
semantic layer on top (see docs/session-chaptering-design.md): it groups
prompts into initiatives via a small Haiku pass and links back into this
same per-unit rendering for drill-down (`chapters --detail`).
"""

import argparse
import os
import sys
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from work_ledger.activity import collapse_to_other, group_by_activity, top_n
from work_ledger.chapters import (
    Chapter,
    cached_chapters,
    check_credentials,
    format_pass_note,
    get_chapters,
    has_uncached_turns,
)
from work_ledger.export import build_export_payload
from work_ledger.history import sync_history, get_status as get_history_status
from work_ledger.limits import (
    DEFAULT_WINDOW_HOURS,
    WindowUsage,
    compute_rate_limit_history,
    compute_window_usage,
    load_threshold_tokens,
    save_threshold_tokens,
)
from work_ledger import pattern_client
from work_ledger.patterns import DEFAULT_PATTERNS_DIR, load_patterns, patterns_for_rule
from work_ledger.recommend import generate_recommendations
from work_ledger.rollup import (
    RollupResult,
    build_rollup_result,
    is_other_cluster,
)
from work_ledger.rollup import collapse_to_other as collapse_rollup_clusters_to_other
from work_ledger.rollup import fold_below_cost as fold_rollup_clusters_below_cost
from work_ledger.rollup import top_n_clusters as top_n_rollup_clusters
from work_ledger.rollup import with_cumulative as with_rollup_cumulative
from work_ledger import rollup_presets
from work_ledger import rollup_semantic
from work_ledger.session_pin import clear_pinned_session, get_pinned_session, set_pinned_session
from work_ledger.timeline import (
    DEFAULT_WINDOW_DAYS,
    build_timeline,
    summarize_timeline,
    top_activity_labels,
    top_category_labels,
)
from work_ledger.trend import BUCKET_SIZES, build_trend
from work_ledger.transcript import (
    Turn,
    TranscriptTailer,
    find_active_transcript,
    find_all_transcripts,
    find_transcripts_by_session_prefix,
)
from work_ledger.waste import find_cross_session_waste_patterns, find_waste_patterns

POLL_INTERVAL_S = 1.0
LIMITS_POLL_INTERVAL_S = 5.0

UNIT_KIND_STYLE = {
    "skill": "cyan",
    "subagent": "magenta",
    "text": "dim",
}

TABLE_COLUMNS = ("Time", "Prompt / task", "Calls", "In tok", "Out tok", "Cost (est.)")


# Both notes below back #46: two known attribution gaps in transcript.py
# that used to be documented only in README prose. Surfacing them in the
# CLI itself means a user sees the caveat at the moment a number might be
# an undercount, not only if they happen to read the README first.


def _sidechain_warning(tailer: "TranscriptTailer") -> str | None:
    """Non-None if this transcript had inline isSidechain entries (an
    older/different transcript format - see transcript.py's module
    docstring) that were skipped rather than parsed. When that happens,
    this session's cost is a silent undercount unless we say so."""
    n = tailer.skipped_sidechain_count
    if n == 0:
        return None
    entry_word = "entry was" if n == 1 else "entries were"
    return (
        f"[yellow]Warning: {n} inlined subagent (isSidechain) {entry_word} skipped in "
        "this transcript - this session's cost may be an undercount. See README's "
        '"Known limitation on subagent attribution".[/yellow]'
    )


_SKILL_FOLLOWON_NOTE = (
    "[dim]Note: \"Skill:\" cost reflects only the invoking call - any follow-on work "
    "a skill drives isn't currently bounded to that skill, since transcripts carry no "
    "scope marker for where a skill's driven work ends (see README's \"Known "
    "limitation on subagent attribution\").[/dim]"
)


def _has_skill_units(turns: list["Turn"]) -> bool:
    return any(unit.kind == "skill" for turn in turns for unit in turn.units)


def _unit_cost_str(unit) -> str:
    return "?" if unit.unknown_model_cost and unit.cost_usd == 0 else f"${unit.cost_usd:.4f}"


def _turn_cost_str(turn_or_turns_cost: float, unknown: bool) -> str:
    return "?" if unknown and turn_or_turns_cost == 0 else f"${turn_or_turns_cost:.4f}"


def _unpriced_note(unknown: bool) -> str:
    """The " (some models unpriced)" suffix on a total's cost cell. Stays
    short deliberately - the cost column is narrow, so the model names go
    in the table's caption (see _unpriced_caption) where they fit."""
    return " (some models unpriced)" if unknown else ""


def _unpriced_caption(models: Iterable[str]) -> str | None:
    """The full-width line under a table naming the models that had no
    rate, or None when there's nothing to name.

    Naming them is the point of #104: `claude-opus-5` went unpriced for
    weeks while it was the default model, and every surface said only that
    *some* model was unpriced - identical text whether 0.1% or 99% of turns
    were affected, and never a hint which one-line table entry was missing.
    Returns None rather than "" so it can be assigned straight to
    Table.caption, where None means "no caption".
    """
    named = sorted(set(models))
    if not named:
        return None
    return f"Unpriced (no rate in pricing.py, shown as \"?\"): {', '.join(named)}"


def _turns_unpriced_models(turns: Iterable[Turn]) -> set[str]:
    models: set[str] = set()
    for turn in turns:
        models |= turn.unpriced_models
    return models


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
    unknown_note = _unpriced_note(tailer.has_unknown_model())
    table.caption = _unpriced_caption(tailer.unpriced_models())
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

    warning = _sidechain_warning(tailer)
    if warning:
        console.print(warning)
    if detail and _has_skill_units(tailer.ordered_turns()):
        console.print(_SKILL_FOLLOWON_NOTE)

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
    unpriced_models: set[str] = set()

    for i, chapter in enumerate(chapters, start=1):
        turns = chapter.turns(tailer)
        cost = _turns_cost(turns)
        unknown = _turns_unknown(turns)
        pct = (cost / grand_total_cost * 100) if grand_total_cost else 0.0
        total_cost += cost
        total_in += sum(t.input_tokens for t in turns)
        total_out += sum(t.output_tokens for t in turns)
        any_unknown = any_unknown or unknown
        unpriced_models |= _turns_unpriced_models(turns)

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

    unknown_note = _unpriced_note(any_unknown)
    table.caption = _unpriced_caption(unpriced_models)
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

    warning = _sidechain_warning(tailer)
    if warning:
        console.print(warning)
    if detail and _has_skill_units(tailer.ordered_turns()):
        console.print(_SKILL_FOLLOWON_NOTE)

    result = get_chapters(tailer, path)

    if result.fallback_reason:
        console.print(f"[yellow]Note: {result.fallback_reason}[/yellow]")
    pass_note = format_pass_note(result)
    if pass_note:
        console.print(f"[dim]This chaptering pass {pass_note}[/dim]")

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
                # escape(): ReportRenderError's own message can contain a
                # literal "[report]" (the pip extra name) - unescaped, rich
                # markup parsing silently swallows it as an (invalid) style
                # tag, corrupting the exact "pip install work-ledger[report]"
                # command the message is trying to hand the user.
                console.print(f"[red]{escape(str(e))}[/red]")
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

    warning = _sidechain_warning(tailer)
    if warning:
        console.print(warning)

    buckets = group_by_activity(tailer)
    if not buckets:
        console.print("[yellow]No units found in this transcript.[/yellow]")
        return

    if any(b.label.startswith("Skill:") for b in buckets):
        console.print(_SKILL_FOLLOWON_NOTE)

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
                # escape(): ReportRenderError's own message can contain a
                # literal "[report]" (the pip extra name) - unescaped, rich
                # markup parsing silently swallows it as an (invalid) style
                # tag, corrupting the exact "pip install work-ledger[report]"
                # command the message is trying to hand the user.
                console.print(f"[red]{escape(str(e))}[/red]")
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


_WASTE_KIND_LABELS = {
    "repeated-read": "Repeated file read",
    "repeated-subagent": "Repeated subagent dispatch",
}


def run_waste(
    transcript_path=None,
    as_json: bool = False,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
):
    """Within-session waste mining (#5): flags the same file Read more than
    once, or the same subagent dispatched more than once with a
    near-identical description, plus their combined cost - a starting
    point, not a recommendation (that's `recommend`/issue #6). Read-only,
    no API call, no chaptering required: like `activity`, everything it
    reads is already parsed locally from the transcript. If this session
    already has cached chapters (from a prior `work-ledger chapters` run),
    patterns are scoped to the chapter they fell in rather than just the
    whole session - `cached_chapters` never triggers a paid Haiku pass as
    a side effect of running this command."""
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
        "[dim]Within-session only - the same pattern recurring across separate sessions "
        "of the same initiative isn't detected here, see `waste --cross-session`. "
        "No API call, no chaptering required.[/dim]\n"
    )

    tailer = TranscriptTailer(path)
    tailer.poll()

    warning = _sidechain_warning(tailer)
    if warning:
        console.print(warning)

    chapters = cached_chapters(path)
    patterns = find_waste_patterns(tailer, chapters)

    if report:
        from work_ledger.report import ReportRenderError, build_waste_report_html, render_png

        out_path = Path(report_out) if report_out else Path(f"work-ledger-waste-{path.stem}.{report_format}")
        html = build_waste_report_html(path.name, patterns)

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
                "kind": p.kind,
                "scope": p.scope,
                "label": p.label,
                "occurrences": p.occurrences,
                "cost_usd": p.cost_usd,
            }
            for p in patterns
        ]
        console.print_json(json.dumps(data))
        return

    console.print()
    if not patterns:
        console.print("[green]No repeated patterns found - nothing matched the current heuristics.[/green]")
        return

    table = Table(title=f"work-ledger waste — {path.name}", expand=True)
    table.add_column("Pattern", width=26)
    table.add_column("Scope", ratio=2, overflow="ellipsis")
    table.add_column("Detail", ratio=3, overflow="fold")
    table.add_column("Times", justify="right", width=7)
    table.add_column("Cost (est.)", justify="right", width=12)

    total_cost = 0.0
    for p in patterns:
        total_cost += p.cost_usd
        table.add_row(
            _WASTE_KIND_LABELS.get(p.kind, p.kind),
            p.scope,
            p.label,
            str(p.occurrences),
            f"${p.cost_usd:.4f}",
        )

    table.add_section()
    table.add_row(
        "",
        "",
        Text("TOTAL flagged", style="bold"),
        "",
        Text(f"${total_cost:.4f}", style="bold green"),
    )
    console.print(table)
    console.print(
        "[dim]This surfaces the pattern and its cost only - not what to do about it "
        "(see issue #6, deliberately separate).[/dim]"
    )


def run_waste_cross_session(
    since: date | None = None,
    until: date | None = None,
    as_json: bool = False,
    confirm: bool = False,
):
    """Cross-session half of #5: the same two waste-mining pattern kinds
    as `waste`, but scoped to a recurring initiative (a #3 rollup cluster)
    across every session it touched, instead of one chapter/session. Only
    reads whatever chapters are already cached - never triggers a new
    chaptering pass, same invariant as `rollup`. A pattern only shows up
    here once it spans 2+ distinct sessions; a single-session repeat is
    already fully covered by plain `waste`.

    Clustering (including the #68 semantic pass, opt-in via
    WORK_LEDGER_ROLLUP_MATCHING=semantic) is computed once via
    `build_rollup_result` and handed to `find_cross_session_waste_patterns`
    - the same result `rollup` itself would compute for this transcript
    set, and the same one `--confirm` reports on below, rather than a
    second independent (and, with no caching, possibly different) call."""
    console = Console()
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not transcripts:
        range_note = " in that date range" if (since or until) else ""
        console.print(f"[red]No session transcripts found{range_note}.[/red]")
        sys.exit(1)

    uncached = _count_sessions_needing_chaptering(transcripts)
    rollup_result = build_rollup_result(transcripts)
    patterns = find_cross_session_waste_patterns(transcripts, rollup_result=rollup_result)

    if as_json:
        import json

        data = [
            {
                "kind": p.kind,
                "initiative": p.initiative,
                "label": p.label,
                "occurrences": p.occurrences,
                "num_sessions": p.num_sessions,
                "cost_usd": p.cost_usd,
            }
            for p in patterns
        ]
        console.print_json(json.dumps(data))
        return

    console.print(
        f"[dim]Cross-session waste mining across {len(transcripts)} session(s) found under "
        "~/.claude/projects/, using whatever's already cached (never re-chapters). Clusters "
        "sessions into initiatives the same way `rollup` does (issue #3).[/dim]\n"
    )

    if not patterns:
        console.print(
            "[green]No repeated patterns found spanning 2+ sessions of the same "
            "initiative - nothing matched the current heuristics.[/green]"
        )
        if uncached:
            console.print(
                f"[dim]{uncached} of {len(transcripts)} session(s) have no cached chapters yet "
                "and aren't reflected above - run `work-ledger chapters --all` to include "
                "them.[/dim]"
            )
        _print_semantic_matching_note(console, rollup_result, confirm)
        return

    table = Table(title="work-ledger waste --cross-session", expand=True)
    table.add_column("Pattern", width=14, overflow="ellipsis")
    table.add_column("Initiative", ratio=2, overflow="ellipsis")
    table.add_column("Detail", ratio=3, overflow="fold")
    table.add_column("Sessions", justify="right", width=8)
    table.add_column("Times", justify="right", width=5)
    table.add_column("Cost (est.)", justify="right", width=11)

    total_cost = 0.0
    for p in patterns:
        total_cost += p.cost_usd
        table.add_row(
            _WASTE_KIND_LABELS.get(p.kind, p.kind),
            p.initiative,
            p.label,
            str(p.num_sessions),
            str(p.occurrences),
            f"${p.cost_usd:.4f}",
        )

    table.add_section()
    table.add_row(
        "",
        "",
        Text("TOTAL flagged", style="bold"),
        "",
        "",
        Text(f"${total_cost:.4f}", style="bold green"),
    )
    console.print(table)
    console.print(
        "[dim]This surfaces the pattern and its cost only - not what to do about it "
        "(see issue #6, deliberately separate).[/dim]"
    )
    if uncached:
        console.print(
            f"[dim]{uncached} of {len(transcripts)} session(s) have no cached chapters yet and "
            "aren't reflected above - run `work-ledger chapters --all` to include them.[/dim]"
        )
    _print_semantic_matching_note(console, rollup_result, confirm)


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


def _validate_top_initiatives(value: int | None) -> None:
    if value is not None and value <= 0:
        print(f"error: --top-initiatives must be a positive integer, got {value}", file=sys.stderr)
        sys.exit(2)


def _validate_min_cost(value: float | None) -> None:
    if value is not None and value < 0:
        print(f"error: --min-cost must be zero or positive, got {value}", file=sys.stderr)
        sys.exit(2)


def _resolve_rollup_flags(args: argparse.Namespace) -> dict:
    """Merge --miso's built-in bundle or --preset's saved bundle (lowest
    precedence) with whatever flags were actually passed on this
    invocation (highest precedence) - issue #97's answer to "too many
    flags to remember." --since/--until/--out are deliberately never
    part of either bundle (see rollup_presets.py) - callers read those
    straight off `args` as always, untouched by this function.

    A value-bearing flag (e.g. --other-threshold) not passed on the CLI
    is None on `args` (argparse's own default for every one of these),
    which doubles as "fall through to the bundle" - the bundle's own
    absence of a key then falls through again to run_rollup's normal
    defaults. A store_true flag (e.g. --confirm) can't distinguish
    "explicitly not requested" from "just not mentioned" - there's no
    CLI syntax for the former anyway - so it's simply OR'd with the
    bundle's value: either source asking for it is enough."""
    bundle: dict = {}
    if args.miso:
        bundle = dict(rollup_presets.MISO_PRESET)
    elif args.preset:
        stored = rollup_presets.get_preset(args.preset)
        if stored is None:
            print(
                f"error: no saved preset named {args.preset!r}. Run --list-presets to see what's saved.",
                file=sys.stderr,
            )
            sys.exit(2)
        bundle = dict(stored)

    def value(flag: str, cli_value):
        return cli_value if cli_value is not None else bundle.get(flag)

    def flag_on(flag: str, cli_value: bool) -> bool:
        return bool(cli_value) or bool(bundle.get(flag, False))

    return {
        "as_json": flag_on("json", args.json),
        "confirm": flag_on("confirm", args.confirm),
        "top": value("top", args.top),
        "report": flag_on("report", args.report),
        "report_format": value("format", args.format) or "html",
        "other_threshold": value("other_threshold", args.other_threshold),
        "top_initiatives": value("top_initiatives", args.top_initiatives),
        "min_cost": value("min_cost", args.min_cost),
        "preview": flag_on("preview", args.preview),
        "semantic": flag_on("semantic", args.semantic),
    }


def _validate_top(value: int | None) -> None:
    if value is not None and value <= 0:
        print(f"error: --top must be a positive integer, got {value}", file=sys.stderr)
        sys.exit(2)


# Subcommands that redefine --transcript/--session on their own parser
# (via _add_transcript_args) - see _check_transcript_flag_placement for why
# that duplication matters. limits/export/patterns/sessions don't accept
# either flag at all, so there's no ambiguity to check for those.
_COMMANDS_WITH_OWN_TRANSCRIPT_FLAGS = {"chapters", "activity", "recommend", "miso", "waste"}


def _check_transcript_flag_placement(argv: list[str], command: str | None) -> None:
    """--transcript/--session are defined on both the top-level parser (for
    the plain `work-ledger --transcript X` dashboard form, with no
    subcommand) and on chapters'/activity's/recommend's own parsers (for
    the documented `work-ledger <command> --transcript X` form). Verified
    via a minimal argparse repro (not guessed): when the same dest is
    defined on both, argparse's subparsers action always lets the
    subcommand's own parsed value - including its unset default - win over
    whatever the parent already parsed, silently discarding it. That makes
    `work-ledger --session X chapters` silently ignore --session entirely
    and fall back to "most recently active session," with no error - a
    real bug a user hit in practice, not a hypothetical.

    Fixing this to actually *work* would mean either breaking the
    documented `work-ledger <command> --transcript X` form (removing the
    subcommand's own definition) or fragile raw-argv value-recovery. Given
    the "before the subcommand" placement was never actually documented
    (every example puts the flag either with no subcommand at all, or
    after one), the correct fix is to reject that specific combination
    outright with a clear, actionable error instead of silently using the
    wrong session."""
    if command not in _COMMANDS_WITH_OWN_TRANSCRIPT_FLAGS:
        return
    try:
        command_index = argv.index(command)
    except ValueError:
        return
    before, after = argv[:command_index], argv[command_index + 1 :]
    for flag in ("--transcript", "--session"):
        appears_before = any(tok == flag or tok.startswith(flag + "=") for tok in before)
        appears_after = any(tok == flag or tok.startswith(flag + "=") for tok in after)
        if appears_before and not appears_after:
            print(
                f"error: {flag} must come after '{command}', not before it - e.g. "
                f"`work-ledger {command} {flag} ...`, not `work-ledger {flag} ... {command}`. "
                "Placing it before the subcommand name silently ignores it (a known "
                "argparse limitation with subcommands - see _check_transcript_flag_placement), "
                "so this is rejected rather than silently watching the wrong session.",
                file=sys.stderr,
            )
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
    read (see find_transcripts_by_session_prefix's docstring).

    If neither is given, a pinned session (`work-ledger session set ...`)
    takes priority over the usual "most recently active" default - an
    explicit --transcript/--session on this specific call still overrides
    the pin, same as any explicit flag beats a saved default."""
    if transcript and session:
        print("error: --transcript and --session are mutually exclusive", file=sys.stderr)
        sys.exit(2)
    if not session:
        if transcript:
            return Path(transcript)
        return get_pinned_session()

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


def _count_sessions_needing_chaptering(transcripts: list[Path]) -> int:
    """How many of `transcripts` have real turns not yet covered by a
    chapters cache - i.e. running `chapters --all` would actually change
    something for them. Deliberately excludes genuinely empty (zero-turn)
    sessions: `cached_chapters` returns [] for those forever (chapters
    --all skips them outright, see run_chapters_all), so counting them as
    "needs chapters --all" is misleading - re-running it can never resolve
    a session with nothing to chapter. Mirrors the has_uncached_turns-based
    accounting timeline.py's build_timeline already uses; `rollup`/`waste
    --cross-session` used the cheaper-but-wrong `not cached_chapters(p)`
    check before this helper existed, which overcounted exactly these
    empty sessions as actionable."""
    count = 0
    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        if not tailer.ordered_turns():
            continue
        if has_uncached_turns(tailer, path):
            count += 1
    return count


def run_session(action: str, value: str | None) -> None:
    """Manage the pinned session (`work-ledger session set/clear/status`) -
    see session_pin.py and _resolve_transcript_arg's docstring for how the
    pin is consumed. `set`'s no-match/ambiguous-prefix errors reuse
    _resolve_transcript_arg's own (via session=value, transcript=None) so
    the wording matches --session's errors exactly rather than drifting."""
    console = Console()
    if action == "set":
        if not value:
            print(
                "error: 'session set' needs a uuid-or-prefix, e.g. `work-ledger session set abc123` "
                "- see `work-ledger sessions` to find one",
                file=sys.stderr,
            )
            sys.exit(2)
        path = _resolve_transcript_arg(None, value)
        set_pinned_session(path)
        console.print(f"[green]Pinned session:[/green] {path.stem}")
        console.print("[dim]Every command defaults to this session now, until `work-ledger session clear`.[/dim]")
        return

    if action == "clear":
        clear_pinned_session()
        console.print("[green]Cleared.[/green] Commands default to the most recently active session again.")
        return

    if action == "status":
        pinned = get_pinned_session()
        if pinned:
            console.print(f"Pinned session: [cyan]{pinned.stem}[/cyan]")
            console.print(f"[dim]{pinned}[/dim]")
        else:
            console.print("[yellow]No session pinned.[/yellow] Commands default to the most recently active session.")
        return


def run_history(action: str) -> None:
    """Manage the local session history store (issue #42) -
    `history sync`/`history status`. This is additive infrastructure other
    commands can build on later (starting with #3's cross-session rollup);
    it is not wired into chapters --all/timeline/trend/serve, which keep
    working exactly as before via their own live sweeps."""
    console = Console()

    if action == "sync":
        console.print(
            "[dim]Syncing local session history store - unchanged sessions (by transcript "
            "mtime) are skipped without being re-read.[/dim]"
        )
        result = sync_history()
        console.print(
            f"[green]Synced.[/green] {result.total_transcripts} session(s) checked, "
            f"{result.updated} updated, {result.unchanged} unchanged (already current)."
        )
        return

    if action == "status":
        status = get_history_status()
        console.print(f"History database: [cyan]{status.db_path}[/cyan]")
        console.print(f"Sessions stored: {status.row_count}")
        if status.row_count:
            console.print(f"Oldest sync: {status.oldest_synced_at}")
            console.print(f"Newest sync: {status.newest_synced_at}")
        else:
            console.print("[yellow]No sessions synced yet.[/yellow] Run `work-ledger history sync`.")
        return


def _parse_turn_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _session_duration_minutes(turns: list[Turn]) -> float:
    """Wall-clock span from the first turn's timestamp to the last's - 0 for
    a single-turn (or empty) session, not just "no data". Real per-turn
    timestamps, not the transcript file's mtime `last_active` already uses -
    same distinction timeline.py draws between the two."""
    if len(turns) < 2:
        return 0.0
    start = _parse_turn_timestamp(turns[0].timestamp)
    end = _parse_turn_timestamp(turns[-1].timestamp)
    if start is None or end is None:
        return 0.0
    return max(0.0, (end - start).total_seconds() / 60)


_SUMMARY_MAX_CHAPTER_TITLES = 3
_SUMMARY_PROMPT_TRUNCATE = 140


def _session_summary(path: Path, first_prompt: str) -> str:
    """A one-line "what was this session about" - free, since it only ever
    reads whatever's already cached (cached_chapters never calls the
    model, same invariant server.py's browsing relies on). Chapter titles
    are themselves short initiative descriptions, so joining them is a
    reasonable summary; falls back to the first prompt for a session
    that isn't chaptered yet, same fallback `sessions`'s own listing
    already leans on for "what is this session" discovery."""
    chapters = cached_chapters(path)
    if chapters:
        titles = [c.title for c in chapters]
        shown = titles[:_SUMMARY_MAX_CHAPTER_TITLES]
        summary = "; ".join(shown)
        remaining = len(titles) - len(shown)
        if remaining > 0:
            summary += f" (+{remaining} more)"
        return summary
    if not first_prompt:
        return "(no prompts)"
    if len(first_prompt) > _SUMMARY_PROMPT_TRUNCATE:
        return first_prompt[:_SUMMARY_PROMPT_TRUNCATE].rstrip() + "…"
    return first_prompt


def build_session_rows(transcripts: list[Path]) -> list[dict]:
    """Per-session summary rows (project, last-active time, first/last
    prompt, turn count, cost, duration, total tokens, a one-line summary)
    - the same shape `sessions`/`sessions --json` render as a table.
    Factored out of run_sessions so `work-ledger serve`'s landing page
    (see server.py) reuses exactly this computation rather than
    re-deriving it - there's exactly one place this data is assembled."""
    rows = []
    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        turns = tailer.ordered_turns()
        first_prompt = turns[0].prompt_snippet if turns else ""
        rows.append(
            {
                "session": path.stem,
                "project": path.parent.name,
                "last_active": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes"),
                "num_turns": len(turns),
                "first_prompt": first_prompt,
                "last_prompt": turns[-1].prompt_snippet if turns else "",
                "cost_usd": tailer.total_cost_usd(),
                "duration_minutes": _session_duration_minutes(turns),
                "total_tokens": tailer.total_input_tokens() + tailer.total_output_tokens(),
                "summary": _session_summary(path, first_prompt),
            }
        )
    return rows


def top_n_session_rows(rows: list[dict], top: int | None) -> list[dict]:
    """`rows` (build_session_rows' shape) truncated to the `top` costliest,
    cost-descending - or `rows` unchanged if `top` is None. Factored out of
    run_sessions so server.py's `serve --top` landing page ranks sessions
    exactly the same way `sessions --top` does, rather than a second
    reimplementation that could drift."""
    if top is None:
        return rows
    return sorted(rows, key=lambda r: r["cost_usd"], reverse=True)[:top]


def top_n_transcripts_by_cost(transcripts: list[Path], top: int | None) -> list[Path]:
    """`transcripts` truncated to the `top` costliest by the exact same
    ranking top_n_session_rows uses (same build_session_rows cost
    computation) - or unchanged if `top` is None. Lets `rollup --top`
    cluster within "my N most expensive sessions" specifically, matching
    `sessions --top`/`serve --top`'s meaning of --top rather than a
    second, different one (contrast `activity --report --top`, which
    truncates already-computed buckets, not sessions - a different axis
    entirely, not a naming collision in practice since they're different
    commands)."""
    if top is None:
        return transcripts
    rows = build_session_rows(transcripts)
    paired = sorted(zip(transcripts, rows), key=lambda pr: pr[1]["cost_usd"], reverse=True)[:top]
    return [p for p, _ in paired]


def run_sessions(
    since: date | None = None,
    until: date | None = None,
    as_json: bool = False,
    top: int | None = None,
):
    """Lightweight listing of every local session transcript, newest first -
    no chaptering, no API call, just what's already parsed locally (last
    active time, first/last prompt, turn count, cost). Meant for discovery:
    "what sessions exist, which one do I mean" before reaching for
    --transcript/--session on another command - a claude.ai/code
    session_... URL can't answer that (see --session's own help text),
    but this listing doesn't need that id at all.

    Both the first and last prompt are shown, not just the first - a
    long-running or resumed session's first prompt (e.g. "how do we track
    X") often stops reflecting what the session is actually about by the
    time you're trying to identify it later; the most recent prompt is
    frequently the more useful cue.

    `top`, when given, switches the sort from newest-first to cost-
    descending and truncates to that many rows - "which sessions are
    actually expensive" instead of "what did I run most recently". Every
    session in --since/--until range still gets its cost computed first
    (no cheaper partial path exists - the cost has to be read to be
    ranked); `top` only trims what's printed, not what's read."""
    console = Console()
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not transcripts:
        range_note = " in that date range" if (since or until) else ""
        console.print(f"[red]No session transcripts found{range_note}.[/red]")
        sys.exit(1)

    rows = build_session_rows(transcripts)

    title = "work-ledger sessions"
    if top is not None:
        rows = top_n_session_rows(rows, top)
        title = f"work-ledger sessions — top {len(rows)} by cost"

    if as_json:
        import json

        console.print_json(json.dumps(rows))
        return

    table = Table(title=title, expand=True)
    table.add_column("Session id", width=10)
    table.add_column("Project", ratio=1, overflow="ellipsis")
    table.add_column("Last active", width=16)
    table.add_column("Turns", justify="right", width=5)
    table.add_column("First prompt", ratio=2, overflow="ellipsis")
    table.add_column("Last prompt", ratio=2, overflow="ellipsis")
    table.add_column("Cost (est.)", justify="right", width=12)
    for r in rows:
        table.add_row(
            r["session"][:8] + "…",
            r["project"],
            r["last_active"],
            str(r["num_turns"]),
            r["first_prompt"] or "[dim](empty)[/dim]",
            r["last_prompt"] or "[dim](empty)[/dim]",
            f"${r['cost_usd']:.4f}",
        )
    console.print()
    console.print(table)
    console.print("[dim]Pass a session's id to --session (a prefix is enough) on another command.[/dim]")


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
                    "unpriced_models": [],
                    "skipped_sidechain_count": tailer.skipped_sidechain_count,
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
                "unpriced_models": tailer.unpriced_models(),
                "skipped_sidechain_count": tailer.skipped_sidechain_count,
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
    unpriced_models: set[str] = set()
    for row in rows:
        any_unknown = any_unknown or row["unknown_model_cost"]
        unpriced_models |= set(row["unpriced_models"])
        cost_str = _turn_cost_str(row["cost_usd"], row["unknown_model_cost"])
        table.add_row(
            row["session_date"],
            Path(row["transcript"]).stem,
            str(row["num_chapters"]),
            row["top_chapter"] or "",
            cost_str,
        )

    unknown_note = _unpriced_note(any_unknown)
    table.caption = _unpriced_caption(unpriced_models)
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
    total_skipped_sidechain = sum(row["skipped_sidechain_count"] for row in rows)
    if total_skipped_sidechain:
        console.print(
            f"[yellow]Warning: {total_skipped_sidechain} inlined subagent (isSidechain) "
            "entries were skipped across these sessions - their cost may be an "
            'undercount. See README\'s "Known limitation on subagent attribution".[/yellow]'
        )


def _print_semantic_matching_note(
    console: Console, result: RollupResult, confirm: bool, semantic_enabled: bool | None = None
) -> None:
    """Print whatever the semantic pass (#68) did this run - a no-op
    entirely when semantic matching wasn't in effect, which is how
    default output (env var unset) stays byte-for-byte unchanged.
    Otherwise always distinguishes "found nothing new to merge" from
    "the pass couldn't run at all" (see rollup_semantic.py's module
    docstring - never a silent difference between the two). `--confirm`
    additionally lists exactly which singleton titles merged into which
    cluster - deliberately minimal, visibility only, not an audit trail
    (see the design doc's Non-goals).

    `semantic_enabled`, when given, is trusted over re-checking the env
    var live (issue #97/#99's bug: run_rollup's `--semantic` sets
    WORK_LEDGER_ROLLUP_MATCHING only for the duration of its own
    build_rollup_result call and restores it before this function ever
    runs, so re-deriving "was semantic on" from the env var here would
    silently print nothing - including swallowing a semantic-pass
    failure's own fallback_reason, exactly the note this function
    exists to surface). None (the default) falls back to checking the
    env var live, unchanged behavior for callers that never touch it
    temporarily (`waste --cross-session`)."""
    if semantic_enabled is None:
        semantic_enabled = rollup_semantic.is_semantic_enabled()
    if not semantic_enabled:
        return
    if result.semantic_fallback_reason:
        console.print(f"[yellow]Note: {result.semantic_fallback_reason}[/yellow]")
    elif result.semantic_merges:
        console.print(
            f"[dim]Semantic matching (WORK_LEDGER_ROLLUP_MATCHING=semantic) merged "
            f"{len(result.semantic_merges)} group(s) of singleton titles into existing "
            "clusters this run - nothing is cached, a later run may cluster differently. "
            "Pass --confirm to see exactly what merged.[/dim]"
        )
    else:
        console.print(
            "[dim]Semantic matching ran (WORK_LEDGER_ROLLUP_MATCHING=semantic) but found "
            "nothing new to merge this run.[/dim]"
        )

    if confirm and result.semantic_merges:
        console.print("[bold]Merged via semantic matching:[/bold]")
        for merge in result.semantic_merges:
            joined = " + ".join(f"{t!r}" for t in merge.titles)
            console.print(f"  {joined} → {merge.merged_title!r}")


def run_rollup(
    since: date | None = None,
    until: date | None = None,
    as_json: bool = False,
    confirm: bool = False,
    top: int | None = None,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
    other_threshold: float | None = None,
    top_initiatives: int | None = None,
    min_cost: float | None = None,
    preview: bool = False,
    semantic: bool = False,
):
    """Cluster the same recurring initiative's chapters across every
    session it touched and total its cost - issue #3. Unlike `chapters
    --all`'s flat per-session listing, this answers "how much has 'Fix
    the double-counting bug' cost in total" directly, by matching
    normalized chapter titles across sessions (see rollup.py's module
    docstring for exactly how, and why that's deterministic-only for v1,
    not an LLM/embedding pass) - plus, opt-in via
    `WORK_LEDGER_ROLLUP_MATCHING=semantic`, a second batched Haiku pass
    over whatever's still a singleton (issue #68, see rollup_semantic.py).

    Reuses whatever chapters are already cached for each session in
    range - never triggers a new chaptering pass itself, so running this
    costs nothing beyond having already run `chapters`/`chapters --all`
    at some point. No default date window (unlike `trend`/`timeline`):
    the whole point of a rollup is a true total across every session an
    initiative touched, not a recent slice.

    `top`, when given, clusters within just the N most expensive sessions
    in range (top_n_transcripts_by_cost - same ranking `sessions --top`/
    `serve --top` use) instead of every session in range - "merge across
    just the sessions I already know are expensive" instead of everything.
    `report` renders the clustering as a shareable HTML/PNG/CSV file
    (build_rollup_report_html/build_rollup_csv) instead of a terminal
    table/--json - the "give my boss a report on what I've been spending
    on" case a localhost-only `serve` page can't cover.

    `other_threshold`/`top_initiatives`/`min_cost` (issue #93) each fold
    part of the cluster list into one "All other" cluster - a percentage-
    of-total cutoff, a hard count cutoff, and an absolute-dollar cutoff
    respectively (rollup.collapse_to_other/top_n_clusters/
    fold_below_cost). At most one actually runs per call - precedence is
    top_initiatives, then min_cost, then other_threshold, matching each
    flag's own help text - applied once, up front, so the table/
    --preview/--report/--json below all agree on the same (possibly
    collapsed) cluster list rather than each collapsing it their own way.
    `preview` prints the same table the default (no --report/--json)
    path already shows, but also works alongside --report/--json so you
    can see what a file will contain before writing it.

    `semantic` (issue #97) is a normal-flag shorthand for
    WORK_LEDGER_ROLLUP_MATCHING=semantic, scoped to just this call - sets
    the env var only for the duration of build_rollup_result below (never
    touches it if it's already set, and always restores whatever was
    there before on the way out, including for tests that call this
    function repeatedly in one process). Doesn't change what the env var
    itself does or costs - purely "one less thing to remember to type,"
    see rollup_presets.py."""
    console = Console()
    all_transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not all_transcripts:
        range_note = " in that date range" if (since or until) else ""
        console.print(f"[red]No session transcripts found{range_note}.[/red]")
        sys.exit(1)

    transcripts = top_n_transcripts_by_cost(all_transcripts, top)

    env_var = rollup_semantic.ROLLUP_MATCHING_ENV_VAR
    already_set = env_var in os.environ
    semantic_enabled_this_run = semantic or already_set  # captured before restoring below - see
    # _print_semantic_matching_note's semantic_enabled param docstring for why this can't just
    # re-check the env var later
    if semantic and not already_set:
        os.environ[env_var] = rollup_semantic.SEMANTIC_MATCHING
    try:
        result = build_rollup_result(transcripts)
    finally:
        if semantic and not already_set:
            del os.environ[env_var]
    clusters = result.clusters
    uncached = _count_sessions_needing_chaptering(transcripts)

    if not clusters:
        console.print(
            "[yellow]No cached chapters found across these sessions.[/yellow] Run "
            "`work-ledger chapters --all` first (small Anthropic API cost) to chapter them."
        )
        return

    n_before_collapse = len(clusters)
    collapse_note = None
    if top_initiatives is not None:
        clusters = top_n_rollup_clusters(clusters, top_initiatives)
        collapse_note = f"--top-initiatives {top_initiatives}"
    elif min_cost is not None:
        clusters = fold_rollup_clusters_below_cost(clusters, min_cost)
        collapse_note = f"--min-cost {min_cost:.2f}"
    elif other_threshold is not None:
        clusters = collapse_rollup_clusters_to_other(clusters, threshold=other_threshold)
        collapse_note = f"--other-threshold {other_threshold}"

    if report:
        from work_ledger.report import ReportRenderError, build_rollup_csv, build_rollup_report_html, render_png

        out_path = Path(report_out) if report_out else Path(f"work-ledger-rollup-{date.today().isoformat()}.{report_format}")

        if report_format == "csv":
            out_path.write_text(build_rollup_csv(clusters), encoding="utf-8")
        else:
            html_content = build_rollup_report_html(
                clusters,
                n_sessions_included=len(transcripts),
                n_sessions_total=len(all_transcripts),
                since=since,
                until=until,
                top=top,
            )
            if report_format == "html":
                out_path.write_text(html_content, encoding="utf-8")
            else:
                try:
                    render_png(html_content, out_path)
                except ReportRenderError as e:
                    console.print(f"[red]{escape(str(e))}[/red]")
                    sys.exit(1)

        console.print(f"[green]Wrote {report_format.upper()} report to {out_path}[/green]")

    if as_json:
        import json

        data = [
            {
                "title": c.display_title,
                "num_sessions": c.num_sessions,
                "num_chapters": c.num_chapters,
                "sessions": c.sessions,
                "cost_usd": c.cost_usd,
                "unknown_model_cost": c.unknown_model_cost,
                "unpriced_models": sorted(c.unpriced_models),
                "is_other": is_other_cluster(c),
            }
            for c in clusters
        ]
        console.print_json(json.dumps(data))

    show_table = preview or (not report and not as_json)
    if not show_table:
        return

    console.print(
        f"[dim]Clustering chapters across {len(transcripts)} session(s) found under "
        "~/.claude/projects/, using whatever's already cached (never re-chapters).[/dim]\n"
    )

    table = Table(title="work-ledger rollup", expand=True)
    table.add_column("Initiative", ratio=2, overflow="ellipsis")
    table.add_column("Sessions", justify="right", width=9)
    table.add_column("Chapters", justify="right", width=9)
    table.add_column("Cost (est.)", justify="right", width=12)
    # Cumulative % only, not also cumulative $ - the Pareto-relevant number,
    # and keeping this column narrow leaves the Initiative column (the one
    # that actually needs the room) from getting ellipsis-truncated too
    # aggressively in an 80-col terminal. Exact cumulative dollars are
    # already in --json/--format csv for anyone who wants them.
    table.add_column("Cumulative", justify="right", width=10)

    grand_total_cost = 0.0
    any_unknown = False
    unpriced_models: set[str] = set()
    for c, _cum_cost, cum_pct in with_rollup_cumulative(clusters):
        any_unknown = any_unknown or c.unknown_model_cost
        unpriced_models |= c.unpriced_models
        grand_total_cost += c.cost_usd
        title_cell = f"[dim italic]{c.display_title}[/dim italic]" if is_other_cluster(c) else c.display_title
        table.add_row(
            title_cell,
            str(c.num_sessions),
            str(c.num_chapters),
            _turn_cost_str(c.cost_usd, c.unknown_model_cost),
            f"{cum_pct:.0f}%",
        )

    unknown_note = _unpriced_note(any_unknown)
    table.caption = _unpriced_caption(unpriced_models)
    table.add_section()
    table.add_row(
        "",
        "",
        Text("GRAND TOTAL", style="bold"),
        Text(f"${grand_total_cost:.4f}{unknown_note}", style="bold green"),
        Text("100%", style="bold green"),
    )
    console.print(table)
    if collapse_note is not None and len(clusters) < n_before_collapse:
        n_folded = n_before_collapse - len(clusters) + 1
        console.print(
            f"[dim]{n_folded} of {n_before_collapse} initiatives folded into 'All other' at "
            f"{collapse_note} (shown as one row above).[/dim]"
        )
    if uncached:
        console.print(
            f"[dim]{uncached} of {len(transcripts)} session(s) have no cached chapters yet and "
            "aren't reflected above - run `work-ledger chapters --all` to include them.[/dim]"
        )
    _print_semantic_matching_note(console, result, confirm, semantic_enabled=semantic_enabled_this_run)


_INSTALL_MODE_LABELS = {
    "editable": "editable clone (pip install -e .)",
    "published-pypi": "published install (PyPI)",
    "published-git": "published install (git ref)",
}


def run_cycle_command(check_status: bool = False, port: int | None = None) -> None:
    """`work-ledger cycle` (issue #73) - the upgrade/restart path
    CLAUDE.md's "CLI/MCP command conventions" section requires. See
    cycle.py's module docstring and docs/cycle-command-design.md for the
    full mechanism; this is just the terminal presentation layer."""
    from work_ledger import cycle as cycle_mod

    console = Console()
    resolved_port = port if port is not None else cycle_mod.DEFAULT_SERVE_PORT

    try:
        report = cycle_mod.check_status(resolved_port) if check_status else cycle_mod.run_cycle(resolved_port)
    except cycle_mod.CycleError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        sys.exit(1)

    mode_label = _INSTALL_MODE_LABELS.get(report.install.mode, report.install.mode)
    console.print(f"[bold]Install mode:[/bold] {mode_label}")
    if report.install.mode == "editable":
        console.print(f"[dim]Repo: {report.install.repo_root}[/dim]")
    else:
        console.print(f"[dim]Version: {report.install.version}[/dim]")

    if report.serve_port_in_use:
        console.print(
            f"[yellow]Something is listening on 127.0.0.1:{report.serve_port} - looks like "
            "`work-ledger serve` may be running. Stop it (Ctrl-C) before or after cycling and "
            "restart it yourself afterward; this command never signals another process.[/yellow]"
        )
    else:
        console.print(f"[dim]Nothing detected listening on 127.0.0.1:{report.serve_port}.[/dim]")

    if check_status:
        console.print()
        if report.install.mode == "editable":
            console.print("[dim]Plain `work-ledger cycle` would run `git pull` in the repo above.[/dim]")
        else:
            command = " ".join(cycle_mod.upgrade_command(report.install))
            console.print(f"[dim]Plain `work-ledger cycle` would run: {command}[/dim]")
        return

    console.print()
    if report.action == "git pull":
        if report.changed:
            console.print(f"[green]Pulled new commits: {report.before[:10]} → {report.after[:10]}[/green]")
        else:
            console.print(f"[green]Already up to date at {report.before[:10]}.[/green]")
    else:
        console.print(f"[dim]Ran: {report.action}[/dim]")
        if report.changed:
            console.print(f"[green]Upgraded: {report.before} → {report.after}[/green]")
        else:
            console.print(f"[green]Already at the latest published version ({report.before}).[/green]")


def run_about_command(as_json: bool = False) -> None:
    """`work-ledger about` (issue #75) - the metadata-hygiene block
    CLAUDE.md's "CLI/MCP command conventions" section requires: short
    description, version, last-updated, commit (if resolvable), and
    author/repo attribution. See about.py's module docstring for how
    those fields are computed; this is just the terminal presentation
    layer, same split run_cycle_command already draws against cycle.py."""
    from work_ledger.about import get_about_info

    info = get_about_info()

    if as_json:
        import json

        console = Console()
        console.print_json(
            json.dumps(
                {
                    "description": info.description,
                    "version": info.version,
                    "last_updated": info.last_updated,
                    "commit": info.commit,
                    "author_email": info.author_email,
                    "author_url": info.author_url,
                    "repo_url": info.repo_url,
                }
            )
        )
        return

    console = Console()
    console.print("[bold]work-ledger[/bold]")
    console.print(info.description)
    console.print()
    console.print(f"[dim]Version:[/dim]      {info.version}")
    console.print(f"[dim]Last updated:[/dim] {info.last_updated}")
    console.print(f"[dim]Commit:[/dim]       {info.commit or '(not resolvable from this install)'}")
    console.print()
    console.print(f"[dim]Author:[/dim]       {info.author_email} · {info.author_url}")
    console.print(f"[dim]Source:[/dim]       {info.repo_url}")


def _print_status_checks(console: Console) -> tuple[bool, str, bool, str]:
    """Print the two `--check-status` checks (chaptering credentials, PNG
    rendering) and return their (ok, message) pairs so the caller can
    branch on them. Shared by `miso --check-status` (which stops right
    here) and plain `miso` (which prints this same block up front, before
    doing any work, per issue #35's requirement that failures surface
    before partial work happens - not the middle of a run)."""
    from work_ledger.report import png_available  # lazy: keeps report.py off the hot path for every other command

    cred_ok, cred_msg = check_credentials()
    png_ok, png_msg = png_available()
    # escape(): the PNG-unavailable message contains a literal "[report]"
    # (the pip extra name) - unescaped, rich's markup parser silently
    # swallows it as an (invalid) style tag, corrupting the exact
    # "pip install work-ledger[report]" command the message hands the
    # user. Escaping once here, and returning the escaped text, means
    # every later reuse of cred_msg/png_msg (the closing summary, the
    # --check-status "what this means" block) is already safe to
    # interpolate into more rich markup without repeating this at each
    # call site.
    cred_msg = escape(cred_msg)
    png_msg = escape(png_msg)

    console.print("[bold]Status check[/bold]")
    cred_style = "green" if cred_ok else "yellow"
    console.print(f"  [{cred_style}]{'OK      ' if cred_ok else 'DEGRADED'}[/{cred_style}] Chaptering credentials — {cred_msg}")
    png_style = "green" if png_ok else "yellow"
    console.print(f"  [{png_style}]{'OK      ' if png_ok else 'DEGRADED'}[/{png_style}] PNG rendering        — {png_msg}")
    console.print()
    return cred_ok, cred_msg, png_ok, png_msg


def _write_html_and_maybe_png(html_content: str, base_name: str, png_ok: bool) -> dict:
    """Write `<base_name>.html` always, and attempt `<base_name>.png` too
    if PNG rendering looked available at the (cheap, import-only)
    --check-status level. That check can't see everything though - the
    `report` extra can be installed while `playwright install chromium`
    was never run, which only shows up when render_png actually tries to
    launch a browser. Catching ReportRenderError here means that specific
    failure degrades this one report to HTML-only rather than aborting the
    rest of miso's pipeline - graceful degradation applies per-step, not
    just at the top. Returns what actually happened so run_miso's closing
    summary can report it precisely rather than repeating the earlier
    (necessarily approximate) --check-status guess."""
    from work_ledger.report import ReportRenderError, render_png

    html_path = Path(f"{base_name}.html")
    html_path.write_text(html_content, encoding="utf-8")
    outcome = {"html": html_path, "png": None, "png_error": None}
    if png_ok:
        png_path = Path(f"{base_name}.png")
        try:
            render_png(html_content, png_path)
            outcome["png"] = png_path
        except ReportRenderError as e:
            outcome["png_error"] = str(e)
    return outcome


def run_miso(
    transcript_path=None,
    check_status_only: bool = False,
    all_sessions: bool = False,
    since: date | None = None,
    until: date | None = None,
):
    """`miso` ("make it so") - issue #35's end-to-end, one-shot command:
    chaptering plus both HTML/PNG reports in a single run, instead of
    remembering the right sequence of `chapters --report`/`activity
    --report` invocations and flags. Pure orchestration over existing
    Show-stage functionality (see CLAUDE.md's rubric) - every step below
    calls the exact same functions run_chapters/run_activity already call
    (get_chapters, build_report_html, build_activity_report_html,
    render_png); nothing here reimplements any of that, and no new network
    call is made beyond chaptering's existing Haiku pass.

    Always prints the same checks `--check-status` reports, up front,
    before touching a transcript or writing a file - so a missing
    credential or a missing `report` extra is visible before any partial
    work happens, not discovered midway through (the issue's own
    `git rebase` comparison: always know where you are and what to do
    next). `check_status_only=True` (the `--check-status` flag) stops
    right after printing that block: no transcript is read, no API call
    is made, no file is written - a pure environment diagnostic.

    `--all` reuses run_chapters_all's existing cross-session sweep as-is
    rather than inventing a multi-session report shape: `chapters --report`
    itself doesn't support `--all` yet (issue #4/#7), and generating a
    report per session here would be new work, not orchestration of
    something that already exists - so --all gets the chaptering summary
    only, with a clear pointer to drop --all for a single session's
    reports."""
    console = Console()
    console.print("[bold]work-ledger miso[/bold] [dim]— chapters + reports, end-to-end[/dim]\n")

    cred_ok, cred_msg, png_ok, png_msg = _print_status_checks(console)

    if check_status_only:
        console.print("[bold]What this means for a real run:[/bold]")
        if cred_ok:
            console.print("  - Chaptering will call the Haiku API and label real initiatives.")
        else:
            console.print(f"  - Chaptering will fall back to a single \"Unsorted\" chapter. Fix: {cred_msg}")
        if png_ok:
            console.print("  - Both HTML and PNG reports will be generated.")
        else:
            console.print(f"  - Only HTML reports will be generated (PNG skipped). Fix: {png_msg}")
        console.print(
            "\n[dim]This only checked your environment - no transcript was read and no API "
            "call was made.[/dim]"
        )
        return

    if all_sessions:
        run_chapters_all(since=since, until=until, as_json=False)
        console.print(
            "\n[yellow]Visual reports (--report) aren't generated in --all mode[/yellow] - the "
            "same scope limit `chapters --report` already has (see issue #4/#7). Drop --all and "
            "pick one session (--transcript/--session, or let miso default to the active/pinned "
            "one) to get HTML/PNG reports for it."
        )
        return

    path = transcript_path or find_active_transcript()
    if path is None:
        console.print(
            "[red]No Claude Code session transcripts found under "
            "~/.claude/projects/. Run a session first, or pass --transcript.[/red]"
        )
        sys.exit(1)

    console.print(f"[dim]Session:[/dim] {path}\n")

    tailer = TranscriptTailer(path)
    tailer.poll()

    warning = _sidechain_warning(tailer)
    if warning:
        console.print(warning)

    # --- Chapters: terminal table + HTML/PNG report -----------------------
    result = get_chapters(tailer, path)
    if result.fallback_reason:
        console.print(f"[yellow]Note: {result.fallback_reason}[/yellow]")
    pass_note = format_pass_note(result)
    if pass_note:
        console.print(f"[dim]This chaptering pass {pass_note}[/dim]")

    chapters = _sorted_by_cost(tailer, result.chapters)
    console.print()
    console.print(
        build_chapters_table(tailer, path.name, chapters, grand_total_cost=tailer.total_cost_usd())
    )

    from work_ledger.report import build_activity_report_html, build_report_html

    chapters_html = build_report_html(path.name, tailer, chapters, result.pass_cost_usd)
    chapters_files = _write_html_and_maybe_png(
        chapters_html, f"work-ledger-miso-chapters-{path.stem}", png_ok
    )

    # --- Activity: terminal table + HTML/PNG report ------------------------
    buckets = group_by_activity(tailer)
    activity_files = None
    if not buckets:
        console.print("\n[yellow]No units found in this transcript - skipping the activity report.[/yellow]")
    else:
        console.print()
        activity_table = Table(title=f"work-ledger activity — {path.name}", expand=True)
        activity_table.add_column("activity type", ratio=3)
        activity_table.add_column("cost (est.)", justify="right", width=14)
        activity_table.add_column("% of total", justify="right", width=10)
        grand_total = sum(b.cost_usd for b in buckets) or 1e-9
        for b in buckets:
            activity_table.add_row(b.label, f"${b.cost_usd:.4f}", f"{b.cost_usd / grand_total * 100:.1f}%")
        console.print(activity_table)

        activity_html = build_activity_report_html(path.name, collapse_to_other(buckets), len(buckets))
        activity_files = _write_html_and_maybe_png(
            activity_html, f"work-ledger-miso-activity-{path.stem}", png_ok
        )

    # --- Closing summary: where things stand, what to do next -------------
    console.print()
    console.print("[bold]Done — where things stand:[/bold]")
    if result.fallback_reason:
        console.print(f"  Chapters: fell back to \"Unsorted\" - fix: {cred_msg}")
    elif result.pass_cost_usd or result.wall_clock_s:
        console.print(f"  Chapters: {len(chapters)} chapter(s) labeled ({format_pass_note(result)} this pass)")
    else:
        console.print(f"  Chapters: {len(chapters)} chapter(s) labeled (from cache - no new API cost)")

    report_line = f"chapters -> {chapters_files['html']}"
    if chapters_files["png"]:
        report_line += f", {chapters_files['png']}"
    console.print(f"  Reports:  {report_line}")
    if activity_files:
        activity_line = f"activity  -> {activity_files['html']}"
        if activity_files["png"]:
            activity_line += f", {activity_files['png']}"
        console.print(f"            {activity_line}")

    if not png_ok:
        console.print(f"  [yellow]PNG skipped for both reports - fix: {png_msg}[/yellow]")
    else:
        png_errors = [e for e in (chapters_files.get("png_error"), (activity_files or {}).get("png_error")) if e]
        if png_errors:
            console.print(f"  [yellow]PNG rendering failed - fix: {escape(png_errors[0])}[/yellow]")


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


def _rate_limit_hit_note(hits) -> str | None:
    """Factual companion to _threshold_note - the actual recorded
    session-limit hits (see compute_rate_limit_history), not an estimate.
    See docs/recommend-workflow-efficiency-design.md Open Question 2."""
    if not hits:
        return None
    n = len(hits)
    when = ", ".join(
        f"{r.hit.timestamp.split('T')[-1][:5]} UTC (resets {r.hit.reset_label or 'unknown'})" for r in hits
    )
    return f"You actually hit your session limit {n} time{'s' if n != 1 else ''} in this window: {when}"


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
        rate_limit_hits = compute_rate_limit_history(window_hours=window_hours)
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
            "rate_limit_hits": [
                {
                    "transcript": str(r.transcript),
                    "timestamp": r.hit.timestamp,
                    "reset_label": r.hit.reset_label,
                }
                for r in rate_limit_hits
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
        hit_note = _rate_limit_hit_note(compute_rate_limit_history(window_hours=window_hours))
        if hit_note:
            renderables.append(Text(hit_note, style="bold yellow"))
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


_SPARKLINE_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[int]) -> str:
    """Render values as a Unicode block sparkline, scaled 0-7 against this
    series' own max. Each series is scaled independently, so comparing
    sparkline *height* across two different series/rows isn't meaningful -
    only one series' own shape over time is."""
    max_v = max(values) if values else 0
    if max_v <= 0:
        return _SPARKLINE_BLOCKS[0] * len(values)
    return "".join(
        _SPARKLINE_BLOCKS[min(len(_SPARKLINE_BLOCKS) - 1, int(v / max_v * (len(_SPARKLINE_BLOCKS) - 1)))]
        for v in values
    )


def _render_timeline_sparklines(console: Console, result, top_activity: list[str], top_categories: list[str]) -> None:
    days = result.days
    console.print(f"[bold]work-ledger timeline[/bold]  [dim]{days[0].day} to {days[-1].day}[/dim]\n")

    console.print("[bold]Activity mix[/bold] [dim](tool/skill/subagent, by day - activity.py's own categories)[/dim]")
    for label in top_activity:
        values = [b.activity_counts.get(label, 0) for b in days]
        console.print(f"  {label:<32} {_sparkline(values)}  [dim]max {max(values)}/day[/dim]")

    console.print("\n[bold]Approach mix[/bold] [dim](chapter category, by day)[/dim]")
    if not top_categories:
        console.print("  [dim](no chaptered sessions in range - run `work-ledger timeline backfill`)[/dim]")
    else:
        for label in top_categories:
            values = [b.category_counts.get(label, 0) for b in days]
            console.print(f"  {label:<32} {_sparkline(values)}  [dim]max {max(values)}/day[/dim]")


def run_timeline(
    since: date | None = None,
    until: date | None = None,
    as_json: bool = False,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
    summary: bool = False,
):
    """How tool usage and approach have changed over time - day-bucketed
    activity mix (activity.py's own tool/skill/subagent categorization,
    just sliced by day) plus chapter-category mix from whatever's already
    cached. Defaults to the last DEFAULT_WINDOW_DAYS days if neither
    --since nor --until is given: there's no persisted cross-session store
    yet (issue #42 not required for this), so every run re-derives from
    transcripts fresh, same as `chapters --all` - an unbounded sweep would
    be slower and answer "all-time" rather than the more useful "recently"
    default. Makes no API call itself; see `timeline backfill` for the
    explicit, cost-disclosed way to complete category data for uncached
    sessions. `summary` only affects the plain terminal view (see
    summarize_timeline() in timeline.py) - --report gets the narrative
    line unconditionally, since it's a small addition to a view that's
    already comprehensive; --json stays raw data, no narrative."""
    console = Console()
    if since is None and until is None:
        since = date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)

    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not transcripts:
        console.print("[red]No session transcripts found in that range.[/red]")
        sys.exit(1)

    result = build_timeline(transcripts)
    if not result.days:
        console.print("[yellow]No turns found in that range.[/yellow]")
        return

    if result.uncached_sessions:
        console.print(
            f"[yellow]{result.uncached_sessions} of {result.total_sessions} session(s) in range aren't "
            "fully chaptered - approach mix will be incomplete for those. Run "
            "`work-ledger timeline backfill` to fill it in (small Anthropic API cost).[/yellow]\n"
        )

    top_activity = top_activity_labels(result.days)
    top_categories = top_category_labels(result.days)

    if report:
        from work_ledger.report import ReportRenderError, build_timeline_report_html, render_png

        range_label = f"{since.isoformat() if since else 'earliest'} to {until.isoformat() if until else 'now'}"
        out_path = (
            Path(report_out) if report_out else Path(f"work-ledger-timeline-{date.today().isoformat()}.{report_format}")
        )
        html = build_timeline_report_html(
            range_label,
            result.days,
            top_activity,
            top_categories,
            result.total_sessions,
            result.uncached_sessions,
        )
        if report_format == "html":
            out_path.write_text(html, encoding="utf-8")
        else:
            try:
                render_png(html, out_path)
            except ReportRenderError as e:
                # escape(): ReportRenderError's own message can contain a
                # literal "[report]" (the pip extra name) - unescaped, rich
                # markup parsing silently swallows it as an (invalid) style
                # tag, corrupting the exact "pip install work-ledger[report]"
                # command the message is trying to hand the user.
                console.print(f"[red]{escape(str(e))}[/red]")
                sys.exit(1)
        console.print(f"[green]Wrote {report_format.upper()} report to {out_path}[/green]")
        return

    if as_json:
        import json

        data = [
            {"day": b.day, "activity_counts": b.activity_counts, "category_counts": b.category_counts}
            for b in result.days
        ]
        console.print_json(json.dumps(data))
        return

    console.print()
    if summary:
        # Printed above the sparklines, not instead of them - --summary is
        # an additional lens on the same data (docs/timeline-narrative-and
        # -maturity-design.md's Part 1), same "additive, doesn't replace
        # the granular view" precedent as every other flag on this command.
        narrative = summarize_timeline(result.days)
        if narrative:
            console.print(f"[bold]Summary[/bold]  {narrative}\n")
        else:
            console.print(
                "[dim]Summary: not enough day-to-day category data yet for a meaningful "
                "narrative.[/dim]\n"
            )
    _render_timeline_sparklines(console, result, top_activity, top_categories)


def run_timeline_backfill(since: date | None = None, until: date | None = None, summary: bool = False) -> None:
    """Chapter any session in range that isn't fully cached yet, then show
    the resulting timeline - the explicit, cost-disclosed way to complete
    the approach-mix panel that plain `timeline` otherwise leaves partial
    rather than paying for silently. Reuses get_chapters()'s existing
    cache: an already-fully-chaptered session costs nothing to touch
    again, same as `chapters --all`."""
    console = Console()
    effective_since = since if since is not None else date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, effective_since, until)]
    if not transcripts:
        console.print("[red]No session transcripts found in that range.[/red]")
        sys.exit(1)

    console.print(
        f"[dim]Chaptering {len(transcripts)} session(s) in range - already-cached sessions cost "
        "nothing to re-run, needs ANTHROPIC_API_KEY for anything genuinely new.[/dim]\n"
    )

    total_cost = 0.0
    newly_processed = 0
    fallback_count = 0
    for path in transcripts:
        tailer = TranscriptTailer(path)
        tailer.poll()
        if not tailer.ordered_turns():
            continue
        result = get_chapters(tailer, path)
        # pass_cost_usd is 0 both when there was nothing new to chapter
        # (already fully cached) AND when new turns existed but the model
        # call fell back (no/invalid key, refusal, etc) - fallback_reason
        # is what actually distinguishes "new turns were processed" from
        # "cache hit, untouched", so both count as newly_processed here.
        if result.pass_cost_usd or result.fallback_reason:
            newly_processed += 1
            total_cost += result.pass_cost_usd
            if result.fallback_reason:
                fallback_count += 1
                console.print(f"[yellow]{path.name}: {result.fallback_reason}[/yellow]")

    if newly_processed:
        note = f" ({fallback_count} fell back to Unsorted, see above)" if fallback_count else ""
        console.print(f"[green]Processed {newly_processed} session(s) newly for ${total_cost:.4f}{note}.[/green]\n")
    else:
        console.print("[green]Everything in range was already cached - nothing new to chapter.[/green]\n")

    run_timeline(since=effective_since, until=until, summary=summary)


def _cost_bar(cost: float, max_cost: float, width: int = 30) -> str:
    """Proportional block-bar for one period's cost against this trend's own
    max - same idea as _sparkline's per-series scaling, just rendered as one
    solid bar per row instead of a single-character-per-value line, since a
    per-period table row has room for a longer, more legible bar."""
    if max_cost <= 0:
        return ""
    filled = max(0, min(width, round(cost / max_cost * width)))
    return "█" * filled


_UNIT_ADVERB = {"day": "daily", "week": "weekly"}


def _render_trend(console: Console, result) -> None:
    buckets = result.buckets
    unit = "day" if result.bucket_size == "day" else "week"
    console.print(
        f"[bold]work-ledger trend[/bold]  [dim]{buckets[0].period} to {buckets[-1].period} "
        f"({_UNIT_ADVERB[unit]}, cost only - see `timeline` for activity/approach mix)[/dim]\n"
    )

    # Reuses _sparkline exactly (same block set, same independent-max
    # scaling) rather than a different terminal visual language - scaled in
    # cents for a bit more resolution than whole-dollar ints would give.
    cents = [round(b.cost_usd * 100) for b in buckets]
    max_cost = max((b.cost_usd for b in buckets), default=0.0)
    console.print(f"  {'Cost':<12} {_sparkline(cents)}  [dim]max ${max_cost:.2f}/{unit}[/dim]\n")

    table = Table(title=f"work-ledger trend — cost by {unit}", expand=True)
    table.add_column("Period", width=14)
    table.add_column("Cost (est.)", justify="right", width=14)
    table.add_column("Turns", justify="right", width=8)
    table.add_column("", ratio=1, overflow="crop")  # bar column, no header
    for b in buckets:
        cost_str = "?" if b.unknown_model_cost and b.cost_usd == 0 else f"${b.cost_usd:.4f}"
        table.add_row(
            b.period,
            cost_str,
            str(b.num_turns),
            Text(_cost_bar(b.cost_usd, max_cost), style="cyan"),
        )
    console.print(table)

    console.print(
        f"\n[dim]Total across {len(buckets)} {unit}(s), {result.total_sessions} session(s): "
        f"${result.total_cost_usd:.4f}[/dim]"
    )
    if any(b.unknown_model_cost for b in buckets):
        named = result.unpriced_models
        which = f" Unpriced: {', '.join(named)}." if named else ""
        console.print(
            "[yellow]Some periods include unpriced models - their cost is a floor, not exact "
            "(shown as \"?\" where the whole period's cost is unknown)."
            f"{which}[/yellow]"
        )


def run_trend(
    since: date | None = None,
    until: date | None = None,
    bucket: str = "day",
    as_json: bool = False,
    report: bool = False,
    report_format: str = "html",
    report_out: str | None = None,
):
    """Is spend trending up or down - cost specifically, bucketed by day or
    week across every session in range, a real time series of dollars
    rather than `chapters --all`'s flat per-session list. A different axis
    than `timeline` (tool/skill/subagent/approach *mix*, deliberately not
    cost - see timeline.py's module docstring): this reads only
    Turn.cost_usd/Turn.timestamp, so unlike timeline's category panel there
    is no cached-vs-uncached distinction and no API call, ever - every
    period's total is either fully priced or flagged unknown, never
    partial. Defaults to the last DEFAULT_WINDOW_DAYS days if neither
    --since nor --until is given, same re-derive-fresh-every-run precedent
    as `chapters --all`/`timeline` (no persisted cross-session store yet -
    issue #42)."""
    console = Console()
    if since is None and until is None:
        since = date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)

    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    if not transcripts:
        console.print("[red]No session transcripts found in that range.[/red]")
        sys.exit(1)

    result = build_trend(transcripts, bucket=bucket)
    if not result.buckets:
        console.print("[yellow]No turns found in that range.[/yellow]")
        return

    if report:
        from work_ledger.report import ReportRenderError, build_trend_report_html, render_png

        range_label = f"{since.isoformat() if since else 'earliest'} to {until.isoformat() if until else 'now'}"
        out_path = (
            Path(report_out) if report_out else Path(f"work-ledger-trend-{date.today().isoformat()}.{report_format}")
        )
        html = build_trend_report_html(range_label, result.buckets, result.bucket_size, result.total_sessions)
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
                "period": b.period,
                "cost_usd": b.cost_usd,
                "num_turns": b.num_turns,
                "unknown_model_cost": b.unknown_model_cost,
                "unpriced_models": sorted(b.unpriced_models),
            }
            for b in result.buckets
        ]
        console.print_json(json.dumps(data))
        return

    console.print()
    _render_trend(console, result)


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
    pass_note = format_pass_note(result)
    if pass_note:
        console.print(f"[dim]This chaptering pass {pass_note}[/dim]")

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


def _version_string() -> str:
    """The bare version number plus commit/date detail, for --version -
    reuses about.py's get_about_info() so it can never drift from `about`'s
    own numbers. Degrades to just the date (no commit) for a published
    install where commit isn't resolvable (see get_about_info's own
    editable-git-only commit resolution) - never fabricates a SHA."""
    from work_ledger.about import get_about_info

    info = get_about_info()
    date = info.last_updated[:10] if info.last_updated else None
    if info.commit and date:
        return f"{info.version} (commit {info.commit}, {date})"
    if date:
        return f"{info.version} (last updated {date})"
    return info.version


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
    from work_ledger.about import REPO_URL

    parser = argparse.ArgumentParser(
        description="Watch Claude Code session cost/token usage in near-real-time.",
        epilog=f"Source and issues: {REPO_URL}\n"
        "Run `work-ledger about` for version, commit, and author detail.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"work-ledger {_version_string()}",
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

    miso_parser = subparsers.add_parser(
        "miso",
        help="\"Make it so\" - run chaptering + both HTML/PNG reports end-to-end in one command "
        "(issue #35), instead of remembering the chapters/activity --report sequence yourself",
    )
    _add_transcript_args(miso_parser)
    miso_parser.add_argument(
        "--check-status",
        action="store_true",
        help="Only check whether this environment has everything needed to run everything "
        "(Anthropic credentials for chaptering, the 'report' extra for PNG rendering) and "
        "print what would happen - reads no transcript, makes no API call, writes no file.",
    )
    miso_parser.add_argument(
        "--all",
        action="store_true",
        help="Chapter every session transcript found under ~/.claude/projects/ instead of just "
        "the active/pinned one - same summary `chapters --all` prints. Visual reports aren't "
        "generated in this mode (same limit `chapters --report` already has - see issue #4/#7). "
        "Incompatible with --transcript/--session.",
    )
    miso_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="With --all: only include sessions last modified on/after this date (YYYY-MM-DD).",
    )
    miso_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="With --all: only include sessions last modified on/before this date (YYYY-MM-DD).",
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

    session_parser = subparsers.add_parser(
        "session",
        help="Pin a session so chapters/activity/recommend default to it instead of the most "
        "recently active one, until cleared - see also `work-ledger sessions` to find one",
    )
    session_parser.add_argument(
        "action",
        choices=["set", "clear", "status"],
        help="'set <value>' pins a session, 'clear' unpins, 'status' shows what's pinned",
    )
    session_parser.add_argument(
        "value",
        type=str,
        nargs="?",
        default=None,
        help="Session UUID (or a prefix of one) - required for 'set', ignored otherwise",
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Manage the local session history store (issue #42) - `sync` incrementally "
        "updates a small local sqlite db from ~/.claude/projects/, `status` shows what's "
        "stored. Additive infrastructure for future cross-session features (#3) - not "
        "required by, and not wired into, chapters --all/timeline/trend/serve.",
    )
    history_parser.add_argument(
        "action",
        choices=["sync", "status"],
        help="'sync' incrementally updates the store (skips sessions unchanged since last "
        "sync); 'status' shows row count and last-sync times",
    )

    sessions_parser = subparsers.add_parser(
        "sessions",
        help="List every local session transcript (project, last-active time, first prompt, "
        "cost) - no chaptering, no API call. Meant for discovery, before reaching for "
        "--transcript/--session on another command",
    )
    sessions_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include sessions last modified on/after this date (YYYY-MM-DD)",
    )
    sessions_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only include sessions last modified on/before this date (YYYY-MM-DD)",
    )
    sessions_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    sessions_parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Show only the N most expensive sessions, sorted by cost descending, instead of "
        "every session newest-first. Combine with --since/--until to scope the pool before "
        "ranking (e.g. `sessions --since 2026-08-01 --top 10` for this month's costliest).",
    )

    timeline_parser = subparsers.add_parser(
        "timeline",
        help="How tool usage and approach have changed over time, day-bucketed - not what it "
        "cost (see chapters/activity for that). Defaults to the last 30 days if no --since/"
        "--until given",
    )
    timeline_parser.add_argument(
        "action",
        nargs="?",
        choices=["show", "backfill"],
        default="show",
        help="'show' (default) prints the timeline; 'backfill' chapters any uncached sessions "
        "in range first (small Anthropic API cost, needs ANTHROPIC_API_KEY), then shows it",
    )
    timeline_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include sessions last modified on/after this date (YYYY-MM-DD). "
        "Default: 30 days ago, if neither --since nor --until is given.",
    )
    timeline_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only include sessions last modified on/before this date (YYYY-MM-DD)",
    )
    timeline_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of terminal sparklines. Not supported with 'backfill'.",
    )
    timeline_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a visual report (HTML or PNG) to a file instead of terminal sparklines. "
        "Not supported with 'backfill'.",
    )
    timeline_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png"],
        default="html",
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium",
    )
    timeline_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-timeline-<date>.<format>)",
    )
    timeline_parser.add_argument(
        "--summary",
        action="store_true",
        help="Also print a 1-3 sentence plain-language narrative of how the chapter-category mix "
        "has shifted between the first and second half of days-with-data in range (alongside the "
        "usual sparkline view, not instead of it). Prints nothing extra if there isn't enough "
        "data yet for a meaningful comparison. Not supported with --json/--report (the report "
        "already includes the narrative when there's enough data).",
    )

    trend_parser = subparsers.add_parser(
        "trend",
        help="Is spend trending up or down - cost bucketed by day/week across all sessions, a "
        "real time series of dollars (not activity mix - see `timeline` for that). Defaults to "
        "the last 30 days if no --since/--until given",
    )
    trend_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include sessions last modified on/after this date (YYYY-MM-DD). "
        "Default: 30 days ago, if neither --since nor --until is given.",
    )
    trend_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only include sessions last modified on/before this date (YYYY-MM-DD)",
    )
    trend_parser.add_argument(
        "--bucket",
        type=str,
        choices=list(BUCKET_SIZES),
        default="day",
        help="Bucket cost by day (default) or by ISO week (Monday-starting)",
    )
    trend_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal sparkline/table",
    )
    trend_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a visual report (HTML or PNG) to a file instead of terminal output",
    )
    trend_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png"],
        default="html",
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium",
    )
    trend_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-trend-<date>.<format>)",
    )

    rollup_parser = subparsers.add_parser(
        "rollup",
        help="Cluster the same recurring initiative's chapters across every session it "
        "touched and total its cost (issue #3) - unlike `chapters --all`'s flat per-session "
        "list, answers \"how much has X cost in total\" directly. Uses deterministic title-"
        "normalization matching, not an LLM/embedding pass (see rollup.py). Reuses already-"
        "cached chapters only - never triggers a new chaptering pass",
    )
    rollup_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include sessions last modified on/after this date (YYYY-MM-DD)",
    )
    rollup_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only include sessions last modified on/before this date (YYYY-MM-DD)",
    )
    rollup_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    rollup_parser.add_argument(
        "--confirm",
        action="store_true",
        help="When WORK_LEDGER_ROLLUP_MATCHING=semantic is set (issue #68) and the semantic "
        "pass actually merged singleton titles this run, print which titles merged into which "
        "cluster. No effect when the env var is unset (the default) or nothing merged - "
        "visibility only, not an audit trail",
    )
    rollup_parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Cluster within just the N most expensive sessions in range (same ranking as "
        "`sessions --top`), instead of every session in range - e.g. `rollup --since "
        "2026-08-01 --top 5` for a merged view of this month's 5 costliest sessions.",
    )
    rollup_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a shareable report (HTML, PNG, or CSV) to a file instead of a "
        "terminal table/--json - a report you can actually send someone, unlike `serve` "
        "which only ever binds 127.0.0.1.",
    )
    rollup_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png", "csv"],
        default=None,  # resolved to "html" after merging with --preset/--miso, see _resolve_rollup_flags
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium. "
        "csv needs nothing extra - initiative/sessions/chapters/cost/cumulative columns, "
        "plain text for a spreadsheet (issue #93).",
    )
    rollup_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-rollup-<date>.<format>)",
    )
    rollup_parser.add_argument(
        "--other-threshold",
        type=float,
        default=None,
        metavar="FRACTION",
        help="Show initiatives individually until their running cost crosses this fraction "
        "of the total (e.g. 0.8 for 80%%), then fold the rest into one 'All other' cluster - "
        "shortens a long tail of small recurring initiatives (issue #93). Opt-in (no effect "
        "unless given, unlike `activity --report`'s always-on default) - distinct from "
        "--top, which scopes which *sessions* get clustered before this ever runs. Applies "
        "to every output mode this run produces (table, --preview, --report, --json). Lowest "
        "precedence of the three collapsing flags - overridden by --top-initiatives or "
        "--min-cost if either is also given.",
    )
    rollup_parser.add_argument(
        "--top-initiatives",
        type=int,
        default=None,
        metavar="N",
        help="Show only the N costliest initiatives individually, folding everything else "
        "into one 'All other' cluster - a hard count cutoff instead of --other-threshold's "
        "percentage-of-total one (issue #93). Distinct from the existing --top, which scopes "
        "which *sessions* get clustered before this ever runs, not which *initiatives* get "
        "shown afterward. Takes precedence over --min-cost and --other-threshold if more "
        "than one is given.",
    )
    rollup_parser.add_argument(
        "--min-cost",
        type=float,
        default=None,
        metavar="DOLLARS",
        help="Fold any initiative costing less than this many dollars into one 'All other' "
        "cluster (issue #93). Unlike --other-threshold's percentage-of-total cutoff, this is "
        "a stable absolute floor - the same --min-cost folds the same set of initiatives "
        "every time, regardless of how total spend shifts month to month. Takes precedence "
        "over --other-threshold if both are given; --top-initiatives takes precedence over "
        "this if all three are given.",
    )
    rollup_parser.add_argument(
        "--preview",
        action="store_true",
        help="Render the same collapsed/cumulative-annotated result --report would write to "
        "a file straight to the terminal instead (or in addition, if --report is also given) "
        "- see what a shareable report will look like before generating one (issue #93).",
    )
    rollup_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Shorthand for WORK_LEDGER_ROLLUP_MATCHING=semantic, scoped to just this "
        "invocation (issue #97) - catches reworded-title duplicates a plain rollup can't. "
        "Same cost/behavior as setting the env var yourself; this flag doesn't persist "
        "beyond this run, and doesn't cache anything (see issue #96).",
    )
    rollup_parser.add_argument(
        "--preset",
        type=str,
        default=None,
        metavar="NAME",
        help="Replay a saved bundle of flags from a previous --save-preset (issue #97) - "
        "any flag you also pass explicitly on this invocation still overrides the preset's "
        "stored value. --since/--until/--out are never part of a saved preset - always pass "
        "those fresh. Mutually exclusive with --miso.",
    )
    rollup_parser.add_argument(
        "--save-preset",
        type=str,
        default=None,
        metavar="NAME",
        help="Save this invocation's resolved flags (after merging with --preset, if also "
        "given) under NAME in ~/.config/work-ledger/rollup_presets.json for later --preset "
        "NAME replay (issue #97) - the rollup still runs normally this time too. Never saves "
        "--since/--until/--out.",
    )
    rollup_parser.add_argument(
        "--list-presets",
        action="store_true",
        help="Print every saved preset and its flags, then exit - no rollup is run (issue #97).",
    )
    rollup_parser.add_argument(
        "--delete-preset",
        type=str,
        default=None,
        metavar="NAME",
        help="Delete a saved preset, then exit - no rollup is run (issue #97).",
    )
    rollup_parser.add_argument(
        "--miso",
        action="store_true",
        help="\"Just give me the standard useful report\" (issue #97, mirrors the `miso` "
        "command's own precedent) - built-in bundle equivalent to --semantic "
        "--other-threshold 0.8 --report --confirm --preview. Not customizable and not saved "
        "anywhere; use a named --preset instead if you want your own bundle. Mutually "
        "exclusive with --preset.",
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

    waste_parser = subparsers.add_parser(
        "waste",
        help="Flag recurring within-session waste - the same file Read more than once, or the "
        "same subagent dispatched more than once with a near-identical description - and its "
        "combined cost. No API call, no chaptering required. Not prescriptive about what to do "
        "(see `recommend`/issue #6)",
    )
    _add_transcript_args(waste_parser)
    waste_parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output instead of a terminal table",
    )
    waste_parser.add_argument(
        "--report",
        action="store_true",
        help="Generate a visual report (HTML or PNG) to a file instead of a terminal table",
    )
    waste_parser.add_argument(
        "--format",
        type=str,
        choices=["html", "png"],
        default="html",
        help="Report format for --report (default: html). png needs the optional "
        "'report' extra: pip install \"work-ledger[report]\" && playwright install chromium",
    )
    waste_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output file path for --report (default: work-ledger-waste-<session>.<format>)",
    )
    waste_parser.add_argument(
        "--cross-session",
        action="store_true",
        help="Cross-session half of #5: the same pattern kinds, scoped to a recurring "
        "initiative (a #3 rollup cluster) across every session it touched, instead of one "
        "session. Can't be combined with --transcript/--session/--report - use --since/"
        "--until instead",
    )
    waste_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="With --cross-session: only include sessions last modified on/after this date "
        "(YYYY-MM-DD)",
    )
    waste_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="With --cross-session: only include sessions last modified on/before this date "
        "(YYYY-MM-DD)",
    )
    waste_parser.add_argument(
        "--confirm",
        action="store_true",
        help="With --cross-session, when WORK_LEDGER_ROLLUP_MATCHING=semantic is set (issue "
        "#68) and the semantic pass actually merged singleton titles this run, print which "
        "titles merged into which cluster. No effect when the env var is unset (the default) "
        "or nothing merged - visibility only, not an audit trail",
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

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start a local-only, read-only web UI (binds 127.0.0.1 only, no auth needed) to "
        "browse every local session and drill into chapters -> turns -> units with real "
        "clickable navigation, instead of re-running a different flag each time. Long-running, "
        "like the plain live dashboard - Ctrl-C to stop. Never triggers a chaptering API call "
        "itself: a session without cached chapters just shows its turns ungrouped until you "
        "run `work-ledger chapters` for it.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765). Always binds 127.0.0.1 - there's no --host "
        "flag, so this can never be pointed at another address by accident.",
    )
    serve_parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only list sessions last modified on/after this date (YYYY-MM-DD) on the landing page",
    )
    serve_parser.add_argument(
        "--until",
        type=str,
        default=None,
        help="Only list sessions last modified on/before this date (YYYY-MM-DD) on the landing page",
    )
    serve_parser.add_argument(
        "--top",
        type=int,
        default=None,
        metavar="N",
        help="Pin the landing page to only the N most expensive sessions (same ranking as "
        "`sessions --top`), instead of every session. Combine with --since/--until to scope "
        "the pool before ranking. The page's title/header shows this scope so it's clear "
        "you're not looking at every session.",
    )
    serve_parser.add_argument(
        "--merge-sessions",
        action="store_true",
        help="Replace the landing page with one combined chapters -> turns -> units tree "
        "spanning every session in scope (--top/--since/--until), chronologically "
        "interleaved - a multi-day/multi-session view for spotting a pattern that repeats "
        "across sessions, since the same chapter title recurring shows up as separate, "
        "still-distinct blocks rather than being clustered away (contrast `rollup`, which "
        "totals cost by initiative - this shows the actual work, unclustered). Each chapter "
        "is tagged with which session it came from. Not the same thing as a shareable report "
        "- this is still a live, 127.0.0.1-only page; see `rollup --report` for something you "
        "can send someone.",
    )

    cycle_parser = subparsers.add_parser(
        "cycle",
        help="Upgrade this install in place (issue #73) - `git pull` for an editable clone, or "
        "the matching pipx/uv-tool/pip upgrade command for a published install, detected "
        "automatically. Never auto-restarts `serve`/`work-ledger-mcp` - see --check-status.",
    )
    cycle_parser.add_argument(
        "--check-status",
        action="store_true",
        help="Report the detected install mode and what `cycle` would run, without changing "
        "anything - reads no files beyond package metadata, runs no git/pip/pipx/uv command.",
    )
    cycle_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to check for a running `work-ledger serve` on (default: 8765, matching "
        "serve's own default - pass the same --port you used with serve if you started it on "
        "a different one)",
    )

    about_parser = subparsers.add_parser(
        "about",
        help="Show this install's About block (issue #75) - short description, version, "
        "last-updated, commit (if resolvable from an editable git checkout), and author/repo "
        "attribution. Read-only, no network call.",
    )
    about_parser.add_argument("--json", action="store_true", help="Output as JSON instead of a formatted block")

    args = parser.parse_args()
    _check_transcript_flag_placement(sys.argv[1:], args.command)

    if args.command == "limits":
        run_limits(
            window_hours=args.window_hours,
            once=args.once,
            set_threshold=args.set_threshold,
            as_json=args.json,
        )
        return

    if args.command == "cycle":
        run_cycle_command(check_status=args.check_status, port=args.port)
        return

    if args.command == "about":
        run_about_command(as_json=args.json)
        return

    if args.command == "session":
        run_session(args.action, args.value)
        return

    if args.command == "history":
        run_history(args.action)
        return

    if args.command == "sessions":
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        _validate_top(args.top)
        run_sessions(since=since, until=until, as_json=args.json, top=args.top)
        return

    if args.command == "serve":
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        _validate_top(args.top)
        from work_ledger.server import run_serve  # lazy: only this subcommand needs http.server

        run_serve(port=args.port, since=since, until=until, top=args.top, merge_sessions=args.merge_sessions)
        return

    if args.command == "timeline":
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        if args.report and args.json:
            print("error: --report and --json can't be combined", file=sys.stderr)
            sys.exit(2)
        if args.summary and (args.report or args.json):
            print(
                "error: --summary can't be combined with --report/--json - --report already "
                "includes the narrative when there's enough data, and --json stays raw data",
                file=sys.stderr,
            )
            sys.exit(2)
        if args.action == "backfill":
            if args.report or args.json:
                print(
                    "error: 'timeline backfill' doesn't support --report/--json - run plain "
                    "`timeline --report`/`timeline --json` after backfilling",
                    file=sys.stderr,
                )
                sys.exit(2)
            run_timeline_backfill(since=since, until=until, summary=args.summary)
        else:
            run_timeline(
                since=since,
                until=until,
                as_json=args.json,
                report=args.report,
                report_format=args.format,
                report_out=args.out,
                summary=args.summary,
            )
        return

    if args.command == "trend":
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        if args.report and args.json:
            print("error: --report and --json can't be combined", file=sys.stderr)
            sys.exit(2)
        run_trend(
            since=since,
            until=until,
            bucket=args.bucket,
            as_json=args.json,
            report=args.report,
            report_format=args.format,
            report_out=args.out,
        )
        return

    if args.command == "rollup":
        if args.list_presets:
            presets = rollup_presets.load_presets()
            if not presets:
                print("No saved rollup presets yet. Create one with `rollup ... --save-preset <name>`.")
            else:
                for name in rollup_presets.list_preset_names():
                    print(f"{name}: {presets[name]}")
            return

        if args.delete_preset:
            removed = rollup_presets.delete_preset(args.delete_preset)
            verb = "Removed" if removed else "No such"
            print(f"{verb} preset {args.delete_preset!r}.")
            return

        if args.miso and args.preset:
            print("error: --miso and --preset are mutually exclusive - pick one", file=sys.stderr)
            sys.exit(2)

        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None

        resolved = _resolve_rollup_flags(args)
        _validate_top(resolved["top"])
        if resolved["other_threshold"] is not None:
            _validate_other_threshold(resolved["other_threshold"])
        _validate_top_initiatives(resolved["top_initiatives"])
        _validate_min_cost(resolved["min_cost"])
        if resolved["report"] and resolved["as_json"]:
            print("error: --report and --json are mutually exclusive", file=sys.stderr)
            sys.exit(2)

        if args.save_preset:
            rollup_presets.save_preset(args.save_preset, resolved)
            print(f"Saved preset {args.save_preset!r}.")

        run_rollup(
            since=since,
            until=until,
            as_json=resolved["as_json"],
            confirm=resolved["confirm"],
            top=resolved["top"],
            report=resolved["report"],
            report_format=resolved["report_format"],
            report_out=args.out,
            other_threshold=resolved["other_threshold"],
            top_initiatives=resolved["top_initiatives"],
            min_cost=resolved["min_cost"],
            preview=resolved["preview"],
            semantic=resolved["semantic"],
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

    if args.command == "waste":
        if args.report and args.json:
            print("error: --report and --json are mutually exclusive", file=sys.stderr)
            sys.exit(2)
        if args.cross_session:
            if args.transcript or args.session or args.report:
                print(
                    "error: --cross-session can't be combined with --transcript, --session, "
                    "or --report",
                    file=sys.stderr,
                )
                sys.exit(2)
            since = _parse_date_arg(args.since, "--since") if args.since else None
            until = _parse_date_arg(args.until, "--until") if args.until else None
            run_waste_cross_session(since=since, until=until, as_json=args.json, confirm=args.confirm)
            return
        if args.confirm:
            print("error: --confirm requires --cross-session", file=sys.stderr)
            sys.exit(2)
        transcript_path = _resolve_transcript_arg(args.transcript, args.session)
        run_waste(
            transcript_path=transcript_path,
            as_json=args.json,
            report=args.report,
            report_format=args.format,
            report_out=args.out,
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

    if args.command == "miso":
        if args.all and (args.transcript or args.session):
            print("error: --all can't be combined with --transcript or --session", file=sys.stderr)
            sys.exit(2)
        if not args.all and (args.since or args.until):
            print("error: --since/--until only apply with --all", file=sys.stderr)
            sys.exit(2)
        since = _parse_date_arg(args.since, "--since") if args.since else None
        until = _parse_date_arg(args.until, "--until") if args.until else None
        transcript_path = None if args.all else _resolve_transcript_arg(args.transcript, args.session)
        run_miso(
            transcript_path=transcript_path,
            check_status_only=args.check_status,
            all_sessions=args.all,
            since=since,
            until=until,
        )
        return

    transcript_path = _resolve_transcript_arg(args.transcript, args.session)
    run(transcript_path=transcript_path, once=args.once, detail=args.detail)


if __name__ == "__main__":
    main()
