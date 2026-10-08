"""Z.ai / ZCode GLM Harvester.

Drives Z.ai (chat.z.ai) account registration, performs ZCode OAuth token exchange,
prompts interactive Aliyun Captcha 2.0 solving, claims the flagship GLM-5.3 Start Plan,
and mints coding-plan API keys for 9Router registration.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import string
import time
import urllib.error
import urllib.request
from typing import Any

from .config import ZaiConfig
from .mail import MailProvider, Mailbox
from .tokenharbor import HarvestedKey
from .zerotwo import CDP

# Regex patterns for OTP code extraction
OTP_PATTERNS = [
    re.compile(r"(?:code|kode|pin|verification)[\s:]*([0-9]{6})", re.IGNORECASE),
    re.compile(r"\b([0-9]{6})\b"),
]

# Z.ai / ZCode Constants
ZAI_ORIGIN = "https://chat.z.ai"
ZAI_AUTH_URL = "https://chat.z.ai/auth"
ZCODE_CLIENT_ID = "client_P8X5CMWmlaRO9gyO-KSqtg"
ZCODE_REDIRECT_URI = "zcode://oauth/callback"
ZCODE_AUTHORIZE_URL = "https://chat.z.ai/api/oauth/authorize"
ZCODE_TOKEN_URL = "https://zcode.z.ai/api/v1/oauth/token"
ZCODE_CLAIM_URL = "https://zcode.z.ai/api/v1/zcode-plan/billing/claim"
ZCODE_PLAN_ID = "zcode-v3-start-plan"
ZAI_BUSINESS_LOGIN_URL = "https://api.z.ai/api/auth/z/login"
ZAI_API_BASE = "https://api.z.ai"
PLAN_API_KEY_NAME = "zcode-api-key"
ALIYUN_SCENE = {"sceneId": "11xygtvd", "prefix": "no8xfe", "region": "sgp"}


def extract_otp(text: str) -> str | None:
    """Extract a 6-digit OTP verification code from email text."""
    if not text:
        return None
    for pat in OTP_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def _rand_password(length: int = 16) -> str:
    """Generate a strong password satisfying Z.ai rules."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    chars += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _http_json(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: float = 30.0) -> dict:
    """Perform JSON HTTP request using stdlib urllib."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {err_msg[:200]}") from exc


class ZaiHarvester:
    """Automates Z.ai registration, ZCode Start-Plan claim, and API key generation."""

    def __init__(
        self,
        cdp: CDP,
        mail: MailProvider,
        config: ZaiConfig | None = None,
        log: Any = print,
    ) -> None:
        self.cdp = cdp
        self.mail = mail
        self.config = config or ZaiConfig()
        self.log = log

    @staticmethod
    def exchange_zcode_token(code: str, state: str) -> dict[str, Any]:
        """Exchange OAuth authorization code for ZCode JWT and Z.ai access token."""
        payload = {
            "provider": "zai",
            "code": code,
            "redirect_uri": ZCODE_REDIRECT_URI,
            "state": state,
        }
        resp = _http_json(ZCODE_TOKEN_URL, method="POST", body=payload)
        code_status = resp.get("code")
        if code_status not in (0, 200, None):
            raise RuntimeError(f"ZCode token exchange failed: {resp.get('msg') or resp}")
        d = resp.get("data") or {}
        return {
            "zcodeJwtToken": d.get("token"),
            "zaiAccessToken": (d.get("zai") or {}).get("access_token"),
            "user": d.get("user"),
            "expiresIn": d.get("expires_in"),
        }

    @staticmethod
    def claim_start_plan(zcode_jwt: str, captcha_param: str) -> tuple[bool, str]:
        """Submit claim request for the free ZCode Start Plan with Aliyun captcha verify param."""
        headers = {
            "Authorization": f"Bearer {zcode_jwt}",
            "X-Aliyun-Captcha-Verify-Param": captcha_param,
            "X-Aliyun-Captcha-Verify-Region": ALIYUN_SCENE["region"],
            "X-ZCode-App-Version": "3.14.4",
        }
        body = {"plan_id": ZCODE_PLAN_ID}
        try:
            resp = _http_json(ZCODE_CLAIM_URL, method="POST", body=body, headers=headers)
            msg = resp.get("msg") or "success"
            ok = resp.get("code") in (0, 200, None)
            return ok, msg
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def mint_plan_api_key(zai_access_token: str) -> dict[str, Any]:
        """Mint a coding-plan API key using the Z.ai business API."""
        # Step 1: Login to business platform
        login_resp = _http_json(ZAI_BUSINESS_LOGIN_URL, method="POST", body={"token": zai_access_token})
        biz_data = login_resp.get("data") or {}
        business_token = biz_data.get("access_token") or biz_data.get("accessToken")
        if not business_token:
            raise RuntimeError("Z.ai business login missing access_token")

        biz_headers = {"Authorization": f"Bearer {business_token.strip()}"}

        # Step 2: Get customer organizations & projects
        info = _http_json(f"{ZAI_API_BASE}/api/biz/customer/getCustomerInfo", headers=biz_headers)
        cust_data = info.get("data") if info.get("data") is not None else info
        orgs = cust_data.get("organizations") or []
        target_org = None
        target_project = None
        for org in orgs:
            for proj in (org.get("projects") or []):
                if str(proj.get("projectType", "")).strip() != "2":
                    target_org = org
                    target_project = proj
                    break
            if target_org:
                break

        if not target_org or not target_project:
            raise RuntimeError("No usable Z.ai organization/project found")

        oid = target_org["organizationId"]
        pid = target_project["projectId"]
        base_keys_url = f"{ZAI_API_BASE}/api/biz/v1/organization/{oid}/projects/{pid}/api_keys"

        # Step 3: Check or create API key
        keys_resp = _http_json(base_keys_url, headers=biz_headers)
        keys_data = keys_resp.get("data") if keys_resp.get("data") is not None else keys_resp
        api_key = None
        if isinstance(keys_data, list):
            api_key = next((k.get("apiKey") for k in keys_data if k.get("name") == PLAN_API_KEY_NAME), None)

        if not api_key:
            created = _http_json(base_keys_url, method="POST", body={"name": PLAN_API_KEY_NAME}, headers=biz_headers)
            c_data = created.get("data") if created.get("data") is not None else created
            api_key = c_data.get("apiKey") if isinstance(c_data, dict) else None

        if not api_key:
            raise RuntimeError("Failed to obtain API key from Z.ai business API")

        # Step 4: Copy secret key
        secret_resp = _http_json(f"{base_keys_url}/copy/{api_key}", headers=biz_headers)
        s_data = secret_resp.get("data") if secret_resp.get("data") is not None else secret_resp
        secret_key = (s_data or {}).get("secretKey")
        if not secret_key:
            raise RuntimeError("Failed to obtain secretKey from Z.ai business API")

        return {
            "planApiKey": f"{api_key}.{secret_key}",
            "organization": target_org.get("organizationName"),
            "project": target_project.get("projectName"),
            "businessToken": business_token,
        }

    async def wait_for_otp(self, mailbox: Mailbox, timeout: float = 60.0) -> str | None:
        """Poll mailbox for verification code."""
        self.log(f"[zai] Menunggu kode verifikasi OTP di inbox {mailbox.address}...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                messages = await self.mail.get_messages(mailbox)
                for msg in messages:
                    content = f"{msg.subject} {msg.text} {msg.html}"
                    code = extract_otp(content)
                    if code:
                        self.log(f"[zai] Ditemukan OTP: {code}")
                        return code
            except Exception as e:
                self.log(f"[zai] Error cek inbox: {e}")
            await asyncio.sleep(3.0)
        return None

    async def solve_aliyun_captcha_interactive(self, timeout: float = 120.0) -> str | None:
        """Inject Aliyun Captcha SDK container and prompt user for interactive solve."""
        self.log("\n" + "=" * 60)
        self.log("[zai] >>> PERHATIAN: SILAKAN GESER SLIDER ALIYUN CAPTCHA PADA BROWSER <<<")
        self.log("[zai] Buka browser dan geser puzzle/slider Aliyun yang muncul...")
        self.log("=" * 60)

        # Inject Aliyun SDK if not present and render container
        inject_js = """
        (scene) => {
            window.__capParam = null;
            window.__capErr = null;
            let el = document.getElementById('__aliyun_cap_box');
            if (!el) {
                el = document.createElement('div');
                el.id = '__aliyun_cap_box';
                el.style.cssText = 'position:fixed;top:30px;left:50%;transform:translateX(-50%);z-index:9999999;background:#fff;padding:16px;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,0.4);border:2px solid #5b8cff';
                el.innerHTML = '<h3 style="margin:0 0 10px;color:#111;text-align:center">Verifikasi Aliyun Captcha (ZCode Claim)</h3><div id="__aliyun_elem"></div><button id="__aliyun_btn" style="display:block;margin:10px auto;padding:6px 16px;background:#5b8cff;color:#fff;border:none;border-radius:4px;cursor:pointer">Tampilkan Slider</button>';
                document.body.appendChild(el);
            }
            if (typeof window.initAliyunCaptcha === 'function') {
                window.initAliyunCaptcha({
                    SceneId: scene.sceneId,
                    mode: 'popup',
                    element: '#__aliyun_elem',
                    button: '#__aliyun_btn',
                    region: scene.region,
                    prefix: scene.prefix,
                    language: 'en',
                    getInstance: (i) => { window.__capInst = i; },
                    success: (p) => { window.__capParam = p; },
                    fail: (e) => { window.__capErr = JSON.stringify(e); }
                });
                const b = document.getElementById('__aliyun_btn');
                if (b) b.click();
            }
            return 'injected';
        }
        """
        await self.cdp.evaluate(f"({inject_js})({json.dumps(ALIYUN_SCENE)})")

        deadline = time.time() + timeout
        while time.time() < deadline:
            param = await self.cdp.evaluate("window.__capParam")
            if param:
                self.log("[zai] Captcha slider berhasil diselesaikan!")
                return param
            err = await self.cdp.evaluate("window.__capErr")
            if err:
                self.log(f"[zai] Captcha error: {err}")
            await asyncio.sleep(1.5)

        self.log("[zai] Waktu verifikasi captcha habis (timeout).")
        return None

    async def harvest(self) -> HarvestedKey:
        """Run complete end-to-end harvest for Z.ai."""
        # 1. Create Mailbox
        self.log("[zai] Membuat mailbox baru...")
        mailbox = await self.mail.create_mailbox()
        password = _rand_password()
        self.log(f"[zai] Mailbox siap: {mailbox.address}")

        # 2. Navigate to chat.z.ai/auth
        self.log(f"[zai] Membuka {ZAI_AUTH_URL}...")
        await self.cdp.navigate(ZAI_AUTH_URL)
        await asyncio.sleep(4.0)

        # 3. Enter email
        fill_email_js = """
        (email) => {
            const inputs = Array.from(document.querySelectorAll('input[type="email"], input[name="email"], input[placeholder*="email" i]'));
            if (inputs.length > 0) {
                const inp = inputs[0];
                inp.value = email;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        }
        """
        await self.cdp.evaluate(f"({fill_email_js})({json.dumps(mailbox.address)})")
        await asyncio.sleep(1.0)

        # Click continue / next button
        click_btn_js = """
        () => {
            const btns = Array.from(document.querySelectorAll('button'));
            const b = btns.find(x => /continue|sign in|sign up|next|lanjut/i.test(x.innerText));
            if (b) { b.click(); return true; }
            return false;
        }
        """
        await self.cdp.evaluate(click_btn_js)
        await asyncio.sleep(3.0)

        # 4. Fill password if password input is present
        fill_pwd_js = """
        (pwd) => {
            const inputs = Array.from(document.querySelectorAll('input[type="password"]'));
            if (inputs.length > 0) {
                const inp = inputs[0];
                inp.value = pwd;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        }
        """
        await self.cdp.evaluate(f"({fill_pwd_js})({json.dumps(password)})")
        await asyncio.sleep(1.0)
        await self.cdp.evaluate(click_btn_js)

        # 5. Wait for OTP from email
        otp = await self.wait_for_otp(mailbox, timeout=self.config.wait_seconds)
        if otp:
            self.log(f"[zai] Mengisi kode OTP: {otp}")
            fill_otp_js = """
            (code) => {
                const inputs = Array.from(document.querySelectorAll('input[type="text"], input[inputmode="numeric"]'));
                if (inputs.length > 0) {
                    const inp = inputs[inputs.length - 1];
                    inp.value = code;
                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            await self.cdp.evaluate(f"({fill_otp_js})({json.dumps(otp)})")
            await asyncio.sleep(1.5)
            await self.cdp.evaluate(click_btn_js)
            await asyncio.sleep(4.0)

        # 6. ZCode OAuth flow
        state = secrets.token_hex(16)
        oauth_url = f"{ZCODE_AUTHORIZE_URL}?client_id={ZCODE_CLIENT_ID}&redirect_uri={ZCODE_REDIRECT_URI}&response_type=code&state={state}"
        self.log(f"[zai] Membuka OAuth authorize ZCode...")
        await self.cdp.navigate(oauth_url)
        await asyncio.sleep(3.0)

        # Approve consent
        consent_js = f"""
        async () => {{
            const body = new URLSearchParams({{
                client_id: '{ZCODE_CLIENT_ID}',
                redirect_uri: '{ZCODE_REDIRECT_URI}',
                response_type: 'code',
                state: '{state}',
                action: 'approve'
            }});
            const r = await fetch('/api/oauth/authorize', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                credentials: 'include',
                body: body
            }});
            return await r.text();
        }}
        """
        consent_raw = await self.cdp.evaluate(f"({consent_js})()")
        code = None
        try:
            consent_data = json.loads(consent_raw) if consent_raw else {}
            redirect_url = consent_data.get("redirect_url", "")
            if "code=" in redirect_url:
                code = redirect_url.split("code=")[1].split("&")[0]
        except Exception:
            pass

        if not code:
            # Check current URL
            cur_url = await self.cdp.evaluate("window.location.href")
            if "code=" in cur_url:
                code = cur_url.split("code=")[1].split("&")[0]

        if not code:
            return HarvestedKey(
                platform="zai",
                email=mailbox.address,
                password=password,
                error="Gagal mendapatkan OAuth authorization code dari Z.ai",
            )

        self.log(f"[zai] Menukarkan authorization code...")
        tokens = self.exchange_zcode_token(code, state)
        zcode_jwt = tokens.get("zcodeJwtToken")
        zai_access = tokens.get("zaiAccessToken")

        if not zcode_jwt or not zai_access:
            return HarvestedKey(
                platform="zai",
                email=mailbox.address,
                password=password,
                error="OAuth token exchange tidak mengembalikan zcodeJwtToken atau zaiAccessToken",
            )

        # 7. Solve Aliyun Captcha slider for Start Plan Claim
        captcha_param = await self.solve_aliyun_captcha_interactive(timeout=self.config.aliyun_timeout)
        if captcha_param:
            self.log("[zai] Mengklaim paket Start Plan (GLM-5.3 3M tokens/hari)...")
            claimed, claim_msg = self.claim_start_plan(zcode_jwt, captcha_param)
            self.log(f"[zai] Status klaim Start Plan: {claim_msg}")
        else:
            self.log("[zai] Melewati klaim Start Plan karena captcha tidak diselesaikan.")

        # 8. Mint Business API key
        self.log("[zai] Membuat API key resmi Z.ai Coding Plan...")
        key_info = self.mint_plan_api_key(zai_access)
        plan_api_key = key_info.get("planApiKey", "")
        self.log(f"[zai] API Key berhasil didapatkan: {plan_api_key[:12]}... (Org: {key_info.get('organization')})")

        # 9. Return HarvestedKey
        return HarvestedKey(
            platform="zai",
            email=mailbox.address,
            password=password,
            api_key=plan_api_key,
        )
