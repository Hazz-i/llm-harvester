"""TokenMix account creator driver.

Drives TokenMix web registration, solves Cloudflare Turnstile via browser CDP,
verifies accounts with disposable mailboxes from mail.tm, and harvests sk-tm-... API keys.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import string
import time
from typing import Any

from .config import TokenMixConfig
from .mail import MailProvider, Mailbox
from .tokenharbor import HarvestedKey
from .zerotwo import CDP

VERIFY_LINK_RE = re.compile(r"https?://(?:www\.)?tokenmix\.ai/(?:verify|auth/verify)[^\s\"'<>]+", re.IGNORECASE)
OTP_CODE_RE = re.compile(r"\b([0-9]{6})\b")
API_KEY_RE = re.compile(r"sk-tm-[a-zA-Z0-9_\-]+")


def _rand_key_name(prefix: str = "prod-tm") -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{prefix}-{suffix}"


class TokenMixCreator:
    """Automates TokenMix registration, Turnstile clearing, and API key harvesting."""

    APP_ORIGIN = "https://tokenmix.ai"
    LOGIN_URL = "https://tokenmix.ai/login"
    DASHBOARD_KEYS_URL = "https://tokenmix.ai/dashboard/keys"

    def __init__(
        self,
        cdp: CDP,
        mail: MailProvider,
        config: TokenMixConfig | None = None,
        log: Any = print,
    ) -> None:
        self.cdp = cdp
        self.mail = mail
        self.config = config or TokenMixConfig()
        self.log = log

    async def _sleep(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)

    async def _reset_session(self) -> None:
        """Clear local storage, session storage, and cookies for tokenmix.ai."""
        try:
            if hasattr(self.cdp, "clear_session"):
                await self.cdp.clear_session(self.APP_ORIGIN)
            elif hasattr(self.cdp, "_send"):
                try:
                    await self.cdp._send(
                        "Storage.clearDataForOrigin",
                        {"origin": self.APP_ORIGIN, "storageTypes": "all"},
                        session=True,
                    )
                    await self.cdp._send("Network.clearBrowserCookies", {}, session=True)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            await self.cdp.navigate("about:blank", wait_ms=1000)
            await self.cdp.evaluate(
                """(()=>{
                    try { localStorage.clear(); sessionStorage.clear(); } catch(e){}
                    try {
                        document.cookie.split(';').forEach(c => {
                            const n = c.split('=')[0].trim();
                            document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
                            document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.tokenmix.ai';
                        });
                    } catch(e){}
                })()"""
            )
        except Exception:
            pass

    async def _wait_for_turnstile(self, timeout_seconds: float = 35.0) -> bool:
        """Wait for Cloudflare Turnstile token to be populated if widget is present."""
        has_widget = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"]')"
        )
        if not has_widget:
            return True

        self.log("[tokenmix] Waiting for Cloudflare Turnstile challenge...")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            token_len = await self.cdp.evaluate(
                """(()=>{
                    const input = document.querySelector('input[name="cf-turnstile-response"]');
                    return input ? (input.value || '').length : 0;
                })()"""
            )
            if token_len and int(token_len) > 0:
                self.log("[tokenmix] Turnstile challenge solved.")
                return True
            await self._sleep(1500)

        self.log("[tokenmix] Turnstile wait reached timeout, continuing anyway...")
        return False

    async def create_account(self) -> HarvestedKey:
        """Create a TokenMix account and harvest an API key."""
        retries = max(1, self.config.max_retries)
        last_error = ""

        for attempt in range(1, retries + 1):
            try:
                return await self._create_single_account()
            except Exception as exc:
                last_error = str(exc)
                self.log(f"[tokenmix] Attempt {attempt}/{retries} failed: {exc}")
                if attempt < retries:
                    await self._sleep(3000)

        return HarvestedKey(
            platform="tokenmix",
            email="",
            password="",
            error=last_error or "Unknown failure",
        )

    async def _create_single_account(self) -> HarvestedKey:
        self.log("[tokenmix] Creating disposable mailbox...")
        mailbox = await self.mail.create_mailbox(prefix="tm")
        email = mailbox.address
        password = mailbox.password
        self.log(f"[tokenmix] Mailbox ready: {email}")

        await self._reset_session()

        # 1. Navigate to auth page
        self.log(f"[tokenmix] Navigating to login/register: {self.LOGIN_URL}")
        await self.cdp.navigate(self.LOGIN_URL, wait_ms=10000)
        await self._sleep(2500)

        # 2. Switch to Register tab
        self.log("[tokenmix] Switching to Register tab...")
        await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')].find(b => /(register|daftar)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(1500)

        # 3. Fill email and referral code
        await self.cdp.evaluate(
            """(()=>{
                const em = document.querySelector('#reg-email') || document.querySelector('input[type="email"]') || document.querySelector('input[name="email"]');
                if (em) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(em, %s);
                    em.dispatchEvent(new Event('input', {bubbles: true}));
                    em.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const ref = document.querySelector('#reg-referral') || document.querySelector('input[name="referral"]');
                if (ref && %s) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(ref, %s);
                    ref.dispatchEvent(new Event('input', {bubbles: true}));
                    ref.dispatchEvent(new Event('change', {bubbles: true}));
                }
            })()""" % (
                json.dumps(email),
                json.dumps(self.config.referral_code or ""),
                json.dumps(self.config.referral_code or ""),
            )
        )
        await self._sleep(1000)

        # 4. Wait for Turnstile before requesting verification code
        await self._wait_for_turnstile(timeout_seconds=30.0)

        # 5. Click "Send code" button
        self.log("[tokenmix] Requesting verification OTP code...")
        await self.cdp.evaluate(
            """(()=>{
                const codeInp = document.querySelector('#reg-code');
                if (codeInp && codeInp.parentElement) {
                    const btn = codeInp.parentElement.querySelector('button');
                    if (btn && !btn.disabled) { btn.click(); return true; }
                }
                const btn = [...document.querySelectorAll('button')].find(b => /(send code|kirim kode|send|kirim)/i.test((b.innerText||'').trim()));
                if (btn && !btn.disabled) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(2500)

        # 6. Wait for verification email from mail.tm
        self.log("[tokenmix] Waiting for verification email from mail.tm...")
        msg = await self.mail.wait_for_message(
            mailbox,
            timeout=self.config.wait_seconds,
            interval=3.0,
            match="tokenmix",
        )
        if not msg:
            msg = await self.mail.wait_for_message(
                mailbox,
                timeout=15.0,
                interval=3.0,
            )

        if not msg:
            raise RuntimeError("Timed out waiting for TokenMix verification email")

        content = (msg.text or "") + "\n" + (msg.html or "")
        code_match = OTP_CODE_RE.search(content)
        if not code_match:
            # Try finding any 6-digit code in email
            all_digits = re.findall(r"\b\d{6}\b", content)
            otp_code = all_digits[0] if all_digits else None
        else:
            otp_code = code_match.group(1)

        if not otp_code:
            raise RuntimeError("Failed to parse 6-digit verification code from email")

        self.log(f"[tokenmix] Received verification OTP code: {otp_code}")

        # 7. Fill OTP, Password, Confirm Password, and agree to terms
        await self.cdp.evaluate(
            """(()=>{
                const codeInp = document.querySelector('#reg-code') || document.querySelector('input[placeholder*="code" i]');
                if (codeInp) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(codeInp, %s);
                    codeInp.dispatchEvent(new Event('input', {bubbles: true}));
                    codeInp.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const pw = document.querySelector('#reg-password') || document.querySelector('input[type="password"]');
                if (pw) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(pw, %s);
                    pw.dispatchEvent(new Event('input', {bubbles: true}));
                    pw.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const pwConf = document.querySelector('#reg-confirm') || [...document.querySelectorAll('input[type="password"]')].pop();
                if (pwConf) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(pwConf, %s);
                    pwConf.dispatchEvent(new Event('input', {bubbles: true}));
                    pwConf.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const terms = document.querySelector('#agree-terms') || document.querySelector('input[type="checkbox"]');
                if (terms && !terms.checked) {
                    terms.click();
                }
            })()""" % (
                json.dumps(otp_code),
                json.dumps(password),
                json.dumps(password),
            )
        )
        await self._sleep(1500)

        # 8. Check Turnstile again if renewed before submit
        await self._wait_for_turnstile(timeout_seconds=20.0)

        # 9. Submit registration form
        self.log("[tokenmix] Submitting registration form...")
        await self.cdp.evaluate(
            """(()=>{
                const btn = document.querySelector('form button[type="submit"]') ||
                            [...document.querySelectorAll('button')].find(b => /(create account|register|sign up|daftar)/i.test((b.innerText || '').trim()));
                if (btn && !btn.disabled) { btn.click(); return true; }
                const form = document.querySelector('form');
                if (form) { form.submit(); return true; }
                return false;
            })()"""
        )
        await self._sleep(4000)

        # 10. Check if dashboard reached or error occurred
        dashboard_ok = False
        for _ in range(10):
            curr_url = await self.cdp.evaluate("window.location.href")
            has_token = await self.cdp.evaluate("!!localStorage.getItem('access_token')")
            if (curr_url and "dashboard" in str(curr_url)) or has_token:
                dashboard_ok = True
                break
            await self._sleep(1500)

        if not dashboard_ok:
            err_msg = await self.cdp.evaluate(
                """(()=>{
                    const toast = document.querySelector('[role="status"], [role="alert"], .toast');
                    if (toast) return toast.innerText.trim();
                    const p = [...document.querySelectorAll('p, div, span')].find(el => /(error|failed|gagal|invalid|already exists)/i.test(el.innerText || ''));
                    return p ? p.innerText.trim() : null;
                })()"""
            )
            if err_msg:
                raise RuntimeError(f"Registration failed with notice: {err_msg}")

        self.log("[tokenmix] Reached dashboard, navigating to API keys...")

        # 11. Navigate to API keys dashboard
        self.log(f"[tokenmix] Navigating to API keys dashboard: {self.DASHBOARD_KEYS_URL}")
        await self.cdp.navigate(self.DASHBOARD_KEYS_URL, wait_ms=10000)
        await self._sleep(3000)

        # 12. Click "+ Create Key" / "+ New Key"
        self.log("[tokenmix] Opening Create Key modal...")
        await self.cdp.evaluate(
            r"""(()=>{
                const btn = [...document.querySelectorAll('button,a')]
                    .find(b => /(create key|\+ create key|new key|\+ new key)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(2000)

        # 13. Type key name in modal
        key_name = _rand_key_name(self.config.key_name_prefix)
        await self.cdp.evaluate(
            """(()=>{
                const input = document.querySelector('.tm-panel input[type="text"]') ||
                              document.querySelector('input[placeholder*="key" i]') ||
                              document.querySelector('input[name="name"]') ||
                              document.querySelector('input[type="text"]');
                if (input) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(input, %s);
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    input.focus();
                    return true;
                }
                return false;
            })()""" % json.dumps(key_name)
        )
        await self._sleep(1000)

        # 14. Click Confirm / Create Key in modal
        await self.cdp.evaluate(
            """(()=>{
                const modal = document.querySelector('.tm-panel') || document.body;
                const btn = [...modal.querySelectorAll('button')]
                    .find(b => /(create key|generate key|submit|save|confirm)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(3000)

        # 15. Extract the generated API key (sk-tm-...)
        api_key = ""
        for _ in range(8):
            extracted = await self.cdp.evaluate(
                r"""(()=>{
                    const code = document.querySelector('code') || document.querySelector('.font-mono');
                    if (code && code.innerText.includes('sk-tm-')) {
                        return code.innerText.trim();
                    }
                    const inputs = [...document.querySelectorAll('input')];
                    for (const inp of inputs) {
                        if (inp.value && inp.value.includes('sk-tm-')) {
                            return inp.value.trim();
                        }
                    }
                    const match = (document.body.innerText || '').match(/sk-tm-[a-zA-Z0-9_\-]+/);
                    return match ? match[0] : null;
                })()"""
            )
            if extracted:
                match = API_KEY_RE.search(str(extracted))
                if match:
                    api_key = match.group(0)
                    break
            await self._sleep(1500)

        if not api_key:
            body = await self.cdp.evaluate("document.body.innerText")
            match = API_KEY_RE.search(body or "")
            if match:
                api_key = match.group(0)

        if not api_key:
            raise RuntimeError("API key sk-tm- not found after creating key in dashboard")

        self.log(f"[tokenmix] Successfully harvested API key: {api_key[:12]}...")
        return HarvestedKey(
            platform="tokenmix",
            email=email,
            password=password,
            api_key=api_key,
        )

