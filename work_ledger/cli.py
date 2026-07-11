"""Terminal dashboard: tails the active Claude Code session transcript and
shows running cost/token usage per prompt, updating in near-real-time.

No telemetry setup, no server, no browser - just run it in a terminal next
to your session.
"""

import argparse
import sys
import time

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from work_ledger.transcript import TranscriptTailer, find_active_transcript

POLL_INTERVAL_S = 1.0


def build_table(tailer: TranscriptTailer, transcript_name: str) -> Table:
    table = Table(title=f"work-ledger — watching {transcript_name}", expand=True)
    table.add_column("Time", style="dim", width=8)
    table.add_column("Prompt", ratio=3, overflow="ellipsis")
    table.add_column("Calls", justify="right", width=6)
    table.add_column("In tok", justify="right", width=8)
    table.add_column("Out tok", justify="right", width=8)
    table.add_column("Cost (est.)", justify="right", width=12)

    for turn in tailer.ordered_turns():
        time_str = turn.timestamp[11:19] if len(turn.timestamp) >= 19 else turn.timestamp
        cost_str = "?" if turn.unknown_model_cost and turn.cost_usd == 0 else f"${turn.cost_usd:.4f}"
        table.add_row(
            time_str,
            turn.prompt_snippet,
            str(turn.num_assistant_messages),
            f"{turn.input_tokens:,}",
            f"{turn.output_tokens:,}",
            cost_str,
        )

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


def run(transcript_path=None, once: bool = False):
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
        console.print(build_table(tailer, path.name))
        return

    with Live(build_table(tailer, path.name), console=console, refresh_per_second=2) as live:
        try:
            while True:
                time.sleep(POLL_INTERVAL_S)
                if tailer.poll():
                    live.update(build_table(tailer, path.name))
        except KeyboardInterrupt:
            pass


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
    args = parser.parse_args()

    from pathlib import Path

    transcript_path = Path(args.transcript) if args.transcript else None
    run(transcript_path=transcript_path, once=args.once)


if __name__ == "__main__":
    main()
