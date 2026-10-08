"""
llmharvester/grok_farm.py - Grok xAI Account Farm Engine
---------------------------------------------------------
Automated production of Grok xAI accounts:
1. Loads fresh Residential Proxy pool (from proxies.txt / Webshare Hunter).
2. Generates disposable mailbox via Mail.tm API.
3. Automates registration on accounts.x.ai with human-like interactions.
4. Completes OTP verification and account provisioning.
5. Exports harvested credentials to harvest/grok_accounts.txt and JSON ledger.
"""
import os
import sys
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import json
import time
import string
import random
import re
import struct
import datetime
import threading
import imaplib
import email as email_pkg
import socket
import urllib.parse
import base64
from typing import Dict, Any, List, Optional, Tuple
import requests
from DrissionPage import Chromium, ChromiumOptions
from colorama import Fore, Style

try:
    from core.browser_utils import setup_chromium_options, get_browser_info, get_browser_install_instructions
except ImportError:
    from .browser_utils import setup_chromium_options, get_browser_info, get_browser_install_instructions

SIGNUP_URL = "https://accounts.x.ai/sign-up?redirect=grok-com"

# Global state untuk live status di Web Dashboard & Terminal Sync
grok_farm_state: Dict[str, Any] = {
    "status": "idle",           # "idle", "running", "completed", "error"
    "progress": 0,              # 0 to 100
    "current_account": 0,
    "total_accounts": 0,
    "harvested_count": 0,
    "harvested_accounts": [],
    "logs": [],
    "current_step": "idle",     # "opening_browser", "entering_email", "waiting_otp", "verifying_otp", "setting_profile", "finalizing", "completed"
    "last_error": None
}
grok_lock = threading.RLock()


def grok_log(message: str, level: str = "info", step: Optional[str] = None):
    """Mencatat log secara simultan ke Terminal (Colorama) dan Web Dashboard state (Thread-safe)."""
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    clean_msg = f"[{now_str}] {message}"

    # Print ke Terminal dengan warna
    if level == "error":
        print(f"{Fore.RED}[!] {clean_msg}{Style.RESET_ALL}", flush=True)
    elif level == "success":
        print(f"{Fore.GREEN}[+] {clean_msg}{Style.RESET_ALL}", flush=True)
    elif level == "warning":
        print(f"{Fore.YELLOW}[*] {clean_msg}{Style.RESET_ALL}", flush=True)
    elif level == "debug":
        print(f"{Fore.CYAN}[~] {clean_msg}{Style.RESET_ALL}", flush=True)
    else:
        print(f"[*] {clean_msg}", flush=True)

    # Simpan ke Web State
    with grok_lock:
        if step:
            grok_farm_state["current_step"] = step
        grok_farm_state["logs"].append(clean_msg)
        if len(grok_farm_state["logs"]) > 60:
            grok_farm_state["logs"] = grok_farm_state["logs"][-60:]


def find_residential_proxies() -> List[str]:
    """Mencari file proxy residential dari proxies.txt, Webshare Hunter, atau pool lokal."""
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_txt = os.environ.get("PROXIES_TXT_PATH")
    candidates = [
        os.path.join(root_dir, "proxies.txt"),
        os.path.join(root_dir, "output", "webshare_residential.txt"),
        os.path.join(root_dir, "output", "live_elite.txt"),
    ]
    if env_txt:
        candidates.insert(0, env_txt)
    proxies = []
    for c in candidates:
        p = os.path.abspath(c)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            proxies.append(line)
                if proxies:
                    break
            except Exception:
                pass
    return proxies


def check_proxy_connect(proxy_str: str, target_host: str = "accounts.x.ai", target_port: int = 443, timeout: float = 3.5) -> bool:
    """Verifikasi konektivitas upstream CONNECT tunnel secara cepat (socket-level)."""
    try:
        parsed = urllib.parse.urlsplit(proxy_str if "://" in proxy_str else f"http://{proxy_str}")
        host = parsed.hostname
        port = parsed.port or 80
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            req = [f"CONNECT {target_host}:{target_port} HTTP/1.1", f"Host: {target_host}:{target_port}"]
            if parsed.username or parsed.password:
                raw_auth = f"{urllib.parse.unquote(parsed.username or '')}:{urllib.parse.unquote(parsed.password or '')}"
                b64_auth = base64.b64encode(raw_auth.encode("utf-8")).decode("ascii")
                req.append(f"Proxy-Authorization: Basic {b64_auth}")
            s.sendall(("\r\n".join(req) + "\r\n\r\n").encode("latin1"))
            resp = s.recv(512)
            first_line = resp.split(b"\r\n")[0].decode("latin1", "ignore")
            return "200" in first_line
    except Exception:
        return False


def select_working_residential_proxy(candidates: List[str], max_tries: int = 15) -> Optional[str]:
    """Pilih proxy yang terbukti aktif dan tidak terkena limit kuota/bandwidth (402)."""
    if not candidates:
        return None
    shuffled = candidates.copy()
    random.shuffle(shuffled)
    for cand in shuffled[:max_tries]:
        clean_name = cand.split("@")[-1] if "@" in cand else cand
        if check_proxy_connect(cand):
            return cand
        grok_log(f"Proxy {clean_name} offline / quota limit (402). Trying next candidate...", level="warning")
    return None


def load_gmail_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Cari kredensial mailbox dari environment (IMAP_* lalu GMAIL_*), config.toml, atau settings.json."""
    for u_key, p_key in (("IMAP_USER", "IMAP_PASSWORD"), ("GMAIL_USER", "GMAIL_APP_PASSWORD")):
        env_user = os.getenv(u_key)
        env_pwd = os.getenv(p_key)
        if env_user and env_pwd:
            return env_user.strip(), env_pwd.replace(" ", "").strip()

    candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "qoder-creator", "config.toml")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                if c.endswith(".toml"):
                    with open(c, "r", encoding="utf-8") as f:
                        text = f.read()
                        u_m = re.search(r'gmail_user\s*=\s*["\']([^"\']+)["\']', text)
                        p_m = re.search(r'gmail_app_password\s*=\s*["\']([^"\']+)["\']', text)
                        if u_m and p_m:
                            return u_m.group(1).strip(), p_m.group(1).replace(" ", "").strip()
                elif c.endswith(".json"):
                    with open(c, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        u = d.get("gmail_user") or d.get("GMAIL_USER")
                        p = d.get("gmail_app_password") or d.get("GMAIL_APP_PASSWORD")
                        if u and p:
                            return u.strip(), p.replace(" ", "").strip()
            except Exception:
                pass
    return "luthfishidqi2@gmail.com", "rmpvdcosyjbcqgqq"


class GmailImapService:
    """Mengelola pembuatan alias email Gmail (+subaddress) dan polling OTP via IMAP.
    
    100% Anti-Banned & Instant OTP:
    1. xAI / Grok tidak pernah memblokir domain @gmail.com.
    2. Google mendukung sub-addressing tak terhingga: user+alias@gmail.com.
    3. Email verifikasi masuk instan ke Gmail utama dan dibaca via SSL IMAP port 993.
    """
    def __init__(self, user: str = None, app_password: str = None, host: str = "imap.gmail.com", port: int = 993):
        cfg_user, cfg_pwd = load_gmail_credentials()
        self.user = (user or cfg_user).strip()
        self.app_password = (app_password or cfg_pwd).replace(" ", "").strip()
        self.host = host
        self.port = port
        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self._tag: Optional[str] = None

    def create_mailbox(self) -> Tuple[str, str]:
        clean_user = self.user.split("@")[0]
        # Catch-all / work domain: unique address on a custom domain so one mailbox
        # (read via IMAP) can back many accounts. Falls back to Gmail +alias.
        domain = (os.getenv("EMAIL_DOMAIN") or "").lstrip("@")
        if domain:
            self._tag = None
            self.email = f"gk_{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}@{domain}"
            self.password = "GrokFarm" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "!@"
            return self.email, self.password
        # Buat tag alias unik (contoh: luthfishidqi2+gk123456@gmail.com)
        self._tag = f"gk{int(time.time()) % 100000}{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
        self.email = f"{clean_user}+{self._tag}@gmail.com"
        self.password = "GrokFarm" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "!@"
        return self.email, self.password

    @staticmethod
    def _html_to_text(raw: str) -> str:
        """Strip <style>/<script>/tags so CSS hex colors don't masquerade as OTP digits."""
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        return raw

    @staticmethod
    def _extract_body(msg_obj) -> str:
        body = ""
        if msg_obj.is_multipart():
            for part in msg_obj.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += GmailImapService._html_to_text(
                            payload.decode("utf-8", errors="replace")
                        ) + " "
        else:
            payload = msg_obj.get_payload(decode=True)
            if payload:
                body = GmailImapService._html_to_text(payload.decode("utf-8", errors="replace"))
        return body

    def _poll(self, timeout_sec: int, matcher) -> Optional[str]:
        """Poll the Gmail INBOX for this alias and return the first code `matcher` yields.

        `matcher(from_hdr, subject, body) -> Optional[str]` decides whether a given
        message is relevant and extracts the verification code from it.
        """
        target_addr = (self.email or "").strip().lower()
        if not target_addr or not self.user or not self.app_password:
            return None

        # Gmail often routes forwarded/catch-all mail to "All Mail" (and sometimes
        # Spam) instead of INBOX, so search those folders too.
        folders = ["INBOX"]
        if "gmail" in (self.host or "").lower():
            folders += ['"[Gmail]/All Mail"', '"[Gmail]/Spam"']

        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            mail = None
            try:
                mail = imaplib.IMAP4_SSL(self.host, self.port)
                mail.login(self.user, self.app_password)

                for folder in folders:
                    try:
                        typ, _ = mail.select(folder, readonly=True)
                    except Exception:
                        continue
                    if typ != "OK":
                        continue

                    status, data = mail.search(None, "ALL")
                    if status != "OK" or not data or not data[0]:
                        continue

                    msg_ids = data[0].split()
                    recent_ids = msg_ids[-25:][::-1]
                    for mid in recent_ids:
                        res, msg_data = mail.fetch(mid, "(RFC822)")
                        if res != "OK" or not msg_data or not msg_data[0]:
                            continue
                        msg_obj = email_pkg.message_from_bytes(msg_data[0][1])

                        to_hdr = str(msg_obj.get("To", "")).lower()
                        delivered_hdr = str(msg_obj.get("Delivered-To", "")).lower()

                        # Pastikan email untuk alias target spesifik akun ini
                        is_target = (
                            target_addr in to_hdr
                            or target_addr in delivered_hdr
                            or (self._tag and (self._tag in to_hdr or self._tag in delivered_hdr))
                        )
                        if not is_target:
                            continue

                        subject = str(msg_obj.get("Subject", ""))
                        from_hdr = str(msg_obj.get("From", "")).lower()
                        code = matcher(from_hdr, subject, self._extract_body(msg_obj))
                        if code:
                            return code
            except Exception:
                pass
            finally:
                if mail:
                    try:
                        mail.logout()
                    except Exception:
                        pass
            time.sleep(3)

        return None

    def poll_verification_code(self, timeout_sec: int = 90) -> Optional[str]:
        """Poll for an xAI/Grok OTP (XXX-XXX or 6 digits)."""
        def matcher(from_hdr: str, subject: str, body: str) -> Optional[str]:
            if not (
                "xai" in from_hdr
                or "grok" in from_hdr
                or "x.ai" in from_hdr
                or "code" in subject.lower()
                or "verif" in subject.lower()
            ):
                return None
            full_text = f"{subject} {body}"
            # Cari pola kode verifikasi xAI (XXX-XXX atau 6 digit angka)
            m = re.search(r"\b([A-Za-z0-9]{3}-[A-Za-z0-9]{3})\b", full_text)
            if m:
                return m.group(1).replace("-", "").strip()
            m = re.search(r"\b(\d{6})\b", full_text)
            if m:
                return m.group(1).strip()
            return None

        return self._poll(timeout_sec, matcher)

    def poll_numeric_code(
        self,
        timeout_sec: int = 90,
        senders: Tuple[str, ...] = ("tokenmix",),
        subjects: Tuple[str, ...] = ("code", "verif", "tokenmix"),
    ) -> Optional[str]:
        """Poll for a plain 6-digit OTP from the given senders/subject keywords (TokenMix & friends)."""
        def matcher(from_hdr: str, subject: str, body: str) -> Optional[str]:
            if not (
                any(s in from_hdr for s in senders)
                or any(s in subject.lower() for s in subjects)
            ):
                return None
            m = re.search(r"\b(\d{6})\b", f"{subject} {body}")
            return m.group(1).strip() if m else None

        return self._poll(timeout_sec, matcher)


class MailTmService:
    """Mengelola pembuatan email instan dan polling kode OTP via Mail.tm & Mail.gw (serasi dengan ZeroTwo/TokenHarbor)."""
    def __init__(self):
        self.api_bases = ["https://api.mail.tm", "https://api.mail.gw"]
        self.api_base = "https://api.mail.tm"
        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.token: Optional[str] = None
        self.account_id: Optional[str] = None

    def create_mailbox(self) -> Tuple[str, str]:
        for base in self.api_bases:
            try:
                r = requests.get(f"{base}/domains", timeout=6.0)
                if r.status_code == 200:
                    domains = r.json().get("hydra:member", [])
                    active_domains = [d["domain"] for d in domains if d.get("isVerified", True) or d.get("isActive", True)]
                    if active_domains:
                        self.api_base = base
                        chosen_domain = random.choice(active_domains)
                        uname = "zt_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
                        self.email = f"{uname}@{chosen_domain}"
                        self.password = "Zt" + "".join(random.choices(string.ascii_letters + string.digits, k=8)) + "aA1!"

                        create_res = requests.post(
                            f"{self.api_base}/accounts",
                            json={"address": self.email, "password": self.password},
                            timeout=7.0
                        )
                        create_res.raise_for_status()
                        self.account_id = create_res.json().get("id")

                        token_res = requests.post(
                            f"{self.api_base}/token",
                            json={"address": self.email, "password": self.password},
                            timeout=7.0
                        )
                        token_res.raise_for_status()
                        self.token = token_res.json().get("token")

                        return self.email, self.password
            except Exception:
                continue

        raise RuntimeError("Gagal membuat mailbox di Mail.tm maupun Mail.gw. Periksa koneksi internet.")

    def poll_verification_code(self, timeout_sec: int = 75) -> Optional[str]:
        if not self.token:
            raise RuntimeError("Mailbox token belum diinisialisasi.")

        headers = {"Authorization": f"Bearer {self.token}"}
        start_time = time.time()

        while time.time() - start_time < timeout_sec:
            try:
                msg_res = requests.get(f"{self.api_base}/messages", headers=headers, timeout=5.0)
                if msg_res.status_code == 200:
                    messages = msg_res.json().get("hydra:member", [])
                    if messages:
                        first_msg_id = messages[0]["id"]
                        detail_res = requests.get(f"{self.api_base}/messages/{first_msg_id}", headers=headers, timeout=5.0)
                        if detail_res.status_code == 200:
                            data = detail_res.json()
                            body = (data.get("text") or "") + " " + (data.get("intro") or "") + " " + (data.get("subject") or "")
                            codes = re.findall(r"\b(\d{6})\b|\b(\d{3}-\d{3})\b", body)
                            if codes:
                                for c in codes[0]:
                                    if c:
                                        return c.replace("-", "").strip()
            except Exception:
                pass
            time.sleep(2.5)

        return None


DuckMailService = MailTmService


def click_email_signup_button(page, timeout: int = 12) -> bool:
    """Mendeteksi tombol 'Sign up with email' / 'Continue with email' pada landing page xAI."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            clicked = page.run_js(r"""
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                function nodeText(node) {
                    return [
                        node.innerText,
                        node.textContent,
                        node.getAttribute('aria-label'),
                        node.getAttribute('title'),
                        node.getAttribute('href'),
                    ].filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                }
                function scoreEntry(node) {
                    const compact = nodeText(node).replace(/\\s+/g, '');
                    const lower = compact.toLowerCase();
                    if (compact.includes('使用邮箱注册')) return 100;
                    if (lower.includes('signupwithemail')) return 95;
                    if (lower.includes('continuewithemail')) return 90;
                    if (lower.includes('email') && (lower.includes('sign') || lower.includes('continue') || lower.includes('use') || lower.includes('with'))) return 80;
                    if (lower === 'email' || lower.includes('邮箱') || lower.includes('sign up with email')) return 75;
                    return 0;
                }
                const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'))
                    .filter((node) => isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true')
                    .map((node) => ({ node, score: scoreEntry(node), text: nodeText(node) }))
                    .filter((item) => item.score > 0)
                    .sort((a, b) => b.score - a.score);
                const target = candidates[0]?.node || null;
                if (!target) return false;
                target.click();
                return candidates[0].text || true;
            """)
            if clicked:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def fill_email_and_submit(page, email: str, timeout: int = 20) -> bool:
    """Mengisi input email dengan pengetikan alami dan dispatch event agar reaktif."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # 1. Cek via JS apakah input email siap atau perlu re-click tombol
            res = page.run_js(r"""
                const email = arguments[0];
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                const inputs = Array.from(document.querySelectorAll('input[type="email"], input[name="email"], input[data-testid="email"], input[placeholder*="email" i], input[autocomplete="email"], input'))
                    .filter(node => isVisible(node) && !node.disabled && !node.readOnly);
                const input = inputs[0];
                if (!input) {
                    const btns = Array.from(document.querySelectorAll('button, a, [role="button"]'))
                        .filter(node => isVisible(node) && !node.disabled);
                    const signupBtn = btns.find(b => {
                        const t = (b.innerText || b.textContent || '').toLowerCase();
                        return t.includes('sign up with email') || t.includes('continue with email') || (t.includes('email') && t.includes('sign'));
                    });
                    if (signupBtn) {
                        signupBtn.click();
                        return 'reclicked';
                    }
                    return false;
                }

                input.focus();
                input.click();
                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                const tracker = input._valueTracker;
                if (tracker) tracker.setValue('');
                if (nativeSetter) nativeSetter.call(input, email);
                else input.value = email;

                input.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, data: email, inputType: 'insertText' }));
                input.dispatchEvent(new InputEvent('input', { bubbles: true, data: email, inputType: 'insertText' }));
                input.dispatchEvent(new Event('change', { bubbles: true }));

                const buttons = Array.from(document.querySelectorAll('button[type="submit"], button, [role="button"]'))
                    .filter(node => isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true');
                const btn = buttons.find(b => {
                    const t = (b.innerText || b.textContent || '').toLowerCase();
                    return t.includes('continue') || t.includes('sign up') || t.includes('next') || t.includes('lanjut') || t.includes('submit');
                });
                if (btn) {
                    btn.click();
                    return 'clicked';
                }
                input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                return 'enter';
            """, email)

            if res in ('clicked', 'enter'):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def fill_otp_and_submit(page, otp_code: str, timeout: int = 15) -> bool:
    """Mengisi kode verifikasi 6 digit ke input OTP."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            filled = page.run_js(r"""
                const code = String(arguments[0] || '').trim();
                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                function setInputValue(input, value) {
                    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    const tracker = input._valueTracker;
                    if (tracker) tracker.setValue('');
                    if (nativeSetter) nativeSetter.call(input, value);
                    else input.value = value;
                    input.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, data: value, inputType: 'insertText' }));
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const aggregate = Array.from(document.querySelectorAll('input[data-input-otp="true"], input[name="code"], input[autocomplete="one-time-code"], input[maxlength="6"], input[inputmode="numeric"]'))
                    .find(node => isVisible(node) && !node.disabled && !node.readOnly && Number(node.maxLength || 6) > 1);

                if (aggregate) {
                    aggregate.focus();
                    setInputValue(aggregate, code);
                    return 'aggregate-filled';
                }

                const otpBoxes = Array.from(document.querySelectorAll('input')).filter(node => {
                    if (!isVisible(node) || node.disabled || node.readOnly) return false;
                    const maxLength = Number(node.maxLength || 0);
                    return maxLength === 1 || String(node.autocomplete || '').toLowerCase() === 'one-time-code';
                });

                if (otpBoxes.length >= code.length) {
                    for (let i = 0; i < code.length; i++) {
                        const ch = code[i];
                        const box = otpBoxes[i];
                        box.focus();
                        setInputValue(box, ch);
                        box.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: ch }));
                        box.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: ch }));
                    }
                    return 'boxes-filled';
                }
                return false;
            """, otp_code)

            if filled:
                time.sleep(1)
                page.run_js(r"""
                    function isVisible(node) {
                        if (!node) return false;
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = node.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    }
                    const buttons = Array.from(document.querySelectorAll('button[type="submit"], button, [role="button"]'))
                        .filter(node => isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true');
                    const btn = buttons.find(b => {
                        const t = (b.innerText || b.textContent || '').toLowerCase();
                        return t.includes('verify') || t.includes('continue') || t.includes('next') || t.includes('confirm');
                    });
                    if (btn) btn.click();
                """)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def fill_profile_and_submit(page, password: str, timeout: int = 20) -> bool:
    """Mengisi First Name, Last Name, dan Password profil."""
    deadline = time.time() + timeout
    fake_first = "Grok" + "".join(random.choices(string.ascii_uppercase, k=1)) + "".join(random.choices(string.ascii_lowercase, k=4))
    fake_last = "".join(random.choices(string.ascii_uppercase, k=1)) + "".join(random.choices(string.ascii_lowercase, k=5))

    while time.time() < deadline:
        try:
            filled = page.run_js(r"""
                const first = arguments[0];
                const last = arguments[1];
                const pwd = arguments[2];

                function isVisible(node) {
                    if (!node) return false;
                    const style = window.getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = node.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                }
                function setVal(node, val) {
                    if (!node) return;
                    node.focus();
                    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    const tracker = node._valueTracker;
                    if (tracker) tracker.setValue('');
                    if (nativeSetter) nativeSetter.call(node, val);
                    else node.value = val;
                    node.dispatchEvent(new InputEvent('input', { bubbles: true, data: val }));
                    node.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const givenInp = document.querySelector('input[data-testid="givenName"], input[name="givenName"], input[autocomplete="given-name"], input[placeholder*="First" i], input[placeholder*="Nama" i]');
                const familyInp = document.querySelector('input[data-testid="familyName"], input[name="familyName"], input[autocomplete="family-name"], input[placeholder*="Last" i]');
                const nameInp = document.querySelector('input[name="name"], input[placeholder*="Name" i]');
                const pwdInp = document.querySelector('input[type="password"], input[data-testid="password"], input[name="password"]');

                if (givenInp && familyInp) {
                    setVal(givenInp, first);
                    setVal(familyInp, last);
                } else if (nameInp) {
                    setVal(nameInp, first + ' ' + last);
                }

                if (pwdInp) {
                    setVal(pwdInp, pwd);
                }

                const buttons = Array.from(document.querySelectorAll('button[type="submit"], button, [role="button"]'))
                    .filter(node => isVisible(node) && !node.disabled && node.getAttribute('aria-disabled') !== 'true');
                const btn = buttons.find(b => {
                    const t = (b.innerText || b.textContent || '').toLowerCase();
                    return t.includes('agree') || t.includes('create') || t.includes('continue') || t.includes('finish') || t.includes('signup') || t.includes('sign up');
                });
                if (btn) {
                    btn.click();
                    return true;
                }
                return !!(givenInp || nameInp);
            """, fake_first, fake_last, password)

            if filled:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def register_single_grok_account(index: int, total: int, headless: bool = True, proxy_gateway: str = None, mail_provider: str = "gmail") -> Optional[Dict[str, Any]]:
    # 1. Select working residential proxy
    residential_list = find_residential_proxies()
    chosen_proxy = select_working_residential_proxy(residential_list) if residential_list else None

    if chosen_proxy:
        grok_log(f"Using Verified Residential Proxy: {chosen_proxy.split('@')[-1] if '@' in chosen_proxy else chosen_proxy}", level="info")
    elif residential_list:
        grok_log("All proxies in pool offline or quota-limited (402). Using direct connection.", level="warning")

    if mail_provider == "gmail":
        mail_svc = GmailImapService()
        grok_log(f"Generating Gmail alias via IMAP (Account [{index}/{total}])...", level="info", step="creating_email")
    else:
        mail_svc = MailTmService()
        grok_log(f"Creating disposable mailbox via Mail.tm / Mail.gw (Account [{index}/{total}])...", level="info", step="creating_email")

    try:
        email, password = mail_svc.create_mailbox()
    except Exception as e:
        grok_log(f"Failed to create email: {e}", level="error")
        return None

    grok_log(f"Active Mailbox: {email} | Password: {password}", level="success", step="opening_browser")

    b_info = get_browser_info()
    if not b_info["available"]:
        grok_log("Chromium/Chrome/Brave browser not found on system!", level="error", step="opening_browser")
        print(get_browser_install_instructions())
        return None

    co = ChromiumOptions()
    co = setup_chromium_options(
        co,
        headless=headless,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    proxy_bridge = None
    effective_proxy = None

    # 1. Prioritaskan proxy residential terverifikasi (kebutuhan utama registrasi Grok xAI)
    if chosen_proxy:
        try:
            try:
                from core.proxy_bridge import prepare_chromium_proxy
            except ImportError:
                from .proxy_bridge import prepare_chromium_proxy
            effective_proxy, proxy_bridge = prepare_chromium_proxy(chosen_proxy)
        except Exception:
            effective_proxy = chosen_proxy

    # 2. Jika tidak ada proxy residential, cek apakah proxy gateway lokal benar-benar aktif & valid HTTP CONNECT
    elif proxy_gateway:
        try:
            import socket
            hp = proxy_gateway.replace("http://", "").replace("https://", "").split(":")
            if len(hp) == 2:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    s.connect((hp[0], int(hp[1])))
                    s.sendall(b"CONNECT accounts.x.ai:443 HTTP/1.1\r\nHost: accounts.x.ai:443\r\n\r\n")
                    resp = s.recv(256)
                    # Pastikan bukan respon 400 Bad Request dari server non-proxy (seperti mediamtx/streaming)
                    if b" 200 " in resp or b" 407 " in resp:
                        effective_proxy = proxy_gateway
        except Exception:
            pass

    if effective_proxy:
        co.set_argument(f"--proxy-server={effective_proxy}")

    ext_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "turnstilePatch"))
    if not os.path.exists(ext_path):
        ext_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "grok-register", "turnstilePatch"))
    if os.path.exists(ext_path):
        co.add_extension(ext_path)

    browser = None
    try:
        browser = Chromium(co)
    except Exception as e:
        grok_log(f"Failed to launch browser ({b_info['name']}): {e}", level="error", step="opening_browser")
        if not b_info.get("available") or not os.path.isfile(b_info.get("path", "")):
            print(get_browser_install_instructions())
        if proxy_bridge:
            try:
                proxy_bridge.stop()
            except Exception:
                pass
        return None

    try:
        page = browser.latest_tab
        grok_log(f"Opening Grok xAI registration page ({b_info['name']}): {SIGNUP_URL}", level="info", step="opening_browser")
        page.get(SIGNUP_URL)
        time.sleep(4)

        # 1. Click 'Sign up with email' button
        grok_log("Locating & clicking 'Sign up with email' button...", level="info", step="entering_email")
        btn_clicked = click_email_signup_button(page, timeout=8)
        if btn_clicked:
            grok_log("Successfully opened email input form.", level="debug")
        time.sleep(1)

        # 2. Submit Email
        grok_log(f"Entering email ({email}) and submitting...", level="info", step="entering_email")
        if not fill_email_and_submit(page, email, timeout=12):
            grok_log("Failed to submit email to registration form.", level="warning")

        # 3. Polling OTP Code
        poll_src = getattr(mail_svc, 'api_base', 'Gmail IMAP Inbox')
        grok_log(f"Waiting for 6-digit OTP code from xAI (polling {poll_src})...", level="info", step="waiting_otp")
        otp_code = mail_svc.poll_verification_code(timeout_sec=90)
        if not otp_code:
            grok_log("OTP wait timed out (90s limit).", level="error")
            return None

        grok_log(f"OTP CODE RECEIVED: {otp_code}!", level="success", step="verifying_otp")

        # 4. Fill OTP
        grok_log(f"Filling OTP code ({otp_code}) into verification form...", level="info", step="verifying_otp")
        fill_otp_and_submit(page, otp_code, timeout=10)
        time.sleep(2.5)

        # 5. Fill profile if prompted
        grok_log("Filling profile data & accepting Terms of Service...", level="info", step="setting_profile")
        fill_profile_and_submit(page, password, timeout=10)
        time.sleep(3)

        # 6. Extract SSO Cookie / session token
        grok_log("Extracting authentication tokens & session cookies...", level="info", step="finalizing")
        # Ensure the web session is fully established (grok.com issues the `sso` cookie).
        try:
            page.get("https://grok.com/")
            time.sleep(3)
        except Exception:
            pass

        cookies = []
        for kwargs in ({"all_domains": True, "all_info": True}, {"all_domains": True}, {}):
            try:
                got = page.cookies(**kwargs)
            except TypeError:
                continue
            except Exception:
                continue
            if got:
                cookies = got
                break

        try:
            names = sorted({(c.get("name") or "") for c in cookies})
            grok_log(f"Captured {len(cookies)} cookie(s): {', '.join(names)}", level="debug")
        except Exception:
            pass

        # Prefer the grok.com `sso` cookie (that's what 9Router's grok-web expects).
        def _pick(name_eq: str | None = None, contains: str | None = None, domain_has: str | None = None):
            for c in cookies:
                n = (c.get("name") or "")
                d = (c.get("domain") or "")
                v = c.get("value")
                if not v:
                    continue
                if name_eq and n.lower() != name_eq:
                    continue
                if contains and contains not in n.lower():
                    continue
                if domain_has and domain_has not in d.lower():
                    continue
                return v
            return None

        for c in cookies:
            n = (c.get("name") or "").lower()
            if "sso" in n or "session" in n or "auth" in n:
                grok_log(
                    f"session cookie: name={c.get('name')} domain={c.get('domain')} len={len(c.get('value') or '')}",
                    level="debug",
                )

        sso_token = (
            _pick(name_eq="sso", domain_has="grok")
            or _pick(name_eq="sso")
            or _pick(name_eq="sso-rw", domain_has="grok")
            or _pick(name_eq="sso-rw")
            or _pick(contains="sso")
            or _pick(name_eq="__secure-next-auth.session-token")
        )
        if sso_token:
            grok_log(f"SSO/session token captured (len={len(sso_token)}).", level="success", step="finalizing")
        else:
            grok_log("No SSO/session cookie found in browser session.", level="warning")

        # xAI may keep auth in local/session storage rather than cookies.
        ls_keys = []
        ss_keys = []
        try:
            ls_keys = page.run_js("return Object.keys(window.localStorage);") or []
        except Exception:
            ls_keys = []
        try:
            ss_keys = page.run_js("return Object.keys(window.sessionStorage);") or []
        except Exception:
            ss_keys = []
        grok_log(f"Storage keys -> localStorage: {ls_keys} | sessionStorage: {ss_keys}", level="debug")
        if not sso_token:
            for store, keys in (("localStorage", ls_keys), ("sessionStorage", ss_keys)):
                for k in keys:
                    lk = str(k).lower()
                    if not any(t in lk for t in ("token", "auth", "sso", "session", "jwt", "access")):
                        continue
                    try:
                        val = page.run_js(f"return window.{store}.getItem({json.dumps(str(k))});")
                    except Exception:
                        val = None
                    if isinstance(val, str) and len(val) > 20:
                        sso_token = val
                        grok_log(f"Auth token found in {store}['{k}'] (len={len(val)}).", level="success", step="finalizing")
                        break
                if sso_token:
                    break

        account_data = {
            "email": email,
            "password": password,
            "sso_token": sso_token,
            "cookies": cookies,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        grok_log(f"SUCCESS! Grok xAI account [{index}/{total}] harvested: {email}", level="success", step="completed")
        return account_data

    except Exception as ex:
        grok_log(f"Grok registration exception: {ex}", level="error")
        return None
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
        if proxy_bridge:
            try:
                proxy_bridge.stop()
            except Exception:
                pass


def save_grok_account(account: Dict[str, Any], output_dir: str = None):
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    harvest_dir = os.path.join(root_dir, "harvest")
    os.makedirs(harvest_dir, exist_ok=True)
    out_dir = output_dir or os.path.join(root_dir, "output")
    os.makedirs(out_dir, exist_ok=True)

    txt_path = os.path.join(harvest_dir, "grok_accounts.txt")
    jsonl_path = os.path.join(harvest_dir, "grok_accounts.jsonl")
    legacy_txt = os.path.join(out_dir, "grok_accounts.txt")
    legacy_json = os.path.join(out_dir, "grok_accounts.json")

    line = f"{account['email']}----{account['password']}----{account.get('sso_token') or 'NO_SSO_COOKIE'}\n"
    for p in (txt_path, legacy_txt):
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)

    json_entry = {
        "platform": "grok",
        "email": account["email"],
        "password": account["password"],
        "sso_token": account.get("sso_token"),
        "created_at": account.get("created_at"),
    }
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(json_entry) + "\n")

    existing_json = []
    if os.path.exists(legacy_json):
        try:
            with open(legacy_json, "r", encoding="utf-8") as f:
                existing_json = json.load(f)
        except Exception:
            existing_json = []

    existing_json.append(account)
    with open(legacy_json, "w", encoding="utf-8") as f:
        json.dump(existing_json, f, indent=2)

    grok_log(f"Account saved to {txt_path} & {jsonl_path}", level="debug")


def run_grok_farm(total: int = 1, headless: bool = True, proxy_gateway: Optional[str] = None, mail_provider: str = "gmail") -> List[Dict[str, Any]]:
    with grok_lock:
        grok_farm_state["status"] = "running"
        grok_farm_state["progress"] = 5
        grok_farm_state["current_account"] = 0
        grok_farm_state["total_accounts"] = total
        grok_farm_state["harvested_count"] = 0
        grok_farm_state["harvested_accounts"] = []
        grok_farm_state["logs"] = []
        grok_farm_state["last_error"] = None

    grok_log(f"Starting Grok xAI Account Farm (Target: {total} accounts, Headless: {headless}, Provider: {mail_provider.upper()})", level="info")

    harvested = []
    for i in range(1, total + 1):
        with grok_lock:
            grok_farm_state["current_account"] = i
            grok_farm_state["progress"] = int(((i - 1) / total) * 90) + 10

        acc = register_single_grok_account(i, total, headless=headless, proxy_gateway=proxy_gateway, mail_provider=mail_provider)
        if acc:
            save_grok_account(acc)
            harvested.append(acc)
            with grok_lock:
                grok_farm_state["harvested_count"] = len(harvested)
                grok_farm_state["harvested_accounts"].append({
                    "email": acc["email"],
                    "password": acc["password"],
                    "created_at": acc["created_at"],
                    "has_sso": bool(acc.get("sso_token"))
                })
        else:
            grok_log(f"Account [{i}/{total}] failed.", level="warning")

        if i < total:
            time.sleep(3)

    with grok_lock:
        grok_farm_state["status"] = "completed"
        grok_farm_state["progress"] = 100
        grok_farm_state["current_step"] = "completed"
        grok_log(f"Harvest complete! Successfully harvested {len(harvested)}/{total} Grok xAI accounts.", level="success")

    return harvested


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    provider = sys.argv[2] if len(sys.argv) > 2 else "gmail"
    run_grok_farm(total=count, headless=False, mail_provider=provider)
