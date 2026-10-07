# -*- coding: utf-8 -*-
"""
llm-harvester Browser Utilities
===============================
Auto-detect and configure Chromium-compatible browsers (Chrome, Brave, Edge, Chromium)
for DrissionPage automation across Linux, Windows, and macOS.
"""

import os
import sys
import json
import shutil
import platform
from typing import Optional, Dict, Any

try:
    from colorama import Fore, Style
except ImportError:
    class _DummyColor:
        def __getattr__(self, _):
            return ""
    Fore = _DummyColor()
    Style = _DummyColor()

try:
    from DrissionPage import Chromium, ChromiumOptions
except ImportError:
    Chromium = None
    ChromiumOptions = None


def get_configured_browser_path() -> Optional[str]:
    """Retrieve custom browser path from settings.json if specified."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    settings_file = os.path.join(base_dir, "config", "settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                b_path = data.get("browser_path", "").strip()
                if b_path and os.path.isfile(b_path):
                    return b_path
        except Exception:
            pass
    return None


def find_system_browser() -> Optional[str]:
    """
    Search for a usable Chromium-based browser on the host system.
    Supports Google Chrome, Chromium, Brave Browser, Microsoft Edge, and Vivaldi.
    """
    # 1. Environment variables override
    for env_var in ("LLM_BROWSER_PATH", "CHROME_PATH", "BROWSER_PATH"):
        val = os.environ.get(env_var, "").strip()
        if val and os.path.isfile(val) and os.access(val, os.X_OK):
            return val

    # 2. settings.json override
    cfg_path = get_configured_browser_path()
    if cfg_path and os.path.isfile(cfg_path) and os.access(cfg_path, os.X_OK):
        return cfg_path

    # 3. Executable names in system PATH
    binaries = [
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "brave-browser-stable",
        "brave",
        "microsoft-edge-stable",
        "microsoft-edge",
        "edge",
        "vivaldi-stable",
        "vivaldi",
    ]
    if sys.platform == "win32":
        binaries = [
            "chrome.exe",
            "brave.exe",
            "msedge.exe",
            "vivaldi.exe",
            "chromium.exe",
        ]

    for b in binaries:
        found = shutil.which(b)
        if found and os.path.isfile(found) and os.access(found, os.X_OK):
            return found

    # 4. Standard platform filesystem paths
    os_name = platform.system().lower()
    candidates = []

    if "linux" in os_name:
        candidates = [
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/brave-browser",
            "/usr/bin/brave-browser-stable",
            "/opt/brave.com/brave/brave-browser",
            "/opt/brave.com/brave/brave",
            "/usr/bin/microsoft-edge-stable",
            "/usr/bin/microsoft-edge",
            "/opt/google/chrome/google-chrome",
            "/opt/microsoft/msedge/msedge",
            "/snap/bin/chromium",
            "/snap/bin/brave",
            "/var/lib/flatpak/exports/bin/com.google.Chrome",
            "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
            "/var/lib/flatpak/exports/bin/com.brave.Browser",
            os.path.expanduser("~/.local/share/flatpak/exports/bin/com.google.Chrome"),
            os.path.expanduser("~/.local/share/flatpak/exports/bin/org.chromium.Chromium"),
            os.path.expanduser("~/.local/share/flatpak/exports/bin/com.brave.Browser"),
        ]
    elif "darwin" in os_name or "mac" in os_name:
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ]
    elif "windows" in os_name or sys.platform == "win32":
        prog_dirs = [
            os.environ.get("PROGRAMFILES", "C:\\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", "C:\\Users\\Default\\AppData\\Local"),
        ]
        sub_paths = [
            r"Google\Chrome\Application\chrome.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe",
        ]
        for pdir in prog_dirs:
            for sub in sub_paths:
                candidates.append(os.path.join(pdir, sub))

    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    return None


def get_browser_name_from_path(b_path: Optional[str]) -> str:
    """Format human-readable browser name based on executable path."""
    if not b_path:
        return "Tidak Ditemukan"
    low = b_path.lower()
    if "brave" in low:
        return "Brave Browser"
    if "msedge" in low or "edge" in low:
        return "Microsoft Edge"
    if "chromium" in low:
        return "Chromium"
    if "vivaldi" in low:
        return "Vivaldi"
    if "chrome" in low:
        return "Google Chrome"
    return "Chromium Browser"


def get_browser_info() -> Dict[str, Any]:
    """Check browser readiness and details."""
    b_path = find_system_browser()
    return {
        "available": b_path is not None,
        "path": b_path,
        "name": get_browser_name_from_path(b_path)
    }


def setup_chromium_options(
    options: Optional[Any] = None,
    headless: bool = False,
    window_size: str = "1920,1080",
    user_agent: Optional[str] = None,
    use_cdp: bool = True,
    cdp_port: int = 9222,
) -> Any:
    """
    Configure ChromiumOptions with system browser path and robust flags.
    Ensures compatibility with modern Chromium, Brave, Edge, and container environments.
    When use_cdp=True, ensures the CDP browser on cdp_port is active and connects to it.
    """
    if ChromiumOptions is None:
        raise ImportError("DrissionPage is not installed. Please install requirements first.")

    co = options if options is not None else ChromiumOptions()

    # Bind auto-detected browser path
    b_path = find_system_browser()
    if b_path:
        co.set_browser_path(b_path)

    if use_cdp:
        try:
            try:
                from .browser import ensure_cdp_browser
            except (ImportError, ValueError):
                from llmharvester.browser import ensure_cdp_browser
            ensure_cdp_browser(port=cdp_port, headless=headless)
            co.set_local_port(cdp_port)
        except Exception:
            co.auto_port()
    else:
        co.auto_port()

    # Critical arguments for modern Chromium & Brave
    co.set_argument("--remote-allow-origins=*")
    co.set_argument("--disable-dev-shm-usage")

    # Only pass --no-sandbox if running as root or in container/Docker.
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    in_container = os.path.exists("/.dockerenv") or bool(os.environ.get("CONTAINER"))
    if is_root or in_container or os.environ.get("NO_SANDBOX") == "1":
        co.set_argument("--no-sandbox")

    if headless:
        co.headless(True)
        co.set_argument(f"--window-size={window_size}")
    else:
        co.set_argument("--start-maximized")

    if user_agent:
        co.set_user_agent(user_agent)

    return co


def get_browser_install_instructions(lang: str = "ID") -> str:
    """Get user-friendly installation advice when no compatible browser is found."""
    if lang == "ID":
        return f"""
{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
{Fore.RED}[ERROR] CHROMIUM BROWSER NOT FOUND!{Style.RESET_ALL}
{Fore.WHITE}llm-harvester requires a Chromium-based browser (Google Chrome, Brave, or Chromium)
to run browser automation tasks (Webshare Hunter / Grok Farm).{Style.RESET_ALL}

{Fore.CYAN}Panduan Pemasangan (Pilih salah satu):{Style.RESET_ALL}
  1. {Fore.GREEN}Pasang Chromium via APT (Sangat Cepat):{Style.RESET_ALL}
     {Fore.YELLOW}sudo apt update && sudo apt install -y chromium-browser{Style.RESET_ALL}

  2. {Fore.GREEN}Pasang Google Chrome Resmi:{Style.RESET_ALL}
     {Fore.YELLOW}wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb{Style.RESET_ALL}
     {Fore.YELLOW}sudo dpkg -i google-chrome-stable_current_amd64.deb{Style.RESET_ALL}

  3. {Fore.GREEN}Gunakan Browser yang Sudah Ada via Environment Variable (.env):{Style.RESET_ALL}
     Tambahkan baris berikut ke file {Fore.WHITE}.env{Style.RESET_ALL}:
     {Fore.YELLOW}CHROME_PATH=/path/ke/executable/browser{Style.RESET_ALL}
{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
"""
    else:
        return f"""
{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
{Fore.RED}[ERROR] CHROMIUM BROWSER NOT FOUND!{Style.RESET_ALL}
{Fore.WHITE}llm-harvester requires a Chromium-based browser (Google Chrome, Brave, or Chromium)
for automated pipelines (Webshare Hunter / Grok Farm).{Style.RESET_ALL}

{Fore.CYAN}Installation Guide (Choose one):{Style.RESET_ALL}
  1. {Fore.GREEN}Install Chromium via APT (Fastest):{Style.RESET_ALL}
     {Fore.YELLOW}sudo apt update && sudo apt install -y chromium-browser{Style.RESET_ALL}

  2. {Fore.GREEN}Install Official Google Chrome:{Style.RESET_ALL}
     {Fore.YELLOW}wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb{Style.RESET_ALL}
     {Fore.YELLOW}sudo dpkg -i google-chrome-stable_current_amd64.deb{Style.RESET_ALL}

  3. {Fore.GREEN}Use Existing Browser via Environment Variable (.env):{Style.RESET_ALL}
     Add this line to your {Fore.WHITE}.env{Style.RESET_ALL} file:
     {Fore.YELLOW}CHROME_PATH=/path/to/browser/binary{Style.RESET_ALL}
{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
"""


def create_browser(
    options: Optional[Any] = None,
    headless: bool = False,
    window_size: str = "1920,1080",
    user_agent: Optional[str] = None
) -> Any:
    """
    Launch a Chromium instance with auto-configured options and clear error diagnostics.
    """
    if Chromium is None:
        raise ImportError("DrissionPage is not installed.")

    b_info = get_browser_info()
    if not b_info["available"]:
        instructions = get_browser_install_instructions()
        print(instructions)
        raise FileNotFoundError(
            "Browser berbasis Chromium (Chrome/Brave/Chromium) tidak ditemukan di sistem. "
            "Silakan pasang browser terlebih dahulu atau tentukan CHROME_PATH di .env."
        )

    co = setup_chromium_options(options=options, headless=headless, window_size=window_size, user_agent=user_agent)

    try:
        browser = Chromium(co)
        return browser
    except Exception as e:
        err_msg = str(e)
        if "browser executable file path cannot be found" in err_msg.lower() or "no such file or directory" in err_msg.lower():
            print(get_browser_install_instructions())
            raise FileNotFoundError(
                f"Gagal meluncurkan browser di path '{b_info.get('path')}': {e}. "
                "Pastikan binary browser valid dan dapat dieksekusi."
            ) from e
        raise e
