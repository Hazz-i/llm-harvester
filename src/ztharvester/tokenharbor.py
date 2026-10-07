"""Token Harbor account creator driver.

Drives the Token Harbor web sign-up, email verification via mail.tm,
and harvests the resulting thk_live_... API key using Chrome DevTools Protocol (CDP).
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

from .config import TokenHarborConfig
from .mail import MailProvider, Mailbox
from .zerotwo import CDP

VERIFY_LINK_RE = re.compile(r"https?://(?:www\.)?tokenharbor\.ai/verify-email\?token=[^\s\"'<>]+", re.IGNORECASE)
API_KEY_RE = re.compile(r"thk_live_[a-zA-Z0-9_\-]+")


@dataclass
class HarvestedKey:
    platform: str
    email: str
    password: str
    api_key: str = ""
    created_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.api_key) and self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "email": self.email,
            "password": self.password,
            "api_key": self.api_key,
            "created_at": self.created_at,
            "error": self.error,
        }


def _rand_key_name(prefix: str = "prod-th") -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{prefix}-{suffix}"


class TokenHarborCreator:
    """Automates the Token Harbor registration and API key harvesting."""

    APP_ORIGIN = "https://tokenharbor.ai"
    SIGNUP_URL = "https://tokenharbor.ai/login?mode=signup"
    DASHBOARD_KEYS_URL = "https://tokenharbor.ai/dashboard/api-keys"

    def __init__(
        self,
        cdp: CDP,
        mail: MailProvider,
        config: TokenHarborConfig | None = None,
        log: Any = print,
    ) -> None:
        self.cdp = cdp
        self.mail = mail
        self.config = config or TokenHarborConfig()
        self.log = log

    async def _sleep(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)

    async def _reset_session(self) -> None:
        """Clear local/session storage and cookies for tokenharbor."""
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

    async def create_account(self) -> HarvestedKey:
        """Create a Token Harbor account, verify via mail.tm, and harvest the API key."""
        retries = max(1, self.config.max_retries)
        last_error = ""

        for attempt in range(1, retries + 1):
            try:
                return await self._create_single_account()
            except Exception as exc:
                last_error = str(exc)
                self.log(f"[tokenharbor] Attempt {attempt}/{retries} failed: {exc}")
                if attempt < retries:
                    await self._sleep(3000)

        return HarvestedKey(
            platform="tokenharbor",
            email="",
            password="",
            error=last_error or "Unknown failure",
        )

    async def _create_single_account(self) -> HarvestedKey:
        self.log("[tokenharbor] Creating disposable mailbox...")
        mailbox = await self.mail.create_mailbox(prefix="th")
        email = mailbox.address
        password = mailbox.password
        self.log(f"[tokenharbor] Mailbox ready: {email}")

        await self._reset_session()

        # 1. Navigate to signup page
        self.log(f"[tokenharbor] Navigating to signup: {self.SIGNUP_URL}")
        await self.cdp.navigate(self.SIGNUP_URL, wait_ms=10000)
        await self._sleep(2000)

        # 2. Fill email and password
        await self.cdp.evaluate(
            """(()=>{
                const em = document.querySelector('input[type="email"]') || document.querySelector('#email') || document.querySelector('input[name="email"]');
                if (em) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(em, %s);
                    em.dispatchEvent(new Event('input', {bubbles: true}));
                    em.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const pw = document.querySelector('input[type="password"]') || document.querySelector('#password') || document.querySelector('input[name="password"]');
                if (pw) {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(pw, %s);
                    pw.dispatchEvent(new Event('input', {bubbles: true}));
                    pw.dispatchEvent(new Event('change', {bubbles: true}));
                }
                return !!(em && pw);
            })()""" % (json.dumps(email), json.dumps(password))
        )
        await self._sleep(1000)

        # 3. Submit signup form
        submitted = await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')]
                    .find(b => /(create account|sign up|daftar)/i.test(b.innerText || ''));
                if (btn) { btn.click(); return true; }
                const form = document.querySelector('form');
                if (form) { form.submit(); return true; }
                return false;
            })()"""
        )
        self.log(f"[tokenharbor] Signup form submitted ({submitted})")
        await self._sleep(4000)

        # If a "Verify email" trigger button exists on screen, click it
        await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')]
                    .find(b => /verify email/i.test(b.innerText || ''));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )

        # 4. Wait for email verification link from mail.tm
        self.log("[tokenharbor] Waiting for verification email from mail.tm...")
        msg = await self.mail.wait_for_message(
            mailbox,
            timeout=self.config.wait_seconds,
            interval=4.0,
            match="token harbor",
        )
        if not msg:
            # Fallback without match filter
            msg = await self.mail.wait_for_message(
                mailbox,
                timeout=15.0,
                interval=3.0,
            )

        if not msg:
            raise RuntimeError("Timed out waiting for Token Harbor verification email")

        content = (msg.text or "") + "\n" + (msg.html or "")
        match = VERIFY_LINK_RE.search(content)
        if not match:
            raise RuntimeError(f"Could not find verification link in email content (length {len(content)})")

        verify_url = match.group(0)
        self.log(f"[tokenharbor] Found verification link: {verify_url}")

        # 5. Open verification link
        await self.cdp.navigate(verify_url, wait_ms=10000)
        await self._sleep(3000)

        # 6. Navigate to dashboard API keys page
        self.log(f"[tokenharbor] Navigating to API keys page: {self.DASHBOARD_KEYS_URL}")
        await self.cdp.navigate(self.DASHBOARD_KEYS_URL, wait_ms=8000)
        await self._sleep(2500)

        # 7. Click "+ New key" or "Create key"
        await self.cdp.evaluate(
            r"""(()=>{
                const btn = [...document.querySelectorAll('button,a')]
                    .find(b => /(new key|\+ new key|create key)/i.test((b.innerText || '').trim()));
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

        # 9. Click Confirm / Create key
        await self.cdp.evaluate(
            """(()=>{
                const btn = [...document.querySelectorAll('button')]
                    .find(b => /(create key|generate key|submit|save)/i.test((b.innerText || '').trim()));
                if (btn) { btn.click(); return true; }
                return false;
            })()"""
        )
        await self._sleep(3000)

        # 10. Extract the generated API key (thk_live_...)
        api_key = ""
        for _ in range(8):
            extracted = await self.cdp.evaluate(
                r"""(()=>{
                    const code = document.querySelector('code') || document.querySelector('.font-mono');
                    if (code && code.innerText.includes('thk_live_')) {
                        return code.innerText.trim();
                    }
                    const inputs = [...document.querySelectorAll('input')];
                    for (const inp of inputs) {
                        if (inp.value && inp.value.includes('thk_live_')) {
                            return inp.value.trim();
                        }
                    }
                    const match = (document.body.innerText || '').match(/thk_live_[a-zA-Z0-9_\-]+/);
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
            # Check whole body as fallback
            body = await self.cdp.evaluate("document.body.innerText")
            match = API_KEY_RE.search(body or "")
            if match:
                api_key = match.group(0)

        if not api_key:
            raise RuntimeError("API key thk_live_ not found after creating key in dashboard")

        self.log(f"[tokenharbor] Successfully harvested API key: {api_key[:12]}...")
        return HarvestedKey(
            platform="tokenharbor",
            email=email,
            password=password,
            api_key=api_key,
        )
