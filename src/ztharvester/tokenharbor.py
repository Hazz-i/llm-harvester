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

    async def _wait_for_turnstile(self, timeout_seconds: float = 30.0) -> bool:
        """Wait for Cloudflare Turnstile token to be populated if widget is present."""
        has_widget = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"]')"
        )
        if not has_widget:
            return True

        self.log("[tokenharbor] Waiting for Cloudflare Turnstile challenge...")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            token_len = await self.cdp.evaluate(
                """(()=>{
                    const input = document.querySelector('input[name="cf-turnstile-response"]');
                    return input ? (input.value || '').length : 0;
                })()"""
            )
            if token_len and int(token_len) > 0:
                self.log("[tokenharbor] Turnstile challenge solved.")
                return True
            await self._sleep(1500)

        self.log("[tokenharbor] Turnstile wait reached timeout, continuing anyway...")
        return False

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
        await self._sleep(2500)

        # Check if redirected to dashboard (session persisted): purge and re-navigate
        curr_url = await self.cdp.evaluate("window.location.href")
        if curr_url and "dashboard" in str(curr_url):
            self.log("[tokenharbor] Session persisted, clearing storage and re-navigating...")
            if hasattr(self.cdp, "clear_session"):
                await self.cdp.clear_session(self.APP_ORIGIN)
            await self.cdp.evaluate(
                """(()=>{
                    try { localStorage.clear(); sessionStorage.clear(); } catch(e){}
                    try {
                        document.cookie.split(';').forEach(c => {
                            const n = c.split('=')[0].trim();
                            document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
                            document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.tokenharbor.ai';
                        });
                    } catch(e){}
                })()"""
            )
            await self.cdp.navigate(self.SIGNUP_URL, wait_ms=10000)
            await self._sleep(3000)

        # Wait for Next.js to hydrate the form inputs
        self.log("[tokenharbor] Waiting for signup form hydration...")
        form_ready = False
        for _ in range(15):
            has_input = await self.cdp.evaluate("!!document.querySelector('input[type=\"email\"]')")
            if has_input:
                form_ready = True
                break
            await self._sleep(1000)

        if not form_ready:
            raise RuntimeError("Signup form failed to render email input")

        # 2. Fill email and password helper
        async def _fill_credentials():
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
                })()""" % (json.dumps(email), json.dumps(password))
            )

        await _fill_credentials()
        await self._sleep(1500)

        # 3. Check if Turnstile is already present on the page
        has_turnstile = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], iframe[src*=\"challenges\"]')"
        )
        if has_turnstile:
            await self._wait_for_turnstile(timeout_seconds=20.0)

        # 4. Submit form (specifically target the submit / "Create account" button, NOT the tab switcher)
        self.log("[tokenharbor] Submitting signup form...")
        signup_ok = False
        for submit_attempt in range(1, 6):
            await _fill_credentials()

            # Click Create account submit button
            await self.cdp.evaluate(
                """(()=>{
                    const btn = document.querySelector('button[type="submit"]') ||
                                document.querySelector('button[data-analytics="login-signup"]') ||
                                [...document.querySelectorAll('button')].find(b => /^create account$/i.test((b.innerText || '').trim()));
                    if (btn && !btn.disabled) {
                        btn.click();
                        return true;
                    }
                    return false;
                })()"""
            )
            await self._sleep(4000)

            curr_url = await self.cdp.evaluate("window.location.href")
            if curr_url and "dashboard" in str(curr_url):
                signup_ok = True
                break

            # Check for error or notification message
            err_msg = await self.cdp.evaluate(
                """(()=>{
                    const p = document.querySelector('p[data-bordered="true"]');
                    if (p && p.innerText) return p.innerText.trim();
                    const alerts = [...document.querySelectorAll('p, div, span')].filter(el => {
                        const t = (el.innerText || '').trim();
                        return /bot check|human check|take a breath|fast|error|snapped|failed/i.test(t);
                    });
                    return alerts.length > 0 ? alerts[0].innerText.trim() : null;
                })()"""
            )
            if err_msg:
                self.log(f"[tokenharbor] Notice during signup: {err_msg}")
                err_lower = str(err_msg).lower()
                if "bot check" in err_lower or "snapped" in err_lower or "refresh" in err_lower:
                    self.log("[tokenharbor] Refreshing signup page after bot check notice...")
                    await self.cdp.navigate(self.SIGNUP_URL, wait_ms=10000)
                    await self._sleep(3000)
                    await _fill_credentials()
                    await self._wait_for_turnstile(timeout_seconds=25.0)
                elif "human check" in err_lower:
                    self.log("[tokenharbor] Human verification challenge active. Waiting for Turnstile...")
                    await self._wait_for_turnstile(timeout_seconds=30.0)
                    await self._sleep(1500)
                    await _fill_credentials()
                elif "take a breath" in err_lower or "fast" in err_lower:
                    await self._sleep(8000)
                    await _fill_credentials()
            else:
                await self._sleep(2000)

        if not signup_ok:
            curr_url = await self.cdp.evaluate("window.location.href")
            if not curr_url or "dashboard" not in str(curr_url):
                raise RuntimeError("Failed to reach dashboard after submitting signup form")

        # 5. On dashboard: dismiss/accept free models modal, and trigger "Verify email"
        self.log("[tokenharbor] Reached dashboard, triggering verification email...")
        await self._sleep(3000)
        await self.cdp.evaluate(
            """(()=>{
                // Click "Enable free models" if banner/modal exists
                const freeBtn = [...document.querySelectorAll('button')].find(b => /(enable free models|not now)/i.test((b.innerText || '').trim()));
                if (freeBtn) freeBtn.click();
            })()"""
        )
        await self._sleep(2000)

        # Click the "Verify email" button on the dashboard banner (retry up to 5 times)
        verified_clicked = False
        for _ in range(5):
            verified_clicked = await self.cdp.evaluate(
                """(()=>{
                    const btn = [...document.querySelectorAll('button')].find(b => /verify email/i.test((b.innerText || '').trim()));
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    return false;
                })()"""
            )
            if verified_clicked:
                break
            await self._sleep(2000)
        self.log(f"[tokenharbor] Clicked dashboard 'Verify email' button ({bool(verified_clicked)})")
        await self._sleep(3000)

        # 7. Wait for verification email from mail.tm
        self.log("[tokenharbor] Waiting for verification email from mail.tm...")
        msg = await self.mail.wait_for_message(
            mailbox,
            timeout=self.config.wait_seconds,
            interval=4.0,
            match_sender="tokenharbor",
        )
        if not msg:
            # Fallback without sender filter
            msg = await self.mail.wait_for_message(
                mailbox,
                timeout=20.0,
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
