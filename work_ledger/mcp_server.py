"""Local MCP server for the pattern-library mechanism (see
docs/pattern-library-design.md) - exposes list_patterns, report_recommended,
report_used, and submit_review_findings as MCP tools, connectable directly
to a Claude Code session.

This is what makes the mechanism "live in-session" rather than only an
after-the-fact CLI report (the actual argument for choosing MCP in the
design doc): a session can consult known patterns while it's happening,
not just when someone later runs `work-ledger recommend`.

Runs over stdio, the standard local MCP transport - `claude mcp add
work-ledger -- work-ledger-mcp` for Claude Code, or the equivalent
mcpServers block for Claude Desktop (see INSTALL.md's "Using work-ledger
inside Claude (MCP)" section for the exact steps and this server's
scope). Reads
the same local pattern content (`load_patterns`) and reports through the
same best-effort, opt-in client (`pattern_client`) as the CLI path, so
there is exactly one source of truth for both.

Honest scoping note: this server runs locally on your machine - it is
not itself "the mother ship." The counters it reports to still need
WORK_LEDGER_PATTERN_BACKEND_URL pointed at an actual deployed backend
(see pattern_client.py); nothing here stands that backend up.
"""

import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "error: work-ledger-mcp needs the optional 'patterns' extra.\n"
        'Run: pip install "work-ledger[patterns]"',
        file=sys.stderr,
    )
    sys.exit(1)

from work_ledger.about import get_about_info
from work_ledger.pattern_client import is_enabled, report_event, submit_findings
from work_ledger.patterns import DEFAULT_PATTERNS_DIR, load_patterns

mcp = FastMCP(
    "work-ledger-patterns",
    instructions=(
        "Known mistakes/patterns/fixes from work-ledger's shared pattern "
        "library. Use list_patterns to see what's available, and call "
        "report_recommended/report_used to contribute to the library's "
        "usage counters when you actually apply one of these. Use "
        "submit_review_findings, only on explicit instruction after a code "
        "review, to forward findings for later curation into new library "
        "entries - see docs/review-findings-harvesting-design.md."
    ),
)


@mcp.tool()
def list_patterns() -> list[dict]:
    """List every entry in the pattern library, with its current counts."""
    entries = load_patterns(DEFAULT_PATTERNS_DIR)
    return [
        {
            "id": e.id,
            "title": e.title,
            "category": e.category,
            "maps_to": e.maps_to_rule_id,
            "pattern": e.pattern,
            "use_case": e.use_case,
            "diagnosis": e.diagnosis,
            "fix": e.fix,
            "recommended_count": e.recommended_count,
            "used_count": e.used_count,
        }
        for e in entries
    ]


@mcp.tool()
def report_recommended(pattern_id: str) -> str:
    """Record that this pattern was just surfaced/recommended. No-op,
    reported honestly, if the pattern library isn't enabled or no backend
    is configured - see pattern_client.py."""
    if not is_enabled():
        return "not reported: pattern library isn't enabled (see `work-ledger patterns enable`)"
    sent = report_event(pattern_id, "recommended")
    return "reported" if sent else "not reported: no backend configured or unreachable"


@mcp.tool()
def report_used(pattern_id: str) -> str:
    """Record that this pattern's fix was actually applied. Same no-op
    behavior as report_recommended when the library isn't enabled or no
    backend is reachable."""
    if not is_enabled():
        return "not reported: pattern library isn't enabled (see `work-ledger patterns enable`)"
    sent = report_event(pattern_id, "used")
    return "reported" if sent else "not reported: no backend configured or unreachable"


@mcp.tool()
def submit_review_findings(findings: list[dict]) -> str:
    """Forward code-review findings (the same shape ReportFindings already
    produces: category, summary, failure_scenario, file, line, verdict)
    for later manual curation into new pattern-library entries. See
    docs/review-findings-harvesting-design.md.

    Only call this on explicit human instruction, after a review has
    already run, for a repo you actually have the right to share findings
    from - that instruction is the real safeguard (see the design doc's
    "Whose codebase is this, actually" section), not anything this tool
    can check on its own. Same no-op behavior as report_recommended/
    report_used when the library isn't enabled or no backend/token is
    configured."""
    sent, message = submit_findings(findings)
    return message if not sent else f"{message}: {len(findings)} finding(s)"


@mcp.tool()
def about() -> dict:
    """The About block (issue #75): short description, version, last-updated,
    commit (if resolvable from an editable git checkout), and author/repo
    attribution for this running work-ledger-mcp instance. Static metadata
    only, not a pattern-library interaction - unconditional, unlike
    report_recommended/report_used/submit_review_findings, which gate on
    the patterns opt-in."""
    info = get_about_info()
    return {
        "description": info.description,
        "version": info.version,
        "last_updated": info.last_updated,
        "commit": info.commit,
        "author_email": info.author_email,
        "author_url": info.author_url,
        "repo_url": info.repo_url,
    }


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
