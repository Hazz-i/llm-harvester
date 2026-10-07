import pytest
from unittest.mock import AsyncMock, patch
from llmharvester.config import HarvesterConfig, ElevenLabsConfig
from llmharvester.elevenlabs import (
    ElevenLabsCreator,
    generate_strong_password,
    extract_elevenlabs_verification_link,
    validate_xi_api_key,
)
from llmharvester.tokenharbor import HarvestedKey
from llmharvester.mail import Mailbox, Message


class MockCDP:
    def __init__(self):
        self.navigated = []
        self.evaluations = []
        self.typed = []

    async def navigate(self, url: str, wait_ms: int = 15000) -> None:
        self.navigated.append(url)

    async def evaluate(self, expression: str, await_promise: bool = False):
        self.evaluations.append(expression)
        if "window.location.href" in expression:
            return self.navigated[-1] if self.navigated else "https://elevenlabs.io/sign-up"
        if "role=\"alert\"" in expression:
            return ""
        if "cf-turnstile-response" in expression:
            if "length" in expression:
                return 50
            return True
        if "sk_" in expression or "xi_" in expression or "api-key" in expression:
            return "xi_live_mockkey_9876543210123456789012"
        if "ElevenCreative" in expression or "Choose your platform" in expression:
            return False
        if "document.body" in expression or "innerText" in expression:
            return "Please check your email to verify your account"
        if "input[type=\"email\"]" in expression and "input[type=\"password\"]" in expression:
            return True
        return True

    async def type_text(self, selector: str, text: str) -> None:
        self.typed.append((selector, text))

    async def insert_text(self, text: str) -> None:
        pass


def test_generate_strong_password():
    pwd = generate_strong_password(16)
    assert len(pwd) == 16
    assert any(c.isupper() for c in pwd)
    assert any(c.islower() for c in pwd)
    assert any(c.isdigit() for c in pwd)
    assert any(c in "!@#$%&*" for c in pwd)


def test_extract_elevenlabs_verification_link():
    raw_html = """
    <div>
        <p>Click below to verify your email address:</p>
        <a href="https://elevenlabs.io/app/action?mode=verifyEmail&amp;oobCode=XYZ123456">Verify Email</a>
    </div>
    """
    link = extract_elevenlabs_verification_link(raw_html)
    assert link == "https://elevenlabs.io/app/action?mode=verifyEmail&oobCode=XYZ123456"

    direct_url = "https://elevenlabs.io/verify-email?token=abcDEF12345"
    assert extract_elevenlabs_verification_link(direct_url) == direct_url


@pytest.mark.asyncio
async def test_validate_xi_api_key():
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {
            "subscription": {
                "character_count": 150,
                "character_limit": 10000,
                "tier": "free",
                "status": "active",
            }
        }
        mock_get.return_value = mock_resp

        info = await validate_xi_api_key("xi_live_testkey")
        assert info is not None
        assert info["character_limit"] == 10000
        assert info["character_count"] == 150
        assert info["tier"] == "free"


@pytest.mark.asyncio
async def test_elevenlabs_creator_flow():
    cdp = MockCDP()
    mail = AsyncMock()
    mailbox = Mailbox(address="el_user@mail.tm", password="Password123!", domain="mail.tm")
    mail.create_mailbox.return_value = mailbox
    mail.wait_for_message.return_value = Message(
        id="el_m1",
        subject="Verify your email for ElevenLabs",
        sender="noreply@elevenlabs.io",
        text="Click to verify: https://elevenlabs.io/app/action?mode=verifyEmail&oobCode=testcode123",
        html="<a href='https://elevenlabs.io/app/action?mode=verifyEmail&amp;oobCode=testcode123'>Verify</a>",
    )

    cfg = ElevenLabsConfig(key_name_prefix="el-test", wait_seconds=5.0, max_retries=1)
    creator = ElevenLabsCreator(cdp, mail, config=cfg)
    creator._sleep = AsyncMock()

    with patch("llmharvester.elevenlabs.validate_xi_api_key", new_callable=AsyncMock) as mock_val:
        mock_val.return_value = {"character_limit": 10000, "character_count": 0, "tier": "free"}
        res = await creator.create_account()

    assert isinstance(res, HarvestedKey)
    assert res.ok
    assert res.platform == "elevenlabs"
    assert res.email == "el_user@mail.tm"
    assert "xi_live_" in res.api_key
    assert any("elevenlabs.io/sign-up" in u for u in cdp.navigated)
    assert any("verifyEmail" in u for u in cdp.navigated)


def test_elevenlabs_config_from_env(monkeypatch):
    monkeypatch.setenv("EL_KEY_PREFIX", "custom-el")
    monkeypatch.setenv("EL_NODE_NAME", "MyElevenLabs")
    monkeypatch.setenv("IMAP_USER", "user@test.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("IMAP_ENABLED", "true")

    cfg = HarvesterConfig.from_env()
    assert cfg.elevenlabs.key_name_prefix == "custom-el"
    assert cfg.elevenlabs.node_name == "MyElevenLabs"
    assert cfg.elevenlabs.imap_user == "user@test.com"
    assert cfg.elevenlabs.imap_password == "secret"
    assert cfg.elevenlabs.imap_enabled is True
