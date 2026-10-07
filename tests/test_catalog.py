import pytest
from unittest.mock import AsyncMock, patch
from ztharvester.catalog import (
    get_default_models,
    fetch_provider_models,
    TOKENHARBOR_MODELS,
    TOKENMIX_MODELS,
    ZEROTWO_MODELS,
)


def test_get_default_models():
    assert len(get_default_models("tokenharbor")) == len(TOKENHARBOR_MODELS)
    assert len(get_default_models("tokenmix")) == len(TOKENMIX_MODELS)
    assert len(get_default_models("zerotwo")) == len(ZEROTWO_MODELS)
    assert get_default_models("unknown") == []

    th_ids = [m["id"] for m in TOKENHARBOR_MODELS]
    assert "claude-opus-5.5" in th_ids
    assert "gpt-6-astra" in th_ids

    tm_ids = [m["id"] for m in TOKENMIX_MODELS]
    assert "gpt-4o" in tm_ids
    assert "deepseek-v4" in tm_ids


@pytest.mark.asyncio
async def test_fetch_provider_models_fallback():
    # When api_key or api_base is empty, returns defaults
    res = await fetch_provider_models("tokenharbor", "", "")
    assert len(res) == len(TOKENHARBOR_MODELS)

    # When network fails, returns defaults
    res = await fetch_provider_models("tokenmix", "bad_key", "http://127.0.0.1:1")
    assert len(res) == len(TOKENMIX_MODELS)


@pytest.mark.asyncio
async def test_fetch_provider_models_success():
    fake_response = {
        "data": [
            {"id": "custom-model-1", "name": "Custom 1"},
            {"id": "custom-model-2", "name": "Custom 2"},
        ]
    }
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: fake_response
        mock_get.return_value = mock_resp

        models = await fetch_provider_models("tokenharbor", "test_key", "https://api.test/v1")
        assert len(models) == 2
        assert models[0]["id"] == "custom-model-1"
        assert models[1]["id"] == "custom-model-2"
