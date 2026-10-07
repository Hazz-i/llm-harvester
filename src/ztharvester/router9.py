"""9Router connector.

Registers harvested ZeroTwo sessions into a running 9Router instance
(https://9router.com) so they appear as OpenAI-compatible provider
connections and are available through the single 9Router endpoint.

9Router exposes a local REST API (default ``http://localhost:20128``):

* ``POST /api/provider-nodes``          create a custom OpenAI-compatible node
* ``POST /api/providers``               create a provider connection
* ``GET  /api/providers``               list connections
* ``GET  /v1/models``                   OpenAI-compatible model list

ZeroTwo does not speak the OpenAI protocol itself, so the connector ships with
an optional built-in shim (:mod:`ztharvester.shim`) and registers ZeroTwo via
that shim by default. If you already run an external ZeroTwo->OpenAI proxy,
point ``--shim-base-url`` at it instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_ROUTER_URL = "http://localhost:20128"
SHIM_PREFIX = "zerotwo"


@dataclass
class RouterResult:
    ok: bool
    node_id: str | None = None
    connection_id: str | None = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class NineRouterClient:
    """Small client for the 9Router provider-management API."""

    def __init__(
        self,
        base_url: str = DEFAULT_ROUTER_URL,
        *,
        api_key: str = "sk_9router",
        password: str | None = None,
        cookie: str | None = None,
        timeout: float = 30.0,
        log: Any = print,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.password = password
        self.cookie = cookie
        self.timeout = timeout
        self.log = log

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    async def login_with_password(self) -> bool:
        if not self.password:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/api/auth/login",
                    json={"password": self.password},
                )
                if r.status_code == 200:
                    cookie_header = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
                    if cookie_header:
                        self.cookie = (self.cookie + "; " + cookie_header) if self.cookie else cookie_header
                    self.log("[router] logged in with password successfully")
                    return True
                self.log(f"[router] password login failed: {r.status_code} {r.text[:120]}")
                return False
        except httpx.HTTPError as exc:
            self.log(f"[router] login request failed: {exc}")
            return False

    async def health(self) -> bool:
        if self.password and not self.cookie:
            await self.login_with_password()
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{self.base_url}/api/settings", headers=self._headers)
                if r.status_code in (401, 403) and self.password:
                    if await self.login_with_password():
                        r = await c.get(f"{self.base_url}/api/settings", headers=self._headers)
                if r.status_code in (401, 403):
                    self.log(f"[router] unauthorized ({r.status_code}): please check NINEROUTER_PASSWORD or NINEROUTER_COOKIE")
                    return False
                return r.status_code < 400
        except httpx.HTTPError:
            return False

    async def list_providers(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.base_url}/api/providers", headers=self._headers)
            if r.status_code >= 400:
                return []
            data = r.json()
        if isinstance(data, dict):
            return data.get("connections") or data.get("providers") or data.get("data") or []
        return data or []

    async def ensure_node(
        self,
        *,
        name: str = "ZeroTwo (shim)",
        base_url: str,
        prefix: str = SHIM_PREFIX,
        api_type: str = "chat",
    ) -> str | None:
        """Create (or find) an OpenAI-compatible provider node for ZeroTwo."""
        existing = await self._find_node(prefix)
        if existing:
            return existing
        payload = {
            "type": "openai-compatible",
            "name": name,
            "baseUrl": base_url,
            "prefix": prefix,
            "apiType": api_type,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/provider-nodes",
                headers=self._headers,
                json=payload,
            )
        if r.status_code >= 400:
            self.log(f"[router] node create failed: {r.status_code} {r.text[:180]}")
            return None
        body = r.json()
        return (body.get("node") or {}).get("id") or body.get("id") or body.get("nodeId")

    async def _find_node(self, prefix: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/api/provider-nodes", headers=self._headers)
            if r.status_code >= 400:
                return None
            data = r.json()
            nodes = data.get("nodes", data) if isinstance(data, dict) else data
            for n in nodes or []:
                if n.get("prefix") == prefix:
                    return n.get("id")
        except httpx.HTTPError:
            return None
        return None

    async def add_connection(
        self,
        *,
        provider: str,
        api_key: str,
        name: str,
        provider_specific: dict[str, Any] | None = None,
    ) -> RouterResult:
        payload: dict[str, Any] = {
            "provider": provider,
            "apiKey": api_key,
            "name": name,
        }
        if provider_specific:
            payload["providerSpecificData"] = provider_specific
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.post(
                    f"{self.base_url}/api/providers", headers=self._headers, json=payload
                )
            if r.status_code >= 400:
                return RouterResult(ok=False, message=f"{r.status_code}: {r.text[:200]}")
            body = r.json()
            conn = body.get("connection") or body.get("provider") or body.get("data") or body
            return RouterResult(
                ok=True,
                connection_id=conn.get("id") if isinstance(conn, dict) else None,
                message="connected",
                raw=body,
            )
        except httpx.HTTPError as exc:
            return RouterResult(ok=False, message=str(exc))

    async def connect_session(
        self,
        *,
        email: str,
        access_token: str,
        node_id: str | None,
        node_prefix: str = SHIM_PREFIX,
        extra: dict[str, Any] | None = None,
    ) -> RouterResult:
        """Register one harvested account credential as a 9Router connection."""
        if not access_token:
            return RouterResult(ok=False, message="missing access token or api key")
        provider = node_id or f"openai-compatible-{node_prefix}"
        extra = extra or {}
        display_name = extra.get("display_name")
        if not display_name:
            if node_prefix == "tokenharbor":
                display_name = "Token Harbor"
            elif node_prefix == "tokenmix":
                display_name = "TokenMix"
            else:
                display_name = "ZeroTwo"
        psd: dict[str, Any] = {
            "prefix": node_prefix,
            "apiType": extra.get("api_type", "chat"),
            "baseUrl": extra.get("base_url", ""),
            "nodeName": extra.get("node_name", f"{display_name} (node)"),
            "connectionProxyEnabled": False,
            "connectionProxyUrl": "",
            "connectionNoProxy": "",
            "email": email,
            "accountType": extra.get("account_type", node_prefix),
        }
        return await self.add_connection(
            provider=provider,
            api_key=access_token,
            name=f"{display_name} · {email}",
            provider_specific=psd,
        )

    async def update_connection(
        self,
        connection_id: str,
        *,
        provider: str,
        api_key: str,
        name: str,
        is_active: bool = True,
        provider_specific: dict[str, Any] | None = None,
    ) -> RouterResult:
        """Update an existing 9Router connection's API key or settings."""
        payload: dict[str, Any] = {
            "provider": provider,
            "apiKey": api_key,
            "name": name,
            "isActive": is_active,
        }
        if provider_specific:
            payload["providerSpecificData"] = provider_specific
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.put(
                    f"{self.base_url}/api/providers/{connection_id}", headers=self._headers, json=payload
                )
            if r.status_code >= 400:
                return RouterResult(ok=False, message=f"{r.status_code}: {r.text[:200]}")
            body = r.json()
            return RouterResult(
                ok=True,
                connection_id=connection_id,
                message="updated",
                raw=body,
            )
        except httpx.HTTPError as exc:
            return RouterResult(ok=False, message=str(exc))

    async def sync_connections(
        self,
        sessions: list[dict[str, Any]],
        *,
        node_id: str | None = None,
        node_prefix: str = SHIM_PREFIX,
        extra: dict[str, Any] | None = None,
    ) -> int:
        """Sync harvested sessions or API keys with 9Router connections (create or update)."""
        providers = await self.list_providers()
        existing_by_email: dict[str, dict[str, Any]] = {}
        for p in providers:
            name = p.get("name", "")
            if " · " in name:
                em = name.split(" · ", 1)[1].strip()
                existing_by_email[em] = p
            elif (p.get("providerSpecificData") or {}).get("email"):
                existing_by_email[p["providerSpecificData"]["email"]] = p

        synced = 0
        target_provider = node_id or f"openai-compatible-{node_prefix}"
        extra = extra or {}
        display_name = extra.get("display_name") or (
            "Token Harbor" if node_prefix == "tokenharbor" else
            "TokenMix" if node_prefix == "tokenmix" else
            "ZeroTwo"
        )
        for s in sessions:
            email = s.get("email")
            token = s.get("access_token") or s.get("api_key")
            if not email or not token:
                continue
            if email in existing_by_email:
                conn = existing_by_email[email]
                cid = conn.get("id")
                psd = conn.get("providerSpecificData") or {
                    "prefix": node_prefix,
                    "apiType": extra.get("api_type", "chat"),
                    "baseUrl": extra.get("base_url", ""),
                    "nodeName": extra.get("node_name", f"{display_name} (node)"),
                    "connectionProxyEnabled": False,
                    "connectionProxyUrl": "",
                    "connectionNoProxy": "",
                    "email": email,
                    "accountType": extra.get("account_type", node_prefix),
                }
                res = await self.update_connection(
                    cid,
                    provider=conn.get("provider") or target_provider,
                    api_key=token,
                    name=conn.get("name") or f"{display_name} · {email}",
                    is_active=True,
                    provider_specific=psd,
                )
                if res.ok:
                    synced += 1
            else:
                res = await self.connect_session(
                    email=email,
                    access_token=token,
                    node_id=node_id,
                    node_prefix=node_prefix,
                    extra=extra,
                )
                if res.ok:
                    synced += 1
        return synced

    async def sync_custom_models(
        self, node_id: str, models: list[dict[str, Any]]
    ) -> int:
        """Register custom models under the given node in 9Router."""
        if not node_id or not models:
            return 0
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/api/models/custom", headers=self._headers)
                existing = set()
                if r.status_code == 200:
                    existing = {
                        m.get("id")
                        for m in r.json().get("models", [])
                        if m.get("providerAlias") == node_id
                    }
                added = 0
                for m in models:
                    mid = m.get("id")
                    if not mid or mid in existing:
                        continue
                    payload = {
                        "providerAlias": node_id,
                        "id": mid,
                        "type": "llm",
                        "name": m.get("name") or mid,
                    }
                    res = await c.post(
                        f"{self.base_url}/api/models/custom",
                        headers=self._headers,
                        json=payload,
                    )
                    if res.status_code == 200:
                        added += 1
                        existing.add(mid)
                if added > 0:
                    self.log(f"[router] registered {added} new custom model(s)")
                return added
        except Exception as exc:  # noqa: BLE001
            self.log(f"[router] sync_custom_models error: {exc}")
            return 0
