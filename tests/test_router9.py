import httpx
import pytest
from ztharvester.router9 import NineRouterClient


@pytest.mark.asyncio
async def test_connect_session_requires_token():
    client = NineRouterClient("http://localhost:1")
    res = await client.connect_session(email="a@b.c", access_token="", node_id=None)
    assert res.ok is False


@pytest.mark.asyncio
async def test_update_connection_failure():
    client = NineRouterClient("http://127.0.0.1:1", timeout=0.5)
    res = await client.update_connection("cid-1", provider="p", api_key="k", name="n")
    assert res.ok is False

