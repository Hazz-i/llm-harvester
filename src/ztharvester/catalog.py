"""Catalog of supported AI/LLM models for multi-platform harvester.

Provides curated model lists and live model-discovery helpers for:
- ZeroTwo (app.zerotwo.ai via local shim)
- Token Harbor (tokenharbor.ai)
- TokenMix (tokenmix.ai)
"""

from __future__ import annotations

from typing import Any
import httpx


# ZeroTwo models exposed via OpenAI-compatible shim
ZEROTWO_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-6-luna", "name": "GPT 6 Luna", "provider": "openai", "type": "llm"},
    {"id": "deepseek-v4.1-flash", "name": "DeepSeek 4.1 Flash", "provider": "deepseek", "type": "llm"},
    {"id": "minimax-m3", "name": "MiniMax M3", "provider": "minimax", "type": "llm"},
    {"id": "glm-5-3-flash", "name": "GLM 5.3 Flash", "provider": "zai", "type": "llm"},
    {"id": "muse-spark-1.3-contributor", "name": "Muse Spark 1.3 (c)", "provider": "meta", "type": "llm"},
]

# Token Harbor models (native OpenAI-compatible endpoint: https://tokenharbor.ai/v1)
TOKENHARBOR_MODELS: list[dict[str, Any]] = [
    {"id": "claude-opus-5.5", "name": "Claude Opus 5.5", "provider": "anthropic", "type": "llm"},
    {"id": "claude-opus-5.5-fast", "name": "Claude Opus 5.5 Fast", "provider": "anthropic", "type": "llm"},
    {"id": "claude-sonnet-5.5", "name": "Claude Sonnet 5.5", "provider": "anthropic", "type": "llm"},
    {"id": "claude-fable-5.1", "name": "Claude Fable 5.1", "provider": "anthropic", "type": "llm"},
    {"id": "gpt-6-astra", "name": "GPT-6 Astra", "provider": "openai", "type": "llm"},
    {"id": "gpt-6-astra-fast", "name": "GPT-6 Astra Fast", "provider": "openai", "type": "llm"},
    {"id": "gpt-5.5", "name": "GPT-5.5", "provider": "openai", "type": "llm"},
    {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra", "provider": "openai", "type": "llm"},
    {"id": "claude-opus-4.8", "name": "Claude Opus 4.8", "provider": "anthropic", "type": "llm"},
    {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro", "provider": "google", "type": "llm"},
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "provider": "anthropic", "type": "llm"},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "provider": "anthropic", "type": "llm"},
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "type": "llm"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai", "type": "llm"},
    {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-r1", "name": "DeepSeek R1", "provider": "deepseek", "type": "llm"},
    {"id": "qwen-2.5-72b", "name": "Qwen 2.5 72B", "provider": "alibaba", "type": "llm"},
    {"id": "llama-3.3-70b", "name": "Llama 3.3 70B", "provider": "meta", "type": "llm"},
]

# TokenMix models (native OpenAI-compatible endpoint: https://api.tokenmix.ai/v1)
TOKENMIX_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai", "type": "llm"},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai", "type": "llm"},
    {"id": "gpt-5.4", "name": "GPT-5.4", "provider": "openai", "type": "llm"},
    {"id": "gpt-5.5", "name": "GPT-5.5", "provider": "openai", "type": "llm"},
    {"id": "o3", "name": "OpenAI o3", "provider": "openai", "type": "llm"},
    {"id": "o3-mini", "name": "OpenAI o3-mini", "provider": "openai", "type": "llm"},
    {"id": "o4-mini", "name": "OpenAI o4-mini", "provider": "openai", "type": "llm"},
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "provider": "anthropic", "type": "llm"},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "provider": "anthropic", "type": "llm"},
    {"id": "claude-opus-4.7", "name": "Claude Opus 4.7", "provider": "anthropic", "type": "llm"},
    {"id": "claude-haiku-4.5", "name": "Claude Haiku 4.5", "provider": "anthropic", "type": "llm"},
    {"id": "deepseek-v4", "name": "DeepSeek V4", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-v3", "name": "DeepSeek V3", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-r1", "name": "DeepSeek R1", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "provider": "deepseek", "type": "llm"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "google", "type": "llm"},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "google", "type": "llm"},
    {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro", "provider": "google", "type": "llm"},
    {"id": "qwen-3.6", "name": "Qwen 3.6", "provider": "alibaba", "type": "llm"},
    {"id": "qwen-2.5-72b", "name": "Qwen 2.5 72B", "provider": "alibaba", "type": "llm"},
    {"id": "kimi-k2.6", "name": "Kimi K2.6", "provider": "moonshot", "type": "llm"},
]


def get_default_models(platform: str) -> list[dict[str, Any]]:
    """Return default curated model catalog for the given platform."""
    p = platform.lower()
    if p in ("tokenharbor", "token-harbor", "th"):
        return list(TOKENHARBOR_MODELS)
    if p in ("tokenmix", "token-mix", "tm"):
        return list(TOKENMIX_MODELS)
    if p in ("zerotwo", "zero-two", "zt"):
        return list(ZEROTWO_MODELS)
    return []


async def fetch_provider_models(
    platform: str,
    api_key: str = "",
    api_base: str = "",
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Fetch live model catalog from provider /v1/models using API key, with fallback to curated models."""
    defaults = get_default_models(platform)
    if not api_key or not api_base:
        return defaults

    url = f"{api_base.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    models = []
                    seen = set()
                    for item in items:
                        if isinstance(item, dict) and "id" in item:
                            mid = item["id"]
                            if mid not in seen:
                                seen.add(mid)
                                models.append({
                                    "id": mid,
                                    "name": item.get("name") or mid,
                                    "type": "llm",
                                })
                        elif isinstance(item, str) and item not in seen:
                            seen.add(item)
                            models.append({"id": item, "name": item, "type": "llm"})
                    if models:
                        return models
    except Exception:
        pass

    return defaults
