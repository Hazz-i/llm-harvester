"""Launch a local Chromium with a fresh debug port and optional proxy."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME_CANDIDATES = [
    "brave-browser",
    "brave",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def update_env_cdp_ws(ws_url: str, env_path: str | Path = ".env") -> bool:
    """Update or append LLM_CDP_WS in .env file with the live websocket URL."""
    import re

    path = Path(env_path)
    if not path.exists():
        path.write_text(f"LLM_CDP_WS={ws_url}\n")
        return True

    content = path.read_text()
    if re.search(r"^LLM_CDP_WS=.*$", content, flags=re.MULTILINE):
        new_content = re.sub(r"^LLM_CDP_WS=.*$", f"LLM_CDP_WS={ws_url}", content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip("\n") + f"\nLLM_CDP_WS={ws_url}\n"

    if new_content != content:
        path.write_text(new_content)
        return True
    return False


def find_chrome(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() or shutil.which(explicit) else None
    for name in CHROME_CANDIDATES:
        path = shutil.which(name) if not name.startswith("/") and "\\" not in name else name
        if path and Path(path).exists():
            return path
    return None


def is_cdp_alive(port: int = 9222, timeout: float = 1.5) -> str | None:
    """Check if Chrome/Brave/Chromium is listening on the CDP debugging port.
    Returns WebSocket debugger URL if alive, otherwise None.
    """
    import urllib.request
    import json
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(url, headers={"User-Agent": "llm-harvester"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None


_active_configs: dict[int, dict] = {}
_active_bridges: dict[int, Any] = {}


def stop_cdp_browser(port: int = 9222, timeout: float = 3.0) -> None:
    """Terminate the CDP browser instance listening on `port`."""
    bridge = _active_bridges.pop(port, None)
    if bridge:
        try:
            bridge.stop()
        except Exception:
            pass
    _active_configs.pop(port, None)

    try:
        subprocess.run(
            ["pkill", "-9", "-f", f"remote-debugging-port={port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_cdp_alive(port, timeout=0.4):
            return
        time.sleep(0.2)


def ensure_cdp_browser(
    port: int = 9222,
    headless: bool = False,
    profile_dir: str | Path = "./chrome-data",
    proxy: str | None = None,
    force_restart: bool = False,
    timeout: float = 15.0,
    log_func = None,
) -> str:
    """Ensure a Chromium/Brave/Chrome browser is running with remote debugging on `port`.
    If already alive with matching headless & proxy configuration, returns live URL.
    Otherwise restarts or launches the browser with desired proxy and display settings.
    """
    def _print(msg: str) -> None:
        if log_func:
            log_func(msg)
        else:
            print(msg)

    desired_cfg = {"headless": bool(headless), "proxy": str(proxy or "").strip()}
    curr_cfg = _active_configs.get(port)

    # 1. Check if alive and whether restart is needed
    if is_cdp_alive(port):
        if force_restart or (curr_cfg is not None and curr_cfg != desired_cfg) or (proxy and curr_cfg is None):
            _print(f"[*] Adapting CDP browser on port {port} (headless={headless}, proxy={'yes' if proxy else 'no'})...")
            stop_cdp_browser(port)
        else:
            ws = is_cdp_alive(port)
            if ws:
                update_env_cdp_ws(ws)
                return ws

    # 2. Find browser binary
    binary = find_chrome()
    if not binary:
        raise RuntimeError("No compatible browser found (Brave, Chrome, Chromium). Please install one.")

    p_dir = os.path.abspath(str(profile_dir))
    os.makedirs(p_dir, exist_ok=True)

    cmd = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={p_dir}",
        "--remote-allow-origins=*",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    in_container = os.path.exists("/.dockerenv") or bool(os.environ.get("CONTAINER"))
    if is_root or in_container or os.environ.get("NO_SANDBOX") == "1":
        cmd.append("--no-sandbox")

    if headless:
        cmd.append("--headless=new")

    if proxy:
        try:
            from .proxy_bridge import prepare_chromium_proxy
            effective_proxy, bridge = prepare_chromium_proxy(proxy)
            if bridge:
                _active_bridges[port] = bridge
            cmd.append(f"--proxy-server={effective_proxy}")
            _print(f"[*] Browser traffic routed via proxy: {effective_proxy}")
        except Exception as e:
            _print(f"[!] Warning: proxy bridge error: {e}, using direct {proxy}")
            cmd.append(f"--proxy-server={proxy}")

    cmd.append("about:blank")

    _print(f"[*] Auto-launching {Path(binary).name} on CDP debug port {port}...")
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ws = is_cdp_alive(port)
        if ws:
            _active_configs[port] = desired_cfg
            update_env_cdp_ws(ws)
            _print(f"[✓] CDP browser ready on port {port}: {ws}")
            return ws
        time.sleep(0.3)

    raise RuntimeError(f"Browser failed to respond on CDP port {port} within {timeout}s.")


def free_port(preferred: int = 9222) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChromeLauncher:
    """Start Chromium with a debug port, fresh profile and optional proxy."""

    def __init__(
        self,
        *,
        chrome: str | None = None,
        port: int = 9222,
        proxy: str | None = None,
        headless: bool = False,
        profile_dir: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.chrome = chrome
        self.port = port
        self.proxy = proxy
        self.headless = headless
        self.profile_dir = profile_dir or tempfile.mkdtemp(prefix="zt-chrome-")
        self.extra_args = extra_args or []
        self.proc: subprocess.Popen | None = None
        self._ws_url: str | None = None

    @property
    def ws_url(self) -> str:
        return self._ws_url or f"ws://127.0.0.1:{self.port}/devtools/browser"

    def command(self) -> list[str]:
        binary = find_chrome(self.chrome)
        if not binary:
            raise RuntimeError("no Chrome/Chromium found; pass --chrome or install one")
        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
        ]
        if self.headless:
            args.append("--headless=new")
        if self.proxy:
            args.append(f"--proxy-server={self.proxy}")
        args.extend(self.extra_args)
        args.append("about:blank")
        return args

    def start(self) -> str:
        self.proc = subprocess.Popen(
            self.command(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ws = self._fetch_ws_url()
            if ws:
                self._ws_url = ws
                return ws
            if self.proc.poll() is not None:
                raise RuntimeError("Chrome exited immediately; check the binary/flags")
            time.sleep(0.3)
        raise RuntimeError("Chrome debug port did not open in time")

    def _fetch_ws_url(self) -> str | None:
        import httpx

        try:
            r = httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
            if r.status_code == 200:
                return r.json().get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None

    def _debug_ready(self) -> bool:
        return self._fetch_ws_url() is not None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


async def launch_async(**kwargs) -> ChromeLauncher:
    launcher = ChromeLauncher(**kwargs)
    await asyncio.get_event_loop().run_in_executor(None, launcher.start)
    return launcher
