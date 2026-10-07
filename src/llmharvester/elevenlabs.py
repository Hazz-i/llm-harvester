"""ElevenLabs account creator driver.

Drives ElevenLabs web sign-up, Cloudflare Turnstile verification,
email verification via mail.tm (or optional IMAP catch-all),
onboarding wizard bypass, and harvests xi-api-key using Chrome DevTools Protocol (CDP).
"""

from __future__ import annotations

import asyncio
import email
import email.message
import html
import imaplib
import json
import re
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import ElevenLabsConfig
from .mail import MailProvider, Mailbox
from .tokenharbor import HarvestedKey
from .zerotwo import CDP

VERIFY_LINK_RE = re.compile(
    r"https?://(?:www\.)?elevenlabs\.io/(?:app/action\?[^\s\"'<>]+|[^\s\"'<>]*(?:verify|confirm)[^\s\"'<>]+)",
    re.IGNORECASE,
)
API_KEY_RE = re.compile(r"\b(?:sk_[a-zA-Z0-9]{32,}|xi_[a-zA-Z0-9]{32,}|[a-f0-9]{32,64})\b")


def _rand_key_name(prefix: str = "prod-el") -> str:
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{prefix}-{suffix}"


def generate_strong_password(length: int = 14) -> str:
    """Generate a password satisfying ElevenLabs complexity requirements."""
    upper = secrets.choice(string.ascii_uppercase)
    lower = secrets.choice(string.ascii_lowercase)
    digit = secrets.choice(string.digits)
    spec = secrets.choice("!@#$%&*")
    all_chars = string.ascii_letters + string.digits + "!@#$%&*"
    rest = "".join(secrets.choice(all_chars) for _ in range(max(4, length - 4)))
    pwd_list = list(upper + lower + digit + spec + rest)
    secrets.SystemRandom().shuffle(pwd_list)
    return "".join(pwd_list)


def extract_elevenlabs_verification_link(raw_content: str) -> str | None:
    """Extract ElevenLabs activation link from raw email content."""
    if not raw_content:
        return None
    decoded = html.unescape(raw_content)
    matches = VERIFY_LINK_RE.findall(decoded)
    for m in matches:
        clean_url = m.rstrip(".,;)>'\"")
        lower = clean_url.lower()
        if "action" in lower or "verify" in lower or "confirm" in lower:
            return clean_url
    return None


def _get_email_body_text(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))
            if "attachment" not in cdisp and ctype in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body += payload.decode(charset, errors="ignore") + "\n"
                    except Exception:
                        body += payload.decode("latin1", errors="ignore") + "\n"
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="ignore")
            except Exception:
                body = payload.decode("latin1", errors="ignore")
    return body


def poll_imap_for_verification_link(
    host: str,
    port: int,
    user: str,
    password: str,
    target_email: str,
    timeout_sec: float = 90.0,
    poll_interval: float = 3.0,
) -> str | None:
    """Synchronous helper to poll IMAP mailbox for ElevenLabs verification link."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        client = None
        try:
            client = imaplib.IMAP4_SSL(host, port)
            client.login(user, password)
            client.select("INBOX", readonly=True)

            status, msg_ids = client.search(None, "ALL")
            if status == "OK" and msg_ids and msg_ids[0]:
                id_list = msg_ids[0].split()
                # Check newest messages first (last 20)
                for mid in reversed(id_list[-20:]):
                    res, data = client.fetch(mid, "(RFC822)")
                    if res != "OK" or not data or not data[0]:
                        continue
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    to_addr = msg.get("To", "")
                    delivered_to = msg.get("Delivered-To", "")
                    all_recipients = f"{to_addr} {delivered_to}".lower()

                    if target_email.lower() in all_recipients or not target_email:
                        body = _get_email_body_text(msg)
                        link = extract_elevenlabs_verification_link(body)
                        if link:
                            return link
        except Exception:
            pass
        finally:
            if client:
                try:
                    client.close()
                    client.logout()
                except Exception:
                    pass
        time.sleep(poll_interval)
    return None


async def validate_xi_api_key(api_key: str, timeout: float = 8.0) -> dict[str, Any] | None:
    """Validate xi-api-key against ElevenLabs REST API and retrieve subscription quota."""
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": api_key, "User-Agent": "llm-harvester"},
            )
            if r.status_code == 200:
                sub = r.json().get("subscription", {})
                return {
                    "character_count": sub.get("character_count", 0),
                    "character_limit": sub.get("character_limit", 10000),
                    "tier": sub.get("tier", "free"),
                    "status": sub.get("status", "active"),
                }
    except Exception:
        pass
    return None


class ElevenLabsCreator:
    """Automates ElevenLabs sign-up, email activation, and xi-api-key harvesting."""

    APP_ORIGIN = "https://elevenlabs.io"
    SIGNUP_URL = "https://elevenlabs.io/sign-up"
    API_KEYS_URL = "https://elevenlabs.io/app/developers/api-keys"

    def __init__(
        self,
        cdp: CDP,
        mail: MailProvider,
        config: ElevenLabsConfig | None = None,
        log: Any = print,
    ) -> None:
        self.cdp = cdp
        self.mail = mail
        self.config = config or ElevenLabsConfig()
        self.log = log

    async def _sleep(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)

    async def _reset_session(self) -> None:
        """Clear local storage, session storage, and cookies for elevenlabs.io."""
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
                            document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.elevenlabs.io';
                        });
                    } catch(e){}
                })()"""
            )
        except Exception:
            pass

    async def _wait_for_turnstile(self, timeout_seconds: float = 30.0) -> bool:
        """Wait for Cloudflare Turnstile token if widget is present."""
        has_widget = await self.cdp.evaluate(
            "!!document.querySelector('input[name=\"cf-turnstile-response\"], [data-turnstile], iframe[src*=\"challenges\"]')"
        )
        if not has_widget:
            return True

        self.log("[elevenlabs] Turnstile widget detected, waiting for challenge verification...")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            token_len = await self.cdp.evaluate(
                """(()=>{
                    const input = document.querySelector('input[name="cf-turnstile-response"]');
                    return input ? (input.value || '').length : 0;
                })()"""
            )
            if token_len and int(token_len) > 0:
                self.log("[elevenlabs] Turnstile challenge verified.")
                return True
            await self._sleep(1500)

        self.log("[elevenlabs] Turnstile wait reached timeout, continuing...")
        return False

    async def _scrape_key_from_page(self) -> str:
        """Scrapes API key from DOM (inputs, code blocks, or data attributes)."""
        res = await self.cdp.evaluate(r"""(()=>{
            const isKey = (s) => {
                if (!s || typeof s !== 'string') return false;
                s = s.trim();
                if (/^[a-f0-9]{32}$/i.test(s)) return true;
                if (/^(?:sk_|xi_)[a-zA-Z0-9_\-]{28,100}$/i.test(s)) return true;
                if (/^[a-zA-Z0-9]{32,64}$/.test(s) && !s.includes(' ')) return true;
                return false;
            };

            // 1. Input/textarea with value matching key pattern
            const inputs = Array.from(document.querySelectorAll('input, textarea'));
            for (const i of inputs) {
                const val = (i.value || '').trim();
                if (isKey(val)) return val;
            }

            // 2. data-* attributes holding keys
            const attrSelectors = ['[data-key]', '[data-api-key]', '[data-value]', '[data-clipboard-text]'];
            const attrEls = Array.from(document.querySelectorAll(attrSelectors.join(',')));
            for (const el of attrEls) {
                for (const attr of ['key', 'apiKey', 'value', 'clipboardText']) {
                    const v = (el.dataset[attr] || el.getAttribute('data-' + attr) || '').trim();
                    if (isKey(v)) return v;
                }
            }

            // 3. Text in code/pre/p/span/div/td/li matching key structure
            const all = Array.from(document.querySelectorAll('code, pre, p, span, div, td, li'));
            for (const el of all) {
                const t = el.innerText ? el.innerText.trim() : '';
                if (!t || t.length < 32 || t.length > 300) continue;
                if (isKey(t)) return t;
                const m = t.match(/\b([a-f0-9]{32}|(?:sk_|xi_)[a-zA-Z0-9_\-]{28,100})\b/i);
                if (m && isKey(m[1])) return m[1];
            }

            // 4. Check window.__lastCopied if set by copy button
            if (window.__lastCopied && isKey(window.__lastCopied)) {
                return window.__lastCopied.trim();
            }

            return '';
        })()""")
        return str(res).strip() if res else ""

    async def _bypass_onboarding(self, max_secs: float = 45.0) -> bool:
        """Bypass the ElevenLabs onboarding wizard by interacting with all wizard steps (matching Key-Farm)."""
        url_now = str(await self.cdp.evaluate("window.location.href") or "")
        is_onboard = (
            "onboarding" in url_now
            or await self.cdp.evaluate(r"""(()=>{
                const text = document.body ? document.body.innerText : '';
                return text.includes('ElevenCreative') || text.includes('Choose your platform') ||
                       text.includes('18 years old') || text.includes('By checking this box');
            })()""")
        )
        if not is_onboard:
            return True

        self.log("[elevenlabs] Bypassing onboarding wizard...")
        onboard_start = time.monotonic()
        consecutive_idle = 0

        while time.monotonic() - onboard_start < max_secs:
            url_curr = str(await self.cdp.evaluate("window.location.href") or "")
            if "onboarding" not in url_curr and ("developers" in url_curr or "api-keys" in url_curr):
                self.log(f"[elevenlabs] Onboarding completed! URL: {url_curr}")
                return True

            body_text = str(await self.cdp.evaluate("document.body ? document.body.innerText : ''") or "")

            # Step 1: Choose your platform (ElevenCreative)
            if "Choose your platform" in body_text or "ElevenCreative" in body_text:
                await self.cdp.evaluate(r"""(()=>{
                    const els = Array.from(document.querySelectorAll('button, div, [role="button"], [role="radio"]'));
                    const creative = els.find(el => (el.innerText || '').includes('ElevenCreative'));
                    if (creative) creative.click();
                })()""")
                await self._sleep(150)

            # Step 2: Check 18+ age agreement checkbox if present
            await self.cdp.evaluate(r"""(()=>{
                const cbs = document.querySelectorAll('button[role="checkbox"], input[type="checkbox"], [role="checkbox"]');
                cbs.forEach(cb => {
                    if (cb.getAttribute('aria-checked') === 'false' || cb.checked === false) {
                        cb.click();
                    }
                });
                const allEls = Array.from(document.querySelectorAll('*'));
                const label = allEls.find(el => el.innerText && (el.innerText.includes('18 years old') || el.innerText.includes('By checking this box')) && el.children.length === 0);
                if (label) {
                    label.click();
                    if (label.parentElement) label.parentElement.click();
                }
            })()""")
            await self._sleep(150)

            # Step 3: Fill name if an empty text input exists
            await self.cdp.evaluate(r"""(()=>{
                const inps = Array.from(document.querySelectorAll('input[type="text"]:not([readonly]), input:not([type]):not([readonly])'));
                const nameInp = inps.find(i => !i.value);
                if (nameInp) {
                    nameInp.value = 'Hunter';
                    nameInp.dispatchEvent(new Event('input', {bubbles: true}));
                    nameInp.dispatchEvent(new Event('change', {bubbles: true}));
                }
            })()""")
            await self._sleep(150)

            # Step 4: Click Next / Continue / Skip / Done etc. (Exact & Starts-with matches from Key-Farm)
            clicked_action = await self.cdp.evaluate(r"""(()=>{
                const btns = Array.from(document.querySelectorAll('button, a'));
                const allowed = ['skip', 'continue', 'next', 'done', 'get started', 'finish', "let's go", 'go to home', 'start creating'];

                // 1. Exact match (case-insensitive)
                for (const kw of allowed) {
                    const target = btns.find(b => {
                        const t = b.innerText ? b.innerText.trim().toLowerCase() : '';
                        return t === kw && !b.disabled && b.offsetParent !== null;
                    });
                    if (target) {
                        target.click();
                        return target.innerText.trim();
                    }
                }

                // 2. Starts with / contains match
                for (const kw of allowed) {
                    const target = btns.find(b => {
                        const t = b.innerText ? b.innerText.trim().toLowerCase() : '';
                        return (t.startsWith(kw) || t === kw) && !b.disabled && b.offsetParent !== null;
                    });
                    if (target) {
                        target.click();
                        return target.innerText.trim();
                    }
                }
                return null;
            })()""")

            if clicked_action:
                self.log(f"[elevenlabs] Onboarding action clicked: '{clicked_action}'")
                consecutive_idle = 0
                await self._sleep(600)
            else:
                consecutive_idle += 1
                if consecutive_idle >= 3:
                    # Fallback handlers if stuck for 3 cycles (~1.5s)
                    fallback_act = await self.cdp.evaluate(r"""(()=>{
                        // Dismiss close button if any
                        const closeBtn = document.querySelector('button[aria-label*="close" i], button[aria-label*="dismiss" i]');
                        if (closeBtn && !closeBtn.disabled) {
                            closeBtn.click();
                            return 'Close';
                        }
                        const opts = Array.from(document.querySelectorAll('[role="radio"], [role="option"], [data-testid*="option"]'));
                        if (opts.length > 0) {
                            opts[0].click();
                            return 'OptionSelect';
                        }
                        return null;
                    })()""")
                    if fallback_act:
                        self.log(f"[elevenlabs] Onboarding fallback action clicked: '{fallback_act}'")
                        consecutive_idle = 0
                    await self._sleep(600)
                else:
                    await self._sleep(500)

                if consecutive_idle >= 6:
                    self.log("[elevenlabs] No further onboarding actions detected, verifying exit...")
                    break

        # Verification guard: Wait until URL genuinely leaves onboarding
        url_now = str(await self.cdp.evaluate("window.location.href") or "")
        if "onboarding" in url_now:
            for _ in range(10):
                await self._sleep(500)
                url_check = str(await self.cdp.evaluate("window.location.href") or "")
                if "onboarding" not in url_check:
                    self.log(f"[elevenlabs] Onboarding completed! URL: {url_check}")
                    break
                await self.cdp.evaluate(r"""(()=>{
                    const btns = Array.from(document.querySelectorAll('button, a'));
                    const b = btns.find(x => ['skip', 'continue', 'done', 'home'].some(k => (x.innerText || '').toLowerCase().includes(k)) && !x.disabled);
                    if (b) b.click();
                })()""")

        return True

    async def create_account(self) -> HarvestedKey:
        """Create an ElevenLabs account and harvest an API key."""
        retries = max(1, self.config.max_retries)
        last_error = ""

        for attempt in range(1, retries + 1):
            try:
                return await self._create_single_account()
            except Exception as exc:
                last_error = str(exc)
                self.log(f"[elevenlabs] Attempt {attempt}/{retries} failed: {exc}")
                if attempt < retries:
                    await self._sleep(3000)

        return HarvestedKey(
            platform="elevenlabs",
            email="",
            password="",
            error=last_error or "failed after all retries",
        )

    async def _create_single_account(self) -> HarvestedKey:
        cfg = self.config
        mailbox: Mailbox | None = None
        use_imap = bool(cfg.imap_enabled and cfg.imap_user and cfg.imap_password)

        if use_imap:
            domain = cfg.email_domain or "hazz.biz.id"
            email_addr = f"el_{secrets.token_hex(4)}@{domain.lstrip('@')}"
            password = generate_strong_password()
            self.log(f"[elevenlabs] Using IMAP Catch-All: {email_addr}")
        else:
            self.log("[elevenlabs] Creating disposable mailbox via mail.tm...")
            mailbox = await self.mail.create_mailbox(prefix="el")
            email_addr = mailbox.address
            password = generate_strong_password()
            self.log(f"[elevenlabs] Mailbox ready: {email_addr}")

        await self._reset_session()

        # 1. Navigate to sign-up page
        self.log(f"[elevenlabs] Opening sign-up page: {self.SIGNUP_URL}")
        await self.cdp.navigate(self.SIGNUP_URL, wait_ms=10000)
        await self._sleep(2500)

        # 2. Dismiss cookie banner if present
        await self.cdp.evaluate("""(()=>{
            const accept = [...document.querySelectorAll('button, a')].find(b => {
                const t = (b.innerText || '').trim().toLowerCase();
                return t === 'accept all' || t === 'accept' || t === 'agree';
            }) || document.querySelector('#onetrust-accept-btn-handler');
            if (accept) accept.click();
        })()""")
        await self._sleep(500)

        # 3. Wait for email and password inputs
        self.log("[elevenlabs] Waiting for registration inputs...")
        form_ready = False
        for _ in range(15):
            has_inputs = await self.cdp.evaluate(
                "!!document.querySelector('input[type=\"email\"], input[name=\"email\"], input#email') && "
                "!!document.querySelector('input[type=\"password\"], input[name=\"password\"], input#password')"
            )
            if has_inputs:
                form_ready = True
                break
            await self._wait_for_turnstile(timeout_seconds=2.0)
            await self._sleep(1000)

        if not form_ready:
            title = await self.cdp.evaluate("document.title")
            curr_url = await self.cdp.evaluate("window.location.href")
            raise RuntimeError(f"Sign-up inputs not found at {curr_url} (title: {title})")

        # 4. Fill credentials with React _valueTracker sync
        self.log("[elevenlabs] Filling registration credentials...")
        await self.cdp.type_text('input[type="email"], input[name="email"], input#email', email_addr)
        await self._sleep(300)
        await self.cdp.type_text('input[type="password"], input[name="password"], input#password', password)
        await self._sleep(500)

        # Reinforce in DOM if values were not stored
        await self.cdp.evaluate("""(()=>{
            function setVal(el, val) {
                if (!el) return;
                el.focus();
                const proto = Object.getPrototypeOf(el);
                const s = (Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value'))?.set;
                if (s) s.call(el, val); else el.value = val;
                if (el._valueTracker) el._valueTracker.setValue('');
                el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
                el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
            }
            setVal(document.querySelector('input[type="email"], input[name="email"], input#email'), %s);
            setVal(document.querySelector('input[type="password"], input[name="password"], input#password'), %s);
        })()""" % (json.dumps(email_addr), json.dumps(password)))
        await self._sleep(1000)

        # 5. Click Sign Up button
        self.log("[elevenlabs] Clicking Sign up button...")
        clicked_signup = await self.cdp.evaluate("""(()=>{
            const btns = Array.from(document.querySelectorAll('button'));
            const btn = btns.find(b => (b.innerText || '').trim().toLowerCase() === 'sign up') ||
                        document.querySelector('button[type="submit"]');
            if (btn && !btn.disabled) {
                btn.click();
                return true;
            }
            return false;
        })()""")
        if not clicked_signup:
            await self.cdp.insert_text("\n")

        # 6. Wait for Turnstile or sign-up confirmation
        self.log("[elevenlabs] Awaiting registration response or challenge...")
        await self._sleep(3000)
        await self._wait_for_turnstile(timeout_seconds=25.0)

        confirmation_detected = False
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            url_now = str(await self.cdp.evaluate("window.location.href") or "")
            body_text = str(await self.cdp.evaluate("document.body ? document.body.innerText : ''") or "").lower()

            if any(k in body_text for k in ["check your email", "verify your email", "check your inbox", "email has been sent", "confirmation email"]):
                self.log("[elevenlabs] Confirmation screen detected: verification email sent.")
                confirmation_detected = True
                break

            if "sign-up" not in url_now and any(k in url_now for k in ["verify", "app", "dashboard", "onboarding"]):
                self.log(f"[elevenlabs] Redirected away from sign-up: {url_now}")
                confirmation_detected = True
                break

            err_msg = await self.cdp.evaluate("""(()=>{
                const alert = document.querySelector('[role="alert"]');
                if (alert && alert.innerText) return alert.innerText.trim();
                const b = document.body ? document.body.innerText : '';
                if (b.includes('already registered') || b.includes('already in use')) return 'Email already registered';
                return '';
            })()""")
            if err_msg and isinstance(err_msg, str) and err_msg.strip():
                raise RuntimeError(f"Sign-up error from ElevenLabs: {err_msg.strip()}")

            await self._sleep(2000)

        # 7. Retrieve verification email link
        verify_url: str | None = None
        if use_imap:
            self.log(f"[elevenlabs] Polling IMAP ({cfg.imap_host}) for verification email...")
            verify_url = await asyncio.to_thread(
                poll_imap_for_verification_link,
                cfg.imap_host,
                cfg.imap_port,
                cfg.imap_user or "",
                cfg.imap_password or "",
                email_addr,
                timeout_sec=cfg.wait_seconds,
            )
        elif mailbox:
            self.log("[elevenlabs] Waiting for verification email from mail.tm...")
            msg = await self.mail.wait_for_message(
                mailbox,
                timeout=cfg.wait_seconds,
                interval=3.5,
                match_sender="elevenlabs",
            )
            if not msg:
                # Fallback check without sender match
                msg = await self.mail.wait_for_message(
                    mailbox,
                    timeout=20.0,
                    interval=3.0,
                )
            if msg:
                content = (msg.text or "") + "\n" + (msg.html or "")
                verify_url = extract_elevenlabs_verification_link(content)

        if not verify_url:
            raise RuntimeError(f"Verification link not received for {email_addr} within timeout")

        self.log(f"[elevenlabs] Verification link retrieved: {verify_url}")

        # 8. Navigate to email verification link
        await self.cdp.navigate(verify_url, wait_ms=10000)
        await self._sleep(3000)

        # Dismiss "Email Verification" modal if displayed ("Continue", "Close")
        await self.cdp.evaluate("""(()=>{
            const btns = Array.from(document.querySelectorAll('button'));
            const btn = btns.find(b => {
                const t = (b.innerText || '').trim().toLowerCase();
                return t === 'continue' || t === 'close';
            });
            if (btn) btn.click();
        })()""")
        await self._sleep(1500)

        # If sign-in form is presented on verification page, enter credentials
        needs_signin = await self.cdp.evaluate(
            "!!document.querySelector('input[type=\"email\"], input[name=\"email\"]') && "
            "!!document.querySelector('input[type=\"password\"], input[name=\"password\"]')"
        )
        if needs_signin:
            self.log("[elevenlabs] Completing verification sign-in...")
            await self.cdp.type_text('input[type="email"], input[name="email"]', email_addr)
            await self._sleep(200)
            await self.cdp.type_text('input[type="password"], input[name="password"]', password)
            await self._sleep(300)
            await self.cdp.evaluate("""(()=>{
                const btns = Array.from(document.querySelectorAll('button'));
                const btn = btns.find(b => (b.innerText || '').trim().toLowerCase() === 'sign in') ||
                            document.querySelector('button[type="submit"]');
                if (btn) btn.click();
            })()""")
            await self._sleep(4000)

        # 9. Wait for dashboard/onboarding redirect & bypass wizard (matching Key-Farm)
        self.log("[elevenlabs] Waiting for dashboard redirect after verification...")
        logged_in = False
        for _ in range(25):
            url_now = str(await self.cdp.evaluate("window.location.href") or "")
            if "sign-in" not in url_now and "sign-up" not in url_now and "action" not in url_now and (
                "app" in url_now or "dashboard" in url_now or "onboarding" in url_now
            ):
                self.log(f"[elevenlabs] Dashboard/Onboarding reached: {url_now}")
                logged_in = True
                break
            await self._sleep(1000)

        # Allow onboarding wizard a moment to render
        for _ in range(8):
            url_check = str(await self.cdp.evaluate("window.location.href") or "")
            if "onboarding" in url_check:
                break
            await self._sleep(500)

        await self._bypass_onboarding(max_secs=45.0)

        # 10. Navigate to API Keys page
        self.log(f"[elevenlabs] Navigating to API Keys page: {self.API_KEYS_URL}")
        api_keys_loaded = False
        for nav_attempt in range(1, 6):
            await self.cdp.navigate(self.API_KEYS_URL, wait_ms=8000)
            await self._sleep(2500)
            url_check = str(await self.cdp.evaluate("window.location.href") or "")
            if "api-keys" in url_check or "developers" in url_check:
                self.log(f"[elevenlabs] API Keys page opened: {url_check}")
                api_keys_loaded = True
                break
            if "onboarding" in url_check:
                self.log(f"[elevenlabs] Redirected back to onboarding (attempt {nav_attempt}/5), completing remaining wizard steps...")
                await self._bypass_onboarding(max_secs=25.0)
                await self._sleep(1500)
            else:
                await self._sleep(1500)

        # Close promotional popups if any
        await self.cdp.evaluate("""(()=>{
            const closeBtns = [...document.querySelectorAll('button')].filter(b => {
                const t = (b.innerText || '').trim().toLowerCase();
                return ['got it', 'close', 'dismiss', 'maybe later'].includes(t);
            });
            closeBtns.forEach(b => b.click());
        })()""")
        await self._sleep(1000)

        # 11. Scrape existing or create new API Key
        # Setup copy event listener on the page to intercept any clipboard actions
        try:
            await self.cdp.evaluate("""(()=>{
                if (!window.__copyListenerAttached) {
                    window.__copyListenerAttached = true;
                    document.addEventListener('copy', (e) => {
                        try {
                            const text = (window.getSelection && window.getSelection().toString()) || '';
                            if (text) window.__lastCopied = text;
                        } catch(err){}
                    }, true);
                }
            })()""")
        except Exception:
            pass

        api_key = await self._scrape_key_from_page()
        if api_key:
            self.log(f"[elevenlabs] Existing API Key detected on page: {api_key[:12]}...")
        else:
            self.log("[elevenlabs] Creating new API Key...")
            create_btn_clicked = await self.cdp.evaluate(r"""(()=>{
                const btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
                const btn = btns.find(b => {
                    const t = (b.innerText || b.getAttribute('aria-label') || '').trim().toLowerCase();
                    return /(?:create|add|new|generate)\s*(?:api)?\s*key/i.test(t) ||
                           t === 'create key' || t === 'create api key' || t === '+ create key';
                });
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()""")

            if create_btn_clicked:
                await self._sleep(1500)

                # Set key name in modal input if present
                await self.cdp.evaluate("""(()=>{
                    const dialog = document.querySelector('div[role="dialog"], [data-state="open"], [aria-modal="true"]');
                    const scope = dialog || document;
                    const nameInp = scope.querySelector('input[placeholder*="name" i], input[placeholder*="key" i], input[type="text"]:not([readonly])');
                    if (nameInp && !nameInp.value) {
                        nameInp.value = 'prod-harvest';
                        nameInp.dispatchEvent(new Event('input', {bubbles: true}));
                        nameInp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                })()""")
                await self._sleep(300)

                # Set permissions to Access / Write if present
                await self.cdp.evaluate("""(()=>{
                    const btns = Array.from(document.querySelectorAll('button, [role="radio"], label'));
                    btns.forEach(b => {
                        const t = (b.innerText || '').trim();
                        if (t === 'Access' || t === 'Write' || t === 'Full access') b.click();
                    });
                })()""")
                await self._sleep(300)

                # Disable Restrict Key toggle if on
                await self.cdp.evaluate("""(()=>{
                    const sw = document.querySelector('[role="switch"]');
                    if (sw && sw.getAttribute('aria-checked') === 'true') sw.click();
                })()""")
                await self._sleep(300)

                # Submit modal
                self.log("[elevenlabs] Submitting API Key creation modal...")
                await self.cdp.evaluate("""(()=>{
                    const dialog = document.querySelector('div[role="dialog"], [data-state="open"], [aria-modal="true"]');
                    const scope = dialog || document;
                    const btns = Array.from(scope.querySelectorAll('button')).filter(b => {
                        const t = (b.innerText || '').trim().toLowerCase();
                        return (/(?:create|save|generate|done|confirm)/i.test(t) || b.type === 'submit') && !b.disabled;
                    });
                    if (btns.length > 0) btns[btns.length - 1].click();
                })()""")
                await self._sleep(1500)

                # Poll newly created key
                for _ in range(15):
                    # Try clicking copy button in modal if present
                    await self.cdp.evaluate("""(()=>{
                        const dialog = document.querySelector('div[role="dialog"], [data-state="open"], [aria-modal="true"]');
                        const scope = dialog || document;
                        const copyBtns = Array.from(scope.querySelectorAll('button, [role="button"]')).filter(b => {
                            const t = (b.innerText || b.getAttribute('aria-label') || '').trim().toLowerCase();
                            return t.includes('copy');
                        });
                        if (copyBtns.length > 0) copyBtns[0].click();
                    })()""")

                    new_key = await self._scrape_key_from_page()
                    if new_key:
                        api_key = new_key
                        self.log(f"[elevenlabs] API Key generated: {api_key[:12]}...")
                        break
                    await self._sleep(800)

        if not api_key:
            raise RuntimeError("Account created and verified, but API Key could not be extracted.")

        # 12. Validate key against ElevenLabs REST API
        self.log(f"[elevenlabs] Validating harvested key: {api_key[:10]}...{api_key[-4:]}")
        quota_info = await validate_xi_api_key(api_key)
        if quota_info:
            char_limit = quota_info.get("character_limit", 10000)
            char_count = quota_info.get("character_count", 0)
            remaining = char_limit - char_count
            self.log(f"[elevenlabs] API Key active! Tier: {quota_info.get('tier', 'free')}, Limit: {char_limit:,} chars (Remaining: {remaining:,})")
        else:
            self.log("[elevenlabs] REST API validation deferred, saving harvested key.")

        return HarvestedKey(
            platform="elevenlabs",
            email=email_addr,
            password=password,
            api_key=api_key,
        )
