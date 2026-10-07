import pytest
from unittest.mock import AsyncMock, patch
from llmharvester.catalog import (
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
    assert "mimo-v2.5:free" in th_ids
    assert "deepseek-v4-flash:free" in th_ids
    assert "deepseek-v4.1-flash:free" in th_ids
    assert "mimo-v2.6-flash:free" in th_ids
    assert len(th_ids) == 4

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
            {"id": "claude-opus-5.5", "name": "Claude Opus 5.5 (Paid)"},
            {"id": "mimo-v2.5:free", "name": "MiMo v2.5 Free"},
            {"id": "deepseek-v4-flash:free", "name": "DeepSeek V4 Flash Free"},
        ]
    }
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: fake_response
        mock_get.return_value = mock_resp

        # Token Harbor filters out non-free models
        th_models = await fetch_provider_models("tokenharbor", "test_key", "https://api.test/v1")
        assert len(th_models) == 2
        assert th_models[0]["id"] == "mimo-v2.5:free"
        assert th_models[1]["id"] == "deepseek-v4-flash:free"

        # Other platforms keep all returned models
        tm_models = await fetch_provider_models("tokenmix", "test_key", "https://api.test/v1")
        assert len(tm_models) == 3
