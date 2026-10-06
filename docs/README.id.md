<div align="center">

# zt-farming

**Pembuat akun ZeroTwo massal · harvester session / token / cookie · koneksi otomatis 9Router**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Buat akun ZeroTwo secara massal, ambil sesi JWT, cookie dan token CSRF-nya, lalu hubungkan setiap akun ke [9Router](https://9router.com) sebagai provider yang kompatibel dengan OpenAI — dari awal sampai akhir.*

[English](../README.md) · [Bahasa Indonesia](README.id.md) · [Español](README.es.md) · [日本語](README.ja.md) · [中文](README.zh.md) · [Français](README.fr.md)

</div>

---

## Apa yang dilakukannya

1. **Membuat** N akun ZeroTwo secara otomatis, masing-masing dengan email sekali pakai dari penyedia kompatibel mail.tm.
2. **Memverifikasi** tautan ajaib (magic link) dan menyelesaikan wizard onboarding (nama, minat).
3. **Mengambil** JWT Supabase `access_token`, `refresh_token`, seluruh cookie (termasuk `cf_clearance` / `__csrf`), token CSRF, profil akun, dan katalog model lengkap.
4. **Menghubungkan** setiap sesi hasil panen ke **9Router** sebagai koneksi provider yang kompatibel dengan OpenAI, sehingga semua akun dapat diakses lewat satu endpoint `/v1`.
5. **Menjembatani** perbedaan protokol dengan shim bawaan yang kompatibel dengan OpenAI, karena API ZeroTwo sendiri tidak berbentuk OpenAI.

## Arsitektur

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Arsitektur zt-farming                            │
└─────────────────────────────────────────────────────────────────────────────┘

       [1] Create Mailbox                 [2] Drive Web Automation
    ┌───────────────────────┐            ┌───────────────────────┐
    │  mail.tm REST API     │            │  Chromium (CDP :9222) │
    │  (Disposable Mailbox) │            │  (Bypass Turnstile)   │
    └──────────┬────────────┘            └───────────┬───────────┘
               │                                     │
               │ Menerima Magic Link                 │ Otomasi Sign-up & Wizard
               ▼                                     ▼
    ┌────────────────────────────────────────────────────────────┐
    │             Platform ZeroTwo (app.zerotwo.ai)              │
    └──────────────────────────────┬─────────────────────────────┘
                                   │
                                   │ [3] Panen JWT, Cookie & CSRF
                                   ▼
    ┌────────────────────────────────────────────────────────────┐
    │                   Harvester Engine (CLI)                   │
    └──────────────┬───────────────────────────────┬─────────────┘
                   │                               │
        Menyimpan  │                     Daftarkan │ Node & Kredensial
        ke Ledger  ▼                       via API ▼
    ┌───────────────────────┐            ┌───────────────────────┐
    │ harvest/              │◄───────────│ OpenAI Shim (:8787)   │
    │ sessions.jsonl        │ Baca live  │ (Dynamic Auth & SSE)  │
    └───────────────────────┘ sessions   └───────────▲───────────┘
                                                     │
                                            Proxy    │ Chat Completions
                                            Request  │ (:20128 /v1)
                                                     ▼
                                         ┌───────────────────────┐
                                         │ AI Gateway 9Router    │
                                         └───────────────────────┘
```

### Penjelasan Alur Arsitektur

- **`create` (mail.tm mailbox)**:  
  Harvester secara otomatis **membuat** kotak email sementara sekali pakai melalui REST API `mail.tm` (`POST /accounts`). Email ini digunakan saat mendaftar ZeroTwo untuk menerima *magic link* verifikasi pendaftaran dan mengecek inbox secara otomatis.
- **`drive` (Chromium CDP)**:  
  Karena antarmuka ZeroTwo dilindungi oleh Cloudflare Turnstile (anti-bot) dan memiliki tahap formulir wizard, permintaan HTTP biasa akan langsung diblokir (403/Turnstile). Harvester **"menyetir" / mengendalikan (drive)** browser Chromium/Chrome/Brave asli lewat protokol **Chrome DevTools Protocol (CDP)** (`:9222`) untuk:
  1. Membuka web ZeroTwo (`app.zerotwo.ai`) dan mengetikkan email pendaftaran.
  2. Mengarahkan browser membuka URL verifikasi *magic link* dari inbox email.
  3. Menyelesaikan formulir onboarding (nama dan minat).
  4. Menyadap dan mengekstrak token Supabase JWT (`access_token`, `refresh_token`), cookie (`cf_clearance`, `__csrf`), dan token CSRF langsung dari sesi browser aktif.
- **Harvester**:  
  Mengorkestrasi seluruh siklus panen, menyimpan akun ke `harvest/sessions.jsonl`, dan mendaftarkan provider node serta kredensial ke 9Router melalui API.
- **OpenAI Shim (`:8787`)**:  
  Menerjemahkan request standar OpenAI `/v1/chat/completions` ke protokol internal ZeroTwo, serta memperbarui token JWT secara otomatis jika mendekati waktu kedaluwarsa.
- **9Router (`:20128`)**:  
  Pintu gerbang terpadu untuk membagi beban chat completion ke seluruh akun yang tersedia melalui shim.

## Instalasi

```bash
git clone https://github.com/Hazz-i/zt-farming.git
cd zt-farming
pip install -e ".[shim]"
```

## Mulai Cepat

### 1. Jalankan browser dengan remote debugging (CDP)

Jalankan Chromium, Google Chrome, atau Brave Browser dengan port debugging aktif:

```bash
# Brave Browser
brave-browser --remote-debugging-port=9222 --user-data-dir=./chrome-data

# Atau Google Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

Dapatkan URL WebSocket debugger lewat: `curl -s http://127.0.0.1:9222/json/version`.

### 2. Konfigurasi `.env`

Salin `.env.example` ke `.env`:

```bash
cp .env.example .env
```

Sesuaikan isi file `.env`:
```env
ZT_CDP_WS=ws://127.0.0.1:9222/devtools/browser/<id>
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
# Jika instance 9Router Anda diproteksi password (login dashboard):
NINEROUTER_PASSWORD=password_dashboard_anda
ZT_SHIM_BASE_URL=http://localhost:8787/v1
```

*(Catatan: File `.env` otomatis dimuat oleh `zt-farming`)*.

### 3. Buat, panen, dan daftarkan akun

```bash
zt-farming run --count 1
```

Setiap akun akan tersimpan di `harvest/sessions.jsonl`. Alat ini otomatis:
- Mendaftarkan node ZeroTwo di 9Router.
- Mendaftarkan seluruh 160+ model AI yang dipanen ke 9Router (`zerotwo/<model_id>`).
- Menghubungkan akun hasil panen ke 9Router.

### 4. Jalankan shim kompatibel OpenAI & sambungkan ke 9Router

Jalankan shim lokal (otomatis membaca cookie & CSRF token terbaru dari `harvest/sessions.jsonl`):

```bash
zt-farming shim --port 8787
```

---

## Pilihan Arsitektur Deployment

Anda bisa menjalankan `zt-farming` dan `9Router` dalam dua skenario utama:

### Skenario A: 1 Mesin (Single-Machine / All-in-One) — TIDAK PERLU Push/Upload!

Jika `zt-farming` berjalan di **mesin yang sama** dengan `9Router`:
> **Anda TIDAK PERLU melakukan upload/SCP/push ke server sama sekali!** Seluruh file dibaca dan ditulis langsung di mesin lokal tersebut.

#### A.1 Semua Berjalan di Komputer Lokal (Laptop)
- **9Router**: Berjalan lokal (`http://localhost:20128`)
- **Shim**: Berjalan lokal (`http://localhost:8787`)
- **Harvester**: Berjalan lokal di laptop yang sama

**Konfigurasi (`.env` di laptop):**
```env
NINEROUTER_URL=http://localhost:20128
NINEROUTER_API_KEY=sk_9router
ZT_SHIM_BASE_URL=http://127.0.0.1:8787/v1
```

**Alur Langkah-demi-Langkah:**
1. Jalankan 9Router lokal Anda.
2. Jalankan shim (via terminal atau PM2):
   ```bash
   zt-farming shim --port 8787
   # atau via PM2:
   pm2 start "zt-farming shim --port 8787" --name zt-shim
   ```
3. Di dasbor 9Router lokal, atur Base URL node ZeroTwo menjadi:
   ```text
   http://127.0.0.1:8787/v1
   ```
4. Buka browser dengan CDP:
   ```bash
   google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
   ```
5. Jalankan panen:
   ```bash
   zt-farming run -n 2
   ```
   *Akun langsung dibuat, tersimpan di `harvest/sessions.jsonl`, dan otomatis terdaftar ke 9Router lokal Anda. Tanpa upload, tanpa Cloudflare Tunnel!*

#### A.2 Semua Berjalan di Server (VPS Saja)
- **9Router**: Berjalan di VPS
- **Shim**: Berjalan di VPS (via systemd atau PM2)
- **Harvester**: Berjalan di VPS (membutuhkan Chromium headless + residential proxy pool)
- **Alur**: Semua bekerja lokal di filesystem dan jaringan loopback VPS. Base URL di 9Router adalah `http://127.0.0.1:8787/v1`.

---

### Skenario B: 2 Mesin (Laptop Harvester + Remote VPS 9Router/Shim)

Gunakan skenario ini untuk memanfaatkan **koneksi internet rumahan laptop Anda** (agar lolos verifikasi bot Cloudflare Turnstile tanpa proxy mahal), sementara **shim & 9Router tetap online 24/7 di VPS**:

- **Laptop**: Chrome CDP + Harvester.
- **VPS**: 9Router + Shim (dikelola oleh systemd atau PM2).
- **Auto-Sync**: Begitu selesai panen di laptop, file `sessions.jsonl` otomatis terkirim via SCP ke VPS dan kredensial langsung terhubung ke 9Router.

**Konfigurasi di Laptop (`.env`):**
```env
NINEROUTER_URL=https://nine.hazz.biz.id
NINEROUTER_API_KEY=sk_...
NINEROUTER_PASSWORD=password_dasbor_anda
ZT_SHIM_BASE_URL=http://127.0.0.1:8787/v1
ZT_REMOTE_SYNC=user@ip-vps:/opt/zt-farming/harvest/sessions.jsonl
```

**Alur Langkah-demi-Langkah:**
1. Di VPS, jalankan shim 24/7 menggunakan systemd atau PM2 (lihat panduan di bawah).
2. Di dasbor 9Router VPS Anda, atur Base URL node `zerotwo` ke:
   ```text
   http://127.0.0.1:8787/v1
   ```
3. Kapan pun Anda ingin panen akun baru di laptop:
   ```bash
   zt-farming run -n 2
   ```
   *Harvester akan membuat akun, mendaftarkannya ke 9Router via API, dan otomatis mengirim file `sessions.jsonl` ke VPS Anda.*

---

### Mengelola Shim dengan `systemd` atau `pm2`

#### Opsi 1: Menjalankan dengan `systemd` (Rekomendasi Linux)

Buat file unit service `/etc/systemd/system/zt-shim.service`:

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

Perintah:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zt-shim
sudo systemctl status zt-shim
sudo journalctl -u zt-shim -f
```

#### Opsi 2: Menjalankan dengan `pm2` (Lokal atau VPS)

```bash
cd /path/to/zt-farming

# Jalankan dengan PM2
pm2 start "zt-farming shim --port 8787" --name zt-shim

# Otomatis hidup saat sistem reboot
pm2 save
pm2 startup

# Cek status dan log
pm2 status
pm2 logs zt-shim
```

---

## CLI

*(Catatan: Perintah `zt-harvester` tetap didukung sebagai alias)*.

| Perintah | Fungsi |
| --- | --- |
| `zt-farming run -n 5` | Buat + panen + hubungkan N akun |
| `zt-farming run -n 5 -s user@vps:/path/sessions.jsonl` | Panen akun dan otomatis upload ke server VPS |
| `zt-farming shim -p 8787` | Jalankan shim ZeroTwo kompatibel OpenAI |
| `zt-farming sync` | Sinkronisasi session aktif langsung ke 9Router |
| `zt-farming proxies --check` | Daftar & uji pool proxy |
| `zt-farming export -f csv` | Ekspor ledger panen |

## Pool Proxy

Sebarkan batas rate per-IP dengan memutar IP keluar tiap akun. Pool menerima format umum `host:port:user:pass`.

```bash
zt-farming run -n 10 --proxy-file proxies.txt
zt-farming proxies --proxy-file proxies.txt --check
```

## API Python

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## Konfigurasi

Salin `config.example.toml` dan `.env.example`:

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-farming run -n 3 --config config.toml
```

Semua kolom terdokumentasi langsung di dalam `config.example.toml`.

## Pengujian

```bash
pip install -e ".[dev]"
pytest -q
```

## Struktur proyek

```
src/ztharvester/
  mail.py      Klien email sekali pakai kompatibel mail.tm
  zerotwo.py   Driver pendaftaran / magic-link / onboarding + harvester
  cdp.py       Adapter CDP (websocket lokal, bridge dalam proses, cloud)
  router9.py   Klien API manajemen provider 9Router
  shim.py      Jembatan protokol OpenAI-kompatibel <-> ZeroTwo
  engine.py    Orkestrasi konkuren + ledger JSONL yang dapat dilanjutkan
  config.py    Model konfigurasi
  cli.py       Antarmuka baris perintah
tests/
docs/          6 translated READMEs
assets/        logo
```

## Kebutuhan

- Python 3.10+
- Chromium yang dapat diakses via CDP (port debug lokal atau browser cloud)
- Instance [9Router](https://9router.com) yang berjalan (default `http://localhost:20128`)

## Catatan

- Edge ZeroTwo memerlukan cookie `cf_clearance` dan token CSRF selain JWT; ekspor keduanya ke shim sekali saja.
- Shim menjalankan satu proses yang melayani setiap akun hasil panen — JWT dibaca per permintaan dari `Authorization`.
- Gunakan secara bertanggung jawab dan hanya pada akun yang sah Anda buat.
- Ratelimit per-IP/per-alamat berlaku di ZeroTwo dan mail.tm. Jaga `--concurrency` tetap rendah (1–2), beri jeda, dan biarkan retry menangani `429` sementara.

## License

MIT — lihat [LICENSE](LICENSE).

<div align="center"><sub>Dibuat untuk ekosistem 9Router · tidak berafiliasi dengan ZeroTwo atau 9Router</sub></div>
