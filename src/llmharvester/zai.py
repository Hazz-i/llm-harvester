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
        import platform as _pl

        if isinstance(captcha_param, dict):
            captcha_param = captcha_param.get("captchaVerifyParam") or json.dumps(captcha_param)
        captcha_param = str(captcha_param)

        osname = {"Linux": "linux", "Darwin": "darwin", "Windows": "win32"}.get(_pl.system(), "linux")
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(_pl.machine(), "x64")
        headers = {
            "Authorization": f"Bearer {zcode_jwt}",
            "X-Aliyun-Captcha-Verify-Param": captcha_param,
            "X-Aliyun-Captcha-Verify-Region": ALIYUN_SCENE["region"],
            "X-ZCode-App-Version": "3.14.4",
            "X-Platform": f"{osname}-{arch}",
        }
        body = {"plan_id": ZCODE_PLAN_ID}
        try:
            resp = _http_json(f"{ZCODE_CLAIM_URL}?app_version=3.14.4", method="POST", body=body, headers=headers)
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

    async def wait_for_otp(self, source, timeout: float = 60.0) -> str | None:
        """Poll mail.tm mailbox OR catch-all IMAP service for the verification code."""
        label = getattr(source, "address", None) or getattr(source, "email", "inbox")
        self.log(f"[zai] Menunggu kode verifikasi OTP di inbox {label}...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if hasattr(source, "poll_numeric_code"):
                    code = await asyncio.to_thread(source.poll_numeric_code, 8)
                    if code:
                        self.log(f"[zai] Ditemukan OTP: {code}")
                        return code
                else:
                    messages = await self.mail.messages(source)
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

    async def _drag_slider(self, distance: float) -> None:
        """Drag the Aliyun slider handle by `distance` px using real CDP mouse events."""
        box = await self.cdp.evaluate(
            """(()=>{const el=document.querySelector('#aliyunCaptcha-sliding-slider');if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2, y:r.top+r.height/2};})()"""
        )
        if not box:
            return
        x0, y0 = float(box["x"]), float(box["y"])
        await self.cdp._send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x0, "y": y0, "button": "left", "clickCount": 1},
            session=True,
        )
        steps = 28
        x = x0
        for i in range(1, steps + 1):
            x = x0 + distance * i / steps
            await self.cdp._send(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y0, "button": "left", "buttons": 1},
                session=True,
            )
            await asyncio.sleep(0.028 + (0.05 if i < 5 else 0.0))
        await asyncio.sleep(0.25)
        await self.cdp._send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y0, "button": "left", "clickCount": 1},
            session=True,
        )

    @staticmethod
    def _cv2_offset(bg_b64: str, slide_b64: str) -> int:
        """Offset (x) of the slide in the background, via Canny edges + template match."""
        try:
            import base64 as _b64

            import cv2
            import numpy as np

            def dec(s: str):
                arr = np.frombuffer(_b64.b64decode(s.split(",", 1)[-1]), np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)

            bg = dec(bg_b64)
            sl = dec(slide_b64)
            if bg is None or sl is None:
                return -1
            gray = cv2.cvtColor(sl, cv2.COLOR_BGR2GRAY)
            ys, xs = np.where(gray > 30)
            if len(xs) and len(ys):
                sl = sl[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

            def edges(img):
                gr = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                e = cv2.Canny(gr, 100, 200)
                return cv2.cvtColor(e, cv2.COLOR_GRAY2BGR)

            e_bg = edges(bg)
            e_sl = edges(sl)
            if e_sl.size == 0 or e_sl.shape[0] > e_bg.shape[0] or e_sl.shape[1] > e_bg.shape[1]:
                return -1
            res = cv2.matchTemplate(e_bg, e_sl, cv2.TM_CCOEFF_NORMED)
            _, _, _, max_loc = cv2.minMaxLoc(res)
            return int(max_loc[0])
        except Exception:
            return -1

    async def solve_aliyun_slider(self, timeout: float = 90.0) -> bool:
        """Auto-solve the Aliyun 'restore image' slider.

        Computes the horizontal offset between the displaced puzzle strip and the
        gap in the background image (brute-force template match in-browser), then
        drags the slider handle there with human-like mouse motion.
        """
        self.log("[zai] Menyelesaikan captcha Aliyun (slider) otomatis...")
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            info = None
            try:
                info = await self.cdp.evaluate(
                    r"""(()=>{
                        const bg=document.querySelector('#aliyunCaptcha-img');
                        const pz=document.querySelector('#aliyunCaptcha-puzzle');
                        const slider=document.querySelector('#aliyunCaptcha-sliding-slider');
                        const track=document.querySelector('#aliyunCaptcha-sliding-body');
                        if(!bg||!pz||!slider||!track||!bg.complete||!pz.complete||!bg.naturalWidth) return null;
                        const toB=(im)=>{try{const c=document.createElement('canvas');c.width=im.naturalWidth;c.height=im.naturalHeight;c.getContext('2d').drawImage(im,0,0);return c.toDataURL('image/png');}catch(e){return null;}};
                        return {bg:toB(bg), pz:toB(pz), imgW:bg.naturalWidth, puzzleW:pz.naturalWidth, trackW:track.clientWidth-slider.clientWidth};
                    })()"""
                )
            except Exception as exc:
                self.log(f"[zai] ambil gambar captcha gagal: {exc}")
                await asyncio.sleep(1.5)
                continue

            if not info or not info.get("bg") or not info.get("pz"):
                await asyncio.sleep(1.0)
                continue

            best_x = self._cv2_offset(info["bg"], info["pz"])
            if best_x < 0:
                await asyncio.sleep(1.0)
                continue
            span = max(1, info["imgW"] - info["puzzleW"])
            ratio = (info["trackW"] / span) if info.get("trackW", 0) > 0 else 1.0
            drag_x = best_x * ratio
            self.log(
                f"[zai] cv2 offset x={best_x}/{span} -> drag {drag_x:.0f}px (attempt {attempt})"
            )
            await self._drag_slider(float(drag_x))
            await asyncio.sleep(2.5)

            try:
                done = await self.cdp.evaluate(
                    """(()=>{const w=document.querySelector('#aliyunCaptcha-window-float');if(!w)return true;const r=w.getBoundingClientRect();return r.width===0||r.height===0||getComputedStyle(w).display==='none'||!w.classList.contains('window-show');})()"""
                )
            except Exception:
                done = False
            if done:
                self.log("[zai] Captcha Aliyun berhasil diselesaikan.")
                return True

            # Failed: refresh for a new challenge and retry.
            await self.cdp.evaluate(
                """(()=>{const b=document.querySelector('#aliyunCaptcha-btn-refresh');if(b)b.click();})()"""
            )
            await asyncio.sleep(2.0)

        self.log("[zai] Gagal menyelesaikan captcha Aliyun (timeout).")
        return False


    async def wait_for_manual_captcha(self, timeout: float = 180.0) -> bool:
        """Print a clear prompt and wait until the user solves the Aliyun slider by hand."""
        self.log("")
        self.log("=" * 66)
        self.log("[zai] >>>>>>  GESER SLIDER ALIYUN SEKARANG DI BROWSER  <<<<<<")
        self.log("[zai] Browser terbuka di chat.z.ai/auth (tab Sign up, form udah keisi).")
        self.log("[zai] Tarik slider sampai gambar nyambung. Aku nunggu di sini...")
        self.log("=" * 66)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                done = await self.cdp.evaluate(
                    """(()=>{const w=document.querySelector('#aliyunCaptcha-window-float');if(!w)return true;const r=w.getBoundingClientRect();return r.width===0||r.height===0||getComputedStyle(w).display==='none'||!w.classList.contains('window-show');})()"""
                )
            except Exception:
                done = False
            if done:
                self.log("[zai] Captcha teratasi. Lanjut ke Create Account...")
                return True
            await asyncio.sleep(1.5)
        self.log("[zai] Waktu captcha habis (timeout).")
        return False

    async def wait_for_verify_link(self, source, timeout: float = 150.0) -> str | None:
        """Poll mail.tm / IMAP for the Z.ai email-verification LINK."""
        self.log("[zai] Menunggu email verifikasi Z.ai (link)...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if hasattr(source, "poll_verify_link"):
                    link = await asyncio.to_thread(source.poll_verify_link, 8, ("z.ai", "zai"))
                    if link:
                        return link
                else:
                    for msg in await self.mail.messages(source):
                        content = f"{msg.subject} {msg.text} {msg.html}"
                        m = re.search(r"https?://[^\s\"'<>)]*verify_email[^\s\"'<>)]*", content)
                        if m:
                            return m.group(0)
            except Exception as e:
                self.log(f"[zai] Error cek link verifikasi: {e}")
            await asyncio.sleep(3.0)
        return None

    async def solve_claim_captcha(self, timeout: float = 180.0) -> str | None:
        """Get an Aliyun `captchaVerifyParam` for the Start-Plan claim (scene 11xygtvd).

        Loads the official Aliyun SDK on the logged-in chat.z.ai page, tries a
        traceless verification, else prompts the user to drag the slider. Never
        raises: returns None if the captcha can't be solved (claim is optional).
        """
        try:
            await self.cdp.navigate("https://chat.z.ai/")
            await asyncio.sleep(3.0)
            self.log(f"[zai] claim page: {await self.cdp.evaluate('window.location.href')}")

            async def _sdk_loaded() -> bool:
                try:
                    return (await self.cdp.evaluate("typeof window.initAliyunCaptcha")) == "function"
                except Exception:
                    return False

            if not await _sdk_loaded():
                await self.cdp.evaluate(
                    """(()=>{window.__sdk='loading';window.AliyunCaptchaConfig={region:%s,prefix:%s};const s=document.createElement('script');s.src='https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js';s.onload=()=>{window.__sdk='loaded';};s.onerror=()=>{window.__sdk='error';};document.head.appendChild(s);return true;})()"""
                    % (json.dumps(ALIYUN_SCENE["region"]), json.dumps(ALIYUN_SCENE["prefix"]))
                )
                for _ in range(10):
                    if await _sdk_loaded():
                        break
                    await asyncio.sleep(1.0)
                self.log(f"[zai] SDK state: {await self.cdp.evaluate('window.__sdk')}")
            if not await _sdk_loaded():
                self.log("[zai] SDK Aliyun tidak termuat di halaman — lewati klaim.")
                return None

            inject = """(function(){
                var scene=%s;
                window.__capParam=null; window.__capErr=null;
                if(typeof window.initAliyunCaptcha!=='function') return 'no-sdk';
                var el=document.getElementById('__caphost');
                if(!el){el=document.createElement('div');el.id='__caphost';
                  el.style.cssText='position:fixed;bottom:10px;left:50%%;transform:translateX(-50%%);z-index:2147483647;background:#fff;padding:10px;border:2px solid #5b8cff;border-radius:8px';
                  document.body.appendChild(el);
                  el.innerHTML='<div style="font:13px sans-serif;margin-bottom:6px">Verifikasi Aliyun - Start Plan (geser slider)</div><div id="__capbox"></div><button id="__capbtn">Tampilkan Slider</button>';}
                try {
                  window.initAliyunCaptcha({SceneId:scene.sceneId,mode:'popup',element:'#__capbox',button:'#__capbtn',region:scene.region,prefix:scene.prefix,language:'en',captchaLogoImg:'',getInstance:function(i){window.__capInst=i;},success:function(p){window.__capParam=p;},fail:function(e){window.__capErr=JSON.stringify(e);}});
                } catch(e){ window.__capErr=String(e); return 'init-err:'+e; }
                return 'ok';
            })()""" % json.dumps(ALIYUN_SCENE)
            await self.cdp.evaluate(inject)
            await asyncio.sleep(1.0)
            await self.cdp.evaluate("""(()=>{const b=document.getElementById('__capbtn');if(b)b.click();})()""")
            await asyncio.sleep(1.0)
            await self.cdp.evaluate("""(()=>{try{if(window.__capInst&&window.__capInst.startTracelessVerification)window.__capInst.startTracelessVerification();}catch(e){}})()""")

            # Try the OpenCV auto-solver first.
            try:
                if await self.solve_aliyun_slider(timeout=45.0):
                    param = await self.cdp.evaluate("window.__capParam")
                    if param:
                        self.log(f"[zai] CaptchaVerifyParam didapat (auto). type={type(param).__name__} val={str(param)[:100]}")
                        return param
            except Exception as exc:
                self.log(f"[zai] auto-solve klaim error: {exc}")

            self.log("")
            self.log("=" * 66)
            self.log("[zai] >>>>>> GESER SLIDER ALIYUN (KLAIM START PLAN) DI BROWSER <<<<<<")
            self.log("[zai] Tarik slider sampai lolos. Aku nunggu + ambil verify param...")
            self.log("=" * 66)
            deadline = time.time() + timeout
            while time.time() < deadline:
                param = await self.cdp.evaluate("window.__capParam")
                if param:
                    self.log("[zai] CaptchaVerifyParam didapat.")
                    return param
                await asyncio.sleep(1.5)
            self.log("[zai] Klaim: captcha tidak selesai (timeout).")
            return None
        except Exception as exc:
            self.log(f"[zai] Klaim captcha error (dilewati): {exc}")
            return None

    async def _oauth_jwt(self) -> tuple[str | None, str | None]:
        """Run the ZCode OAuth consent + exchange. Returns (zcodeJwtToken, zaiAccessToken)."""
        state = secrets.token_hex(16)
        oauth_url = f"{ZCODE_AUTHORIZE_URL}?client_id={ZCODE_CLIENT_ID}&redirect_uri={ZCODE_REDIRECT_URI}&response_type=code&state={state}"
        self.log("[zai] Membuka OAuth authorize ZCode...")
        await self.cdp.navigate(oauth_url)
        await asyncio.sleep(3.0)
        consent_js = (
            f"(async () => {{ const body=new URLSearchParams({{client_id:'{ZCODE_CLIENT_ID}', "
            f"redirect_uri:'{ZCODE_REDIRECT_URI}', response_type:'code', state:'{state}', action:'approve'}}); "
            "const r=await fetch('/api/oauth/authorize',{method:'POST',"
            "headers:{'Content-Type':'application/x-www-form-urlencoded'},credentials:'include',body});"
            "return await r.text(); })()"
        )
        code = None
        try:
            consent_raw = await self.cdp.evaluate(consent_js, await_promise=True)
            data = json.loads(consent_raw) if consent_raw else {}
            redirect_url = data.get("redirect_url", "")
            if "code=" in redirect_url:
                code = redirect_url.split("code=")[1].split("&")[0]
        except Exception as exc:
            self.log(f"[zai] oauth consent error: {exc}")
        if not code:
            cur = str(await self.cdp.evaluate("window.location.href"))
            if "code=" in cur:
                code = cur.split("code=")[1].split("&")[0]
        if not code:
            return None, None
        self.log("[zai] Menukarkan authorization code...")
        tokens = self.exchange_zcode_token(code, state)
        return tokens.get("zcodeJwtToken"), tokens.get("zaiAccessToken")

    @staticmethod
    def claim_status(zcode_jwt: str) -> dict:
        try:
            return _http_json(
                "https://zcode.z.ai/api/v1/zcode-plan/billing/current?app_version=3.14.4",
                headers={"Authorization": f"Bearer {zcode_jwt}"},
            )
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _has_active_plan(status: dict) -> bool:
        if not isinstance(status, dict):
            return False
        data = status.get("data")
        if isinstance(data, list):
            return len(data) > 0
        if isinstance(data, dict):
            plans = data.get("plans") or data.get("list") or data.get("items")
            if isinstance(plans, list):
                return len(plans) > 0
            return bool(plans)
        return False

    async def _apply_cookies(self, cookies: list) -> None:
        for c in cookies or []:
            try:
                params: dict = {"name": c.get("name"), "value": c.get("value"), "path": c.get("path", "/")}
                if c.get("domain"):
                    params["domain"] = c["domain"]
                else:
                    params["url"] = "https://chat.z.ai"
                await self.cdp._send("Network.setCookie", params, session=True)
            except Exception:
                pass

    async def _chat_login(self, email: str, password: str) -> bool:
        """Sign in to an existing Z.ai account (NO registration)."""
        self.log(f"[zai] Login ulang (bukan daftar): {email}")
        await self.cdp.navigate(ZAI_AUTH_URL)
        await asyncio.sleep(4.0)
        await self.cdp.evaluate(
            """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/continue with email/i.test((x.innerText||'').replace(/\\n/g,' ')));if(b)b.click();})()"""
        )
        await asyncio.sleep(2.0)
        await self.cdp.evaluate(
            """(()=>{const set=(sel,val)=>{const el=document.querySelector(sel);if(!el)return;const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,val);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};set('input[name="email"]',%s);set('input[name="current-password"],input[type="password"]',%s);})()"""
            % (json.dumps(email), json.dumps(password))
        )
        await asyncio.sleep(1.0)
        await self.cdp.evaluate(
            """(()=>{const el=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/start verification/i.test((e.textContent||'').trim()));if(el){(el.closest('button')||el).click();}})()"""
        )
        await asyncio.sleep(2.0)
        await self.wait_for_manual_captcha(timeout=self.config.aliyun_timeout)
        await self.cdp.evaluate(
            """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^sign in$/i.test((x.innerText||'').trim()));if(b)b.click();})()"""
        )
        await asyncio.sleep(6.0)
        cur = str(await self.cdp.evaluate("window.location.href"))
        self.log(f"[zai] login result url: {cur}")
        # Success = no longer on the exact login page (/auth), e.g. home or /auth/oauth/authorize.
        path = cur.split("?")[0].rstrip("/")
        return not path.endswith("/auth")

    async def claim_existing(self, record: dict) -> HarvestedKey:
        """Claim Start Plan for an already-harvested account (login reuse, no signup)."""
        email = record.get("email", "")
        password = record.get("password", "")
        api_key = record.get("api_key", "")
        extra = record.get("extra") or {}
        zcode_jwt = extra.get("zcodeJwtToken")

        if extra.get("cookies"):
            await self._apply_cookies(extra["cookies"])

        if zcode_jwt and self._has_active_plan(self.claim_status(zcode_jwt)):
            self.log(f"[zai] {email} sudah claim Start Plan.")
            return HarvestedKey(platform="zai", email=email, password=password, api_key=api_key,
                                extra={**extra, "alreadyClaimed": True})

        if not zcode_jwt:
            if not password or not await self._chat_login(email, password):
                self.log(f"[zai] Login gagal untuk {email} (masih di /auth) — klaim dibatalkan.")
                return HarvestedKey(platform="zai", email=email, password=password, api_key=api_key,
                                    error="Login gagal untuk klaim")
            zcode_jwt, _ = await self._oauth_jwt()
            if not zcode_jwt:
                return HarvestedKey(platform="zai", email=email, password=password, api_key=api_key,
                                    error="OAuth gagal saat klaim")
            # Persist session so future runs skip the login step.
            try:
                cks = await self.cdp.get_cookies(["https://chat.z.ai"])
            except Exception:
                cks = []
            extra = {**extra, "zcodeJwtToken": zcode_jwt, "cookies": cks}

        self.log(f"[zai] Klaim Start Plan untuk {email}...")
        param = await self.solve_claim_captcha(timeout=self.config.aliyun_timeout)
        if not param:
            return HarvestedKey(platform="zai", email=email, password=password, api_key=api_key,
                                error="Captcha klaim tidak diselesaikan",
                                extra={**extra, "startPlanClaimed": False})
        claimed, msg = self.claim_start_plan(zcode_jwt, param)
        self.log(f"[zai] Hasil klaim: {msg}")
        return HarvestedKey(platform="zai", email=email, password=password, api_key=api_key,
                            error=None if claimed else msg,
                            extra={**extra, "startPlanClaimed": claimed})

    async def harvest(self) -> HarvestedKey:
        """Run complete end-to-end harvest for Z.ai."""
        # 1. Email source: catch-all IMAP preferred (Z.ai rejects disposable domains).
        dom = (os.getenv("EMAIL_DOMAIN") or "").lstrip("@")
        iu = os.getenv("IMAP_USER")
        ipw = os.getenv("IMAP_PASSWORD")
        imap_on = os.getenv("IMAP_ENABLED", "").lower() in ("1", "true", "yes")
        imap_svc = None
        mailbox = None
        if dom and iu and ipw and imap_on:
            from .grok_farm import GmailImapService

            email_addr = f"zai_{secrets.token_hex(4)}@{dom}"
            imap_svc = GmailImapService(
                iu, ipw, host=os.getenv("IMAP_HOST", "imap.gmail.com"),
                port=int(os.getenv("IMAP_PORT", "993")),
            )
            imap_svc.email = email_addr
            self.log(f"[zai] Catch-all IMAP mailbox: {email_addr}")
        else:
            self.log("[zai] Membuat mailbox mail.tm...")
            mailbox = await self.mail.create_mailbox()
            email_addr = mailbox.address
            self.log(f"[zai] Mailbox siap: {email_addr}")
        password = _rand_password()

        # 2. Navigate to chat.z.ai/auth
        self.log(f"[zai] Membuka {ZAI_AUTH_URL}...")
        await self.cdp.navigate(ZAI_AUTH_URL)
        await asyncio.sleep(4.0)

        # 3. Click "Continue with Email"
        await self.cdp.evaluate(
            """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/continue with email/i.test((x.innerText||'').replace(/\\n/g,' ')));if(b)b.click();})()"""
        )
        await asyncio.sleep(2.0)

        # 4. Switch to the "Sign up" tab
        await self.cdp.evaluate(
            """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^sign up$/i.test((x.innerText||'').trim()));if(b)b.click();})()"""
        )
        await asyncio.sleep(2.0)

        # 5. Fill Full Name + Email + Password
        await self.cdp.evaluate(
            """(()=>{
                const set=(sel,val)=>{const el=document.querySelector(sel);if(!el)return false;const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,val);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true;};
                set('input[placeholder*="Full Name" i]', %s);
                set('input[name="email"]', %s);
                set('input[name="new-password"]', %s);
            })()""" % (json.dumps("Zai User"), json.dumps(        email_addr), json.dumps(password))
        )
        await asyncio.sleep(1.5)

        # 6. Trigger and auto-solve the Aliyun captcha
        await self.cdp.evaluate(
            """(()=>{const el=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&/start verification/i.test((e.textContent||'').trim()));if(el){(el.closest('button')||el).click();}})()"""
        )
        await asyncio.sleep(4.0)
        solved = await self.solve_aliyun_slider(timeout=45.0)
        if not solved:
            self.log("[zai] Auto-solver tidak berhasil, lanjut solve manual...")
            solved = await self.wait_for_manual_captcha(timeout=self.config.aliyun_timeout)
        if not solved:
            return HarvestedKey(
                platform="zai",
                email=        email_addr,
                password=password,
                error="Captcha Aliyun tidak terselesaikan",
            )

        # 7. Submit "Create Account"
        await self.cdp.evaluate(
            """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/create account/i.test((x.innerText||'').trim()));if(b)b.click();})()"""
        )
        await asyncio.sleep(6.0)
        cur = await self.cdp.evaluate("window.location.href")
        self.log(f"[zai] Setelah Create Account: {cur}")

        # 8. Email verification via link (Z.ai sends a verify_email URL)
        if cur and "/auth/verify" in cur:
            source = imap_svc or mailbox
            link = await self.wait_for_verify_link(source, timeout=max(150.0, self.config.wait_seconds))
            if not link:
                return HarvestedKey(
                    platform="zai", email=email_addr, password=password,
                    error="Email verifikasi zai tidak diterima",
                )
            self.log("[zai] Membuka link verifikasi email...")
            await self.cdp.navigate(link)
            await asyncio.sleep(6.0)
            # "Complete Registration" page: set password + confirm, then submit.
            await self.cdp.evaluate(
                """(()=>{
                    const set=(el,val)=>{if(!el)return;const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,val);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
                    const pws=[...document.querySelectorAll('input[type="password"]')];
                    set(pws[0], %s);
                    set(pws[1], %s);
                })()""" % (json.dumps(password), json.dumps(password))
            )
            await asyncio.sleep(1.0)
            await self.cdp.evaluate(
                """(()=>{const b=[...document.querySelectorAll('button')].find(x=>/complete registration/i.test((x.innerText||'').trim()));if(b)b.click();})()"""
            )
            await asyncio.sleep(6.0)
            self.log(f"[zai] Setelah Complete Registration: {await self.cdp.evaluate('window.location.href')}")

        # 6. ZCode OAuth → JWT
        zcode_jwt, zai_access = await self._oauth_jwt()
        if not zcode_jwt or not zai_access:
            return HarvestedKey(
                platform="zai", email=email_addr, password=password,
                error="Gagal mendapatkan OAuth token ZCode/Z.ai",
            )

        # 7. Claim the free Start Plan (Aliyun captcha — traceless or manual slider)
        self.log("[zai] Klaim Start Plan (GLM-5.3 3M token/hari)...")
        claimed = False
        captcha_param = await self.solve_claim_captcha(timeout=self.config.aliyun_timeout)
        if captcha_param:
            claimed, claim_msg = self.claim_start_plan(zcode_jwt, captcha_param)
            self.log(f"[zai] Status klaim Start Plan: {claim_msg}")
        else:
            self.log("[zai] Klaim Start Plan dilewati (captcha tidak diselesaikan).")

        # 8. Mint Business API key
        self.log("[zai] Membuat API key resmi Z.ai Coding Plan...")
        key_info = self.mint_plan_api_key(zai_access)
        plan_api_key = key_info.get("planApiKey", "")
        self.log(f"[zai] API Key berhasil didapatkan: {plan_api_key[:12]}... (Org: {key_info.get('organization')})")

        # 9. Capture session (for later re-claim without signup) and return
        cookies = []
        try:
            cookies = await self.cdp.get_cookies(["https://chat.z.ai"])
        except Exception:
            pass
        sess_token = next((c.get("value") for c in cookies if c.get("name") == "token"), None)
        return HarvestedKey(
            platform="zai",
            email=email_addr,
            password=password,
            api_key=plan_api_key,
            extra={
                "zcodeJwtToken": zcode_jwt,
                "zaiAccessToken": zai_access,
                "zaiSessionToken": sess_token,
                "cookies": cookies,
                "startPlanClaimed": claimed,
            },
        )


def load_unclaimed(output_dir: str = "harvest") -> dict | None:
    """Return the latest harvested Z.ai account that hasn't claimed the Start Plan.

    Picks the newest record per email (JSONL is append-only) so a later record that
    carries the stored JWT/cookies is preferred, and returns the first unclaimed one.
    """
    from pathlib import Path

    p = Path(output_dir) / "zai_keys.jsonl"
    if not p.exists():
        return None
    latest: dict[str, dict] = {}
    order: list[str] = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        em = rec.get("email")
        if not em:
            continue
        if em not in latest:
            order.append(em)
        latest[em] = rec
    candidates = [latest[em] for em in order]
    # Prefer accounts we already hold a JWT for, then fall back to any with a password.
    for want_jwt in (True, False):
        for rec in candidates:
            extra = rec.get("extra") or {}
            if extra.get("startPlanClaimed"):
                continue
            if want_jwt and not extra.get("zcodeJwtToken"):
                continue
            if not want_jwt and not rec.get("password"):
                continue
            return rec
    return None
