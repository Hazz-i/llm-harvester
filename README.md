<div align="center">

<img src="assets/logo.png" width="140" alt="zt-farming logo">

# zt-farming

**Bulk ZeroTwo account creator · session / token / cookie harvester · 9Router auto-connect**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Create ZeroTwo accounts in bulk, harvest their JWT session, cookies and CSRF token, and wire every account into [9Router](https://9router.com) as an OpenAI-compatible provider — end to end.*

[English](README.md) · [Bahasa Indonesia](docs/README.id.md) · [Español](docs/README.es.md) · [日本語](docs/README.ja.md) · [中文](docs/README.zh.md) · [Français](docs/README.fr.md)

</div>

---

## What it does

1. **Creates** N ZeroTwo accounts automatically, each with a disposable mailbox from a mail.tm-compatible provider.
2. **Verifies** the magic link and walks the onboarding wizard (name, interests).
3. **Harvests** the Supabase JWT `access_token`, `refresh_token`, the full cookie jar (incl. `cf_clearance` / `__csrf`), the CSRF token, the account profile, and the complete model catalog.
4. **Connects** every harvested session into **9Router** as an OpenAI-compatible provider connection, so all accounts are reachable through one `/v1` endpoint.
5. **Bridges the protocol gap** with a built-in OpenAI-compatible shim, because ZeroTwo's own API is not OpenAI-shaped.

Everything is written to a crash-safe JSONL ledger you can resume, export or audit.

## Architecture

```
                 +-------------------+        magic link         +------------------+
   create -----> |  mail.tm mailbox  | <------------------------ |                  |
                 +-------------------+                           |                  |
                                                               |   ZeroTwo web /  |
                 +-------------------+     CDP automation        |   API endpoints  |
   drive  ----> |  Chromium (CDP)   | ------------------------> |                  |
                 +-------------------+                           +------------------+
                                                                         |
                               harvest JWT + cookies + csrf               |
                 +-------------------+ <---------------------------------+
                 |     Harvester     |
                 +---------+---------+
                           |
              +------------+-------------+
              |                          |
      +-------v-------+         +--------v---------+
      |  sessions.jsonl|         |  OpenAI shim     |
      +---------------+         |  (port 8787)     |
                                +--------+---------+
                                         |
                                +--------v---------+
                                |     9Router      |
                                |   :20128 /v1     |
                                +------------------+
```

## Install

```bash
git clone https://github.com/Hazz-i/zt-farming.git
cd zt-farming
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

### 2. Configure `.env`

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Set your configuration:
```env
ZT_CDP_WS=ws://127.0.0.1:9222/devtools/browser/<id>
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
# If your 9Router instance is password-protected (dashboard auth):
NINEROUTER_PASSWORD=your_dashboard_password
ZT_SHIM_BASE_URL=http://localhost:8787/v1
```

*(Note: `.env` is automatically loaded by `zt-farming`)*.

### 3. Create, harvest, and connect accounts

```bash
zt-farming run --count 1
```

Every account lands in `harvest/sessions.jsonl`. The tool automatically:
- Registers the ZeroTwo node in 9Router.
- Registers all 160+ harvested AI models into 9Router (`zerotwo/<model_id>`).
- Connects each harvested account credential into 9Router.

### 4. Run the OpenAI-compatible shim & connect to 9Router

Start the local shim (automatically loads latest cookies & CSRF token from `harvest/sessions.jsonl`):

```bash
zt-farming shim --port 8787
```

---

## Deployment Architectures

You can run `zt-farming` and `9Router` in two primary setups:

### Setup A: Single-Machine Setup (All-in-One / 1 Mesin) — No Push Needed!

If `zt-farming` runs on the **same machine** as `9Router`:
> **You do NOT need to push/SCP any files to a server!** Everything reads from and writes to the local machine directly.

#### A.1 Running Everything on Local Machine (Laptop)
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
2. Start the shim (via terminal or PM2):
   ```bash
   zt-farming shim --port 8787
   # atau via PM2:
   pm2 start "zt-farming shim --port 8787" --name zt-shim
   ```
3. In 9Router dashboard, set the ZeroTwo node Base URL to:
   ```text
   http://127.0.0.1:8787/v1
   ```
4. Start your browser with CDP:
   ```bash
   google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
   ```
5. Run harvest:
   ```bash
   zt-farming run -n 2
   ```
   *The accounts are created, saved to `harvest/sessions.jsonl`, and automatically wired into your local 9Router. Zero upload, zero tunnel needed!*

#### A.2 Running Everything on VPS (Server Only)
- **9Router**: Running on VPS
- **Shim**: Running on VPS (via systemd or PM2)
- **Harvester**: Running on VPS (requires headless Chromium + residential proxy pool)
- **Flow**: Everything operates locally on the VPS file system and loopback network. Node Base URL in 9Router is `http://127.0.0.1:8787/v1`.

---

### Setup B: Split-Machine Setup (Laptop Harvester + Remote VPS 9Router/Shim)

Use this setup to take advantage of your **laptop's residential ISP connection** (to easily pass Cloudflare turnstiles) while keeping the **shim & 9Router online 24/7 on your VPS**:

- **Laptop**: Chrome CDP + Harvester.
- **VPS**: 9Router + Shim (managed by systemd or PM2).
- **Auto-Sync**: When harvest finishes on laptop, it automatically SCP's `sessions.jsonl` to the VPS and updates 9Router.

**Configuration on Laptop (`.env`):**
```env
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
NINEROUTER_PASSWORD=your_password
ZT_SHIM_BASE_URL=http://127.0.0.1:8787/v1
ZT_REMOTE_SYNC=user@vps:/opt/zt-farming/harvest/sessions.jsonl
```

**Workflow:**
1. On your VPS, run the shim 24/7 using systemd or PM2 (see below).
2. On your VPS 9Router dashboard, set the `zerotwo` node Base URL to:
   ```text
   http://127.0.0.1:8787/v1
   ```
3. Whenever you want to harvest new accounts on your laptop:
   ```bash
   zt-farming run -n 2
   ```
   *Harvester will create accounts, register them into 9Router via API, and automatically SCP `sessions.jsonl` to your VPS.*

---

### Managing the Shim with `systemd` or `pm2`

#### Option 1: Running with `systemd` (Recommended for Linux)

Create `/etc/systemd/system/zt-shim.service`:

```ini
[Unit]
Description=ZeroTwo OpenAI Shim Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/zt-farming
ExecStart=/opt/zt-farming/.venv/bin/zt-farming shim --port 8787
Restart=always
RestartSec=5
EnvironmentFile=/opt/zt-farming/.env

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
cd /path/to/zt-farming

# Start with PM2
pm2 start "zt-farming shim --port 8787" --name zt-shim

# Auto-start on reboot
pm2 save
pm2 startup

# Check status and logs
pm2 status
pm2 logs zt-shim
```

## CLI

*(Note: `zt-harvester` is also retained as an alias for backwards compatibility)*.

| Command | Purpose |
| --- | --- |
| `zt-farming run -n 5` | Create + harvest + connect N accounts |
| `zt-farming run -n 5 -s user@vps:/path/sessions.jsonl` | Harvest and auto-upload to remote VPS |
| `zt-farming shim -p 8787` | Run the OpenAI-compatible ZeroTwo shim |
| `zt-farming sync` | Synchronize active sessions into 9Router |
| `zt-farming proxies --check` | List and test the proxy pool |
| `zt-farming export -f csv` | Export the harvest ledger |

## Proxy pool

Spread the per-IP rate limits by rotating the exit IP per account. The pool
accepts the common `host:port:user:pass` format.

```bash
# inline
zt-farming run -n 10 --proxy "31.59.20.176:6754:user:pass" --proxy "45.38.107.97:6014:user:pass"

# from a file
zt-farming run -n 10 --proxy-file proxies.txt

# verify reachability + exit IPs
zt-farming proxies --proxy-file proxies.txt --check
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
