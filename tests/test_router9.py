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


@pytest.mark.asyncio
async def test_prune_unwanted_models():
    from unittest.mock import AsyncMock, patch

    client = NineRouterClient("http://127.0.0.1:20128", timeout=1.0)
    mock_get_resp = AsyncMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json = lambda: {
        "models": [
            {"providerAlias": "node-1", "id": "mimo-v2.5:free"},
            {"providerAlias": "node-1", "id": "paid-model-1"},
            {"providerAlias": "node-2", "id": "paid-model-2"},
        ]
    }

    mock_del_resp = AsyncMock()
    mock_del_resp.status_code = 200

    with patch("httpx.AsyncClient.get", return_value=mock_get_resp), \
         patch("httpx.AsyncClient.delete", return_value=mock_del_resp) as mock_delete:
        pruned = await client.prune_unwanted_models("node-1", {"mimo-v2.5:free"})
        assert pruned == 1
        mock_delete.assert_called_once_with(
            "http://127.0.0.1:20128/api/models/custom",
            headers=client._headers,
            params={"providerAlias": "node-1", "id": "paid-model-1"},
        )


