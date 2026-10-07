"""Webshare API integration for fetching and syncing proxies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import httpx

from .proxy import Proxy


class WebshareClient:
    """Client for Webshare.io v2 API."""

    BASE_URL = "https://proxy.webshare.io/api/v2"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("WEBSHARE_API_KEY", "").strip()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.api_key}",
            "Accept": "application/json",
        }

    async def fetch_proxies(self, mode: str = "direct", page_size: int = 100) -> list[Proxy]:
        """Fetch list of proxies from Webshare API."""
        if not self.api_key:
            raise ValueError("Webshare API key is required. Set WEBSHARE_API_KEY or provide explicitly.")

        proxies: list[Proxy] = []
        page = 1
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                url = f"{self.BASE_URL}/proxy/list/?mode={mode}&page={page}&page_size={page_size}"
                r = await client.get(url, headers=self.headers)
                if r.status_code == 401:
                    raise PermissionError("Invalid Webshare API key")
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                for item in results:
                    host = item.get("proxy_address")
                    port = item.get("port")
                    user = item.get("username", "")
                    pwd = item.get("password", "")
                    if host and port:
                        proxies.append(
                            Proxy(
                                host=host,
                                port=int(port),
                                username=user,
                                password=pwd,
                                scheme="http",
                            )
                        )
                if not data.get("next") or not results:
                    break
                page += 1

        return proxies

    def sync_to_file(self, proxies: list[Proxy], filepath: str | Path = "proxies.txt", append: bool = True) -> int:
        """Save or append Webshare proxies to proxies.txt."""
        path = Path(filepath)
        existing_lines = set()
        if path.exists() and append:
            for line in path.read_text().splitlines():
                if line.strip() and not line.startswith("#"):
                    existing_lines.add(line.strip())

        new_count = 0
        lines_to_write = []
        for p in proxies:
            entry = f"{p.host}:{p.port}:{p.username}:{p.password}" if p.username else f"{p.host}:{p.port}"
            if entry not in existing_lines:
                lines_to_write.append(entry)
                existing_lines.add(entry)
                new_count += 1

        if lines_to_write:
            write_header = not path.exists() or path.stat().st_size == 0
            with path.open("a" if append and path.exists() else "w") as fh:
                if write_header:
                    fh.write("# One proxy per line, host:port:user:pass or http://user:pass@host:port\n")
                for line in lines_to_write:
                    fh.write(line + "\n")

        return new_count
