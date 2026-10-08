"""Catalog of supported AI/LLM models for multi-platform harvester.

Provides curated model lists and live model-discovery helpers for:
- ZeroTwo (app.zerotwo.ai via local shim)
- Token Harbor (tokenharbor.ai)
- TokenMix (tokenmix.ai)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import httpx

TARGET_ZAI: str = "zai"

# Z.ai / ZCode GLM models
ZAI_MODELS: list[dict[str, Any]] = [
    {"id": "GLM-5.3", "name": "GLM 5.3", "provider": "zai", "type": "llm"},
    {"id": "GLM-5.3-Flash", "name": "GLM 5.3 Flash", "provider": "zai", "type": "llm"},
    {"id": "GLM-4.5-Flash", "name": "GLM 4.5 Flash", "provider": "zai", "type": "llm"},
]

@dataclass
class TargetCatalog:
    name: str
    display_name: str
    category: str
    models: list[str] = field(default_factory=list)
    default_port: int = 20128
    ledger_file: str = "zai_keys.jsonl"


# ZeroTwo models exposed via OpenAI-compatible shim
ZEROTWO_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-6-luna", "name": "GPT 6 Luna", "provider": "openai", "type": "llm"},
    {"id": "deepseek-v4.1-flash", "name": "DeepSeek 4.1 Flash", "provider": "deepseek", "type": "llm"},
    {"id": "minimax-m3", "name": "MiniMax M3", "provider": "minimax", "type": "llm"},
    {"id": "glm-5-3-flash", "name": "GLM 5.3 Flash", "provider": "zai", "type": "llm"},
    {"id": "muse-spark-1.3-contributor", "name": "Muse Spark 1.3 (c)", "provider": "meta", "type": "llm"},
]

# Token Harbor free models (native OpenAI-compatible endpoint: https://tokenharbor.ai/v1)
TOKENHARBOR_MODELS: list[dict[str, Any]] = [
    {"id": "mimo-v2.5:free", "name": "MiMo v2.5 (Free)", "provider": "xiaomi", "type": "llm"},
    {"id": "deepseek-v4-flash:free", "name": "DeepSeek V4 Flash (Free)", "provider": "deepseek", "type": "llm"},
    {"id": "deepseek-v4.1-flash:free", "name": "DeepSeek V4.1 Flash (Free)", "provider": "deepseek", "type": "llm"},
    {"id": "mimo-v2.6-flash:free", "name": "MiMo v2.6 Flash (Free)", "provider": "xiaomi", "type": "llm"},
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


# ElevenLabs audio & voice models (native endpoint: https://api.elevenlabs.io/v1)
ELEVENLABS_MODELS: list[dict[str, Any]] = [
    {"id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2", "provider": "elevenlabs", "type": "llm"},
    {"id": "eleven_turbo_v2_5", "name": "Eleven Turbo v2.5", "provider": "elevenlabs", "type": "llm"},
    {"id": "eleven_flash_v2_5", "name": "Eleven Flash v2.5", "provider": "elevenlabs", "type": "llm"},
    {"id": "eleven_multilingual_v1", "name": "Eleven Multilingual v1", "provider": "elevenlabs", "type": "llm"},
    {"id": "eleven_monolingual_v1", "name": "Eleven Monolingual v1", "provider": "elevenlabs", "type": "llm"},
]


# Grok xAI models (native OpenAI-compatible endpoint: https://api.x.ai/v1)
GROK_MODELS: list[dict[str, Any]] = [
    {"id": "grok-4", "name": "Grok 4", "provider": "xai", "type": "llm"},
    {"id": "grok-4-fast", "name": "Grok 4 Fast", "provider": "xai", "type": "llm"},
    {"id": "grok-3", "name": "Grok 3", "provider": "xai", "type": "llm"},
    {"id": "grok-3-mini", "name": "Grok 3 Mini", "provider": "xai", "type": "llm"},
    {"id": "grok-2-1212", "name": "Grok 2", "provider": "xai", "type": "llm"},
]


def get_default_models(platform: str) -> list[dict[str, Any]]:
    """Return default curated model catalog for the given platform."""
    p = platform.lower()
    if p in ("tokenharbor", "token-harbor", "th"):
        return list(TOKENHARBOR_MODELS)
    if p in ("tokenmix", "token-mix", "tm"):
        return list(TOKENMIX_MODELS)
    if p in ("elevenlabs", "eleven-labs", "el"):
        return list(ELEVENLABS_MODELS)
    if p in ("zerotwo", "zero-two", "zt"):
        return list(ZEROTWO_MODELS)
    if p in ("grok", "grok-xai", "xai"):
        return list(GROK_MODELS)
    if p in ("zai", "zcode", "glm"):
        return list(ZAI_MODELS)
    return []


def get_target_catalog(target: str) -> TargetCatalog:
    """Return TargetCatalog metadata for the target."""
    t = target.lower()
    if t in (TARGET_ZAI, "zcode", "glm"):
        return TargetCatalog(
            name=TARGET_ZAI,
            display_name="Z.ai (GLM-5.3 Coding Plan)",
            category="oauth",
            models=["GLM-5.3", "GLM-5.3-Flash", "GLM-4.5-Flash"],
            default_port=20128,
            ledger_file="zai_keys.jsonl",
        )
    return TargetCatalog(
        name=t,
        display_name=t.title(),
        category="custom",
        models=[m["id"] for m in get_default_models(t)],
        default_port=20128,
        ledger_file=f"{t}_keys.jsonl",
    )


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
    if platform.lower() in ("elevenlabs", "eleven-labs", "el"):
        headers["xi-api-key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") if isinstance(data, dict) else (data.get("models") if isinstance(data, dict) else data)
                if isinstance(items, list) and items:
                    models = []
                    seen = set()
                    is_tokenharbor = platform.lower() in ("tokenharbor", "token-harbor", "th")
                    th_allowed = {m["id"] for m in TOKENHARBOR_MODELS}

                    for item in items:
                        if isinstance(item, dict):
                            mid = item.get("id") or item.get("model_id")
                            if not mid:
                                continue
                            if is_tokenharbor and mid not in th_allowed and not mid.endswith(":free"):
                                continue
                            if mid not in seen:
                                seen.add(mid)
                                models.append({
                                    "id": mid,
                                    "name": item.get("name") or mid,
                                    "type": "tts" if platform.lower() in ("elevenlabs", "el") else "llm",
                                })
                        elif isinstance(item, str):
                            if is_tokenharbor and item not in th_allowed and not item.endswith(":free"):
                                continue
                            if item not in seen:
                                seen.add(item)
                                models.append({"id": item, "name": item, "type": "tts" if platform.lower() in ("elevenlabs", "el") else "llm"})
                    if models:
                        return models
    except Exception:
        pass

    return defaults
