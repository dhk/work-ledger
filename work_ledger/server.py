"""`work-ledger serve`: a local-only, read-only web UI over the same session
data `sessions`/`chapters --detail` already compute - real clickable
navigation (landing page listing every local session -> per-session
drill-down: chapters -> turns -> units) instead of re-running a different
CLI flag each time. See issue #43 and docs/show-tell-do-model.md's "1. A
local web UI" section for the design this implements.

Explicitly Show-stage (see CLAUDE.md's rubric): this module only renders
already-computed Turn/Unit/Chapter data as HTML and serves it over a
socket bound to 127.0.0.1 - it never calls the chaptering model (uses
chapters.cached_chapters, never chapters.get_chapters, so opening this UI
can't trigger a paid Haiku pass as a side effect of browsing), never
writes anything to disk, and there is deliberately no --host flag, so it
can never be pointed at a non-localhost address by accident.

Deliberately stdlib-only (`http.server`), matching report.py's own
precedent that HTML generation needs no extra dependency - issue #43
floated a small framework dependency as an open question, but nothing
here needed one, since report.py's rendering (this module's only other
real dependency) was already stdlib.
"""

import html
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.console import Console

from work_ledger.chapters import cached_chapters
from work_ledger.cli import _in_date_range, build_session_rows, top_n_session_rows
from work_ledger.git_activity import GitActivity, find_git_activity
from work_ledger.report import build_session_detail_html, build_sessions_index_html
from work_ledger.transcript import TranscriptTailer, find_all_transcripts

DEFAULT_SERVE_PORT = 8765
BIND_HOST = "127.0.0.1"  # local-only, deliberately not configurable - see module docstring


def _matching_transcripts(session_id: str) -> list[Path]:
    """Resolve a URL path segment to transcript file(s) - exact stem match
    first (what every link this module itself generates uses, via the full
    `path.stem`), falling back to a prefix match only if there's no exact
    hit, so a hand-typed short id behaves the same way --session's prefix
    matching already does elsewhere in the CLI."""
    all_transcripts = find_all_transcripts()
    exact = [p for p in all_transcripts if p.stem == session_id]
    if exact:
        return exact
    return [p for p in all_transcripts if p.stem.startswith(session_id)]


def _error_page(message: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>work-ledger — not found</title></head>"
        "<body style='font-family:system-ui;padding:40px;'>"
        f"<p>{html.escape(message)}</p>"
        '<p><a href="/">&larr; All sessions</a></p></body></html>'
    )


def _disambiguation_page(session_id: str, matches: list[Path]) -> str:
    items = "".join(
        f'<li><a href="/session/{html.escape(p.stem)}">{html.escape(p.stem)}</a> '
        f"&mdash; {html.escape(p.parent.name)}</li>"
        for p in matches
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>work-ledger — ambiguous session</title></head>"
        "<body style='font-family:system-ui;padding:40px;'>"
        f"<p>{html.escape(session_id)!r} matches more than one session:</p>"
        f"<ul>{items}</ul>"
        '<p><a href="/">&larr; All sessions</a></p></body></html>'
    )


def _scope_note(since: date | None, until: date | None, top: int | None, n_shown: int) -> str | None:
    """Human-readable description of an active --since/--until/--top filter,
    for the landing page's title/header - None when nothing is scoped, so
    the page reads exactly as it did before this option existed."""
    parts = []
    if top is not None:
        parts.append(f"top {n_shown} by cost")
    if since and until:
        parts.append(f"{since.isoformat()} to {until.isoformat()}")
    elif since:
        parts.append(f"since {since.isoformat()}")
    elif until:
        parts.append(f"until {until.isoformat()}")
    return " · ".join(parts) if parts else None


def render_landing(since: date | None, until: date | None, top: int | None = None) -> str:
    """Every local transcript, newest first, filtered the same way `sessions
    --since/--until` filters - re-derived fresh on every request (no cache),
    so a session that appears on disk after the server starts shows up on
    the next page load without a restart.

    `top`, when given, pins the page to just the N costliest sessions in
    range (same ranking `sessions --top` uses, via the same
    top_n_session_rows helper) instead of every session - "browse just the
    sessions I already know are expensive" instead of scrolling past every
    cheap one to find them."""
    transcripts = [p for p in find_all_transcripts() if _in_date_range(p, since, until)]
    rows = build_session_rows(transcripts)
    rows = top_n_session_rows(rows, top)
    scope_note = _scope_note(since, until, top, len(rows))
    return build_sessions_index_html(rows, scope_note=scope_note)


def render_session_detail(session_id: str) -> tuple[int, str]:
    matches = _matching_transcripts(session_id)
    if not matches:
        return 404, _error_page(f"No session found matching {session_id!r}.")
    if len(matches) > 1:
        return 200, _disambiguation_page(session_id, matches)

    path = matches[0]
    tailer = TranscriptTailer(path)
    tailer.poll()
    chapters = cached_chapters(path)  # never get_chapters() - see module docstring

    turns = tailer.ordered_turns()
    if turns:
        git_activity = find_git_activity(tailer.cwd, turns[0].timestamp, turns[-1].timestamp)
    else:
        # No turns at all - nothing to correlate a time window against;
        # same "unavailable, not an error" shape find_git_activity's own
        # missing-cwd/missing-repo cases already use.
        git_activity = GitActivity(repo_available=False)

    return 200, build_session_detail_html(path.stem, path.parent.name, tailer, chapters, git_activity)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "work-ledger-serve/1"

    def _send_html(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib-mandated method name
        path = urlparse(self.path).path

        if path in ("", "/"):
            self._send_html(200, render_landing(self.server.since, self.server.until, self.server.top))
            return

        if path.startswith("/session/"):
            session_id = unquote(path[len("/session/") :]).strip("/")
            if not session_id:
                self._send_html(404, _error_page("No session id given."))
                return
            status, body = render_session_detail(session_id)
            self._send_html(status, body)
            return

        self._send_html(404, _error_page(f"No route for {path!r}."))

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        # Quiet by default - matches the plain live dashboard's own posture
        # of not spamming the terminal it was started from; this is a
        # single-user local browsing tool, not something that needs an
        # access log.
        pass


def run_serve(
    port: int = DEFAULT_SERVE_PORT,
    since: date | None = None,
    until: date | None = None,
    top: int | None = None,
) -> None:
    """Long-running, like the plain `work-ledger` live dashboard: starts,
    prints where it's listening, and runs until Ctrl-C. One-shot (serve
    once and exit) wasn't chosen - a browsable UI is meant to be left open
    in a tab while you click around, not re-run per page view."""
    console = Console()
    httpd = ThreadingHTTPServer((BIND_HOST, port), _RequestHandler)
    httpd.since = since
    httpd.until = until
    httpd.top = top
    url = f"http://{BIND_HOST}:{port}/"
    console.print(f"[green]work-ledger serve[/green] — [bold]{url}[/bold]")
    if top is not None:
        console.print(f"[dim]Pinned to the {top} most expensive session(s) in range.[/dim]")
    console.print(
        f"[dim]Local-only: bound to {BIND_HOST}, never leaves this machine, no auth needed "
        "(nothing off-localhost can reach it to authenticate against). Read-only - browsing "
        "never edits a transcript or its chapter cache, and never triggers a chaptering API "
        "call; sessions without cached chapters just show their turns ungrouped. "
        "Ctrl-C to stop.[/dim]\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    finally:
        httpd.server_close()
