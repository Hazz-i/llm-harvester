<div align="center">

# llm-harvester

**Multi-platform AI / LLM account creator & token harvester · ZeroTwo, Token Harbor & TokenMix · 9Router auto-connect**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Bulk-provision AI accounts with disposable mail.tm mailboxes, harvest JWT sessions, cookies, or API keys across ZeroTwo, Token Harbor, and TokenMix, and wire them directly into [9Router](https://9router.com) as OpenAI-compatible providers — end to end.*

[English](README.md) · [Bahasa Indonesia](docs/README.id.md) · [Español](docs/README.es.md) · [日本語](docs/README.ja.md) · [中文](docs/README.zh.md) · [Français](docs/README.fr.md)

</div>

---

## What it does

1. **Multi-Target Farming**: Supports **ZeroTwo** (`app.zerotwo.ai`), **Token Harbor** (`tokenharbor.ai`), **TokenMix** (`api.tokenmix.ai`), **ElevenLabs** (`elevenlabs.io`), and **Grok xAI** (`accounts.x.ai`) with interactive terminal selection or direct CLI flags.
2. **Interactive TUI Dashboard (`./main.py`)**: Full-featured terminal interface with real-time readiness diagnostics, system status tables, and one-click harvesting across 7 dedicated tools.
3. **Flexible Network Routing (Direct by Default)**:
   - **Direct Connection (Default)**: Uses clean local residential ISP connection for maximum Cloudflare Turnstile human trust score without proxy overhead.
   - **Cloudflare WARP (`:10808`)**: Built-in WireGuard account generator via official Cloudflare REST API and local `sing-box` daemon for clean Cloudflare edge IPs (`hosting: false`).
   - **Proxy Pool**: Automatic rotation via `proxies.txt` or residential proxies when farming at higher volumes.
4. **Webshare Residential Hunter**: Automated residential proxy extractor powered by AI audio captcha solving (Google SpeechRecognition / CapSolver fallback).
5. **Turnstile & React-Aware Automation**:
   - Native CDP input typing (`Input.insertText`) + React `_valueTracker` synchronization preventing cleared form values in Next.js controlled components.
   - Automatic Cloudflare Turnstile verification detection and solving.
   - Auto-detects display mode requirements (forcing Visible Window for Turnstile challenges when needed).
6. **Credential Harvesting & 9Router Auto-Connect**:
   - **Token Harbor**: Generates `thk_live_...` API keys, extracts/syncs 20+ model IDs, and auto-registers into **9Router** as a native OpenAI-compatible provider node.
   - **TokenMix**: Generates `sk-tm-...` API keys, extracts/syncs 22+ model IDs, and auto-registers into **9Router** as a native OpenAI-compatible provider node.
   - **ElevenLabs**: Generates `xi-api-key` (10,000 characters free quota), bypasses onboarding wizard, verifies email via `mail.tm` or IMAP catch-all, and syncs TTS voice models into **9Router**.
   - **ZeroTwo**: Intercepts Supabase JWTs (`access_token`, `refresh_token`), cookies (`cf_clearance`, `__csrf`), CSRF tokens, and registers into **9Router** via a local OpenAI shim.
   - **Grok xAI**: Automates residential proxy account creation with Gmail subaddress aliases and auto-OTP.
7. **Crash-Safe Ledger Output**: Writes append-only JSONL ledgers (`sessions.jsonl`, `tokenharbor_keys.jsonl`, `tokenmix_keys.jsonl`, `elevenlabs_keys.jsonl`, `elevenlabs_keys.txt`, `grok_accounts.txt`).

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           llm-harvester Architecture                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │                                           NETWORK ROUTING LAYER                                           │
   │  [1] Direct Connection (Default)  │  [2] Cloudflare WARP (:10808)  │  [3] Proxy Pool (Webshare/Residential)│
   └─────────────────────────────────────┬─────────────────────────────────────────────────────────────────────┘
                                         │ Routes Browser & HTTP Traffic
                                         ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │                                      BROWSER AUTOMATION & IDENTITY LAYER                                  │
   │  • Auto-CDP: Brave / Chromium / Chrome (Port :9222, auto-launched without start-browser.sh)                │
   │  • Native CDP Input (`Input.insertText`) + React `_valueTracker` State Sync                               │
   │  • Cloudflare Turnstile Challenge Detection & Auto-Solver                                                 │
   │  • mail.tm Hydra REST API & Optional IMAP Catch-All Listener                                              │
   └─────────────────────────────────────┬─────────────────────────────────────────────────────────────────────┘
                                         │ Orchestrates Sign-ups
                                         ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │                                      MULTI-PLATFORM HARVEST TARGETS                                       │
   │  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐  │
   │  │  ZeroTwoCreator  │ │TokenHarborCreator│ │ TokenMixCreator  │ │ElevenLabsCreator │ │   GrokCreator    │  │
   │  │ (app.zerotwo.ai) │ │ (tokenharbor.ai) │ │  (tokenmix.ai)   │ │ (elevenlabs.io)  │ │ (accounts.x.ai)  │  │
   │  └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘  │
   └───────────┼────────────────────┼────────────────────┼────────────────────┼────────────────────┼────────────┘
               │                    │                    │                    │                    │
               │ Supabase JWT,      │ Live API Keys      │ Live API Keys      │ xi-api-key (10k    │ Session Tokens
               │ Cookies & CSRF     │ (thk_live_...)     │ (sk-tm-...)        │ free characters)   │ & Credentials
               ▼                    ▼                    ▼                    ▼                    ▼
   ┌──────────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │ harvest/             │ │ harvest/         │ │ harvest/         │ │ harvest/         │ │ harvest/         │
   │ sessions.jsonl       │ │ tokenharbor_keys │ │ tokenmix_keys    │ │ elevenlabs_keys  │ │ grok_accounts.txt│
   └───────────┬──────────┘ └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘ └──────────────────┘
               │                     │                    │                    │
               │ Local SSE Shim      │ Direct Node & Sync │ Direct Node & Sync │ Direct TTS Node
               │ (:8787)             │ (20+ Model IDs)    │ (22+ Model IDs)    │ & Models Sync
               ▼                     ▼                    ▼                    ▼
   ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────┐
   │                                            9Router AI GATEWAY                                             │
   │                             (Multi-Account Load Balancing & Unified AI Endpoint)                          │
   └───────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

```mermaid
flowchart TD
    subgraph Routing["1. Network Routing Layer"]
        R1["Direct Connection (Default / Residential ISP)"]
        R2["Cloudflare WARP (WireGuard Anycast :10808)"]
        R3["Proxy Pool (proxies.txt / Webshare Residential)"]
    end

    subgraph Automation["2. Automation & Bot Bypass (CDP :9222)"]
        CDP["Auto-CDP: Brave / Chrome Controller (Port :9222)"]
        REACT["Native Input & React _valueTracker Sync"]
        TURN["Cloudflare Turnstile Detection & Auto-Solver"]
        MAIL["mail.tm Hydra API / Optional IMAP Catch-All"]
    end

    subgraph Harvesters["3. Multi-Target Harvesting"]
        ZT["ZeroTwo (app.zerotwo.ai)"]
        TH["Token Harbor (tokenharbor.ai)"]
        TM["TokenMix (tokenmix.ai)"]
        EL["ElevenLabs (elevenlabs.io)"]
        GK["Grok xAI (accounts.x.ai)"]
    end

    subgraph Storage["4. Crash-Safe Ledgers"]
        L_ZT[("harvest/sessions.jsonl")]
        L_TH[("harvest/tokenharbor_keys.jsonl")]
        L_TM[("harvest/tokenmix_keys.jsonl")]
        L_EL[("harvest/elevenlabs_keys.jsonl & .txt")]
        L_GK[("harvest/grok_accounts.txt")]
    end

    subgraph Gateway["5. 9Router AI Gateway Integration"]
        SHIM["ZeroTwo OpenAI Shim (:8787)"]
        ROUTER["9Router AI Gateway\n(Unified OpenAI & TTS API Endpoint)"]
    end

    Routing --> Automation
    Automation --> Harvesters

    ZT -->|Supabase JWT & Cookies| L_ZT
    TH -->|thk_live_... API Keys| L_TH
    TM -->|sk-tm-... API Keys| L_TM
    EL -->|xi-api-key Free Tier| L_EL
    GK -->|Credentials & Cookies| L_GK

    L_ZT --> SHIM --> ROUTER
    L_TH -->|Direct Node + Models Sync| ROUTER
    L_TM -->|Direct Node + Models Sync| ROUTER
    L_EL -->|Direct Node + TTS Models Sync| ROUTER
```

### Architecture Flow Explained

1. **Network Routing Layer**:
   - **Direct Connection (Default)**: Direct local connection without proxies. Ideal for passing Cloudflare Turnstile with native ISP reputation.
   - **Cloudflare WARP (`:10808`)**: Registers a WireGuard profile via the official Cloudflare REST API and routes traffic through a local `sing-box` mixed proxy daemon.
   - **Proxy Pool**: Distributes traffic across authenticated HTTP/SOCKS5 proxies from `proxies.txt` or Webshare Residential.

2. **Browser Automation via CDP (`:9222`)**:
   Controls a real Chromium, Google Chrome, or Brave Browser session via the **Chrome DevTools Protocol (CDP)** (`:9222`). Features native `Input.insertText` typing with React `_valueTracker` synchronization to prevent Next.js controlled forms from wiping input state, while solving Cloudflare Turnstile anti-bot challenges natively.

3. **Disposable Identity Provisioning (`mail.tm`)**:
   Automatically provisions disposable mailboxes on-demand via the `mail.tm` REST API (`POST /accounts`). It polls incoming messages to extract verification magic links (ZeroTwo), account confirmation links (Token Harbor), or OTP verification codes (TokenMix) without needing third-party webmail tabs.

4. **Multi-Target Creators**:
   - **`ZeroTwoCreator`**: Automates sign-up at `app.zerotwo.ai`, follows magic links, completes onboarding, and intercepts Supabase JWT tokens (`access_token`, `refresh_token`), session cookies (`cf_clearance`, `__csrf`), and CSRF tokens.
   - **`TokenHarborCreator`**: Automates registration at `tokenharbor.ai`, verifies via `mail.tm`, navigates to API keys, and generates production API keys (`thk_live_...`).
   - **`TokenMixCreator`**: Automates registration at `tokenmix.ai`, solves Turnstile, verifies email via `mail.tm`, and generates API keys (`sk-tm-...`).
   - **`GrokCreator`**: Automates account provisioning on `accounts.x.ai` with residential proxy rotation.

5. **Dedicated Ledgers**:
   Stores harvested credentials in append-only, crash-safe JSONL ledger files:
   - `harvest/sessions.jsonl` (ZeroTwo sessions)
   - `harvest/tokenharbor_keys.jsonl` (Token Harbor API keys)
   - `harvest/tokenmix_keys.jsonl` (TokenMix API keys)
   - `harvest/grok_accounts.txt` (Grok accounts)

6. **Direct 9Router Integration & Model Catalog Sync**:
   - **ZeroTwo**: Registers an OpenAI-compatible node (`http://localhost:8787/v1`) backed by the local shim, mapping exclusive ZeroTwo models (`gpt-6-luna`, `deepseek-v4.1-flash`, etc.).
   - **Token Harbor**: Directly creates an OpenAI provider node in 9Router (`https://tokenharbor.ai/v1`), registers harvested API keys, and automatically syncs all 20+ model IDs (`claude-opus-5.5`, `gpt-6-astra`, `deepseek-v3`, etc.).
   - **TokenMix**: Directly creates an OpenAI provider node in 9Router (`https://api.tokenmix.ai/v1`), registers harvested API keys, and automatically syncs all 22+ model IDs (`gpt-4o`, `deepseek-v4`, `gemini-2.5-flash`, etc.).



## Install

```bash
git clone https://github.com/Hazz-i/llm-harvester.git
cd llm-harvester
pip install -e ".[shim]"
```

## Quickstart

### 1. Browser CDP (Auto-Started)

`llm-harvester` automatically detects and launches your local Chromium, Google Chrome, or Brave Browser with remote debugging enabled on port `9222`. You do **not** need to manually run an external launch script or configure websocket URLs.

If you prefer to start your browser manually beforehand:

```bash
# Brave
brave-browser --remote-debugging-port=9222 --user-data-dir=./chrome-data

# Or Google Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

*(Note: `llm-harvester` automatically auto-detects running browsers on port 9222 and updates `.env` dynamically!)*

### 2. Configure `.env` or `config.toml`

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

#### A. General Configuration (Token Harbor, TokenMix, ElevenLabs & ZeroTwo)
These settings are used across all platforms:

```env
# Browser CDP (Auto-detected & auto-started on port 9222; only set for remote/cloud CDP)
# LLM_CDP_WS=ws://127.0.0.1:9222/devtools/browser/<id>

# 9Router AI Gateway (Local http://localhost:20128 or Remote https://nine.yourdomain.com)
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
# If your 9Router instance is password-protected (dashboard auth):
NINEROUTER_PASSWORD=your_dashboard_password
```

> [!TIP]
> **Farming Token Harbor, TokenMix, or ElevenLabs?**  
> That's all you need! These platforms output native API keys (`thk_live_...`, `sk-tm-...`, and `xi-api-key`) and connect directly to cloud APIs. **No VPS, no local shim, and no port 8787 required.** You can start harvesting immediately!
> For ElevenLabs, email verification is performed automatically via `mail.tm` by default, or you can optionally configure `IMAP_USER`, `IMAP_PASSWORD`, and `IMAP_ENABLED=true` in `.env` for custom catch-all domains.

#### B. ZeroTwo-Specific Configuration (Requires Shim & Local/VPS Setup)
Because ZeroTwo uses Supabase JWTs and session cookies instead of standard API keys, it requires the OpenAI-compatible translation shim (`:8787`):

```env
# Base URL of the ZeroTwo shim (local laptop: http://127.0.0.1:8787/v1)
LLM_SHIM_BASE_URL=http://localhost:8787/v1

# Optional: If running 9Router & Shim 24/7 on a remote VPS (Setup B)
# LLM_REMOTE_SYNC=user@vps:/opt/llm-harvester/harvest/sessions.jsonl
```

*(Note: `.env` or `config.toml` is automatically loaded by `llm-harvester`)*.

### 3. Create & Harvest Accounts

#### A. Interactive TUI Menu (`./main.py`)
Run the terminal dashboard:
```bash
./main.py
```
Or use the CLI interactive prompt:
```bash
llm-harvester run
```
```text
Select farming target:
  [1] ZeroTwo      (app.zerotwo.ai)    -> JWT Session, Cookies, 9Router
  [2] Token Harbor (tokenharbor.ai)    -> API Key (thk_live_...), mail.tm
  [3] TokenMix     (tokenmix.ai)       -> API Key (sk-tm-...), mail.tm
  [4] ElevenLabs   (elevenlabs.io)     -> API Key (xi-api-key), mail.tm / IMAP
Choice [1-4] (default 1):
```

#### B. Direct Target Flag
```bash
# Farm 5 Token Harbor accounts (direct API keys -> 9Router + models synced)
llm-harvester run --target tokenharbor --count 5

# Farm 3 TokenMix accounts (direct API keys -> 9Router + models synced)
llm-harvester run --target tokenmix --count 3

# Farm 2 ElevenLabs accounts (10,000 free chars each -> 9Router + TTS models synced)
llm-harvester run --target elevenlabs --count 2

# Farm 2 ZeroTwo accounts (harvests sessions -> 9Router via shim)
llm-harvester run --target zerotwo --count 2
```

*(Note: `zt-harvester` alias is also available).*

### 4. Run the OpenAI-compatible shim (ZeroTwo ONLY)

> [!NOTE]
> **ZeroTwo only!** Token Harbor and TokenMix connect directly to their public cloud endpoints and register directly into 9Router without running any local shim. Only start the shim if you are harvesting or using **ZeroTwo**.

Start the local shim (automatically loads latest cookies & CSRF token from `harvest/sessions.jsonl`):

```bash
llm-harvester shim --port 8787
```

---

## ZeroTwo Architecture: Local Machine vs Remote Server (VPS)

> [!IMPORTANT]
> **This deployment section is strictly specific to ZeroTwo!**
> - **Token Harbor & TokenMix** run 100% standalone on your local machine without needing a VPS or shim server.
> - **ZeroTwo** requires the architectures below because it authenticates with Supabase JWT sessions and cookies, which must be served through the OpenAI-compatible shim (`:8787`).

You can run **ZeroTwo** in two primary setups:

### Setup A: Single-Machine Setup (All-in-One / Local Laptop) — No VPS Needed!

If you want to run everything on your **local machine (laptop)** without paying for or managing a VPS:
> **You do NOT need to push/SCP any files to a server!** Everything reads from and writes to the local machine directly.

- **9Router**: Running locally (`http://localhost:20128`)
- **Shim**: Running locally (`http://localhost:8787`)
- **Harvester**: Running locally on the same laptop

**Configuration (`.env` on laptop):**
```env
NINEROUTER_URL=http://localhost:20128
NINEROUTER_API_KEY=sk_9router
LLM_SHIM_BASE_URL=http://127.0.0.1:8787/v1
```

**Step-by-Step Flow:**
1. Start your local 9Router.
2. Start the ZeroTwo shim (via terminal or PM2):
   ```bash
   llm-harvester shim --port 8787
   # or via PM2:
   pm2 start "llm-harvester shim --port 8787" --name zt-shim
   ```
3. In 9Router dashboard, the ZeroTwo node Base URL is set to `http://127.0.0.1:8787/v1`.
4. Start your browser with CDP:
   ```bash
   google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
   ```
5. Run harvest:
   ```bash
   llm-harvester run --target zerotwo -n 2
   ```
   *The accounts are created, saved to `harvest/sessions.jsonl`, and automatically wired into your local 9Router. Zero upload, zero VPS needed!*

---

### Setup B: Split-Machine Setup (Laptop Harvester + Remote 24/7 VPS Server)

Use this setup to take advantage of your **laptop's residential ISP connection** (to easily pass Cloudflare turnstiles) while keeping the **ZeroTwo shim & 9Router online 24/7 on your VPS**:

- **Laptop**: Chrome CDP + Harvester.
- **VPS**: 9Router + ZeroTwo Shim (managed by systemd or PM2).
- **Auto-Sync**: When harvest finishes on laptop, it automatically SCP's `sessions.jsonl` to the VPS and updates 9Router.

**Configuration on Laptop (`.env`):**
```env
NINEROUTER_URL=https://nine.yourdomain.com
NINEROUTER_API_KEY=sk_...
NINEROUTER_PASSWORD=your_password
LLM_SHIM_BASE_URL=http://127.0.0.1:8787/v1
LLM_REMOTE_SYNC=user@vps:/opt/llm-harvester/harvest/sessions.jsonl
```

**Workflow:**
1. On your VPS, run the shim 24/7 using systemd or PM2 (see below).
2. On your VPS 9Router dashboard, set the `zerotwo` node Base URL to:
   ```text
   http://127.0.0.1:8787/v1
   ```
3. Whenever you want to harvest new accounts on your laptop:
   ```bash
   llm-harvester run --target zerotwo -n 2
   ```
   *Harvester will create accounts, register them into 9Router via API, and automatically SCP `sessions.jsonl` to your VPS.*

---

### Managing the ZeroTwo Shim with `systemd` or `pm2`

#### Option 1: Running with `systemd` (Recommended for Linux VPS)

Create `/etc/systemd/system/zt-shim.service`:

```ini
[Unit]
Description=ZeroTwo OpenAI Shim Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/llm-harvester
ExecStart=/opt/llm-harvester/.venv/bin/llm-harvester shim --port 8787
Restart=always
RestartSec=5
EnvironmentFile=/opt/llm-harvester/.env

[Install]
WantedBy=multi-user.target
```

Commands:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zt-shim
sudo systemctl status zt-shim
sudo journalctl -u zt-shim -f
```

#### Option 2: Running with `pm2` (Local Machine or VPS)

```bash
cd /path/to/llm-harvester

# Start with PM2
pm2 start "llm-harvester shim --port 8787" --name zt-shim

# Auto-start on reboot
pm2 save
pm2 startup

# Check status and logs
pm2 status
pm2 logs zt-shim
```

## CLI Reference

*(Note: `llm-harvester`, `llm-harvest`, and `zt-harvester` are available CLI entry points)*.

| Command | Purpose |
| --- | --- |
| `./main.py` | Launch interactive TUI Dashboard (Readiness diagnostic, 1-click harvester, WARP & proxies) |
| `llm-harvester run` | Interactive prompt to select target (ZeroTwo, Token Harbor, TokenMix, Grok xAI) |
| `llm-harvester run -t tokenharbor --direct` | Harvest Token Harbor using Direct Connection (clean local residential ISP, default) |
| `llm-harvester run -t tokenharbor --warp` | Harvest Token Harbor routing traffic through Cloudflare WARP (:10808) |
| `llm-harvester run -t tokenharbor --proxy-file proxies.txt` | Harvest Token Harbor routing through rotated proxy pool |
| `llm-harvester run -t tokenharbor -n 5` | Harvest 5 Token Harbor accounts & push keys + models to 9Router |
| `llm-harvester run -t tokenmix -n 3` | Harvest 3 TokenMix accounts & push keys + models to 9Router |
| `llm-harvester run -t zerotwo -n 2` | Harvest 2 ZeroTwo accounts & connect to 9Router via shim |
| `llm-harvester run -t zerotwo -n 5 -s user@vps:...` | Harvest ZeroTwo accounts and auto-upload ledger via SCP to remote VPS |
| `llm-harvester warp status` | Check status of local Cloudflare WARP proxy daemon (:10808) |
| `llm-harvester warp start` | Start sing-box WARP daemon on port 10808 (auto-registers if needed) |
| `llm-harvester warp stop` | Stop sing-box WARP daemon |
| `llm-harvester warp register` | Register a fresh Cloudflare WARP WireGuard profile via official REST API |
| `llm-harvester shim -p 8787` | Run the OpenAI-compatible ZeroTwo shim |
| `llm-harvester sync --target all` | Synchronize all harvested accounts & API keys into 9Router |
| `llm-harvester proxies --check` | List, auto-discover, and test the proxy pool |
| `llm-harvester export -f csv` | Export the harvest ledger |

## Cloudflare WARP & Proxy Pool

### 1. Cloudflare WARP (Recommended)
Cloudflare WARP provides a clean, legitimate edge IP (`hosting: false`) directly through Cloudflare's global network, preventing bot flags without needing third-party proxy subscriptions:

```bash
# Check status
llm-harvester warp status

# Start daemon
llm-harvester warp start

# Run harvest with WARP
llm-harvester run -t tokenharbor -n 1 --warp
```

### 2. Residential & Datacenter Proxy Pool
Spread per-IP rate limits by rotating exit IPs per account. The pool accepts `host:port:user:pass` or `http://user:pass@host:port` format:

```bash
# Inline proxies
llm-harvester run -n 10 --proxy "31.59.20.176:6754:user:pass"

# From a file (Auto-discovers proxies.txt, output/webshare_residential.txt, output/live_elite.txt)
llm-harvester run -n 10 --proxy-file proxies.txt

# Verify reachability + exit IPs
llm-harvester proxies --check
```

## Python API

```python
import asyncio
from llmharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## Configuration

Copy `config.example.toml` and `env.example`:

```bash
cp config.example.toml config.toml
cp .env.example .env
llm-harvester run -n 3 --config config.toml
```

Every field is documented inline in `config.example.toml`.

## Test

```bash
pip install -e ".[dev]"
pytest -q
```

## Project layout

```
src/llmharvester/
  warp.py              Cloudflare WARP WireGuard & sing-box daemon manager
  webshare_hunter.py   Webshare residential IP hunter with AI audio solver
  grok_farm.py         Grok xAI automated account creator
  tokenharbor.py       Token Harbor registration & API key harvester
  tokenmix.py          TokenMix registration & API key harvester
  zerotwo.py           ZeroTwo sign-up & Supabase JWT interceptor
  browser.py           CDP browser controller & proxy router
  browser_utils.py     Chromium/Brave locator & environment setup
  cdp.py               Chrome DevTools Protocol (CDP) client & native typing
  proxy.py             Proxy pool with auto-discovery & rotation
  proxy_bridge.py      Local bridge for authenticated Chromium proxies
  router9.py           9Router API integration & model catalog sync
  shim.py              OpenAI-compatible protocol bridge
  mail.py              mail.tm disposable email client
  engine.py            Concurrent orchestration & ledger management
  config.py            Configuration models
  cli.py               Typer CLI entrypoint
main.py                Interactive TUI terminal dashboard
tests/                 Unit and integration tests
output/                Generated proxy outputs and WARP configs
harvest/               Harvested session ledgers (JSONL)

## Requirements

- Python 3.10+
- A Chromium reachable over CDP (local debug port or a cloud browser)
- A running [9Router](https://9router.com) instance (default `http://localhost:20128`)

## Notes

- ZeroTwo's edge requires the `cf_clearance` cookie and a CSRF token in addition to the JWT; export them to the shim once.
- The shim keeps a single process serving every harvested account — the JWT is read per request from `Authorization`.
- Both ZeroTwo and mail.tm apply per-IP and per-address rate limits. Keep `--concurrency` low (1–2), space out runs, and let the built-in retries handle transient `429`s.
- Use responsibly and only on accounts you are authorised to create.

## License

MIT — see [LICENSE](LICENSE).

<div align="center"><sub>Built for the 9Router ecosystem · not affiliated with ZeroTwo or 9Router</sub></div>
