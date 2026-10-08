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
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.api_key) and self.error is None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "platform": self.platform,
            "email": self.email,
            "password": self.password,
            "api_key": self.api_key,
            "created_at": self.created_at,
            "error": self.error,
        }
        if self.extra:
            out["extra"] = self.extra
        return out


def _rand_key_name(prefix: str = "prod-th") -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{prefix}-{suffix}"


class TokenHarborCreator:
    """Automates the Token Harbor registration and API key harvesting."""

    APP_ORIGIN = "https://tokenharbor.ai"
    SIGNUP_URL = "https://tokenharbor.ai/login?mode=signup"
    DASHBOARD_URL = "https://tokenharbor.ai/dashboard"
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
        # Wait up to 6 seconds for widget/input to mount in DOM
        widget_deadline = time.monotonic() + 6.0
        while time.monotonic() < widget_deadline:
            has_widget = await self.cdp.evaluate(
                "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"], [id*=\"turnstile\" i], [class*=\"turnstile\" i]')"
            )
            if has_widget:
                break
            await self._sleep(800)

        has_widget = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"], [id*=\"turnstile\" i], [class*=\"turnstile\" i]')"
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

    async def _enable_free_models(self, attempts: int = 6) -> bool:
        """Turn ON the dashboard "Free models enabled" toggle (Data & privacy card).

        Token Harbor's free models stay disabled until this switch is flipped, so
        after a key is generated we visit the dashboard and make sure it is on.
        """
        self.log("[tokenharbor] Ensuring 'Free models enabled' toggle is ON...")
        try:
            await self.cdp.navigate(self.DASHBOARD_URL, wait_ms=8000)
        except Exception as exc:
            self.log(f"[tokenharbor] Dashboard navigation for free models failed: {exc}")
            return False
        await self._sleep(2500)

        toggle_js = r"""(()=>{
            const norm = (s) => (s || '').trim().toLowerCase();
            const meta = (el) => norm(el.getAttribute('aria-label')) + ' ' +
                                 norm(el.getAttribute('name')) + ' ' +
                                 norm(el.getAttribute('id'));
            const switchers = '[role="switch"], input[type="checkbox"], button[aria-checked]';

            // 1) Direct switch lookup by accessible name/id/name.
            let sw = [...document.querySelectorAll(switchers)]
                .find(el => meta(el).includes('free model'));
            if (!sw) {
                // 2) Looser match on "free".
                sw = [...document.querySelectorAll(switchers)]
                    .find(el => meta(el).includes('free model') || meta(el).includes('free models'));
            }
            // 3) Fallback: find the "Free models enabled" label and walk up to its card.
            if (!sw) {
                const leaves = [...document.querySelectorAll('*')]
                    .filter(el => el.children.length === 0 && /free models? enabled/i.test((el.textContent || '').trim()));
                for (const leaf of leaves) {
                    let anc = leaf;
                    for (let i = 0; i < 6 && anc; i++, anc = anc.parentElement) {
                        const cand = anc.querySelector(switchers);
                        if (cand) { sw = cand; break; }
                    }
                    if (sw) break;
                }
            }
            if (!sw) return { found: false };

            const read = () => {
                if (sw.tagName === 'INPUT' && sw.type === 'checkbox') return !!sw.checked;
                const aria = sw.getAttribute('aria-checked');
                if (aria !== null) return aria === 'true';
                const ds = sw.getAttribute('data-state');
                if (ds !== null) return ds === 'checked';
                return null;
            };

            const wasOn = read();
            if (wasOn !== true) {
                try { sw.scrollIntoView({ block: 'center' }); } catch (e) {}
                try { sw.click(); } catch (e) {}
            }
            return { found: true, wasOn: wasOn, nowOn: read(), clicked: wasOn !== true };
        })()"""

        for attempt in range(1, attempts + 1):
            try:
                res = await self.cdp.evaluate(toggle_js)
            except Exception as exc:
                self.log(f"[tokenharbor] Free models toggle probe failed: {exc}")
                await self._sleep(1500)
                continue

            if isinstance(res, dict) and res.get("found"):
                if res.get("nowOn") is True or res.get("wasOn") is True:
                    self.log("[tokenharbor] Free models are enabled.")
                    return True
                # Switch state unreadable but we clicked it; assume it applied.
                if res.get("nowOn") is None and res.get("clicked"):
                    self.log("[tokenharbor] Free models toggle clicked (state not readable).")
                    return True
            else:
                self.log(f"[tokenharbor] Free models toggle not visible yet (attempt {attempt}/{attempts})...")
            await self._sleep(1500)

        self.log("[tokenharbor] Could not confirm 'Free models enabled' toggle state.")
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

        # Check if Turnstile challenge is active before inputs render
        has_turnstile = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"]')"
        )
        if has_turnstile:
            self.log("[tokenharbor] Turnstile challenge detected prior to form inputs, waiting for verification...")
            await self._wait_for_turnstile(timeout_seconds=25.0)

        # Wait for Next.js to hydrate the form inputs and ensure Sign up tab is active
        self.log("[tokenharbor] Waiting for signup form hydration...")
        form_ready = False
        for _ in range(25):
            # Ensure "Sign up" tab is selected (not "Sign in")
            await self.cdp.evaluate("""(()=>{
                const btns = Array.from(document.querySelectorAll('button, a, [role="tab"]'));
                const signupBtn = btns.find(b => {
                    const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                    return txt === 'sign up' || txt === 'register' || txt === 'create account';
                });
                const isCreateAcct = !!document.querySelector('button[type="submit"]')?.innerText?.toLowerCase()?.includes('create');
                const hasInvite = !!document.querySelector('input[name="invite_code"]');
                if (signupBtn && (!isCreateAcct && !hasInvite)) {
                    signupBtn.click();
                }
            })()""")

            has_inputs = await self.cdp.evaluate(
                "!!document.querySelector('input[name=\"email\"], input[type=\"email\"]') && !!document.querySelector('input[name=\"password\"], input[type=\"password\"]')"
            )
            if has_inputs:
                form_ready = True
                break
            await self._sleep(1000)

        if not form_ready:
            page_info = await self.cdp.evaluate("""(()=>{
                return {
                    url: window.location.href,
                    title: document.title,
                    inputs: Array.from(document.querySelectorAll('input')).map(i => ({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder})),
                    buttons: Array.from(document.querySelectorAll('button')).map(b => (b.innerText || b.textContent || '').trim()).slice(0, 5)
                };
            })()""")
            self.log(f"[tokenharbor] Form hydration failed. Page state: {page_info}")
            raise RuntimeError(f"Signup form failed to render inputs (URL: {page_info.get('url') if isinstance(page_info, dict) else 'unknown'})")

        # 2. Robust Credential Fill Function
        async def _fill_credentials():
            # Ensure signup tab is active
            await self.cdp.evaluate("""(()=>{
                const btns = Array.from(document.querySelectorAll('button, a'));
                const signupBtn = btns.find(b => (b.innerText || b.textContent || '').trim().toLowerCase() === 'sign up');
                const isCreateAcct = !!document.querySelector('button[type="submit"]')?.innerText?.toLowerCase()?.includes('create');
                if (signupBtn && !isCreateAcct) signupBtn.click();
            })()""")
            await self._sleep(300)

            # Type email using type_text (Input.insertText + React sync)
            await self.cdp.type_text('input[name="email"], input[type="email"]', email)
            await self._sleep(300)

            # Type password using type_text (Input.insertText + React sync)
            await self.cdp.type_text('input[name="password"], input[type="password"]', password)
            await self._sleep(500)

            # Verify and fallback if either field didn't retain value
            vals = await self.cdp.evaluate("""(()=>{
                const em = document.querySelector('input[name="email"], input[type="email"]');
                const pw = document.querySelector('input[name="password"], input[type="password"]');
                return {
                    em_len: em ? (em.value || '').length : 0,
                    pw_len: pw ? (pw.value || '').length : 0
                };
            })()""")
            if not isinstance(vals, dict) or vals.get("em_len", 0) == 0 or vals.get("pw_len", 0) == 0:
                self.log(f"[tokenharbor] Reinforcing credentials into DOM (current: em={vals.get('em_len') if isinstance(vals, dict) else 0}, pw={vals.get('pw_len') if isinstance(vals, dict) else 0})...")
                await self.cdp.evaluate("""(()=>{
                    function setInput(el, val) {
                        if (!el) return;
                        el.focus();
                        const proto = Object.getPrototypeOf(el);
                        const s = (Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'))?.set;
                        if (s) s.call(el, val); else el.value = val;
                        if (el._valueTracker) el._valueTracker.setValue('');
                        el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
                    }
                    setInput(document.querySelector('input[name="email"], input[type="email"]'), %s);
                    setInput(document.querySelector('input[name="password"], input[type="password"]'), %s);
                })()""" % (json.dumps(email), json.dumps(password)))

        await _fill_credentials()
        await self._sleep(1500)

        # 3. Always wait for Cloudflare Turnstile token before submitting
        await self._wait_for_turnstile(timeout_seconds=25.0)
        # Natural human pause after Turnstile is solved to avoid "take a breath / too fast" rate-limiting
        await self._sleep(2000)

        # 4. Submit form
        self.log("[tokenharbor] Submitting signup form...")
        signup_ok = False
        for submit_attempt in range(1, 6):
            # Verify credentials are still present before clicking submit
            creds_ok = await self.cdp.evaluate("""(()=>{
                const em = document.querySelector('input[name="email"], input[type="email"]');
                const pw = document.querySelector('input[name="password"], input[type="password"]');
                return Boolean(em && em.value && em.value.length > 0 && pw && pw.value && pw.value.length >= 8);
            })()""")
            if not creds_ok:
                self.log("[tokenharbor] Inputs empty or cleared, re-filling before submit...")
                await _fill_credentials()
                await self._sleep(1000)

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
            await self._sleep(4500)

            curr_url = await self.cdp.evaluate("window.location.href")
            if curr_url and "dashboard" in str(curr_url):
                signup_ok = True
                break

            # Check for error or notification message on leaf elements (avoid matching page container)
            err_msg = await self.cdp.evaluate(
                """(()=>{
                    const p = document.querySelector('p[data-bordered="true"]');
                    if (p && p.innerText) return p.innerText.trim();
                    const alerts = [...document.querySelectorAll('p, div, span')].filter(el => {
                        if (el.children.length > 0) return false;
                        const t = (el.innerText || '').trim();
                        return t.length > 0 && t.length < 250 && /bot check|human check|take a breath|fast|error|snapped|failed|couldn't create/i.test(t);
                    });
                    return alerts.length > 0 ? alerts[0].innerText.trim() : null;
                })()"""
            )
            if err_msg:
                self.log(f"[tokenharbor] Notice during signup: {err_msg}")
                err_lower = str(err_msg).lower()
                if "too many sign-ups" in err_lower or "too many signups" in err_lower or "couldn't create" in err_lower:
                    raise RuntimeError(f"Rate limited or blocked by Token Harbor: {err_msg}. Use proxy pool or Cloudflare WARP to rotate IP.")
                elif "take a breath" in err_lower or "fast" in err_lower:
                    self.log("[tokenharbor] Backing off 8s due to pace throttle...")
                    await self._sleep(8000)
                elif "human check" in err_lower:
                    self.log("[tokenharbor] Human verification requested. Waiting for Turnstile...")
                    await self._wait_for_turnstile(timeout_seconds=25.0)
                    await self._sleep(2500)
                elif "bot check" in err_lower or "snapped" in err_lower:
                    self.log("[tokenharbor] Refreshing signup page after bot check notice...")
                    await self.cdp.navigate(self.SIGNUP_URL, wait_ms=10000)
                    await self._sleep(3000)
                    await _fill_credentials()
                    await self._sleep(2000)
                    await self._wait_for_turnstile(timeout_seconds=25.0)
                    await self._sleep(2500)
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

        # Turn ON the "Free models enabled" toggle so free models work right away.
        await self._enable_free_models()

        return HarvestedKey(
            platform="tokenharbor",
            email=email,
            password=password,
            api_key=api_key,
        )
