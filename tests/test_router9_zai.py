import pytest
from unittest.mock import AsyncMock, patch
from llmharvester.router9 import NineRouterClient, RouterResult


@pytest.mark.asyncio
async def test_register_glm_connection():
    client = NineRouterClient("http://localhost:20128")
    with patch.object(
        client,
        "add_connection",
        new=AsyncMock(return_value=RouterResult(ok=True, connection_id="conn_123", message="connected")),
    ) as mock_add:
        res = await client.register_glm_connection("test_api_key.secret_123", email="user@test.com")
        assert res.ok is True
        assert res.connection_id == "conn_123"
        mock_add.assert_called_once()
        kwargs = mock_add.call_args.kwargs
        assert kwargs["provider"] == "glm"
        assert kwargs["api_key"] == "test_api_key.secret_123"
        assert "user@test.com" in kwargs["name"]
