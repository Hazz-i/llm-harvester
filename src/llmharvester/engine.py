"""Bulk orchestration engine.

Creates N accounts concurrently, harvests each session, persists every result
to disk in a resumable JSONL ledger, and registers the sessions into 9Router.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .catalog import fetch_provider_models, get_default_models
from .cdp import BridgeCDP, HttpCDP, LocalCDP
from .config import HarvesterConfig
from .elevenlabs import ElevenLabsCreator
from .mail import MailProvider
from .router9 import NineRouterClient
from .tokenharbor import TokenHarborCreator
from .tokenmix import TokenMixCreator
from .zerotwo import HarvestedSession, ZeroTwoCreator


class Ledger:
    """Append-only, crash-safe record of every harvested session."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[dict[str, Any]] = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    try:
                        self._records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    def append(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        with self.path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def summary(self) -> dict[str, Any]:
        total = len(self._records)
        ok = sum(1 for r in self._records if r.get("access_token") or r.get("api_key"))
        routed = sum(1 for r in self._records if r.get("router", {}).get("ok"))
        return {"total": total, "harvested": ok, "routed": routed}


class Harvester:
    def __init__(self, config: HarvesterConfig, log: Any = print) -> None:
        self.config = config
        self.log = log
        self.ledger = self._init_ledger(config.target)

    def _init_ledger(self, target: str) -> Ledger:
        ledger_name = "sessions.jsonl"
        if target == "tokenharbor":
            ledger_name = "tokenharbor_keys.jsonl"
        elif target == "tokenmix":
            ledger_name = "tokenmix_keys.jsonl"
        elif target == "elevenlabs":
            ledger_name = "elevenlabs_keys.jsonl"
        elif target == "zai":
            ledger_name = "zai_keys.jsonl"
        return Ledger(Path(self.config.output_dir) / ledger_name)

    async def _make_cdp(self, proxy: str | None = None) -> Any:
        b = self.config.browser
        if b.mode == "bridge":
            raise RuntimeError("bridge mode is only available inside the browser harness")
        if b.mode == "cloud" and b.cdp_url:
            cdp = HttpCDP(b.cdp_url, b.api_key)
            return await cdp.connect()

        async def _probe_local_ws(target_url: str = "http://127.0.0.1:9222") -> str | None:
            import httpx
            from urllib.parse import urlparse

            try:
                parsed = urlparse(target_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 9222
                if host in ("127.0.0.1", "localhost", "0.0.0.0"):
                    async with httpx.AsyncClient(timeout=2) as client:
                        r = await client.get(f"http://{host}:{port}/json/version")
                        if r.status_code == 200:
                            return r.json().get("webSocketDebuggerUrl")
            except Exception:
                pass
            return None

        from .browser import update_env_cdp_ws, ensure_cdp_browser

        if b.cdp_url:
            cdp = HttpCDP(b.cdp_url, b.api_key)
            return await cdp.connect()

        # If proxy is provided, ensure local browser is routed via proxy bridge
        if proxy or not b.cdp_ws:
            live_ws = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ensure_cdp_browser(port=9222, headless=b.headless, proxy=proxy, log_func=self.log)
            )
            b.cdp_ws = live_ws
            update_env_cdp_ws(live_ws)
            return await LocalCDP(live_ws).connect()

        if b.cdp_ws:
            try:
                return await LocalCDP(b.cdp_ws).connect()
            except Exception:
                fresh_ws = await _probe_local_ws(b.cdp_ws)
                if fresh_ws and fresh_ws != b.cdp_ws:
                    self.log(f"[cdp] Existing cdp_ws expired, auto-recovered fresh endpoint: {fresh_ws}")
                    b.cdp_ws = fresh_ws
                    update_env_cdp_ws(fresh_ws)
                    return await LocalCDP(fresh_ws).connect()
                self.log(f"[cdp] Configured cdp_ws unreachable. Auto-activating CDP browser on port 9222...")
                live_ws = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: ensure_cdp_browser(port=9222, headless=b.headless, proxy=proxy, log_func=self.log)
                )
                b.cdp_ws = live_ws
                update_env_cdp_ws(live_ws)
                return await LocalCDP(live_ws).connect()

    async def create_one(
        self,
        index: int,
        *,
        mail: MailProvider,
        router: NineRouterClient | None,
        node_id: str | None,
        proxy: str | None = None,
    ) -> dict[str, Any]:
        cfg = self.config

        if cfg.target == "tokenharbor":
            cdp = await self._make_cdp(proxy)
            try:
                creator = TokenHarborCreator(cdp, mail, config=cfg.tokenharbor, log=self.log)
                res = await creator.create_account()
                record = res.as_dict()
                record["index"] = index
                record["finished_at"] = time.time()
                if router is not None and res.ok and cfg.router.enabled:
                    models = await fetch_provider_models("tokenharbor", res.api_key, cfg.tokenharbor.api_base)
                    record["models"] = [m["id"] for m in models]
                    if node_id:
                        await router.prune_unwanted_models(node_id, {m["id"] for m in models})
                        await router.sync_custom_models(node_id, models)
                    r_res = await router.connect_session(
                        email=res.email,
                        access_token=res.api_key,
                        node_id=node_id,
                        node_prefix=cfg.tokenharbor.node_prefix,
                        extra={
                            "base_url": cfg.tokenharbor.api_base,
                            "node_name": cfg.tokenharbor.node_name,
                            "display_name": "Token Harbor",
                            "account_type": "tokenharbor",
                            "api_type": "chat",
                        },
                    )
                    record["router"] = asdict(r_res)
                    self.log(f"[{index}] 9router: {'ok' if r_res.ok else r_res.message} ({len(record['models'])} models)")
                self.ledger.append(record)
                return record
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher and hasattr(launcher, "stop"):
                    try:
                        res_stop = launcher.stop()
                        if asyncio.iscoroutine(res_stop):
                            await res_stop
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass

        if cfg.target == "tokenmix":
            cdp = await self._make_cdp(proxy)
            try:
                creator = TokenMixCreator(cdp, mail, config=cfg.tokenmix, log=self.log)
                res = await creator.create_account()
                record = res.as_dict()
                record["index"] = index
                record["finished_at"] = time.time()
                if router is not None and res.ok and cfg.router.enabled:
                    models = await fetch_provider_models("tokenmix", res.api_key, cfg.tokenmix.api_base)
                    record["models"] = [m["id"] for m in models]
                    if node_id:
                        await router.sync_custom_models(node_id, models)
                    r_res = await router.connect_session(
                        email=res.email,
                        access_token=res.api_key,
                        node_id=node_id,
                        node_prefix=cfg.tokenmix.node_prefix,
                        extra={
                            "base_url": cfg.tokenmix.api_base,
                            "node_name": cfg.tokenmix.node_name,
                            "display_name": "TokenMix",
                            "account_type": "tokenmix",
                            "api_type": "chat",
                        },
                    )
                    record["router"] = asdict(r_res)
                    self.log(f"[{index}] 9router: {'ok' if r_res.ok else r_res.message} ({len(record['models'])} models)")
                self.ledger.append(record)
                return record
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher and hasattr(launcher, "stop"):
                    try:
                        res_stop = launcher.stop()
                        if asyncio.iscoroutine(res_stop):
                            await res_stop
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass

        if cfg.target == "elevenlabs":
            cdp = await self._make_cdp(proxy)
            try:
                creator = ElevenLabsCreator(cdp, mail, config=cfg.elevenlabs, log=self.log)
                res = await creator.create_account()
                record = res.as_dict()
                record["index"] = index
                record["finished_at"] = time.time()
                if res.api_key:
                    keys_txt = Path(self.config.output_dir) / "elevenlabs_keys.txt"
                    try:
                        existing_keys = set(keys_txt.read_text().splitlines()) if keys_txt.exists() else set()
                        if res.api_key not in existing_keys:
                            with keys_txt.open("a", encoding="utf-8") as kf:
                                kf.write(res.api_key + "\n")
                    except Exception:
                        pass
                if router is not None and res.ok and cfg.router.enabled:
                    models = await fetch_provider_models("elevenlabs", res.api_key, cfg.elevenlabs.api_base)
                    record["models"] = [m["id"] for m in models]
                    if node_id:
                        await router.sync_custom_models(node_id, models)
                    r_res = await router.connect_session(
                        email=res.email,
                        access_token=res.api_key,
                        node_id=node_id,
                        node_prefix=cfg.elevenlabs.node_prefix,
                        extra={
                            "base_url": cfg.elevenlabs.api_base,
                            "node_name": cfg.elevenlabs.node_name,
                            "display_name": "ElevenLabs",
                            "account_type": "elevenlabs",
                            "api_type": "chat",
                        },
                    )
                    record["router"] = asdict(r_res)
                    self.log(f"[{index}] 9router: {'ok' if r_res.ok else r_res.message} ({len(record['models'])} models)")
                self.ledger.append(record)
                return record
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher and hasattr(launcher, "stop"):
                    try:
                        res_stop = launcher.stop()
                        if asyncio.iscoroutine(res_stop):
                            await res_stop
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass

        if cfg.target == "zai":
            cdp = await self._make_cdp(proxy)
            try:
                from .zai import ZaiHarvester, load_unclaimed

                creator = ZaiHarvester(cdp, mail, config=cfg.zai, log=self.log)
                existing = load_unclaimed(cfg.output_dir)
                if existing is not None:
                    self.log(f"[zai] Akun harvest belum claim -> klaim saja (tanpa daftar): {existing.get('email')}")
                    res = await creator.claim_existing(existing)
                else:
                    res = await creator.harvest()
                record = res.as_dict()
                record["index"] = index
                record["finished_at"] = time.time()
                if router is not None and res.ok and cfg.router.enabled:
                    r_res = await router.register_glm_connection(
                        api_key=res.api_key,
                        email=res.email,
                    )
                    record["router"] = asdict(r_res)
                    self.log(f"[{index}] 9router (glm): {'ok' if r_res.ok else r_res.message}")
                self.ledger.append(record)
                return record
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher and hasattr(launcher, "stop"):
                    try:
                        res_stop = launcher.stop()
                        if asyncio.iscoroutine(res_stop):
                            await res_stop
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass

        account: dict[str, Any] = {"index": index, "started_at": time.time()}
        mailbox = None
        session: HarvestedSession | None = None
        for attempt in range(1, cfg.zerotwo.max_retries + 2):
            mailbox = await mail.create_mailbox(cfg.mail.domain, cfg.mail.prefix)
            self.log(f"[{index}] attempt {attempt}: mailbox {mailbox.address}"
                     + (f" via {proxy}" if proxy else ""))
            cdp = await self._make_cdp(proxy)
            try:
                creator = ZeroTwoCreator(
                    cdp, name=cfg.zerotwo.name, interest=cfg.zerotwo.interest,
                    log=self.log,
                )
                session = await creator.harvest(
                    waittime=cfg.zerotwo.wait_seconds, mail_provider=mail,
                    mailbox=mailbox,
                )
                if session.ok:
                    self.log(f"[{index}] harvested {session.email} "
                             f"({len(session.models)} models)")
                    break
                self.log(f"[{index}] failed: {session.error}")
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher:
                    try:
                        launcher.stop()
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass
        if session is None:
            session = HarvestedSession(
                email=getattr(mailbox, "address", ""),
                password=getattr(mailbox, "password", ""),
                error="no attempt completed",
            )
        record = asdict(session)
        record["index"] = index
        record["mailbox"] = mailbox.as_dict() if mailbox else {}
        record["finished_at"] = time.time()
        record.update(account)
        if router is not None and session.ok and cfg.router.enabled:
            if node_id:
                models = session.models if session.models else get_default_models("zerotwo")
                await router.sync_custom_models(node_id, models)
            result = await router.connect_session(
                email=session.email,
                access_token=session.access_token,
                node_id=node_id,
                node_prefix=cfg.router.node_prefix,
                extra={
                    "base_url": cfg.router.shim_base_url,
                    "node_name": cfg.router.node_name,
                    "display_name": "ZeroTwo",
                    "account_type": "zerotwo",
                    "api_type": "chat",
                },
            )
            record["router"] = asdict(result)
            self.log(f"[{index}] 9router: {'ok' if result.ok else result.message}")
        self.ledger.append(record)
        return record

    async def run(self, count: int, target: str | None = None) -> dict[str, Any]:
        cfg = self.config
        if target and target != "select":
            cfg.target = target
            self.ledger = self._init_ledger(target)

        pool = cfg.build_proxy_pool()
        if pool:
            self.log(f"proxy pool: {len(pool)} exit IPs")

        router: NineRouterClient | None = None
        node_id: str | None = None
        if cfg.router.enabled and cfg.target in ("zerotwo", "tokenharbor", "tokenmix", "elevenlabs", "zai"):
            router = NineRouterClient(
                cfg.router.base_url,
                api_key=cfg.router.api_key,
                password=cfg.router.password,
                cookie=cfg.router.cookie,
                log=self.log,
            )
            if await router.health():
                if cfg.target == "tokenharbor":
                    node_id = await router.ensure_node(
                        name=cfg.tokenharbor.node_name,
                        base_url=cfg.tokenharbor.api_base,
                        prefix=cfg.tokenharbor.node_prefix,
                    )
                    if node_id:
                        th_models = get_default_models("tokenharbor")
                        await router.prune_unwanted_models(node_id, {m["id"] for m in th_models})
                        await router.sync_custom_models(node_id, th_models)
                elif cfg.target == "tokenmix":
                    node_id = await router.ensure_node(
                        name=cfg.tokenmix.node_name,
                        base_url=cfg.tokenmix.api_base,
                        prefix=cfg.tokenmix.node_prefix,
                    )
                    if node_id:
                        await router.sync_custom_models(node_id, get_default_models("tokenmix"))
                elif cfg.target == "elevenlabs":
                    node_id = await router.ensure_node(
                        name=cfg.elevenlabs.node_name,
                        base_url=cfg.elevenlabs.api_base,
                        prefix=cfg.elevenlabs.node_prefix,
                        api_type="chat",
                    )
                    if node_id:
                        await router.sync_custom_models(node_id, get_default_models("elevenlabs"))
                else:
                    node_id = await router.ensure_node(
                        name=cfg.router.node_name,
                        base_url=cfg.router.shim_base_url,
                        prefix=cfg.router.node_prefix,
                    )
                    if node_id:
                        await router.sync_custom_models(node_id, get_default_models("zerotwo"))
                self.log(f"9router online, target={cfg.target}, node={node_id}")
            else:
                self.log("9router unreachable - sessions will be saved but not routed "
                         f"({cfg.router.base_url})")
                router = None

        sem = asyncio.Semaphore(max(1, cfg.concurrency))

        async def worker(i: int) -> dict[str, Any]:
            async with sem:
                proxy = pool.next(key=str(i), sticky=cfg.proxy.sticky) if pool else None
                proxy_url = proxy.url if proxy else None
                mail = MailProvider(cfg.mail.base_url, proxy=proxy_url)
                async with mail:
                    return await self.create_one(
                        i, mail=mail, router=router, node_id=node_id,
                        proxy=proxy_url,
                    )

        results = await asyncio.gather(*(worker(i) for i in range(1, count + 1)))
        summary = self.ledger.summary()
        summary["proxies"] = len(pool)
        self.log(f"done: {summary}")
        return summary
