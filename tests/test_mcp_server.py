import pytest

pytest.importorskip("mcp", reason="mcp is an optional dependency (the `patterns` extra)")

import asyncio

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
    }
