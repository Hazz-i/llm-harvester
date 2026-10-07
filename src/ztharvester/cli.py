"""llm-harvester command line interface."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from .config import HarvesterConfig
from .engine import Harvester

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    typer = None
    Console = None
    Table = None


def _console():
    return Console() if Console else None


def _banner() -> None:
    c = _console()
    text = (
        "\n[bold cyan]llm-harvester[/bold cyan] - multi-platform AI / LLM account creator & "
        "token harvester\n" if c else "llm-harvester\n"
    )
    c.print(text) if c else print(text)


def _log(message: str) -> None:
    c = _console()
    if c:
        c.print(f"[dim]{message}[/dim]")
    else:
        print(message)


def _sync_remote(destination: str, output_dir: str, log: Any = print) -> bool:
    import subprocess
    sessions_path = Path(output_dir) / "sessions.jsonl"
    if not sessions_path.exists():
        log(f"[sync] File {sessions_path} does not exist, skipping remote upload.")
        return False
    cmd = ["scp", str(sessions_path), destination]
    log(f"[sync] Uploading {sessions_path} to {destination}...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            log(f"[sync] Successfully uploaded sessions to {destination}")
            return True
        else:
            log(f"[sync] SCP failed ({proc.returncode}): {proc.stderr.strip()}")
            return False
    except Exception as exc:
        log(f"[sync] SCP error: {exc}")
        return False


def _resolve_target(explicit_target: str | None, cfg_target: str = "select") -> str:
    target_candidate = explicit_target or cfg_target or "select"
    target_candidate = target_candidate.lower().strip()

    if target_candidate in ("1", "zerotwo", "zt"):
        return "zerotwo"
    if target_candidate in ("2", "tokenharbor", "th"):
        return "tokenharbor"
    if target_candidate in ("3", "tokenmix", "tm"):
        return "tokenmix"

    c = _console()
    prompt_text = (
        "\n[bold yellow]?[/bold yellow] [bold]Select farming target:[/bold]\n"
        "  [cyan][1][/cyan] ZeroTwo      (app.zerotwo.ai)    -> JWT Session, Cookies, 9Router\n"
        "  [cyan][2][/cyan] Token Harbor (tokenharbor.ai)    -> API Key (thk_live_...), mail.tm\n"
        "  [cyan][3][/cyan] TokenMix     (tokenmix.ai)       -> API Key (sk-tm-...), mail.tm\n"
        "Choice [1-3] (default 1): "
    )
    if c:
        c.print(prompt_text, end="")
    else:
        print(prompt_text, end="")
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "1"

    if ans in ("2", "tokenharbor", "th"):
        return "tokenharbor"
    if ans in ("3", "tokenmix", "tm"):
        return "tokenmix"
    return "zerotwo"


if typer is not None:
    app = typer.Typer(add_completion=False, help="Multi-platform AI / LLM account creator & token harvester")

    @app.command()
    def run(
        count: int = typer.Option(1, "--count", "-n", help="Number of accounts to create"),
        target: str | None = typer.Option(None, "--target", "-t", help="Target platform: zerotwo | tokenharbor | tokenmix | select"),
        config: Path | None = typer.Option(None, "--config", "-c", help="TOML config file"),
        cdp_ws: str | None = typer.Option(None, "--cdp-ws", help="CDP websocket URL of a browser"),
        cdp_url: str | None = typer.Option(None, "--cdp-url", help="CDP HTTP endpoint (cloud browser)"),
        cdp_api_key: str | None = typer.Option(None, "--cdp-api-key", help="API key for the cloud browser"),
        router_url: str | None = typer.Option(None, "--router-url", help="9Router base URL"),
        shim_url: str | None = typer.Option(None, "--shim-base-url", help="OpenAI-compatible shim base URL"),
        no_router: bool = typer.Option(False, "--no-router", help="Skip 9Router registration"),
        proxy: list[str] = typer.Option(None, "--proxy", help="Proxy host:port:user:pass (repeatable)"),
        proxy_file: str | None = typer.Option(None, "--proxy-file", help="File with one proxy per line"),
        concurrency: int | None = typer.Option(None, "--concurrency", help="Parallel sign-ups"),
        output: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
        remote_sync: str | None = typer.Option(None, "--remote-sync", "-s", help="Remote SSH/SCP destination (e.g. user@vps:/opt/llm-harvester/harvest/sessions.jsonl)"),
    ) -> None:
        """Create accounts and register them into 9Router."""
        _banner()
        cfg = (
            HarvesterConfig.from_toml(config)
            if config and config.exists()
            else HarvesterConfig.from_env()
        )
        selected_target = _resolve_target(target, cfg.target)
        cfg.target = selected_target
        _log(f"[target] Active farming target: {selected_target}")
        if proxy:
            cfg.proxy.enabled = True
            cfg.proxy.inline = list(proxy)
        if proxy_file:
            cfg.proxy.enabled = True
            cfg.proxy.file = proxy_file
        if cdp_ws:
            cfg.browser.cdp_ws = cdp_ws
        if cdp_url:
            cfg.browser.cdp_url = cdp_url
        if cdp_api_key:
            cfg.browser.api_key = cdp_api_key
        if router_url:
            cfg.router.base_url = router_url
        if shim_url:
            cfg.router.shim_base_url = shim_url
        if no_router:
            cfg.router.enabled = False
        if concurrency:
            cfg.concurrency = concurrency
        if output:
            cfg.output_dir = output
        if remote_sync:
            cfg.remote_sync = remote_sync

        harvester = Harvester(cfg, log=_log)
        summary = asyncio.run(harvester.run(count))
        c = _console()
        if c and Table:
            table = Table(title="Harvest summary")
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            for k, v in summary.items():
                table.add_row(k, str(v))
            c.print(table)
        else:
            print(json.dumps(summary, indent=2))

        if cfg.remote_sync:
            _sync_remote(cfg.remote_sync, cfg.output_dir, log=_log)

    @app.command()
    def shim(
        host: str = typer.Option("0.0.0.0", "--host"),
        port: int = typer.Option(8787, "--port", "-p"),
    ) -> None:
        """Run the built-in OpenAI-compatible ZeroTwo shim."""
        _banner()
        from .shim import build_app, _load_all_sessions

        sessions = _load_all_sessions()
        _log(f"[shim] Loaded {len(sessions)} harvested session(s) from harvest/sessions.jsonl:")
        for s in sessions:
            _log(f"  • {s.get('email', 'unknown')}")

        try:
            import uvicorn
        except ImportError:
            print("uvicorn is required for the shim: pip install uvicorn", file=sys.stderr)
            raise typer.Exit(1)
        uvicorn.run(build_app(), host=host, port=port)

    @app.command()
    def sync(
        target: str = typer.Option("all", "--target", "-t", help="Target platform: zerotwo | tokenharbor | tokenmix | all"),
        router_url: str | None = typer.Option(None, "--router-url", help="9Router base URL"),
        config: Path | None = typer.Option(None, "--config", "-c", help="TOML config file"),
    ) -> None:
        """Sync harvested sessions or API keys into 9Router (registers nodes, credentials & models)."""
        _banner()
        cfg = (
            HarvesterConfig.from_toml(config)
            if config and config.exists()
            else HarvesterConfig.from_env()
        )
        if router_url:
            cfg.router.base_url = router_url

        from .catalog import get_default_models
        from .router9 import NineRouterClient

        def _read_records(p: Path) -> list[dict[str, Any]]:
            if not p.exists():
                return []
            res = []
            for line in p.read_text().splitlines():
                if line.strip():
                    try:
                        res.append(json.loads(line))
                    except Exception:
                        pass
            return res

        client = NineRouterClient(
            cfg.router.base_url,
            api_key=cfg.router.api_key,
            password=cfg.router.password,
            cookie=cfg.router.cookie,
            log=_log,
        )

        async def _do_sync():
            if cfg.router.password:
                await client.login_with_password()

            targets_to_sync = (
                ["zerotwo", "tokenharbor", "tokenmix"]
                if target.lower() in ("all", "*")
                else [target.lower()]
            )

            total_synced = 0
            for t in targets_to_sync:
                if t in ("zerotwo", "zt"):
                    sessions = _read_records(Path(cfg.output_dir) / "sessions.jsonl")
                    if not sessions:
                        _log(f"[router] No ZeroTwo sessions found in {cfg.output_dir}/sessions.jsonl")
                        continue
                    node_id = await client.ensure_node(
                        name=cfg.router.node_name,
                        base_url=cfg.router.shim_base_url,
                        prefix=cfg.router.node_prefix,
                    )
                    if node_id:
                        await client.sync_custom_models(node_id, get_default_models("zerotwo"))
                    count = await client.sync_connections(
                        sessions,
                        node_id=node_id,
                        node_prefix=cfg.router.node_prefix,
                        extra={
                            "base_url": cfg.router.shim_base_url,
                            "node_name": cfg.router.node_name,
                            "display_name": "ZeroTwo",
                            "account_type": "zerotwo",
                        },
                    )
                    _log(f"[router] ZeroTwo: synced {count} connection(s) (node={node_id})")
                    total_synced += count

                elif t in ("tokenharbor", "th"):
                    keys = _read_records(Path(cfg.output_dir) / "tokenharbor_keys.jsonl")
                    if not keys:
                        _log(f"[router] No Token Harbor keys found in {cfg.output_dir}/tokenharbor_keys.jsonl")
                        continue
                    node_id = await client.ensure_node(
                        name=cfg.tokenharbor.node_name,
                        base_url=cfg.tokenharbor.api_base,
                        prefix=cfg.tokenharbor.node_prefix,
                    )
                    if node_id:
                        await client.sync_custom_models(node_id, get_default_models("tokenharbor"))
                    count = await client.sync_connections(
                        keys,
                        node_id=node_id,
                        node_prefix=cfg.tokenharbor.node_prefix,
                        extra={
                            "base_url": cfg.tokenharbor.api_base,
                            "node_name": cfg.tokenharbor.node_name,
                            "display_name": "Token Harbor",
                            "account_type": "tokenharbor",
                        },
                    )
                    _log(f"[router] Token Harbor: synced {count} key(s) (node={node_id})")
                    total_synced += count

                elif t in ("tokenmix", "tm"):
                    keys = _read_records(Path(cfg.output_dir) / "tokenmix_keys.jsonl")
                    if not keys:
                        _log(f"[router] No TokenMix keys found in {cfg.output_dir}/tokenmix_keys.jsonl")
                        continue
                    node_id = await client.ensure_node(
                        name=cfg.tokenmix.node_name,
                        base_url=cfg.tokenmix.api_base,
                        prefix=cfg.tokenmix.node_prefix,
                    )
                    if node_id:
                        await client.sync_custom_models(node_id, get_default_models("tokenmix"))
                    count = await client.sync_connections(
                        keys,
                        node_id=node_id,
                        node_prefix=cfg.tokenmix.node_prefix,
                        extra={
                            "base_url": cfg.tokenmix.api_base,
                            "node_name": cfg.tokenmix.node_name,
                            "display_name": "TokenMix",
                            "account_type": "tokenmix",
                        },
                    )
                    _log(f"[router] TokenMix: synced {count} key(s) (node={node_id})")
                    total_synced += count

            _log(f"[router] Total synced {total_synced} connection(s) to 9Router at {cfg.router.base_url}")

        asyncio.run(_do_sync())

    @app.command()
    def refresh(
        file: Path = typer.Option(Path("harvest/sessions.jsonl"), "--file", "-f", help="Sessions JSONL file"),
        threshold: float = typer.Option(1200.0, "--threshold", "-t", help="Refresh if expiry within N seconds"),
        all: bool = typer.Option(False, "--all", "-a", help="Force refresh all accounts regardless of expiry"),
    ) -> None:
        """Inspect and refresh Supabase tokens for harvested sessions."""
        _banner()
        from .shim import SessionPool

        pool = SessionPool(file)
        thresh = float("inf") if all else threshold
        stats = asyncio.run(pool.refresh_all(threshold_seconds=thresh))
        c = _console()
        if c and Table:
            table = Table(title=f"Session Token Refresh ({file})")
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            for k, v in stats.items():
                table.add_row(k, str(v))
            c.print(table)
        else:
            print(json.dumps(stats, indent=2))

    @app.command()
    def proxies(
        proxy: list[str] = typer.Option(None, "--proxy", help="Proxy host:port:user:pass (repeatable)"),
        proxy_file: str | None = typer.Option(None, "--proxy-file"),
        check: bool = typer.Option(False, "--check", help="Test each proxy exit IP"),
    ) -> None:
        """List and optionally test the proxy pool."""
        from .proxy import ProxyPool

        pool = ProxyPool.from_env()
        for line in proxy or []:
            pool.add(line)
        if proxy_file:
            from pathlib import Path

            path = Path(proxy_file)
            if path.exists():
                for line in path.read_text().splitlines():
                    pool.add(line)
        c = _console()
        if not pool:
            msg = "no proxies configured (use --proxy or ZT_PROXIES)"
            c.print(f"[yellow]{msg}[/yellow]") if c else print(msg)
            return
        if not check:
            for i, p in enumerate(pool.proxies, 1):
                print(f"{i:>2}  {p.url}")
            return

        import httpx

        async def _test(p) -> tuple[str, bool, str]:
            try:
                async with httpx.AsyncClient(proxy=p.url, timeout=15) as h:
                    r = await h.get("https://api.ipify.org?format=json")
                    return p.url, True, r.json().get("ip", "")
            except Exception as exc:  # noqa: BLE001
                return p.url, False, str(exc)[:60]

        results = asyncio.run(_gather([_test(p) for p in pool.proxies]))

        if c and Table:
            t = Table(title="Proxy pool")
            t.add_column("Proxy")
            t.add_column("OK")
            t.add_column("Exit IP / error")
            for url, ok, info in results:
                t.add_row(url, "yes" if ok else "no", info)
            c.print(t)
        else:
            for url, ok, info in results:
                print(url, ok, info)

    def _gather(coros):
        async def runner():
            import asyncio as _a

            return await _a.gather(*coros)

        return runner()

    @app.command()
    def export(
        output: str = typer.Option("harvest/sessions.jsonl", "--output", "-o"),
        fmt: str = typer.Option("json", "--format", "-f", help="json | csv"),
    ) -> None:
        """Export harvested sessions to a portable file."""
        from .engine import Ledger

        ledger = Ledger(output)
        records = ledger.records
        if fmt == "csv":
            import csv
            import io

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["email", "access_token", "refresh_token", "default_model"])
            for r in records:
                writer.writerow([
                    r.get("email", ""), r.get("access_token", ""),
                    r.get("refresh_token", ""), r.get("default_model", ""),
                ])
            Path(output).with_suffix(".csv").write_text(buf.getvalue())
            print(f"wrote {output.rsplit('.', 1)[0]}.csv")
        else:
            print(json.dumps(records, indent=2))

    def _entry() -> None:
        app()

else:  # pragma: no cover
    def _entry() -> None:
        print("typer is required: pip install typer", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _entry()
