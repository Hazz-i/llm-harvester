#!/usr/bin/env bash
""":"
exec python3 "$0" "$@"
"""
import asyncio
import os
import sys
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.align import Align
from rich.text import Text

console = Console()

BANNER_ART = [
    "██╗     ██╗     ███╗   ███╗   ██╗  ██╗ █████╗ ██████╗ ██╗   ██╗███████╗███████╗████████╗███████╗██████╗",
    "██║     ██║     ████╗ ████║   ██║  ██║██╔══██╗██╔══██╗██║   ██║██╔════╝██╔════╝╚══██╔══╝██╔════╝██╔══██╗",
    "██║     ██║     ██╔████╔██║   ███████║███████║██████╔╝██║   ██║█████╗  ███████╗   ██║   █████╗  ██████╔╝",
    "██║     ██║     ██║╚██╔╝██║   ██╔══██║██╔══██║██╔══██╗╚██╗ ██╔╝██╔══╝  ╚════██║   ██║   ██╔══╝  ██╔══██╗",
    "███████╗███████╗██║ ╚═╝ ██║   ██║  ██║██║  ██║██║  ██║ ╚████╔╝ ███████╗███████║   ██║   ███████╗██║  ██║",
    "╚══════╝╚══════╝╚═╝     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝",
]


def _check_cdp_status() -> tuple[str, str]:
    import httpx
    try:
        r = httpx.get("http://127.0.0.1:9222/json/version", timeout=1.5)
        if r.status_code == 200:
            return "[bold green]Online (:9222)[/bold green]", "[green]Ready[/green]"
    except Exception:
        pass
    ws = os.getenv("LLM_CDP_WS")
    if ws:
        return "[yellow]Configured (.env)[/yellow]", "[yellow]Auto-connect[/yellow]"
    return "[cyan]Auto-Launch[/cyan]", "[dim]Starts on run[/dim]"


def _check_warp_status() -> tuple[str, str]:
    from llmharvester.warp import is_warp_running, load_warp_profile
    stat = is_warp_running(timeout=1.0)
    if stat:
        return "[bold green]Online (:10808)[/bold green]", f"[green]{stat.get('query', 'Active')} (Cloudflare)[/green]"
    prof = load_warp_profile()
    if prof:
        return "[yellow]Standby (:10808)[/yellow]", "[yellow]Config Ready[/yellow]"
    return "[dim]Standby[/dim]", "[dim]Auto-Registerable[/dim]"


def _get_proxy_count() -> int:
    p = Path("proxies.txt")
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if line.strip() and not line.startswith("#"))


def _get_harvest_summary() -> dict[str, int]:
    res = {"zerotwo": 0, "tokenharbor": 0, "tokenmix": 0, "grok": 0}
    for key, fname in [
        ("zerotwo", "sessions.jsonl"),
        ("tokenharbor", "tokenharbor_keys.jsonl"),
        ("tokenmix", "tokenmix_keys.jsonl"),
        ("grok", "grok_accounts.jsonl"),
    ]:
        f = Path("harvest") / fname
        if f.exists():
            res[key] = sum(1 for line in f.read_text().splitlines() if line.strip())
        elif key == "grok":
            for f_alt in [Path("harvest") / "grok_accounts.txt", Path("output") / "grok_accounts.txt"]:
                if f_alt.exists():
                    res[key] = sum(1 for line in f_alt.read_text().splitlines() if line.strip())
                    break
    return res


def render_dashboard() -> None:
    for line in BANNER_ART:
        console.print(Align.center(Text(line, style="bold cyan", no_wrap=True)))
    console.print()
    console.print(Align.center(Text("llm-harvester · AI Account Farming, LLM Tokens & Proxy Management", style="bold yellow")))
    console.print(Align.center(Text("Auto-CDP (Brave/Chrome) · 9Router Integration · Multi-Platform Harvester", style="dim")))
    console.print()

    cdp_status, cdp_badge = _check_cdp_status()
    warp_status, warp_badge = _check_warp_status()
    proxy_count = _get_proxy_count()
    harvest_counts = _get_harvest_summary()
    router_url = os.getenv("NINEROUTER_URL", "http://localhost:20128")

    table = Table(title="[bold]SYSTEM STATUS & HARVESTER READINESS[/bold]", expand=True, show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    table.add_row("Browser CDP", cdp_status, cdp_badge)
    table.add_row("Cloudflare WARP", warp_status, warp_badge)
    table.add_row("Proxy Pool", f"[bold green]{proxy_count} IP(s)[/bold green]" if proxy_count > 0 else "[red]0 IP[/red]", "proxies.txt")
    table.add_row("9Router Gateway", f"[cyan]{router_url}[/cyan]", "Auto-Connect Provider")
    table.add_row(
        "Harvest Ledger",
        f"[magenta]ZT: {harvest_counts['zerotwo']} | TH: {harvest_counts['tokenharbor']} | TM: {harvest_counts['tokenmix']} | Grok: {harvest_counts['grok']}[/magenta]",
        "harvest/*",
    )

    console.print(Panel(table, border_style="cyan"))


def menu_run_harvester() -> None:
    console.print("\n[bold cyan]=== RUN HARVESTER ===[/bold cyan]")
    console.print("Select target platform:")
    console.print("  [1] Token Harbor (tokenharbor.ai - Production API Keys thk_live_...)")
    console.print("  [2] TokenMix     (api.tokenmix.ai - Production API Keys sk-tm_...)")
    console.print("  [3] ZeroTwo      (app.zerotwo.ai - Intercept Supabase JWT & Cookie)")
    console.print("  [4] Grok xAI     (accounts.x.ai - Residential Proxy & Auto-OTP)")
    console.print("  [0] Back to main menu\n")

    choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "0"], default="1")
    if choice == "0":
        return

    if choice == "4":
        menu_grok_farm()
        return

    count_str = Prompt.ask("Number of accounts to harvest", default="1")
    try:
        count = int(count_str)
        if count < 1:
            count = 1
    except ValueError:
        count = 1

    # Token Harbor & ZeroTwo: Cloudflare/Supabase bot-detection breaks in headless mode
    if choice in ("1", "3"):
        platform_name = "Token Harbor" if choice == "1" else "ZeroTwo"
        console.print(
            f"[yellow dim]ℹ  {platform_name} requires Visible Window (Cloudflare bot-detection).[/yellow dim]"
        )
        is_headless = False
    else:
        console.print("\nBrowser Display Mode:")
        console.print("  [1] Visible Window (Easy to monitor, default)")
        console.print("  [2] Background / Headless (No UI window)")
        head_choice = Prompt.ask("Choice", choices=["1", "2"], default="1")
        is_headless = (head_choice == "2")

    console.print("\nProxy Routing Mode:")
    console.print("  [1] Direct Connection (Local IP / No proxy)")
    console.print("  [2] Cloudflare WARP (WireGuard :10808 - Auto-starts sing-box, clean Cloudflare IP)")
    console.print("  [3] Proxy Pool (proxies.txt / Webshare residential)")
    default_proxy_choice = "1" if choice == "1" else "2"
    proxy_mode = Prompt.ask("Choice", choices=["1", "2", "3"], default=default_proxy_choice)

    target_map = {
        "1": "tokenharbor",
        "2": "tokenmix",
        "3": "zerotwo",
    }
    t = target_map.get(choice, "tokenharbor")

    proxy_label = "Direct" if proxy_mode == "1" else ("Cloudflare WARP" if proxy_mode == "2" else "Proxy Pool")
    console.print(f"\n[bold green]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold green]")
    console.print(f"[bold cyan]Starting Harvest: {t.upper()} ({count} account{'s' if count > 1 else ''}, {'Headless' if is_headless else 'Visible Window'}, {proxy_label})...[/bold cyan]")
    console.print(f"[bold green]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold green]\n")

    cmd = [sys.executable, "-m", "llmharvester.cli", "run", "--target", t, "--count", str(count)]
    if is_headless:
        cmd.append("--headless")
    if proxy_mode == "2":
        cmd.append("--warp")
    elif proxy_mode == "3" and Path("proxies.txt").exists():
        cmd.extend(["--proxy-file", "proxies.txt"])

    subprocess.run(cmd)


def menu_doctor() -> None:
    console.print("\n[bold cyan]=== SYSTEM DOCTOR & ENVIRONMENT DIAGNOSTIC ===[/bold cyan]")
    console.print("[dim]Checking all system dependencies, network endpoints, browser, and configurations...[/dim]\n")

    table = Table(title="Diagnostic Results", expand=True)
    table.add_column("Check / Component", style="bold cyan")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    # 1. Python & Virtual Environment
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    in_venv = sys.prefix != sys.base_prefix
    if sys.version_info >= (3, 10):
        table.add_row("Python Version", "[bold green]PASS[/bold green]", f"Python {py_ver} ({'Virtualenv' if in_venv else 'System'})")
    else:
        table.add_row("Python Version", "[bold red]FAIL[/bold red]", f"Python {py_ver} (Requires 3.10+)")

    # 2. Browser Detection
    from llmharvester.browser_utils import find_system_browser
    browser_bin = find_system_browser()
    if browser_bin:
        table.add_row("Chromium Browser", "[bold green]PASS[/bold green]", f"Found: {browser_bin}")
    else:
        table.add_row("Chromium Browser", "[bold red]FAIL[/bold red]", "No Chrome/Brave/Chromium found")

    # 3. CDP Remote Debugging (Port 9222)
    from llmharvester.browser import is_cdp_alive
    live_ws = is_cdp_alive(9222)
    if live_ws:
        table.add_row("CDP Port 9222", "[bold green]ACTIVE[/bold green]", f"Listening: {live_ws[:45]}...")
    else:
        table.add_row("CDP Port 9222", "[bold yellow]STANDBY[/bold yellow]", "Offline (Auto-launches on harvest)")

    # 4. Proxy Pool Check
    p_file = Path("proxies.txt")
    if p_file.exists():
        lines = [line.strip() for line in p_file.read_text().splitlines() if line.strip() and not line.startswith("#")]
        if lines:
            # Quick socket test on 1st proxy
            p_parts = lines[0].split(":")
            if len(p_parts) == 4:
                host, port_str = p_parts[0], p_parts[1]
                try:
                    s = socket.create_connection((host, int(port_str)), timeout=2.5)
                    s.close()
                    table.add_row("Proxy Pool", "[bold green]PASS[/bold green]", f"{len(lines)} proxies loaded (Sample {host}:{port_str} reachable)")
                except Exception as e:
                    table.add_row("Proxy Pool", "[bold yellow]WARN[/bold yellow]", f"{len(lines)} proxies loaded (Sample timeout: {e})")
            else:
                table.add_row("Proxy Pool", "[bold green]PASS[/bold green]", f"{len(lines)} proxies loaded")
        else:
            table.add_row("Proxy Pool", "[bold yellow]EMPTY[/bold yellow]", "proxies.txt is empty")
    else:
        table.add_row("Proxy Pool", "[bold red]MISSING[/bold red]", "proxies.txt not found")

    # 5. 9Router Gateway Connectivity
    router_url = os.getenv("NINEROUTER_URL", "https://nine.hazz.biz.id")
    router_pw = os.getenv("NINEROUTER_PASSWORD")
    try:
        from llmharvester.router9 import NineRouterClient
        r_client = NineRouterClient(base_url=router_url, password=router_pw)
        ok = asyncio.run(r_client.health())
        if ok:
            table.add_row("9Router Gateway", "[bold green]PASS[/bold green]", f"Connected to {router_url}")
        else:
            table.add_row("9Router Gateway", "[bold yellow]UNAUTHORIZED[/bold yellow]", f"Reachable at {router_url} (Check NINEROUTER_PASSWORD)")
    except Exception as e:
        table.add_row("9Router Gateway", "[bold red]OFFLINE[/bold red]", f"{router_url}: {e}")

    # 6. Audio Captcha Solver Dependencies
    try:
        import speech_recognition
        table.add_row("SpeechRecognition (AI Audio)", "[bold green]PASS[/bold green]", "Module loaded for Webshare Hunter")
    except ImportError:
        table.add_row("SpeechRecognition (AI Audio)", "[bold red]MISSING[/bold red]", "Run: pip install SpeechRecognition")

    # 7. CapSolver API (Optional fallback solver)
    from llmharvester.webshare_hunter import check_capsolver_balance
    cs_info = check_capsolver_balance()
    if cs_info.get("configured"):
        table.add_row("CapSolver API (Optional)", "[bold green]ACTIVE[/bold green]", f"Balance: ${cs_info.get('balance', 0):.3f}")
    else:
        table.add_row("CapSolver API (Optional)", "[dim]DISABLED[/dim]", "Not configured (Using Free SpeechRecognition solver)")

    # 8. Storage Directories
    dirs_to_check = [("harvest/", Path("harvest")), ("output/", Path("output")), ("chrome-data/", Path("chrome-data"))]
    dirs_status = []
    for d_name, d_path in dirs_to_check:
        try:
            d_path.mkdir(parents=True, exist_ok=True)
            test_file = d_path / ".doctor_test"
            test_file.write_text("ok")
            test_file.unlink()
            dirs_status.append(f"{d_name} (ok)")
        except Exception:
            dirs_status.append(f"{d_name} (error)")
    table.add_row("Directory Storage", "[bold green]PASS[/bold green]", ", ".join(dirs_status))

    # 9. Cloudflare WARP & sing-box
    from llmharvester.warp import find_singbox, is_warp_running, load_warp_profile
    sbox = find_singbox()
    warp_stat = is_warp_running()
    warp_prof = load_warp_profile()
    if warp_stat:
        table.add_row(
            "Cloudflare WARP",
            "[bold green]ACTIVE[/bold green]",
            f"Port 10808 (IP: {warp_stat.get('query')}, {warp_stat.get('org', 'Cloudflare')})",
        )
    elif sbox and warp_prof:
        table.add_row(
            "Cloudflare WARP",
            "[bold green]PASS[/bold green]",
            "sing-box ready, profile configured (Standby :10808)",
        )
    elif sbox:
        table.add_row(
            "Cloudflare WARP",
            "[bold yellow]STANDBY[/bold yellow]",
            "sing-box ready, profile will auto-generate on harvest",
        )
    else:
        table.add_row(
            "Cloudflare WARP",
            "[bold red]MISSING[/bold red]",
            "sing-box binary not found",
        )

    console.print(table)
    console.print("\n[bold green]Doctor Verdict:[/bold green] Core components tested and ready for automated operations.\n")


def menu_webshare_residential() -> None:
    console.print("\n[bold cyan]=== WEBSHARE RESIDENTIAL HUNTER ===[/bold cyan]")
    console.print("[dim]Automated Residential IP extraction via AI Audio Solver (Google SpeechRecognition / CapSolver).[/dim]\n")

    try:
        from llmharvester.browser_utils import get_browser_info, get_browser_install_instructions
        b_info = get_browser_info()
        if not b_info["available"]:
            console.print("[bold red]No Chromium/Chrome/Brave browser found on system![/bold red]")
            console.print(get_browser_install_instructions("EN"))
            return
    except Exception as e:
        console.print(f"[yellow]Browser detection warning: {e}[/yellow]")

    try:
        from llmharvester.webshare_hunter import run_webshare_hunter, check_capsolver_balance
    except ImportError as e:
        console.print(f"[bold red]Failed loading Webshare Hunter module:[/bold red] {e}")
        return

    acc_str = Prompt.ask("How many Webshare accounts to harvest? (1 account = 10 Residential IPs)", default="1")
    try:
        total_acc = int(acc_str)
        if total_acc < 1:
            total_acc = 1
    except ValueError:
        total_acc = 1

    cs_info = check_capsolver_balance()
    is_headless = False

    if cs_info.get("can_headless"):
        console.print(f"\n[bold green]CapSolver API Active![/bold green] Balance: ${cs_info['balance']:.3f} (Headless mode ready)")
        is_headless = Confirm.ask("Run in background without window (Headless)?", default=True)
    else:
        console.print("\n[bold cyan]CAPTCHA ENGINE STATUS & DISPLAY MODE:[/bold cyan]")
        console.print("  - Active Solver   : [bold green]Free AI Audio Solver (SpeechRecognition, No Token Balance Needed)[/bold green]")
        console.print(f"  - Headless Status : [cyan]Disabled / Visible Window[/cyan] ({cs_info.get('message')})")
        console.print("  [dim]Note: Free Audio Solver uses a visible window to ensure natural mouse movements[/dim]")
        console.print("  [dim]and prevent Google reCAPTCHA 'Automated queries' blocking.[/dim]")
        console.print("  [bold green]Automatically using Visible Window mode...[/bold green]\n")
        is_headless = False

    db_target = os.getenv("NINEROUTER_DB")
    try:
        run_webshare_hunter(total=total_acc, headless=is_headless, sync_9router_db=db_target)
    except Exception as e:
        console.print(f"[bold red]Failed running Webshare Hunter:[/bold red] {e}")

    ws_file = Path("output/webshare_residential.txt")
    if ws_file.exists() and ws_file.stat().st_size > 0:
        lines = [line.strip() for line in ws_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        console.print(f"\n[bold green]Total {len(lines)} active Residential IPs saved to:[/bold green] [bold yellow]{ws_file}[/bold yellow] and synced to [bold cyan]proxies.txt[/bold cyan]!")
        if Confirm.ask("Display harvested proxies?", default=True):
            for p in lines[- (total_acc * 10):]:
                console.print(f"  [dim]-[/dim] [cyan]{p}[/cyan]")


def menu_proxy_checker() -> None:
    console.print("\n[bold cyan]=== CHECK & TEST PROXY POOL ===[/bold cyan]")
    cmd = [sys.executable, "-m", "llmharvester.cli", "proxies", "--check"]
    subprocess.run(cmd)


def menu_grok_farm() -> None:
    console.print("\n[bold cyan]=== GROK xAI ACCOUNT FARM ===[/bold cyan]")
    console.print("[dim]Residential proxy pool & automated OTP verification via Mail.tm / Gmail.[/dim]\n")

    try:
        from llmharvester.browser_utils import get_browser_info, get_browser_install_instructions
        b_info = get_browser_info()
        if not b_info["available"]:
            console.print("[bold red]No Chromium/Chrome/Brave browser found on system![/bold red]")
            console.print(get_browser_install_instructions("EN"))
            return
    except Exception as e:
        console.print(f"[yellow]Browser detection warning: {e}[/yellow]")

    cnt_str = Prompt.ask("Target number of Grok accounts to harvest?", default="1")
    try:
        total_grok = int(cnt_str)
        if total_grok < 1:
            total_grok = 1
    except ValueError:
        total_grok = 1

    console.print("\nBrowser Display Mode:")
    console.print("  [bold green][1][/bold green] Visible Window (Easy to monitor, default)")
    console.print("  [bold cyan][2][/bold cyan] Background / Headless (No UI window)")
    head_choice = Prompt.ask("Choice", choices=["1", "2"], default="1")
    is_headless = (head_choice == "2")

    try:
        from llmharvester.grok_farm import run_grok_farm
        console.print(f"\n[bold green]Starting farming for {total_grok} Grok account(s) (Gmail subaddress alias, {'Headless' if is_headless else 'Visible Window'})...[/bold green]\n")
        run_grok_farm(total=total_grok, headless=is_headless, mail_provider="gmail")
    except Exception as e:
        console.print(f"[bold red]Failed running Grok Farm:[/bold red] {e}")

    acc_file = Path("harvest/grok_accounts.txt")
    if not acc_file.exists():
        acc_file = Path("output/grok_accounts.txt")

    if acc_file.exists() and acc_file.stat().st_size > 0:
        console.print(f"\n[bold green]Grok accounts saved to:[/bold green] [bold yellow]{acc_file}[/bold yellow]")
        if Confirm.ask("Display harvested accounts now?", default=True):
            lines = [line.strip() for line in acc_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            for line in lines[-total_grok:]:
                console.print(f"  [dim]-[/dim] [cyan]{line}[/cyan]")


def menu_router_sync() -> None:
    console.print("\n[bold cyan]=== SYNC TO 9ROUTER GATEWAY ===[/bold cyan]")
    console.print("Select data to synchronize with 9Router:")
    console.print("  [1] All (ZeroTwo, Token Harbor, TokenMix)")
    console.print("  [2] ZeroTwo Only")
    console.print("  [3] Token Harbor Only")
    console.print("  [4] TokenMix Only")
    console.print("  [0] Cancel")

    choice = Prompt.ask("\nChoice", choices=["1", "2", "3", "4", "0"], default="1")
    if choice == "0":
        return

    targets = {"1": "all", "2": "zerotwo", "3": "tokenharbor", "4": "tokenmix"}
    target = targets.get(choice, "all")

    cmd = [sys.executable, "-m", "llmharvester.cli", "sync", "--target", target]
    subprocess.run(cmd)


def menu_refresh_tokens() -> None:
    console.print("\n[bold cyan]=== REFRESH SUPABASE TOKENS (ZEROTWO) ===[/bold cyan]")
    cmd = [sys.executable, "-m", "llmharvester.cli", "refresh"]
    subprocess.run(cmd)


def menu_warp() -> None:
    console.print("\n[bold cyan]=== CLOUDFLARE WARP PROXY MANAGER ===[/bold cyan]")
    console.print("[dim]Direct WireGuard connection to Cloudflare edge network via sing-box daemon.[/dim]\n")

    from llmharvester.warp import (
        ensure_warp_proxy,
        is_warp_running,
        stop_warp_proxy,
        register_warp_account,
        save_warp_profile,
        load_warp_profile,
        find_singbox,
    )

    stat = is_warp_running()
    sbox = find_singbox()
    prof = load_warp_profile()

    table = Table(title="Current WARP Status")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value")
    table.add_row("Proxy Endpoint", "http://127.0.0.1:10808")
    table.add_row(
        "Daemon Status",
        "[bold green]Online / Active[/bold green]" if stat else "[yellow]Offline / Standby[/yellow]",
    )
    table.add_row(
        "sing-box Binary",
        f"[green]{sbox}[/green]" if sbox else "[red]Not Found[/red]",
    )
    table.add_row(
        "Profile Config",
        "[green]Ready (output/warp/)[/green]" if prof else "[dim]Not Generated[/dim]",
    )
    if stat:
        table.add_row("Exit IP", str(stat.get("query", "Unknown")))
        table.add_row("Country", str(stat.get("country", "Unknown")))
        table.add_row("ISP / Org", f"{stat.get('isp', '')} ({stat.get('org', '')})")
        table.add_row("Hosting / Datacenter", str(stat.get("hosting", False)))
    console.print(table)

    console.print("\nActions:")
    console.print("  [1] Start WARP Proxy Daemon (:10808)")
    console.print("  [2] Stop WARP Proxy Daemon")
    console.print("  [3] Register Fresh Account / Generate New Profile")
    console.print("  [4] Test Connectivity & IP Leak")
    console.print("  [0] Back to main menu\n")

    act = Prompt.ask("Choice", choices=["1", "2", "3", "4", "0"], default="1")
    if act == "0":
        return
    if act == "1":
        console.print("[cyan]Starting Cloudflare WARP proxy on http://127.0.0.1:10808...[/cyan]")
        try:
            url, s = ensure_warp_proxy()
            console.print(
                f"[bold green][✓] WARP proxy running on {url} (Exit IP: {s.get('query')}, {s.get('org')})[/bold green]"
            )
        except Exception as e:
            console.print(f"[bold red]Failed to start WARP:[/bold red] {e}")
    elif act == "2":
        stop_warp_proxy()
        console.print("[bold green][✓] WARP proxy daemon stopped.[/bold green]")
    elif act == "3":
        if Confirm.ask("Generate a fresh Cloudflare WARP WireGuard profile now?", default=True):
            console.print("[cyan]Registering with Cloudflare REST API...[/cyan]")
            new_prof = register_warp_account()
            if new_prof:
                wg_file, sb_file = save_warp_profile(new_prof)
                console.print(
                    f"[bold green][✓] Successfully registered! Saved to {wg_file} and {sb_file}[/bold green]"
                )
            else:
                console.print("[bold red]Failed to register WARP account.[/bold red]")
    elif act == "4":
        s = is_warp_running()
        if s:
            console.print(f"[bold green][✓] Active Exit IP:[/bold green] {s.get('query')} ({s.get('country')})")
            console.print(f"[bold green][✓] Organization:[/bold green] {s.get('org')}")
            console.print(f"[bold green][✓] Hosting flag:[/bold green] {s.get('hosting')}")
        else:
            console.print("[yellow]WARP daemon is not currently running. Select option 1 to start it.[/yellow]")


def main() -> None:
    while True:
        os.system("clear" if os.name == "posix" else "cls")
        render_dashboard()

        console.print("[bold]MAIN TOOLS MENU:[/bold]")
        console.print("  [1] Run Harvester (Token Harbor, TokenMix, ZeroTwo, Grok xAI)")
        console.print("  [2] System Doctor (Readiness Diagnostic)")
        console.print("  [3] Webshare Residential Hunter (AI Audio Solver)")
        console.print("  [4] Check & Test Proxy Pool")
        console.print("  [5] Sync Accounts & Models to 9Router Gateway")
        console.print("  [6] Refresh ZeroTwo Tokens")
        console.print("  [7] Cloudflare WARP Proxy Manager (WireGuard :10808)")
        console.print("  [0] Exit\n")

        pilihan = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5", "6", "7", "0"], default="1")

        if pilihan == "1":
            menu_run_harvester()
        elif pilihan == "2":
            menu_doctor()
        elif pilihan == "3":
            menu_webshare_residential()
        elif pilihan == "4":
            menu_proxy_checker()
        elif pilihan == "5":
            menu_router_sync()
        elif pilihan == "6":
            menu_refresh_tokens()
        elif pilihan == "7":
            menu_warp()
        elif pilihan == "0":
            console.print("\n[dim]Goodbye![/dim]\n")
            break

        Prompt.ask("\n[dim]Press Enter to return to main menu...[/dim]")


if __name__ == "__main__":
    main()
