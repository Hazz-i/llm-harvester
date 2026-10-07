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
    REGISTER_URL = "https://tokenmix.ai/register"
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
            await self.cdp.navigate("about:blank", wait_ms=2000)
            if hasattr(self.cdp, "_send"):
                try:
                    await self.cdp._send(
                        "Storage.clearDataForOrigin",
                        {"origin": self.APP_ORIGIN, "storageTypes": "all"},
                    )
                    await self.cdp._send("Network.clearBrowserCookies", {})
                except Exception:
                    pass
        except Exception:
            pass

    async def _wait_for_turnstile(self, timeout_seconds: float = 40.0) -> bool:
        """Wait for Cloudflare Turnstile token to be populated if widget is present."""
        has_widget = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile]')"
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

        # 1. Navigate to registration page
        self.log(f"[tokenmix] Navigating to register: {self.REGISTER_URL}")
        await self.cdp.navigate(self.REGISTER_URL, wait_ms=10000)
        await self._sleep(2000)

        # 2. Fill registration form
        await self.cdp.evaluate(
            """(()=>{
                const em = document.querySelector('input[type="email"]') || document.querySelector('input[name="email"]');
                if (em) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(em, %s);
                    em.dispatchEvent(new Event('input', {bubbles: true}));
                    em.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const pw = document.querySelector('input[type="password"]') || document.querySelector('input[name="password"]');
                if (pw) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(pw, %s);
                    pw.dispatchEvent(new Event('input', {bubbles: true}));
                    pw.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const ref = document.querySelector('input[name="referral"]') || document.querySelector('input[name="ref"]');
                if (ref && %s) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(ref, %s);
                    ref.dispatchEvent(new Event('input', {bubbles: true}));
                    ref.dispatchEvent(new Event('change', {bubbles: true}));
                }
                return !!(em && pw);
            })()""" % (
                json.dumps(email),
                json.dumps(password),
                json.dumps(self.config.referral_code or ""),
                json.dumps(self.config.referral_code or ""),
            )
        )
        await self._sleep(1000)

        # 3. Wait for Turnstile
        await self._wait_for_turnstile(timeout_seconds=40.0)

        # 4. Submit registration
        self.log("[tokenmix] Submitting registration form...")
        await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')]
                    .find(b => /(register|sign up|create account|daftar)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                const form = document.querySelector('form');
                if (form) { form.submit(); return true; }
                return false;
            })()"""
        )
        await self._sleep(4000)

        # 5. Wait for verification email from mail.tm
        self.log("[tokenmix] Waiting for verification email from mail.tm...")
        msg = await self.mail.wait_for_message(
            mailbox,
            timeout=self.config.wait_seconds,
            interval=4.0,
            match="tokenmix",
        )
        if not msg:
            # Fallback without match filter
            msg = await self.mail.wait_for_message(
                mailbox,
                timeout=15.0,
                interval=3.0,
            )

        if not msg:
            raise RuntimeError("Timed out waiting for TokenMix verification email")

        content = (msg.text or "") + "\n" + (msg.html or "")

        # Check for link verification
        link_match = VERIFY_LINK_RE.search(content)
        if link_match:
            verify_url = link_match.group(0)
            self.log(f"[tokenmix] Navigating to verification link: {verify_url}")
            await self.cdp.navigate(verify_url, wait_ms=10000)
            await self._sleep(2500)
        else:
            # Check for 6-digit OTP code
            code_match = OTP_CODE_RE.search(content)
            if code_match:
                otp_code = code_match.group(1)
                self.log(f"[tokenmix] Submitting verification OTP code: {otp_code}")
                await self.cdp.evaluate(
                    """(()=>{
                        const input = document.querySelector('input[name="code"]') ||
                                      document.querySelector('input[type="text"]') ||
                                      document.querySelector('input[placeholder*="code" i]');
                        if (input) {
                            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                            setter.call(input, %s);
                            input.dispatchEvent(new Event('input', {bubbles: true}));
                            input.dispatchEvent(new Event('change', {bubbles: true}));
                            return true;
                        }
                        return false;
                    })()""" % json.dumps(otp_code)
                )
                await self._sleep(1000)
                await self.cdp.evaluate(
                    """(()=>{
                        const btn = [...document.querySelectorAll('button')]
                            .find(b => /(verify|confirm|submit|lanjut)/i.test((b.innerText || '').trim()));
                        if (btn) btn.click();
                    })()"""
                )
                await self._sleep(3000)

        # 6. Navigate to API keys dashboard
        self.log(f"[tokenmix] Navigating to API keys dashboard: {self.DASHBOARD_KEYS_URL}")
        await self.cdp.navigate(self.DASHBOARD_KEYS_URL, wait_ms=8000)
        await self._sleep(2500)

        # 7. Click "+ Create Key" / "+ New Key"
        await self.cdp.evaluate(
            r"""(()=>{
                const btn = [...document.querySelectorAll('button,a')]
                    .find(b => /(new key|\+ new key|create key|\+ create key)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(1500)

        # 8. Type key name
        key_name = _rand_key_name(self.config.key_name_prefix)
        await self.cdp.evaluate(
            """(()=>{
                const input = document.querySelector('input[placeholder*="key" i]') ||
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

        # 9. Click Confirm / Save
        await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')]
                    .find(b => /(create key|generate key|submit|save|confirm)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(3000)

        # 10. Extract the generated API key (sk-tm-...)
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
