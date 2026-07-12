"""Local MCP server for the pattern-library mechanism (see
docs/pattern-library-design.md) - exposes list_patterns, report_recommended,
and report_used as MCP tools, connectable directly to a Claude Code session.

This is what makes the mechanism "live in-session" rather than only an
after-the-fact CLI report (the actual argument for choosing MCP in the
design doc): a session can consult known patterns while it's happening,
not just when someone later runs `work-ledger recommend`.

Runs over stdio, the standard local MCP transport - add it to your
Claude Code MCP config pointing at `work-ledger-mcp` (see README). Reads
the same local pattern content (`load_patterns`) and reports through the
same best-effort, opt-in client (`pattern_client`) as the CLI path, so
there is exactly one source of truth for both.

Honest scoping note: this server runs locally on your machine - it is
not itself "the mother ship." The counters it reports to still need
WORK_LEDGER_PATTERN_BACKEND_URL pointed at an actual deployed backend
(see pattern_client.py); nothing here stands that backend up.
"""

from mcp.server.fastmcp import FastMCP

from work_ledger.pattern_client import is_enabled, report_event
from work_ledger.patterns import DEFAULT_PATTERNS_DIR, load_patterns

mcp = FastMCP(
    "work-ledger-patterns",
    instructions=(
        "Known mistakes/patterns/fixes from work-ledger's shared pattern "
        "library. Use list_patterns to see what's available, and call "
        "report_recommended/report_used to contribute to the library's "
        "usage counters when you actually apply one of these."
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


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
