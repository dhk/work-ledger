import pytest

pytest.importorskip("mcp", reason="mcp is an optional dependency (the `patterns` extra)")

import asyncio

from work_ledger import mcp_server
from work_ledger.mcp_server import mcp


def test_server_registers_expected_tools():
    async def _list():
        return await mcp.list_tools()

    tools = asyncio.run(_list())
    names = {t.name for t in tools}
    assert names == {
        "list_patterns",
        "report_recommended",
        "report_used",
        "submit_review_findings",
        "about",
    }


def test_about_tool_returns_expected_shape(monkeypatch):
    """about() is unconditional (issue #75) - unlike report_recommended/
    report_used/submit_review_findings, it must never gate on
    pattern_client.is_enabled(), since it's static metadata about the
    running code, not a pattern-library interaction."""
    from work_ledger.about import AboutInfo

    fake = AboutInfo(
        description="Lightweight, near-real-time Claude Code usage/cost tracker for individuals",
        version="1.2.3",
        last_updated="2026-07-20T10:00:00+00:00",
        commit="abc1234",
        author_email="davehk@gmail.com",
        author_url="www.dhk.io",
        repo_url="https://github.com/dhk/work-ledger",
    )
    monkeypatch.setattr(mcp_server, "get_about_info", lambda: fake)

    result = mcp_server.about()
    assert result == {
        "description": fake.description,
        "version": "1.2.3",
        "last_updated": "2026-07-20T10:00:00+00:00",
        "commit": "abc1234",
        "author_email": "davehk@gmail.com",
        "author_url": "www.dhk.io",
        "repo_url": "https://github.com/dhk/work-ledger",
    }
