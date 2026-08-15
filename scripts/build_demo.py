#!/usr/bin/env python3
"""Generate the browsable demo under `docs/demo/` (issue #109).

The repo ships no screenshots, so the only way to find out what
work-ledger looks like is to install it, have transcripts, and - for the
initiative-level views - pay for a chaptering pass. This script closes
that gap: it fabricates a plausible set of sessions, runs them through
the *real* renderers, and writes self-contained HTML plus PNG stills.

Two rules make this worth having rather than a liability:

1. **Generated, never hand-drawn.** Every page here comes out of
   `report.py`'s actual functions, fed by transcripts parsed by the
   actual `TranscriptTailer` and priced by the actual `pricing.py`. Cost
   figures are therefore correct arithmetic over the fabricated inputs -
   units sum to turns, turns to chapters, chapters to the session total -
   because nothing here computes a number by hand. PR #41 is the
   cautionary tale: a hand-placed asset captioned "matches actual product
   output" that stopped matching about a hundred commits later.

2. **The data is fabricated and says so.** Every generated page carries a
   banner stating the figures are illustrative, so the disclosure travels
   with the asset if it's ever shared standalone. Real dogfood
   transcripts are deliberately not used - a `serve` page carries prompts,
   file paths, `cwd` and commit subjects, and shipping a real session as
   a demo would undercut the privacy promise in the most visible place
   the project has.

Usage:

    python scripts/build_demo.py            # HTML only
    python scripts/build_demo.py --png      # also render PNG stills

PNG rendering needs the `report` extra (`pip install "work-ledger[report]"`
plus `playwright install chromium`); without it the HTML is still written
and the PNG step reports why it skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from work_ledger import report  # noqa: E402
from work_ledger.chapters import Chapter, Section  # noqa: E402
from work_ledger.cli import build_session_rows  # noqa: E402
from work_ledger.git_activity import Commit, GitActivity  # noqa: E402
from work_ledger.rollup import build_rollup_result  # noqa: E402
from work_ledger.transcript import TranscriptTailer  # noqa: E402

OUT_DIR = REPO_ROOT / "docs" / "demo"

# Opus 5 - the model these figures are priced at, so the demo shows the
# same rates a current session would.
MODEL = "claude-opus-5"

_BANNER_SENTENCE = (
    "Every figure below is fabricated for illustration. "
    "No real session, prompt, or repository is represented here."
)


# --------------------------------------------------------------------------
# Fabricated source material
#
# Deliberately mundane, recognizable engineering work. Two initiatives
# recur across sessions so the rollup has something real to cluster; the
# rest are one-offs, which is what an honest rollup mostly looks like.
# --------------------------------------------------------------------------

SESSIONS = [
    {
        "id": "a1f4c8e2-demo-4b7a-9c31-000000000001",
        "project": "-home-dev-acme-api",
        "day": 0,
        "chapters": [
            (
                "Add rate limiting to the public API",
                "feature-build",
                [
                    ("Design the limiter", [
                        ("add a token bucket rate limiter to the public API", 2400, 512_000, 24_000, 3100),
                        ("where should the bucket state live - redis or in-process?", 1800, 610_000, 12_000, 2400),
                    ]),
                    ("Wire it into the router", [
                        ("wire the limiter into the request router", 2100, 688_000, 18_000, 2800),
                        ("add the 429 response and Retry-After header", 1600, 712_000, 9_000, 1900),
                    ]),
                ],
            ),
            (
                "Fix the flaky integration suite",
                "bug-fix",
                [
                    ("Find the race", [
                        ("integration tests fail about 1 in 5 runs, find out why", 2900, 744_000, 31_000, 4200),
                        ("is it the shared fixture or the clock?", 1400, 792_000, 8_000, 1700),
                    ]),
                ],
            ),
        ],
        "commits": [
            ("Add token-bucket rate limiter to public API (#412)", ["412"]),
            ("Return 429 with Retry-After when the bucket is empty", []),
        ],
    },
    {
        "id": "b2e5d9f3-demo-4c8b-8d42-000000000002",
        "project": "-home-dev-acme-api",
        "day": 2,
        "chapters": [
            (
                "Add rate limiting to the public API",
                "feature-build",
                [
                    ("Per-tenant limits", [
                        ("extend the rate limiter to per-tenant buckets", 2600, 620_000, 22_000, 3400),
                        ("what happens when a tenant is deleted mid-window?", 1500, 664_000, 7_000, 1600),
                    ]),
                ],
            ),
            (
                "Document the limiter for downstream teams",
                "documentation",
                [
                    ("Write it up", [
                        ("write the rate limiting docs for downstream teams", 1900, 540_000, 14_000, 2600),
                    ]),
                ],
            ),
        ],
        "commits": [
            ("Per-tenant rate limit buckets (#418)", ["418"]),
        ],
    },
    {
        "id": "c3d6eaf4-demo-4d9c-9e53-000000000003",
        "project": "-home-dev-acme-api",
        "day": 5,
        "chapters": [
            (
                "Migrate auth to short-lived tokens",
                "refactor",
                [
                    ("Plan the migration", [
                        ("plan the migration from long-lived API keys to short-lived tokens", 3100, 486_000, 28_000, 4800),
                        ("how do we keep existing integrations working during rollout?", 1700, 552_000, 9_000, 2200),
                    ]),
                    ("Token issuance", [
                        ("implement the token issuance endpoint", 2400, 618_000, 19_000, 3000),
                    ]),
                ],
            ),
        ],
        "commits": [
            ("Add short-lived token issuance endpoint (#421)", ["421"]),
        ],
    },
    {
        "id": "d4e7fb05-demo-4eab-8f64-000000000004",
        "project": "-home-dev-acme-web",
        "day": 6,
        "chapters": [
            (
                "Migrate auth to short-lived tokens",
                "refactor",
                [
                    ("Client-side refresh", [
                        ("update the web client to refresh short-lived tokens", 2200, 574_000, 17_000, 2900),
                        ("handle the refresh failing mid-request", 1500, 612_000, 8_000, 1800),
                    ]),
                ],
            ),
            (
                "Fix checkout test flakiness",
                "bug-fix",
                [
                    ("Reproduce", [
                        ("checkout tests are flaky in CI but pass locally", 2700, 648_000, 26_000, 3600),
                    ]),
                ],
            ),
        ],
        "commits": [
            ("Refresh short-lived tokens in the web client (#57)", ["57"]),
            ("Stabilise checkout test fixtures", []),
        ],
    },
    {
        "id": "e5f80c16-demo-4fbc-9075-000000000005",
        "project": "-home-dev-acme-web",
        "day": 8,
        "chapters": [
            (
                "Rebuild the settings page",
                "feature-build",
                [
                    ("Layout", [
                        ("rebuild the account settings page with the new design system", 2800, 502_000, 24_000, 3800),
                        ("make the form sections collapsible", 1600, 566_000, 9_000, 2000),
                    ]),
                ],
            ),
        ],
        "commits": [
            ("Rebuild account settings with the new design system (#61)", ["61"]),
        ],
    },
]

BASE_DAY = datetime(2026, 8, 3, 9, 12, 0)


def _ts(day: int, minute_offset: int) -> str:
    return (BASE_DAY + timedelta(days=day, minutes=minute_offset)).isoformat() + "Z"


def _write_session(root: Path, spec: dict) -> Path:
    """Write one fabricated transcript in Claude Code's real JSONL shape -
    one line per content block, `usage` repeated verbatim on every line for
    the same message.id, exactly as the real format does (and as the
    parser's message.id dedup expects)."""
    project_dir = root / spec["project"]
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{spec['id']}.jsonl"

    entries: list[dict] = []
    prompt_n = 0
    minute = 0

    for _title, _category, sections in spec["chapters"]:
        for _section_title, prompts in sections:
            for prompt_text, inp, cache_read, cache_write, out in prompts:
                prompt_n += 1
                pid = f"p{prompt_n}"
                entries.append({
                    "type": "user",
                    "promptId": pid,
                    "timestamp": _ts(spec["day"], minute),
                    "message": {"role": "user", "content": prompt_text},
                })
                usage = {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": cache_write,
                        "ephemeral_1h_input_tokens": 0,
                    },
                }
                blocks = [
                    {"type": "text", "text": f"Working on: {prompt_text}"},
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "src/limiter.py"}},
                    {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/limiter.py"}},
                ]
                for block in blocks:
                    entries.append({
                        "type": "assistant",
                        "timestamp": _ts(spec["day"], minute + 1),
                        "message": {
                            "id": f"msg-{spec['id'][:8]}-{prompt_n}",
                            "model": MODEL,
                            "usage": usage,
                            "content": [block],
                        },
                    })
                minute += 7

    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def _write_chapter_cache(transcript: Path, spec: dict) -> list[Chapter]:
    """Write the `<session>.chapters.json` cache beside the transcript, so
    the rollup and detail views read chapters the same way they would after
    a real chaptering pass - no model call involved, and none possible."""
    chapters: list[Chapter] = []
    prompt_n = 0
    for title, category, sections in spec["chapters"]:
        built_sections = []
        for section_title, prompts in sections:
            ids = []
            for _ in prompts:
                prompt_n += 1
                ids.append(f"p{prompt_n}")
            built_sections.append(Section(title=section_title, prompt_ids=ids))
        chapters.append(Chapter(title=title, sections=built_sections, category=category))

    cache = {
        "chaptered_prompt_ids": [pid for c in chapters for pid in c.prompt_ids],
        "chapters": [
            {
                "title": c.title,
                "category": c.category,
                "sections": [{"title": s.title, "prompt_ids": s.prompt_ids} for s in c.sections],
            }
            for c in chapters
        ],
    }
    (transcript.parent / f"{transcript.stem}.chapters.json").write_text(
        json.dumps(cache, indent=2), encoding="utf-8"
    )
    return chapters


def _git_activity(spec: dict) -> GitActivity:
    return GitActivity(
        repo_available=True,
        # Deliberately None: with a remote set, the renderer turns every SHA
        # and PR badge into a real github.com link. For fabricated commits
        # that would deep-link to whatever unrelated repo happens to own
        # that name - worse than a dead link. Without it the panel still
        # shows commits, subjects and PR badges, just as plain text.
        remote_owner_repo=None,
        commits=[
            Commit(
                sha=f"{i}bcdef0123456789abcdef0123456789abcdef01",
                short_sha=f"{i}bcdef0",
                subject=subject,
                author_date=_ts(spec["day"], 60 + i * 20),
                pr_refs=refs,
            )
            for i, (subject, refs) in enumerate(spec["commits"], start=1)
        ],
    )


# --------------------------------------------------------------------------
# Post-processing: make the generated pages work as static files
# --------------------------------------------------------------------------

_BANNER_CSS = (
    "margin:0 0 1.25rem;padding:.7rem .95rem;border:1px solid rgba(214,158,46,.6);"
    "background:rgba(236,178,46,.14);border-radius:6px;font-size:.85rem;"
    "line-height:1.5;color:inherit;"
)


def _localize(html: str, session_ids: list[str]) -> str:
    """Rewrite `serve`'s absolute routes to the sibling files this script
    writes, and stamp the disclosure banner in. `serve` builds real HTTP
    routes (`/session/<id>`, `/`) because it's a server; on disk those
    would 404, so the demo rewrites them rather than the renderer growing a
    "static mode" nobody else needs."""
    for sid in session_ids:
        html = html.replace(f'href="/session/{sid}"', f'href="session-{sid[:8]}.html"')
    html = html.replace('href="/"', 'href="sessions.html"')

    banner = f'<div style="{_BANNER_CSS}"><strong>Illustrative data.</strong> {_BANNER_SENTENCE}</div>'
    # Inside the page's own container so it inherits the report's width and
    # theme, rather than floating full-bleed above it.
    match = re.search(r"<body[^>]*>", html)
    if match:
        html = html[: match.end()] + "\n" + banner + html[match.end() :]
    return html


def _render_png(html: str, dst: Path, width: int = 1000) -> str | None:
    """Screenshot `html` to `dst`. Returns None on success, or a reason
    string if it couldn't.

    Prefers `report.render_png` - the real thing the `--report --format
    png` path uses, so the stills are produced the same way a user's
    reports are. Falls back to launching an explicitly-located Chromium
    when playwright can't find its own: a machine can have a perfectly
    good browser installed at a build number the installed playwright
    doesn't expect, which is a tooling mismatch rather than a missing
    browser. Set WORK_LEDGER_CHROMIUM to point at one.
    """
    try:
        report.render_png(html, dst, width=width)
        return None
    except report.ReportRenderError as primary:
        candidates = [os.environ.get("WORK_LEDGER_CHROMIUM"), "/opt/pw-browsers/chromium"]
        executable = next((c for c in candidates if c and Path(c).exists()), None)
        if executable is None:
            return str(primary)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return str(primary)

        tmp_html = dst.with_suffix(".tmp.html")
        tmp_html.write_text(html, encoding="utf-8")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=executable)
                page = browser.new_page(viewport={"width": width, "height": 800})
                page.goto(tmp_html.resolve().as_uri())
                page.screenshot(path=str(dst), full_page=True)
                browser.close()
        except Exception as e:  # noqa: BLE001 - any launch/render failure is just "no PNG"
            return f"{primary} (fallback via {executable} also failed: {e})"
        finally:
            tmp_html.unlink(missing_ok=True)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", action="store_true", help="also render PNG stills")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        root.mkdir()

        transcripts: list[Path] = []
        chapters_by_path: dict[Path, list[Chapter]] = {}
        for spec in SESSIONS:
            path = _write_session(root, spec)
            chapters_by_path[path] = _write_chapter_cache(path, spec)
            transcripts.append(path)

        session_ids = [s["id"] for s in SESSIONS]
        written: list[Path] = []

        # 1. Landing page - every session, one bar each, sortable.
        rows = build_session_rows(transcripts)
        for row in rows:
            # build_session_rows takes last_active from file mtime, which is
            # "now" for files this script just wrote. Restate it from the
            # fabricated timeline so the demo reads as a real week of work.
            spec = next(s for s in SESSIONS if s["id"] == row["session"])
            row["last_active"] = _ts(spec["day"], 90)[:-1]
        index_html = _localize(
            report.build_sessions_index_html(rows, scope_note="demo data · 5 sessions"),
            session_ids,
        )
        (OUT_DIR / "sessions.html").write_text(index_html, encoding="utf-8")
        written.append(OUT_DIR / "sessions.html")

        # 2. Per-session drill-down - the open/close tree.
        for spec, path in zip(SESSIONS, transcripts):
            tailer = TranscriptTailer(path)
            tailer.poll()
            detail_html = _localize(
                report.build_session_detail_html(
                    session_id=spec["id"],
                    project=spec["project"],
                    tailer=tailer,
                    chapters=chapters_by_path[path],
                    git_activity=_git_activity(spec),
                ),
                session_ids,
            )
            out = OUT_DIR / f"session-{spec['id'][:8]}.html"
            out.write_text(detail_html, encoding="utf-8")
            written.append(out)

        # 3. Rollup - the same initiative totalled across sessions, via the
        #    real clustering over the caches written above.
        result = build_rollup_result(transcripts)
        rollup_html = _localize(
            report.build_rollup_report_html(
                clusters=result.clusters,
                n_sessions_included=len(transcripts),
                n_sessions_total=len(transcripts),
            ),
            session_ids,
        )
        (OUT_DIR / "rollup.html").write_text(rollup_html, encoding="utf-8")
        written.append(OUT_DIR / "rollup.html")

        for p in written:
            print(f"wrote {p.relative_to(REPO_ROOT)}")

        total = sum(r["cost_usd"] for r in rows)
        print(f"\n{len(rows)} fabricated sessions, ${total:.2f} total, "
              f"{len(result.clusters)} initiative(s) after clustering")

        if args.png:
            # The detail page's chapters are collapsed by default, which is
            # right for the live page but useless in a still - a screenshot
            # of a closed tree can't show the drill-down that's the point of
            # it. Expand the first chapter for the still only; the checked-in
            # HTML keeps the real default so the demo behaves like `serve`.
            stills = [
                (OUT_DIR / "sessions.html", OUT_DIR / "sessions.png", False),
                (OUT_DIR / f"session-{SESSIONS[0]['id'][:8]}.html", OUT_DIR / "session-detail.png", True),
                (OUT_DIR / "rollup.html", OUT_DIR / "rollup.png", False),
            ]
            for src, dst, expand in stills:
                html = src.read_text(encoding="utf-8")
                if expand:
                    html = html.replace('<details class="chapter-d"', '<details open class="chapter-d"', 1)
                reason = _render_png(html, dst)
                if reason is not None:
                    print(f"\nPNG rendering skipped: {reason}", file=sys.stderr)
                    return 0
                print(f"wrote {dst.relative_to(REPO_ROOT)}")
                dst.with_suffix(".tmp.html").unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
