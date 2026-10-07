"""OpenAI-compatible shim for ZeroTwo.

9Router talks to upstreams using the OpenAI protocol. ZeroTwo's own API is
*not* OpenAI-compatible: it authenticates with a Supabase JWT and expects a
provider/model pair. This shim bridges the two so a harvested ZeroTwo session
can be plugged straight into 9Router as an OpenAI-compatible provider.

Run it with::

    llm-harvester shim --port 8787

Then register the harvested sessions against ``http://<host>:8787/v1``.

Endpoints
---------
GET  /v1/models
POST /v1/chat/completions   (streaming + non-streaming)
GET  /healthz

The shim reads the ZeroTwo JWT from the request's ``Authorization: Bearer``
header, so a single shim process serves every harvested account. ZeroTwo's edge
also expects the Cloudflare clearance cookie and a CSRF token, so those are
configured once via ``LLM_ZT_COOKIES`` / ``LLM_ZT_CSRF`` (see ``.env.example``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

ZEROTWO_CHAT = "https://api.zerotwo.ai/api/ai/chat/stream"
ZEROTWO_CSRF = "https://api.zerotwo.ai/api/auth/csrf-token"
SUPABASE_REFRESH_URL = "https://jdbcevjbqaoxrxxwqwux.supabase.co/auth/v1/token?grant_type=refresh_token"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpkYmNldmpicWFveHJ4eHdxd3V4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTgyNDcyMzUsImV4cCI6MjA3MzgyMzIzNX0."
    "UcUJUjMocwijFTtYFKYuTgIODYWc4uxDByu2tI6XGQg"
)

# Requested exclusive models
ALLOWED_MODELS = [
    {"id": "gpt-6-luna", "name": "GPT 6 Luna", "provider": "openai"},
    {"id": "deepseek-v4.1-flash", "name": "DeepSeek 4.1 Flash", "provider": "deepseek"},
    {"id": "minimax-m3", "name": "MiniMax M3", "provider": "minimax"},
    {"id": "glm-5-3-flash", "name": "GLM 5.3 Flash", "provider": "zai"},
    {"id": "muse-spark-1.3-contributor", "name": "Muse Spark 1.3 (c)", "provider": "meta"},
]

MODEL_ALIASES = {
    "luna": "gpt-6-luna",
    "zerotwo/luna": "gpt-6-luna",
    "zerotwo/gpt-6-luna": "gpt-6-luna",
    "openai/gpt-6-luna": "gpt-6-luna",
    "openai/luna": "gpt-6-luna",
    "glm-5-3-flash": "zai-org-glm-5-3-flash",
    "glm-5.3-flash": "zai-org-glm-5-3-flash",
    "zai/glm-5-3-flash": "zai-org-glm-5-3-flash",
    "zai/glm-5.3-flash": "zai-org-glm-5-3-flash",
    "zerotwo/glm-5-3-flash": "zai-org-glm-5-3-flash",
    "deepseek/deepseek-v4.1-flash": "deepseek-v4.1-flash",
    "zerotwo/deepseek-v4.1-flash": "deepseek-v4.1-flash",
    "minimax/minimax-m3": "minimax-m3",
    "zerotwo/minimax-m3": "minimax-m3",
    "meta/muse-spark-1.3-contributor": "muse-spark-1.3-contributor",
    "zerotwo/muse-spark-1.3-contributor": "muse-spark-1.3-contributor",
}

# A pragmatic provider map; ZeroTwo model ids are prefixed like "openai/gpt-5".
PROVIDER_BY_PREFIX = {
    "gpt": "openai", "o1": "openai", "o3": "openai", "o4": "openai",
    "claude": "anthropic", "gemini": "google", "gemma": "google",
    "grok": "xai", "deepseek": "deepseek", "qwen": "qwen", "glm": "zai",
    "kimi": "kimi", "command": "cohere", "mistral": "mistral",
    "sonar": "perplexity", "llama": "meta", "minimax": "minimax",
    "mimo": "mimo", "mercury": "inception", "muse": "meta",
}


def _load_model_providers() -> dict[str, str]:
    from pathlib import Path
    sessions_file = Path("harvest/sessions.jsonl")
    providers = {
        "gpt-6-luna": "openai",
        "deepseek-v4.1-flash": "deepseek",
        "minimax-m3": "minimax",
        "glm-5-3-flash": "zai",
        "zai-org-glm-5-3-flash": "zai",
        "muse-spark-1.3-contributor": "meta",
    }
    if sessions_file.exists():
        try:
            for line in sessions_file.read_text().splitlines():
                if not line.strip():
                    continue
                d = json.loads(line)
                for m in d.get("models", []):
                    mid = m.get("id")
                    p = m.get("provider")
                    if mid and p:
                        providers[mid] = p
                        if "/" not in mid:
                            providers[f"{p}/{mid}"] = p
        except Exception:
            pass
    return providers


def split_model(model: str, known_models: dict[str, str] | None = None) -> tuple[str, str]:
    if model.startswith("zerotwo/"):
        model = model.removeprefix("zerotwo/")
    if "[" in model and model.endswith("]"):
        model = model[:model.index("[")]
    if model in MODEL_ALIASES:
        model = MODEL_ALIASES[model]
    if known_models and model in known_models:
        p = known_models[model]
        if model.startswith(f"{p}/"):
            return p, model[len(p) + 1:]
        return p, model
    if "/" in model:
        provider, _, name = model.partition("/")
        return provider, name
    base = model.split("-")[0].lower()
    return PROVIDER_BY_PREFIX.get(base, "openai"), model


def _chunk(model: str, delta: dict[str, Any], finish: str | None = None) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


class ZeroTwoShim:
    def __init__(
        self,
        *,
        timeout: float = 300.0,
        cookies: str = "",
        csrf: str = "",
        pool: SessionPool | None = None,
    ) -> None:
        self.timeout = timeout
        self.cookies = cookies
        self.csrf = csrf
        self._csrf_cache: dict[str, tuple[str, float]] = {}
        self.pool = pool or SessionPool()

    async def get_csrf(self, token: str) -> str:
        now = time.time()
        if token in self._csrf_cache:
            val, exp = self._csrf_cache[token]
            if now < exp - 300:
                return val
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(
                    ZEROTWO_CSRF,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Origin": "https://app.zerotwo.ai",
                        "Referer": "https://app.zerotwo.ai/",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    fresh = data.get("token", "")
                    exp_in = data.get("expiresIn", 3600)
                    if fresh:
                        self._csrf_cache[token] = (fresh, now + exp_in)
                        return fresh
        except Exception:
            pass
        return self.csrf

    def _headers(self, token: str, csrf: str | None = None, cookies: str | None = None) -> dict[str, str]:
        active_csrf = csrf or self.csrf
        active_cookies = cookies or self.cookies
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": "https://app.zerotwo.ai",
            "Referer": "https://app.zerotwo.ai/",
        }
        if active_csrf:
            headers["x-csrf-token"] = active_csrf

        cookie_parts = []
        if active_cookies:
            parts = [c.strip() for c in active_cookies.split(";") if c.strip() and not c.strip().startswith("__csrf=")]
            if active_csrf:
                parts.append(f"__csrf={active_csrf}")
            cookie_parts.extend(parts)
        elif active_csrf:
            cookie_parts.append(f"__csrf={active_csrf}")

        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        return headers

    def _body(self, req: dict[str, Any], *, stream: bool, known_models: dict[str, str] | None = None) -> dict[str, Any]:
        provider, model = split_model(req.get("model", "openai/gpt-5"), known_models)
        messages = req.get("messages", [])
        clean = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for b in content:
                    if isinstance(b, dict):
                        if b.get("type") == "text" and isinstance(b.get("text"), str):
                            text_parts.append(b["text"])
                        elif "content" in b and isinstance(b["content"], str):
                            text_parts.append(b["content"])
                    elif isinstance(b, str):
                        text_parts.append(b)
                content = "".join(text_parts)
            elif not isinstance(content, str):
                content = str(content) if content is not None else ""

            # Sanitize large agent / hook messages for ZeroTwo's web chat limits
            if role == "system" and len(content) > 2000:
                content = content[:2000]
            elif "SessionStart:startup hook" in content:
                # Drop this message entirely — consecutive user msgs cause WORK_AGENT_START_FAILED
                continue
            elif "</system-reminder>" in content:
                content = content.split("</system-reminder>")[-1].strip()

            if len(content) > 4000:
                content = content[:4000]

            if not content.strip():
                continue

            clean.append({
                "role": role,
                "content": content,
                "id": m.get("id") or str(uuid.uuid4()),
            })
        last_user = next(
            (m["content"] for m in reversed(clean) if m["role"] == "user"), ""
        )
        if not last_user and clean:
            last_user = clean[-1]["content"]
        
        context_msg = last_user
        if "</system-reminder>" in context_msg:
            context_msg = context_msg.split("</system-reminder>")[-1].strip()
        if len(context_msg) > 1000:
            context_msg = context_msg[:1000]
        if not context_msg:
            context_msg = "Hello"

        effort = req.get("reasoning_effort", "medium")
        body: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "messages": clean,
            "attachments": [],
            "contextData": {
                "message": context_msg,
                "has_files": False,
                "file_count": 0,
                "mode": {"type": "thread", "retrieval": None},
                "unifiedTurnVersion": 1,
            },
            "stream": True,
        }
        if effort:
            body["reasoning_effort"] = effort
        return body

    async def chat(
        self, req: dict[str, Any], token: str, csrf: str | None = None, cookies: str | None = None, known_models: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Non-streaming completion: drain the SSE stream and return one JSON."""
        provider, model = split_model(req.get("model", "openai/gpt-5"), known_models)
        text_parts: list[str] = []
        async for piece in self._raw_stream(req, token, csrf=csrf, cookies=cookies, known_models=known_models):
            if piece["type"] == "text":
                text_parts.append(piece["value"])
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{provider}/{model}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": "stop",
            }],
            "usage": {},
        }

    async def stream(
        self, req: dict[str, Any], token: str, csrf: str | None = None, cookies: str | None = None, known_models: dict[str, str] | None = None
    ) -> AsyncIterator[str]:
        provider, model = split_model(req.get("model", "openai/gpt-5"), known_models)
        out_model = f"{provider}/{model}"
        yield _chunk(out_model, {"role": "assistant"})
        try:
            async for piece in self._raw_stream(req, token, csrf=csrf, cookies=cookies, known_models=known_models):
                if piece["type"] == "text" and piece["value"]:
                    yield _chunk(out_model, {"content": piece["value"]})
        except Exception as exc:
            yield _chunk(out_model, {"content": f"[shim error: {exc}]"})
        yield _chunk(out_model, {}, finish="stop")
        yield "data: [DONE]\n\n"

    async def resolve_session(self, token_or_id: str) -> dict[str, Any] | None:
        """Find the session and proactively refresh its access_token if expired, or fallback to healthy session."""
        return await self.pool.get_healthy_session(token_or_id)

    async def refresh_token_for_session(self, token: str) -> str | None:
        sessions = await self.pool.load()
        target_s = _find_session(token, sessions)
        if not target_s or not target_s.get("refresh_token"):
            return None
        ok = await self.pool.refresh_session(target_s)
        if ok:
            await self.pool.save(sessions)
            print(f"[shim] Token refreshed for {target_s.get('email', 'unknown')}")
            return target_s.get("access_token")
        return None

    async def _raw_stream(
        self, req: dict[str, Any], token: str, csrf: str | None = None, cookies: str | None = None, known_models: dict[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        active_csrf = csrf or await self.get_csrf(token)
        retried_csrf = False
        refreshed_token = False
        out_body = self._body(req, stream=True, known_models=known_models)
        print(f"[shim DEBUG] messages count={len(out_body.get('messages', []))}, contextData msg len={len(out_body.get('contextData', {}).get('message', ''))}")

        while True:
            headers = self._headers(token, csrf=active_csrf, cookies=cookies)
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                async with c.stream(
                    "POST", ZEROTWO_CHAT, headers=headers,
                    json=out_body,
                ) as r:
                    if r.status_code == 401 and not refreshed_token:
                        new_tok = await self.refresh_token_for_session(token)
                        if new_tok:
                            token = new_tok
                            refreshed_token = True
                            active_csrf = await self.get_csrf(token)
                            continue

                        # Mark current session dead and attempt failover to another healthy session in pool
                        await self.pool.mark_dead(token, "401 unauthorized")
                        alt_sess = await self.pool.get_healthy_session()
                        if alt_sess and alt_sess.get("access_token") != token:
                            token = alt_sess["access_token"]
                            if alt_sess.get("cookies"):
                                cookies = "; ".join(f"{c['name']}={c['value']}" for c in alt_sess["cookies"] if c.get("name"))
                            active_csrf = alt_sess.get("csrf_token") or await self.get_csrf(token)
                            print(f"[shim] 401 failover: switched to session {alt_sess.get('email', 'unknown')}")
                            refreshed_token = True
                            continue

                        err_body = (await r.aread()).decode(errors="replace")
                        raise RuntimeError(f"ZeroTwo API returned {r.status_code}: {err_body}")

                    if r.status_code == 403 and not retried_csrf:
                        err_body = (await r.aread()).decode(errors="replace")
                        if "CSRF" in err_body or "Forbidden" in err_body:
                            self._csrf_cache.pop(token, None)
                            active_csrf = await self.get_csrf(token)
                            retried_csrf = True
                            continue
                        raise RuntimeError(f"ZeroTwo API returned {r.status_code}: {err_body}")
                    elif r.status_code >= 400:
                        err_body = (await r.aread()).decode(errors="replace")
                        raise RuntimeError(f"ZeroTwo API returned {r.status_code}: {err_body}")

                    deltas_seen = False
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            return
                        try:
                            ev = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue

                        if ev.get("status") == "error":
                            v = ev.get("v") or {}
                            err_msg = v.get("message") or v.get("displayMessage") or str(v)
                            try:
                                with open("/tmp/zt_last_error_req.json", "w") as ef:
                                    json.dump(out_body, ef)
                            except Exception:
                                pass
                            print(f"[shim DEBUG] ZeroTwo API stream error: {err_msg}, ev={ev}", file=sys.stderr)
                            raise RuntimeError(f"ZeroTwo API stream error: {err_msg}")

                        entity = ev.get("entity")
                        status = ev.get("status")
                        v = ev.get("v")

                        if entity == "message.content" and status == "delta" and isinstance(v, dict):
                            d = v.get("delta") or {}
                            txt = d.get("text") or d.get("content") or ""
                            if txt:
                                txt = txt.replace("<ent>", "").replace("</ent>", "")
                                if txt:
                                    deltas_seen = True
                                    yield {"type": "text", "value": txt}
                                continue

                        if entity == "message" and status == "completed" and isinstance(v, dict):
                            if not deltas_seen:
                                full_txt = v.get("content") or ""
                                if full_txt:
                                    full_txt = full_txt.replace("<ent>", "").replace("</ent>", "")
                                    yield {"type": "text", "value": full_txt}
                            continue

                        if not deltas_seen:
                            text = self._extract_text(ev)
                            if text:
                                yield {"type": "text", "value": text}
                    return

    @staticmethod
    def _extract_text(payload: Any) -> str:
        """Pull assistant text out of ZeroTwo's stream entity payloads."""
        if not isinstance(payload, dict):
            return ""
        v = payload.get("v")
        if isinstance(v, dict):
            for key in ("content", "text", "delta", "output_text"):
                val = v.get(key)
                if isinstance(val, str):
                    return val
                if isinstance(val, dict):
                    t = val.get("text") or val.get("content") or val.get("delta")
                    if isinstance(t, str):
                        return t
        for key in ("content", "text", "delta", "output_text"):
            val = payload.get(key)
            if isinstance(val, str):
                return val
            if isinstance(val, dict):
                t = val.get("text") or val.get("content") or val.get("delta")
                if isinstance(t, str):
                    return t
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            c = choices[0]
            if isinstance(c, dict):
                delta = c.get("delta")
                if isinstance(delta, dict):
                    if isinstance(delta.get("content"), str):
                        return delta["content"]
                    if isinstance(delta.get("text"), str):
                        return delta["text"]
                if isinstance(c.get("message", {}).get("content"), str):
                    return c["message"]["content"]
                if isinstance(c.get("text"), str):
                    return c["text"]
        return ""


def _extract_jwt_claims(jwt_str: str) -> dict[str, Any]:
    """Safely decode unverified claims from a JWT string."""
    if not isinstance(jwt_str, str) or not jwt_str or jwt_str.count(".") < 2:
        return {}
    try:
        payload = jwt_str.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _load_all_sessions() -> list[dict[str, Any]]:
    """Load all sessions from harvest/sessions.jsonl."""
    from pathlib import Path
    sessions_file = Path("harvest/sessions.jsonl")
    result = []
    if sessions_file.exists():
        try:
            for line in sessions_file.read_text().splitlines():
                if not line.strip():
                    continue
                result.append(json.loads(line))
        except Exception:
            pass
    return result


def _find_session(token_or_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a session matching an access token, email, user_id, or even an expired/rotated JWT."""
    if not token_or_id or not sessions:
        return None
    token_or_id_clean = token_or_id.strip()

    # 1. Exact match on access_token
    for s in sessions:
        if s.get("access_token") == token_or_id_clean:
            return s

    # 2. Match on email or user_id
    for s in sessions:
        if s.get("email") == token_or_id_clean or s.get("user_id") == token_or_id_clean:
            return s

    # 3. Match on JWT sub / email if token_or_id is a JWT (even if expired or previous token)
    claims = _extract_jwt_claims(token_or_id_clean)
    if claims:
        sub = claims.get("sub")
        email = claims.get("email")
        for s in sessions:
            if sub and s.get("user_id") == sub:
                return s
            if email and s.get("email") == email:
                return s

    return None


async def refresh_supabase_token(refresh_token: str) -> tuple[str | None, str | None]:
    """Exchange a Supabase refresh_token for a fresh access_token and refresh_token."""
    if not refresh_token:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(
                SUPABASE_REFRESH_URL,
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                json={"refresh_token": refresh_token},
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("access_token"), data.get("refresh_token")
    except Exception:
        pass
    return None, None


def _load_sessions_map() -> dict[str, dict[str, Any]]:
    result = {}
    for s in _load_all_sessions():
        token = s.get("access_token")
        if token:
            result[token] = s
    return result


class SessionPool:
    """Thread-safe, lock-protected manager for harvested ZeroTwo sessions."""

    def __init__(self, sessions_path: str | Path = "harvest/sessions.jsonl") -> None:
        self.path = Path(sessions_path)
        self._lock = asyncio.Lock()
        self._cached_sessions: list[dict[str, Any]] = []

    async def load(self) -> list[dict[str, Any]]:
        async with self._lock:
            if not self.path.exists():
                return []
            sessions = []
            try:
                for line in self.path.read_text().splitlines():
                    if line.strip():
                        sessions.append(json.loads(line))
            except Exception:
                pass
            self._cached_sessions = sessions
            return list(sessions)

    async def save(self, sessions: list[dict[str, Any]]) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".tmp")
            content = "\n".join(json.dumps(s) for s in sessions) + ("\n" if sessions else "")
            tmp_path.write_text(content)
            tmp_path.replace(self.path)
            self._cached_sessions = list(sessions)

    async def refresh_session(self, s: dict[str, Any]) -> bool:
        rt = s.get("refresh_token")
        if not rt:
            s["status"] = "expired"
            s["last_refresh_error"] = "no_refresh_token"
            return False
        new_at, new_rt = await refresh_supabase_token(rt)
        if new_at:
            s["access_token"] = new_at
            if new_rt:
                s["refresh_token"] = new_rt
            s["status"] = "active"
            s["last_refreshed_at"] = time.time()
            s.pop("last_refresh_error", None)
            return True
        else:
            s["status"] = "expired"
            s["last_refresh_error"] = "refresh_failed"
            return False

    async def refresh_all(self, threshold_seconds: float = 1200.0) -> dict[str, int]:
        sessions = await self.load()
        if not sessions:
            return {"total": 0, "refreshed": 0, "active": 0, "failed": 0}

        now = time.time()
        refreshed_count = 0
        active_count = 0
        failed_count = 0
        changed = False

        for s in sessions:
            at = s.get("access_token", "")
            claims = _extract_jwt_claims(at)
            exp = claims.get("exp")
            needs_refresh = False
            if not exp or (exp - now) <= threshold_seconds:
                needs_refresh = True

            if needs_refresh:
                ok = await self.refresh_session(s)
                if ok:
                    refreshed_count += 1
                    active_count += 1
                    changed = True
                else:
                    failed_count += 1
                    changed = True
            else:
                s["status"] = "active"
                active_count += 1

        if changed:
            await self.save(sessions)

        return {
            "total": len(sessions),
            "refreshed": refreshed_count,
            "active": active_count,
            "failed": failed_count,
        }

    async def get_healthy_session(self, preferred_token_or_id: str | None = None) -> dict[str, Any] | None:
        sessions = await self.load()
        if not sessions:
            return None

        now = time.time()

        # 1. Check preferred
        if preferred_token_or_id:
            s = _find_session(preferred_token_or_id, sessions)
            if s and s.get("status") not in ("expired", "dead"):
                claims = _extract_jwt_claims(s.get("access_token", ""))
                exp = claims.get("exp")
                if not exp or exp - now <= 120:
                    ok = await self.refresh_session(s)
                    if ok:
                        await self.save(sessions)
                        return s
                else:
                    return s

        # 2. Preferred is missing, dead, or expired -> Failover to any healthy session
        for s in sessions:
            if s.get("status") in ("expired", "dead"):
                continue
            claims = _extract_jwt_claims(s.get("access_token", ""))
            exp = claims.get("exp")
            if not exp or exp - now <= 120:
                ok = await self.refresh_session(s)
                if ok:
                    await self.save(sessions)
                    return s
            else:
                return s

        return None

    async def mark_dead(self, token_or_id: str, reason: str = "") -> None:
        sessions = await self.load()
        target = _find_session(token_or_id, sessions)
        if target:
            target["status"] = "dead"
            target["last_error"] = reason
            await self.save(sessions)


def build_app(shim: ZeroTwoShim | None = None, pool: SessionPool | None = None) -> Any:
    """Return an ASGI app exposing the OpenAI-compatible surface with auto-refresh."""
    import os
    from pathlib import Path

    default_cookies = os.getenv("LLM_ZT_COOKIES") or os.getenv("ZT_ZT_COOKIES", "")
    default_csrf = os.getenv("LLM_ZT_CSRF") or os.getenv("ZT_ZT_CSRF", "")
    if not default_cookies or not default_csrf:
        p = Path("harvest/sessions.jsonl")
        if p.exists():
            for line in reversed(p.read_text().splitlines()):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if not default_csrf and data.get("csrf_token"):
                        default_csrf = data["csrf_token"]
                    if not default_cookies and data.get("cookies"):
                        default_cookies = "; ".join(f"{c['name']}={c['value']}" for c in data["cookies"] if c.get("name"))
                    if default_cookies and default_csrf:
                        break
                except Exception:
                    pass

    pool = pool or (shim.pool if shim else SessionPool())
    shim = shim or ZeroTwoShim(
        cookies=default_cookies,
        csrf=default_csrf,
        pool=pool,
    )

    bg_task: asyncio.Task | None = None

    async def _auto_refresh_worker() -> None:
        try:
            stats = await pool.refresh_all(threshold_seconds=1200.0)
            if stats.get("refreshed", 0) > 0 or stats.get("failed", 0) > 0:
                print(
                    f"[shim auto-refresh] startup: {stats['active']} active, "
                    f"{stats['refreshed']} refreshed, {stats['failed']} failed"
                )
        except Exception as exc:
            print(f"[shim auto-refresh startup error] {exc}", file=sys.stderr)

        while True:
            try:
                await asyncio.sleep(600)  # check every 10 minutes
                stats = await pool.refresh_all(threshold_seconds=1200.0)
                if stats.get("refreshed", 0) > 0 or stats.get("failed", 0) > 0:
                    print(
                        f"[shim auto-refresh] {stats['active']} active, "
                        f"{stats['refreshed']} refreshed, {stats['failed']} failed"
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[shim auto-refresh error] {exc}", file=sys.stderr)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal bg_task
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    if bg_task is None or bg_task.done():
                        bg_task = asyncio.create_task(_auto_refresh_worker())
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    if bg_task and not bg_task.done():
                        bg_task.cancel()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return

        if scope["type"] != "http":
            return

        # Fallback in case server did not emit lifespan events
        if bg_task is None or bg_task.done():
            bg_task = asyncio.create_task(_auto_refresh_worker())
        path = scope["path"]
        method = scope["method"]
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()

        if path == "/healthz":
            await _json(send, 200, {"status": "ok"})
            return
        if path == "/v1/models" and method == "GET":
            await _json(send, 200, {"object": "list", "data": _model_list()})
            return
        if path == "/v1/chat/completions" and method == "POST":
            body = await _read_json(receive)
            model_req = body.get("model", "unknown")
            is_stream = bool(body.get("stream"))

            if not token:
                print(f"[shim] 401 Unauthorized: missing bearer token for model={model_req}", file=sys.stderr)
                await _json(send, 401, {"error": {"message": "missing bearer token"}})
                return

            sess = await shim.resolve_session(token)
            if sess:
                active_token = sess.get("access_token") or token
                req_csrf = sess.get("csrf_token") or None
                req_cookies = "; ".join(f"{c['name']}={c['value']}" for c in sess["cookies"] if c.get("name")) if sess.get("cookies") else None
                user_desc = sess.get("email", "unknown")
            else:
                active_token = token
                req_csrf = None
                req_cookies = None
                user_desc = f"external ({token[:12]}...)"

            print(f"[shim] POST /v1/chat/completions model={model_req} user={user_desc} stream={is_stream}")

            known_models = _load_model_providers()

            if is_stream:
                await _stream(send, shim.stream(body, active_token, csrf=req_csrf, cookies=req_cookies, known_models=known_models))
            else:
                try:
                    result = await shim.chat(body, active_token, csrf=req_csrf, cookies=req_cookies, known_models=known_models)
                    print(f"[shim] 200 OK model={model_req} user={user_desc}")
                    await _json(send, 200, result)
                except Exception as exc:
                    print(f"[shim] 502 Bad Gateway for {model_req} (user={user_desc}): {exc}", file=sys.stderr)
                    await _json(send, 502, {"error": {"message": str(exc)}})
            return
        await _json(send, 404, {"error": {"message": "not found"}})

    return app


def _model_list() -> list[dict[str, Any]]:
    return [
        {"id": m["id"], "object": "model", "owned_by": m["provider"]}
        for m in ALLOWED_MODELS
    ]


async def _read_json(receive: Any) -> dict[str, Any]:
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body"):
            break
    return json.loads(body or b"{}")


async def _json(send: Any, status: int, payload: Any) -> None:
    data = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": data})


async def _stream(send: Any, gen: AsyncIterator[str]) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": [
        (b"content-type", b"text/event-stream"),
        (b"cache-control", b"no-cache"),
        (b"connection", b"keep-alive"),
    ]})
    async for chunk in gen:
        await send({"type": "http.response.body", "body": chunk.encode(),
                    "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})
