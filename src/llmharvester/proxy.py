"""Proxy pool with round-robin / sticky rotation.

Each account can be bound to a distinct exit IP so per-IP rate limits on the
mail provider and on ZeroTwo are spread across the pool. Proxies are parsed
from the ``host:port:user:pass`` convention used by most rotating-proxy
resellers, and can be supplied inline, via env, or via a file.

Example
-------
>>> pool = ProxyPool.from_env()
>>> proxy = pool.next()
>>> proxy.url
'http://ipqievzh:wd6foi2vce6h@31.59.20.176:6754'
"""

from __future__ import annotations

import itertools
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    username: str = ""
    password: str = ""
    scheme: str = "http"

    @property
    def url(self) -> str:
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password}@" if self.password else f"{self.username}@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def is_socks(self) -> bool:
        return self.scheme.startswith("socks")

    def httpx_mounts(self) -> dict[str, dict[str, str]]:
        return {
            "http://": {"proxy": self.url},
            "https://": {"proxy": self.url},
        }

    @classmethod
    def parse(cls, line: str, scheme: str = "http") -> "Proxy | None":
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        if "://" in line:
            scheme, _, rest = line.partition("://")
        else:
            rest = line
        if "@" in rest:
            user_auth, _, host_port = rest.rpartition("@")
            user, _, pwd = user_auth.partition(":")
            if ":" in host_port:
                host, _, port = host_port.partition(":")
                try:
                    return cls(host=host, port=int(port), username=user, password=pwd, scheme=scheme)
                except ValueError:
                    return None
            return None
        parts = rest.split(":")
        if len(parts) == 2:
            host, port = parts
            try:
                return cls(host=host, port=int(port), scheme=scheme)
            except ValueError:
                return None
        if len(parts) >= 4:
            host, port, user, pwd = parts[0], parts[1], parts[2], ":".join(parts[3:])
            try:
                return cls(host=host, port=int(port), username=user, password=pwd, scheme=scheme)
            except ValueError:
                return None
        return None


class ProxyPool:
    """Holds proxies and hands them out with optional stickiness."""

    def __init__(self, proxies: Iterable[Proxy] = (), *, scheme: str = "http") -> None:
        self.proxies: list[Proxy] = list(proxies)
        self.scheme = scheme
        self._cycle = itertools.cycle(self.proxies) if self.proxies else None
        self._sticky: dict[str, Proxy] = {}

    def __len__(self) -> int:
        return len(self.proxies)

    def __bool__(self) -> bool:
        return bool(self.proxies)

    def add(self, entry: str | Proxy) -> None:
        proxy = entry if isinstance(entry, Proxy) else Proxy.parse(entry, self.scheme)
        if proxy:
            self.proxies.append(proxy)
            self._cycle = itertools.cycle(self.proxies)

    def next(self, key: str | None = None, *, sticky: bool = False) -> Proxy | None:
        """Return the next proxy in round-robin order.

        When ``sticky`` is set and ``key`` is provided, the same proxy is
        returned for the same key (e.g. an email address or index), so an
        account keeps one exit IP across its creation flow.
        """
        if not self.proxies:
            return None
        if sticky and key is not None:
            if key not in self._sticky:
                self._sticky[key] = self.next()
            return self._sticky[key]
        assert self._cycle is not None
        return next(self._cycle)

    def random(self) -> Proxy | None:
        return random.choice(self.proxies) if self.proxies else None

    @classmethod
    def from_lines(cls, lines: Iterable[str], scheme: str = "http") -> "ProxyPool":
        pool = cls(scheme=scheme)
        for line in lines:
            pool.add(line)
        return pool

    @classmethod
    def from_env(cls, var: str = "LLM_PROXIES", file_var: str = "LLM_PROXY_FILE") -> "ProxyPool":
        pool = cls()
        inline = os.getenv(var, "") or (os.getenv("ZT_PROXIES", "") if var == "LLM_PROXIES" else "")
        for line in inline.replace(",", "\n").splitlines():
            pool.add(line)
        path = os.getenv(file_var, "") or (os.getenv("ZT_PROXY_FILE", "") if file_var == "LLM_PROXY_FILE" else "")
        if path and Path(path).exists():
            for line in Path(path).read_text().splitlines():
                pool.add(line)
        scheme = os.getenv("LLM_PROXY_SCHEME") or os.getenv("ZT_PROXY_SCHEME", "http")
        pool.scheme = scheme
        # Auto-discover proxy files when no proxies loaded from env vars
        if not pool.proxies:
            for fallback in [
                "proxies.txt",
                "output/webshare_residential.txt",
                "output/live_elite.txt",
            ]:
                fp = Path(fallback)
                if fp.exists() and fp.stat().st_size > 0:
                    for line in fp.read_text().splitlines():
                        pool.add(line)
                    if pool.proxies:
                        break
        return pool
