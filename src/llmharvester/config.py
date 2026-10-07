"""Configuration models for llm-harvester."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MailConfig:
    base_url: str = "https://api.mail.tm"
    domain: str | None = None
    prefix: str = "zt"


@dataclass
class ZeroTwoConfig:
    name: str = "Burz"
    interest: str = "Just exploring"
    wait_seconds: float = 240.0
    max_retries: int = 2


@dataclass
class TokenHarborConfig:
    key_name_prefix: str = "prod-th"
    wait_seconds: float = 120.0
    max_retries: int = 2
    api_base: str = "https://tokenharbor.ai/v1"
    node_name: str = "Token Harbor"
    node_prefix: str = "tokenharbor"


@dataclass
class TokenMixConfig:
    key_name_prefix: str = "prod-tm"
    referral_code: str | None = None
    wait_seconds: float = 120.0
    max_retries: int = 2
    api_base: str = "https://api.tokenmix.ai/v1"
    node_name: str = "TokenMix"
    node_prefix: str = "tokenmix"



@dataclass
class RouterConfig:
    base_url: str = "http://localhost:20128"
    api_key: str = "sk_9router"
    password: str | None = None
    cookie: str | None = None
    shim_base_url: str = "http://localhost:8787/v1"
    node_name: str = "ZeroTwo (shim)"
    node_prefix: str = "zerotwo"
    enabled: bool = True


@dataclass
class BrowserConfig:
    """How to reach the Chromium instance used for sign-ups."""

    mode: str = "cdp"  # cdp | bridge | cloud
    cdp_ws: str | None = None
    cdp_url: str | None = None
    api_key: str | None = None
    headless: bool = False
    launch_path: str | None = None
    # When true, the browser's own traffic exits through a pool proxy. Local
    # Chromium cannot change proxy per tab, so this applies to cloud browsers
    # that accept a proxy configuration at creation time.
    route_through_pool: bool = False


@dataclass
class ProxyConfig:
    """Exit-IP pool used to spread per-IP rate limits."""

    enabled: bool = False
    scheme: str = "http"
    inline: list[str] = field(default_factory=list)
    file: str | None = None
    sticky: bool = True



@dataclass
class HarvesterConfig:
    target: str = "select"  # select | zerotwo | tokenharbor | tokenmix
    mail: MailConfig = field(default_factory=MailConfig)
    zerotwo: ZeroTwoConfig = field(default_factory=ZeroTwoConfig)
    tokenharbor: TokenHarborConfig = field(default_factory=TokenHarborConfig)
    tokenmix: TokenMixConfig = field(default_factory=TokenMixConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    concurrency: int = 1
    output_dir: str = "harvest"
    remote_sync: str | None = None

    @classmethod
    def from_env(cls, **overrides: Any) -> "HarvesterConfig":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        cfg = cls()

        def _get(key: str, default: Any = None) -> Any:
            val = os.getenv(f"LLM_{key}")
            if val is not None and val != "":
                return val
            zt_val = os.getenv(f"ZT_{key}")
            if zt_val is not None and zt_val != "":
                return zt_val
            return default

        cfg.target = _get("TARGET", cfg.target)
        cfg.mail.base_url = _get("MAIL_BASE_URL", cfg.mail.base_url)
        cfg.mail.domain = _get("MAIL_DOMAIN") or None
        cfg.zerotwo.name = _get("NAME", cfg.zerotwo.name)
        cfg.zerotwo.interest = _get("INTEREST", cfg.zerotwo.interest)
        cfg.tokenharbor.key_name_prefix = os.getenv("TH_KEY_PREFIX", cfg.tokenharbor.key_name_prefix)
        cfg.tokenharbor.api_base = os.getenv("TH_API_BASE", cfg.tokenharbor.api_base)
        cfg.tokenharbor.node_name = os.getenv("TH_NODE_NAME", cfg.tokenharbor.node_name)
        cfg.tokenharbor.node_prefix = os.getenv("TH_NODE_PREFIX", cfg.tokenharbor.node_prefix)
        cfg.tokenmix.key_name_prefix = os.getenv("TM_KEY_PREFIX", cfg.tokenmix.key_name_prefix)
        cfg.tokenmix.api_base = os.getenv("TM_API_BASE", cfg.tokenmix.api_base)
        cfg.tokenmix.node_name = os.getenv("TM_NODE_NAME", cfg.tokenmix.node_name)
        cfg.tokenmix.node_prefix = os.getenv("TM_NODE_PREFIX", cfg.tokenmix.node_prefix)
        cfg.tokenmix.referral_code = os.getenv("TM_REFERRAL") or cfg.tokenmix.referral_code
        cfg.router.base_url = os.getenv("NINEROUTER_URL", cfg.router.base_url)
        cfg.router.api_key = os.getenv("NINEROUTER_API_KEY", cfg.router.api_key)
        cfg.router.password = os.getenv("NINEROUTER_PASSWORD") or None
        cfg.router.cookie = os.getenv("NINEROUTER_COOKIE") or None
        cfg.router.shim_base_url = _get("SHIM_BASE_URL", cfg.router.shim_base_url)
        cfg.browser.cdp_ws = _get("CDP_WS") or None
        cfg.browser.cdp_url = _get("CDP_URL") or None
        cfg.browser.api_key = os.getenv("BROWSER_USE_API_KEY") or None
        cfg.browser.mode = _get("BROWSER_MODE", cfg.browser.mode)
        cfg.browser.headless = _get("HEADLESS", "0").lower() in ("1", "true", "yes")
        cfg.concurrency = int(_get("CONCURRENCY", str(cfg.concurrency)))
        cfg.remote_sync = _get("REMOTE_SYNC") or None
        proxies = _get("PROXIES", "")
        if proxies.strip():
            cfg.proxy.enabled = True
            cfg.proxy.inline = [
                p for p in proxies.replace(",", "\n").splitlines() if p.strip()
            ]
        proxy_file = _get("PROXY_FILE")
        if proxy_file:
            cfg.proxy.file = proxy_file
            cfg.proxy.enabled = True
        cfg.proxy.scheme = _get("PROXY_SCHEME", cfg.proxy.scheme)
        cfg.proxy.sticky = _get("PROXY_STICKY", "1") not in ("0", "false", "False")
        for key, value in overrides.items():
            if isinstance(value, dict) and hasattr(cfg, key):
                section = getattr(cfg, key)
                for k, v in value.items():
                    setattr(section, k, v)
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    @classmethod
    def from_toml(cls, path: str | Path) -> "HarvesterConfig":
        import tomllib

        data = tomllib.loads(Path(path).read_text())
        return cls(
            target=data.get("target", "select"),
            mail=MailConfig(**data.get("mail", {})),
            zerotwo=ZeroTwoConfig(**data.get("zerotwo", {})),
            tokenharbor=TokenHarborConfig(**data.get("tokenharbor", {})),
            tokenmix=TokenMixConfig(**data.get("tokenmix", {})),
            router=RouterConfig(**data.get("router", {})),
            browser=BrowserConfig(**data.get("browser", {})),
            proxy=ProxyConfig(**data.get("proxy", {})),
            concurrency=data.get("concurrency", 1),
            output_dir=data.get("output_dir", "harvest"),
        )

    def build_proxy_pool(self) -> "ProxyPool":
        from .proxy import ProxyPool

        if not self.proxy.enabled:
            return ProxyPool()
        pool = ProxyPool(scheme=self.proxy.scheme)
        for line in self.proxy.inline:
            pool.add(line)
        if self.proxy.file:
            from pathlib import Path

            path = Path(self.proxy.file)
            if path.exists():
                for line in path.read_text().splitlines():
                    pool.add(line)
        return pool
