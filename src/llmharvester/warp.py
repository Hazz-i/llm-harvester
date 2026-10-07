"""Cloudflare WARP WireGuard & Sing-box Proxy Manager.

Registers free Cloudflare WARP WireGuard profiles directly via Cloudflare REST API,
generates sing-box mixed HTTP/SOCKS5 inbound configurations, and manages
the local proxy daemon for harvesting with clean Cloudflare edge IPs.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

CLOUDFLARE_REG_API = "https://api.cloudflareclient.com/v0a2158/reg"
DEFAULT_WARP_PORT = 10808
DEFAULT_WARP_DIR = Path("output/warp")

_warp_process: subprocess.Popen | None = None


def find_singbox() -> str | None:
    """Find sing-box executable in PATH or user directories."""
    which_path = shutil.which("sing-box")
    if which_path and Path(which_path).exists():
        return which_path

    candidates = [
        Path.home() / ".local/bin/sing-box",
        Path("/usr/local/bin/sing-box"),
        Path("/usr/bin/sing-box"),
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return None


def generate_x25519_keypair() -> tuple[str, str]:
    """Generate X25519 private & public keypair encoded in standard Base64."""
    try:
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:
        raise RuntimeError(
            "cryptography is required for WARP key generation. Run: uv pip install cryptography"
        ) from e

    priv_key = x25519.X25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    priv_raw = priv_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return (
        base64.b64encode(priv_raw).decode("ascii"),
        base64.b64encode(pub_raw).decode("ascii"),
    )


def register_warp_account(timeout: float = 12.0) -> dict[str, Any] | None:
    """Register a fresh Cloudflare WARP WireGuard profile via public REST API.

    Returns dict with keys, endpoints, IPv4/IPv6 addresses.
    """
    priv_b64, pub_b64 = generate_x25519_keypair()
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")

    payload = {
        "key": pub_b64,
        "install_id": "",
        "fcm_token": "",
        "tos": now_iso,
        "model": "PC",
        "serial_number": "",
        "locale": "en_US",
    }

    req = urllib.request.Request(
        CLOUDFLARE_REG_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "okhttp/3.12.1",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                data = json.loads(resp.read().decode("utf-8"))
                account_id = data.get("id")
                token = data.get("token")
                cfg = data.get("config", {})
                peers = cfg.get("peers", [])
                peer = peers[0] if peers else {}
                peer_pub = peer.get("public_key", "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=")

                endpoint_obj = peer.get("endpoint", {})
                endpoint_host = endpoint_obj.get("host", "engage.cloudflareclient.com:2408")

                interface = cfg.get("interface", {})
                addresses = interface.get("addresses", {})
                v4_addr = addresses.get("v4", "172.16.0.2")
                v6_addr = addresses.get("v6", "")

                return {
                    "account_id": account_id,
                    "token": token,
                    "private_key": priv_b64,
                    "public_key": pub_b64,
                    "peer_public_key": peer_pub,
                    "endpoint": endpoint_host,
                    "v4_address": v4_addr,
                    "v6_address": v6_addr,
                    "dns": "1.1.1.1, 1.0.0.1",
                    "created_at": now_iso,
                }
    except Exception as e:
        print(f"[-] Cloudflare WARP registration failed: {e}")
    return None


def build_wireguard_conf(profile: dict[str, Any]) -> str:
    """Format WARP profile into standard WireGuard .conf format."""
    addrs = [profile["v4_address"]]
    if profile.get("v6_address"):
        addrs.append(profile["v6_address"])
    addr_str = ", ".join(addrs)

    return (
        f"[Interface]\n"
        f"PrivateKey = {profile['private_key']}\n"
        f"Address = {addr_str}\n"
        f"DNS = {profile.get('dns', '1.1.1.1')}\n\n"
        f"[Peer]\n"
        f"PublicKey = {profile['peer_public_key']}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"Endpoint = {profile['endpoint']}\n"
    )


def build_singbox_config(profile: dict[str, Any], local_port: int = DEFAULT_WARP_PORT) -> dict[str, Any]:
    """Format WARP profile into sing-box 1.11+ endpoint mixed inbound config."""
    ep_str = profile.get("endpoint", "engage.cloudflareclient.com:2408")
    if ":" in ep_str:
        ep_host, ep_port_str = ep_str.split(":", 1)
        ep_port = int(ep_port_str)
    else:
        ep_host = ep_str
        ep_port = 2408

    local_addrs: list[str] = []
    v4 = profile.get("v4_address", "172.16.0.2")
    local_addrs.append(f"{v4}/32" if "/" not in v4 else v4)

    v6 = profile.get("v6_address", "")
    if v6:
        local_addrs.append(f"{v6}/128" if "/" not in v6 else v6)

    return {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": local_port,
            }
        ],
        "endpoints": [
            {
                "type": "wireguard",
                "tag": "warp-out",
                "address": local_addrs,
                "private_key": profile["private_key"],
                "peers": [
                    {
                        "address": ep_host,
                        "port": ep_port,
                        "public_key": profile["peer_public_key"],
                        "allowed_ips": ["0.0.0.0/0", "::/0"],
                        "reserved": [0, 0, 0],
                    }
                ],
                "mtu": 1280,
            }
        ],
        "route": {
            "final": "warp-out",
        },
    }


def save_warp_profile(
    profile: dict[str, Any],
    output_dir: Path | str = DEFAULT_WARP_DIR,
    local_port: int = DEFAULT_WARP_PORT,
) -> tuple[Path, Path]:
    """Save profile to disk as profile.json, warp.conf, and warp_singbox.json."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    profile_path = out / "profile.json"
    profile_path.write_text(json.dumps(profile, indent=2))

    wg_path = out / "warp.conf"
    wg_path.write_text(build_wireguard_conf(profile))

    singbox_path = out / "warp_singbox.json"
    singbox_cfg = build_singbox_config(profile, local_port=local_port)
    singbox_path.write_text(json.dumps(singbox_cfg, indent=2))

    return wg_path, singbox_path


def load_warp_profile(output_dir: Path | str = DEFAULT_WARP_DIR) -> dict[str, Any] | None:
    """Load an existing WARP profile from output/warp or fallbacks."""
    candidates = [
        Path(output_dir) / "profile.json",
        Path("output/warp/profile.json"),
        Path("../petani-proxy/output/warp/warp.conf"),
    ]

    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            if p.suffix == ".json":
                try:
                    return json.loads(p.read_text())
                except Exception:
                    pass
            elif p.suffix == ".conf":
                # Parse wireguard .conf fallback
                try:
                    content = p.read_text()
                    prof: dict[str, Any] = {}
                    for line in content.splitlines():
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if k == "PrivateKey":
                                prof["private_key"] = v
                            elif k == "PublicKey":
                                prof["peer_public_key"] = v
                            elif k == "Address":
                                parts = [x.strip() for x in v.split(",")]
                                prof["v4_address"] = parts[0]
                                if len(parts) > 1:
                                    prof["v6_address"] = parts[1]
                            elif k == "Endpoint":
                                prof["endpoint"] = v
                    if "private_key" in prof and "peer_public_key" in prof:
                        return prof
                except Exception:
                    pass
    return None


def is_warp_running(port: int = DEFAULT_WARP_PORT, timeout: float = 2.5) -> dict[str, Any] | None:
    """Check if the local WARP proxy port is active and responding.

    Returns dict with IP and ISP if active, None otherwise.
    """
    proxy_url = f"http://127.0.0.1:{port}"
    try:
        req = urllib.request.Request(
            "http://ip-api.com/json?fields=country,isp,org,query,proxy,hosting",
            headers={"User-Agent": "llm-harvester-warp"},
        )
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def stop_warp_proxy(port: int = DEFAULT_WARP_PORT) -> None:
    """Terminate running sing-box instances using port or warp config."""
    global _warp_process
    if _warp_process:
        try:
            _warp_process.terminate()
            _warp_process.wait(timeout=2.0)
        except Exception:
            try:
                _warp_process.kill()
            except Exception:
                pass
        _warp_process = None

    # Kill any external sing-box running warp_singbox.json
    try:
        subprocess.run(
            ["pkill", "-f", "warp_singbox.json"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass


def start_warp_proxy(
    config_path: Path | str,
    port: int = DEFAULT_WARP_PORT,
    timeout: float = 8.0,
) -> subprocess.Popen:
    """Launch sing-box in background with the WARP config."""
    global _warp_process
    binary = find_singbox()
    if not binary:
        raise RuntimeError(
            "sing-box executable not found! Install sing-box or put it in ~/.local/bin/sing-box"
        )

    config_p = Path(config_path).resolve()
    if not config_p.exists():
        raise FileNotFoundError(f"sing-box config not found at: {config_p}")

    stop_warp_proxy(port)
    time.sleep(0.5)

    proc = subprocess.Popen(
        [binary, "run", "-c", str(config_p)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _warp_process = proc

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = is_warp_running(port, timeout=1.5)
        if status:
            return proc
        time.sleep(0.4)

    # If timeout occurred, check if process died
    poll = proc.poll()
    if poll is not None:
        raise RuntimeError(f"sing-box exited immediately with code {poll}")

    return proc


def ensure_warp_proxy(
    port: int = DEFAULT_WARP_PORT,
    output_dir: Path | str = DEFAULT_WARP_DIR,
) -> tuple[str, dict[str, Any]]:
    """Ensure WARP proxy is running on local port. Auto-registers and launches if needed.

    Returns (proxy_url, status_dict).
    """
    proxy_url = f"http://127.0.0.1:{port}"
    existing_status = is_warp_running(port)
    if existing_status:
        return proxy_url, existing_status

    out = Path(output_dir)
    singbox_cfg_file = out / "warp_singbox.json"

    # Profile lookup or creation
    profile = load_warp_profile(out)
    if not profile or not singbox_cfg_file.exists():
        print("[*] No existing Cloudflare WARP profile found. Registering a fresh one...")
        profile = register_warp_account()
        if not profile:
            raise RuntimeError("Failed to register Cloudflare WARP account via Cloudflare REST API")
        save_warp_profile(profile, output_dir=out, local_port=port)
    else:
        # Re-save config to ensure port matches
        save_warp_profile(profile, output_dir=out, local_port=port)

    print(f"[*] Starting Cloudflare WARP proxy on {proxy_url} via sing-box...")
    start_warp_proxy(singbox_cfg_file, port=port)
    status = is_warp_running(port)
    if not status:
        raise RuntimeError(f"WARP proxy started but failed health check on {proxy_url}")

    return proxy_url, status
