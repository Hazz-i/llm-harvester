"""OpenAI-compatible shim for ZeroTwo.

9Router talks to upstreams using the OpenAI protocol. ZeroTwo's own API is
*not* OpenAI-compatible: it authenticates with a Supabase JWT and expects a
provider/model pair. This shim bridges the two so a harvested ZeroTwo session
can be plugged straight into 9Router as an OpenAI-compatible provider.

Run it with::

    zt-harvester shim --port 8787

Then register the harvested sessions against ``http://<host>:8787/v1``.

Endpoints
---------
GET  /v1/models
POST /v1/chat/completions   (streaming + non-streaming)
GET  /healthz

The shim reads the ZeroTwo JWT from the request's ``Authorization: Bearer``
header, so a single shim process serves every harvested account. ZeroTwo's edge
also expects the Cloudflare clearance cookie and a CSRF token, so those are
configured once via ``ZT_ZT_COOKIES`` / ``ZT_ZT_CSRF`` (see ``.env.example``).
"""

from __future__ import annotations

import base64
import json
import sys
import time
import uuid
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
    "glm-5-3-flash": "zai-org-glm-5-3-flash",
    "glm-5.3-flash": "zai-org-glm-5-3-flash",
    "zai/glm-5-3-flash": "zai-org-glm-5-3-flash",
    "zai/glm-5.3-flash": "zai-org-glm-5-3-flash",
    "openai/gpt-6-luna": "gpt-6-luna",
    "deepseek/deepseek-v4.1-flash": "deepseek-v4.1-flash",
    "minimax/minimax-m3": "minimax-m3",
    "meta/muse-spark-1.3-contributor": "muse-spark-1.3-contributor",
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
    def __init__(self, *, timeout: float = 300.0, cookies: str = "", csrf: str = "") -> None:
        self.timeout = timeout
        self.cookies = cookies
        self.csrf = csrf
        self._csrf_cache: dict[str, tuple[str, float]] = {}

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
            clean.append({
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "id": m.get("id") or str(uuid.uuid4()),
            })
        last_user = next(
            (m["content"] for m in reversed(clean) if m["role"] == "user"), ""
        )
        effort = req.get("reasoning_effort", "medium")
        return {
            "provider": provider,
            "model": model,
            "messages": clean,
            "tool_choice": "auto",
            "reasoning_effort": effort,
            "attachments": [],
            "contextData": {
                "message": last_user,
                "has_files": False,
                "file_count": 0,
                "toolChoice": "auto",
                "reasoning_effort": effort,
                "is_hybrid_reasoning": True,
                "modelProvider": provider,
                "actualProviderName": provider,
                "mode": {"type": "thread", "retrieval": None},
                "unifiedTurnVersion": 1,
                "research_true": False,
                "browserExecution": "executor",
                "approvalPolicy": "never",
                "sandboxMode": "danger-full-access",
                "permissionMode": "bypassPermissions",
            },
            "stream": True,
        }

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
        """Find the session and proactively refresh its access_token if expired or close to expiry."""
        from pathlib import Path
        p = Path("harvest/sessions.jsonl")
        if not p.exists():
            return None
        sessions = _load_all_sessions()
        sess = _find_session(token_or_id, sessions)
        if not sess:
            return None

        current_token = sess.get("access_token", "")
        claims = _extract_jwt_claims(current_token)
        exp = claims.get("exp")
        now = time.time()
        needs_refresh = False
        if not exp or now >= exp - 120:
            needs_refresh = True

        if needs_refresh and sess.get("refresh_token"):
            new_at, new_rt = await refresh_supabase_token(sess["refresh_token"])
            if new_at:
                sess["access_token"] = new_at
                if new_rt:
                    sess["refresh_token"] = new_rt
                p.write_text("\n".join(json.dumps(x) for x in sessions) + "\n")
                print(f"[shim] Proactively refreshed token for {sess.get('email', 'unknown')}")
            else:
                print(f"[shim] Warning: token refresh failed for {sess.get('email', 'unknown')}", file=sys.stderr)

        return sess

    async def refresh_token_for_session(self, token: str) -> str | None:
        from pathlib import Path
        p = Path("harvest/sessions.jsonl")
        if not p.exists():
            return None
        sessions = _load_all_sessions()
        target_s = _find_session(token, sessions)
        if not target_s or not target_s.get("refresh_token"):
            return None
        new_at, new_rt = await refresh_supabase_token(target_s["refresh_token"])
        if new_at:
            target_s["access_token"] = new_at
            if new_rt:
                target_s["refresh_token"] = new_rt
            p.write_text("\n".join(json.dumps(x) for x in sessions) + "\n")
            print(f"[shim] Token refreshed for {target_s.get('email', 'unknown')}")
            return new_at
        return None

    async def _raw_stream(
        self, req: dict[str, Any], token: str, csrf: str | None = None, cookies: str | None = None, known_models: dict[str, str] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        active_csrf = csrf or await self.get_csrf(token)
        retried_csrf = False
        refreshed_token = False

        while True:
            headers = self._headers(token, csrf=active_csrf, cookies=cookies)
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                async with c.stream(
                    "POST", ZEROTWO_CHAT, headers=headers,
                    json=self._body(req, stream=True, known_models=known_models),
                ) as r:
                    if r.status_code == 401 and not refreshed_token:
                        new_tok = await self.refresh_token_for_session(token)
                        if new_tok:
                            token = new_tok
                            refreshed_token = True
                            active_csrf = await self.get_csrf(token)
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


def build_app(shim: ZeroTwoShim | None = None) -> Any:
    """Return an ASGI app exposing the OpenAI-compatible surface."""
    import os
    from pathlib import Path

    default_cookies = os.getenv("ZT_ZT_COOKIES", "")
    default_csrf = os.getenv("ZT_ZT_CSRF", "")
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

    shim = shim or ZeroTwoShim(
        cookies=default_cookies,
        csrf=default_csrf,
    )

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
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
