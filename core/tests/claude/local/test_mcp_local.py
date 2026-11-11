"""The MCP tools the owner calls from Claude sessions, run in-process on the
local suite's seeded SANDBOX (cloud blocked). These tools are deterministic
(no model call), so a failure here is a store/ledger/privacy bug."""
import pytest

from tests.claude import mcp_cases


@pytest.fixture(scope="module")
def mcp_server(client):
    """The server module re-pointed at the sandbox make_client created."""
    return mcp_cases.load_server()


@pytest.mark.parametrize("check", mcp_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_mcp_local(client, mcp_server, check):
    check(client, mcp_server)
