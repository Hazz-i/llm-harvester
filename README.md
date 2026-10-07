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

1. **Multi-Target Farming**: Supports **ZeroTwo** (`app.zerotwo.ai`), **Token Harbor** (`tokenharbor.ai`), and **TokenMix** (`tokenmix.ai`) with interactive CLI selection or direct flag.
2. **Automated Provisioning**: Automatically registers accounts using disposable mailboxes from `mail.tm`.
3. **Turnstile & Verification**: Automatically handles Cloudflare Turnstile anti-bot challenges and clicks verification email links or enters OTP codes.
4. **Credential Harvesting & 9Router Auto-Connect**:
   - **ZeroTwo**: Extracts Supabase JWTs (`access_token`, `refresh_token`), cookies (`cf_clearance`, `__csrf`), CSRF tokens, and registers into **9Router** via a local OpenAI shim.
   - **Token Harbor**: Generates `thk_live_...` API keys, extracts/syncs model IDs, and auto-registers into **9Router** as a native OpenAI-compatible provider node.
   - **TokenMix**: Generates `sk-tm-...` API keys, extracts/syncs model IDs, and auto-registers into **9Router** as a native OpenAI-compatible provider node.
5. **Ledger Output**: Writes crash-safe, append-only JSONL files (`sessions.jsonl`, `tokenharbor_keys.jsonl`, `tokenmix_keys.jsonl`).

## Architecture

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       llm-harvester Architecture                                       │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘

              [1] Disposable Mailbox Provisioning          [2] Browser Automation & Bot Bypass
           ┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
           │          mail.tm REST API            │     │       Chromium / Chrome (CDP :9222)  │
           │    (Temp Email, Link & OTP Polling)  │     │     (Cloudflare Turnstile Bypass)    │
           └──────────────────┬───────────────────┘     └──────────────────┬───────────────────┘
                              │                                            │
                              ▼                                            ▼
           ┌───────────────────────────────────────────────────────────────────────────────────┐
           │                              llm-harvester CLI Engine                             │
           │                      (Interactive Selector or --target Flag)                      │
           └──────────────┬─────────────────────────┬──────────────────────────┬───────────────┘
                          │                         │                          │
        [Target: zerotwo] │     [Target: tokenharbor]│        [Target: tokenmix]│
                          ▼                         ▼                          ▼
               ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
               │    ZeroTwoCreator     │ │  TokenHarborCreator   │ │    TokenMixCreator    │
               │   (app.zerotwo.ai)    │ │   (tokenharbor.ai)    │ │    (tokenmix.ai)      │
               └──────────┬────────────┘ └──────────┬────────────┘ └───────────┬───────────┘
                          │                         │                          │
                          │ Harvests Supabase JWT,  │ Harvests API Key         │ Harvests API Key
                          │ Cookies & CSRF Token    │ (thk_live_...)           │ (sk-tm-...)
                          ▼                         ▼                          ▼
               ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
               │ harvest/              │ │ harvest/              │ │ harvest/              │
               │ sessions.jsonl        │ │ tokenharbor_keys.jsonl│ │ tokenmix_keys.jsonl   │
               └──────────┬────────────┘ └──────────┬────────────┘ └───────────┬───────────┘
                          │                         │                          │
             Via Shim     │                         │ Direct OpenAI Node       │ Direct OpenAI Node
             & SSE        │                         │ + Model Catalog Sync     │ + Model Catalog Sync
                          ▼                         ▼                          ▼
               ┌───────────────────────┐ ┌─────────────────────────────────────────────────┐
               │  OpenAI Shim (:8787)  │ │      Native OpenAI Provider Nodes (9Router)     │
               └──────────┬────────────┘ └─────────────────────────┬───────────────────────┘
                          │                                        │
                          └───────────────────┬────────────────────┘
                                              ▼
                                 ┌─────────────────────────┐
                                 │   9Router AI Gateway    │
                                 │  (Multi-Account Pooling)│
                                 └─────────────────────────┘
```

### Architecture Flow Explained

1. **Disposable Mailbox (`mail.tm`)**:
   Automatically provisions disposable mailboxes on-demand via the `mail.tm` REST API (`POST /accounts`). It polls incoming messages to extract verification magic links (ZeroTwo), account confirmation links (Token Harbor), or OTP verification codes (TokenMix) without needing third-party webmail browser tabs.

2. **Browser Automation via CDP (`:9222`)**:
   Controls a real Chromium, Google Chrome, or Brave Browser session via the **Chrome DevTools Protocol (CDP)** (`:9222`). This bypasses Cloudflare Turnstile anti-bot challenges natively, handles dynamic form wizards, and enables live extraction of cookies, local storage, and authentication tokens.

3. **Multi-Target Creators**:
   - **`ZeroTwoCreator`**: Automates sign-up at `app.zerotwo.ai`, follows the email magic link, completes the onboarding wizard, and intercepts Supabase JWT tokens (`access_token`, `refresh_token`), session cookies (`cf_clearance`, `__csrf`), and CSRF tokens.
   - **`TokenHarborCreator`**: Automates registration at `tokenharbor.ai`, verifies the account via the confirmation URL received from `mail.tm`, logs in, navigates to the API keys management page, and creates/extracts a production API key (`thk_live_...`).
   - **`TokenMixCreator`**: Automates registration at `tokenmix.ai`, solves Cloudflare Turnstile via CDP, verifies email via `mail.tm`, navigates to dashboard API keys, and creates/extracts an API key (`sk-tm-...`).

4. **Dedicated Ledgers**:
   Stores harvested credentials in append-only, crash-safe JSONL ledger files:
   - `harvest/sessions.jsonl` (ZeroTwo sessions)
   - `harvest/tokenharbor_keys.jsonl` (Token Harbor API keys)
   - `harvest/tokenmix_keys.jsonl` (TokenMix API keys)

5. **Direct 9Router Integration & Model Catalog Sync**:
   - **ZeroTwo**: Registers an OpenAI-compatible node with `baseUrl: http://localhost:8787/v1` backed by the local shim, mapping exclusive ZeroTwo models (`gpt-6-luna`, `deepseek-v4.1-flash`, etc.).
   - **Token Harbor**: Directly creates an OpenAI provider node in 9Router (`baseUrl: https://tokenharbor.ai/v1`, prefix: `tokenharbor`), registers harvested API keys as connection accounts, and automatically syncs all 20+ model IDs (`claude-opus-5.5`, `gpt-6-astra`, `deepseek-v3`, etc.).
   - **TokenMix**: Directly creates an OpenAI provider node in 9Router (`baseUrl: https://api.tokenmix.ai/v1`, prefix: `tokenmix`), registers harvested API keys as connection accounts, and automatically syncs all 22+ model IDs (`gpt-4o`, `deepseek-v4`, `gemini-2.5-flash`, etc.).



## Install

```bash
git clone https://github.com/Hazz-i/llm-harvester.git
cd llm-harvester
pip install -e ".[shim]"
```

## Quickstart

### 1. Launch a browser with remote debugging (CDP)

Launch Chromium, Google Chrome, or Brave Browser with debugging enabled:

```bash
# Brave
brave-browser --remote-debugging-port=9222 --user-data-dir=./chrome-data

# Or Google Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

Get your WebSocket debugger URL via `curl -s http://127.0.0.1:9222/json/version`.

### 2. Configure `.env` or `config.toml`

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

#### A. General Configuration (Token Harbor, TokenMix & ZeroTwo)
These settings are used across all platforms:

```env
# Browser CDP (Local Chromium/Chrome/Brave on port 9222)
ZT_CDP_WS=ws://127.0.0.1:9222/devtools/browser/<id>

# 9Router AI Gateway (Local http://localhost:20128 or Remote https://nine.yourdomain.com)
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
# If your 9Router instance is password-protected (dashboard auth):
NINEROUTER_PASSWORD=your_dashboard_password
```

> [!TIP]
> **Farming Token Harbor or TokenMix?**  
> That's all you need! Both platforms output native OpenAI-compatible API keys (`thk_live_...` and `sk-tm-...`) and connect directly to cloud APIs. **No VPS, no local shim, and no port 8787 required.** You can start harvesting immediately!

#### B. ZeroTwo-Specific Configuration (Requires Shim & Local/VPS Setup)
Because ZeroTwo uses Supabase JWTs and session cookies instead of standard API keys, it requires the OpenAI-compatible translation shim (`:8787`):

```env
# Base URL of the ZeroTwo shim (local laptop: http://127.0.0.1:8787/v1)
ZT_SHIM_BASE_URL=http://localhost:8787/v1

# Optional: If running 9Router & Shim 24/7 on a remote VPS (Setup B)
# ZT_REMOTE_SYNC=user@vps:/opt/llm-harvester/harvest/sessions.jsonl
```

*(Note: `.env` or `config.toml` is automatically loaded by `llm-harvester`)*.

### 3. Create & Harvest Accounts

#### A. Interactive Selection (Prompt)
Simply run without arguments to choose interactively:
```bash
llm-harvester run
```
```text
Target platform farming:
  [1] ZeroTwo (Browser CDP + Mail.tm -> 9Router)
  [2] Token Harbor (Mail.tm + thk_live_... API key)
  [3] TokenMix (Browser CDP + Mail.tm + sk-tm-... API key)
Choice [1-3] (default 1):
```

#### B. Direct Target Flag
```bash
# Farm 5 Token Harbor accounts (direct API keys -> 9Router + models synced)
llm-harvester run --target tokenharbor --count 5

# Farm 3 TokenMix accounts (direct API keys -> 9Router + models synced)
llm-harvester run --target tokenmix --count 3

# Farm 2 ZeroTwo accounts (harvests sessions -> 9Router via shim)
llm-harvester run --target zerotwo --count 2
```

*(Note: `zt-harvester` and `zt-farming` aliases are also available).*

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
ZT_SHIM_BASE_URL=http://127.0.0.1:8787/v1
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
ZT_SHIM_BASE_URL=http://127.0.0.1:8787/v1
ZT_REMOTE_SYNC=user@vps:/opt/llm-harvester/harvest/sessions.jsonl
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

*(Note: `zt-harvester` and `zt-farming` are also retained as aliases for backwards compatibility)*.

| Command | Purpose |
| --- | --- |
| `llm-harvester run` | Interactive prompt to select target (ZeroTwo, Token Harbor, or TokenMix) |
| `llm-harvester run -t tokenharbor -n 5` | Harvest 5 Token Harbor accounts & push keys + models to 9Router |
| `llm-harvester run -t tokenmix -n 3` | Harvest 3 TokenMix accounts & push keys + models to 9Router |
| `llm-harvester run -t zerotwo -n 2` | Harvest 2 ZeroTwo accounts & connect to 9Router via shim |
| `llm-harvester run -t zerotwo -n 5 -s user@vps:...` | Harvest ZeroTwo accounts and auto-upload ledger via SCP to remote VPS |
| `llm-harvester shim -p 8787` | Run the OpenAI-compatible ZeroTwo shim |
| `llm-harvester sync --target all` | Synchronize all harvested accounts & API keys into 9Router |
| `llm-harvester proxies --check` | List and test the proxy pool |
| `llm-harvester export -f csv` | Export the harvest ledger |

## Proxy pool

Spread the per-IP rate limits by rotating the exit IP per account. The pool
accepts the common `host:port:user:pass` format.

```bash
# inline
llm-harvester run -n 10 --proxy "31.59.20.176:6754:user:pass" --proxy "45.38.107.97:6014:user:pass"

# from a file
llm-harvester run -n 10 --proxy-file proxies.txt

# verify reachability + exit IPs
llm-harvester proxies --proxy-file proxies.txt --check
```

Proxies are applied to:

- the harvester's own HTTP calls (mail.tm, 9Router) — via `httpx`;
- a locally launched Chromium — via `--proxy-server=<url>`.

> Cloud browsers created by the Browser Use API only accept a
> `proxy_country_code`, not a custom proxy URL, so a pool is used with a local
> Chromium launch (mode `cdp` without `--cdp-ws`/`--cdp-url`). Some reseller
> pools restrict access to a whitelisted source IP — verify with
> `zt-farming proxies --check` before a long run.

Set `ZT_PROXIES` (newline/comma separated) or `ZT_PROXY_FILE` to configure the
pool through the environment.

## Python API

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

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
zt-farming run -n 3 --config config.toml
```

Every field is documented inline in `config.example.toml`.

## Test

```bash
pip install -e ".[dev]"
pytest -q
```

## Project layout

```
src/ztharvester/
  mail.py      mail.tm-compatible disposable mailbox client
  zerotwo.py   sign-up / magic-link / onboarding driver + harvester
  cdp.py       CDP adapters (local websocket, in-process bridge, cloud)
  router9.py   9Router provider-management API client
  shim.py      OpenAI-compatible <-> ZeroTwo protocol bridge
  engine.py    concurrent orchestration + resumable JSONL ledger
  config.py    configuration models
  cli.py       command line interface
tests/
docs/          6 translated READMEs
assets/        logo
```

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
