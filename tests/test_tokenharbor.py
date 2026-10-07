import pytest
from unittest.mock import AsyncMock, MagicMock
from ztharvester.config import TokenHarborConfig
from ztharvester.tokenharbor import TokenHarborCreator, HarvestedKey
from ztharvester.mail import Mailbox, Message


class MockCDP:
    def __init__(self):
        self.navigated = []
        self.evaluations = []
        self.clicked_selectors = []
        self.clicked_texts = []
        self.typed = []

    async def navigate(self, url: str, wait_ms: int = 15000) -> None:
        self.navigated.append(url)

    async def evaluate(self, expression: str, await_promise: bool = False):
        self.evaluations.append(expression)
        if "thk_live_" in expression or "api-key" in expression:
            return "thk_live_1234567890abcdef"
        return True

    async def click_text(self, text: str) -> bool:
        self.clicked_texts.append(text)
        return True

    async def click_selector(self, selector: str) -> bool:
        self.clicked_selectors.append(selector)
        return True

    async def type_text(self, selector: str, text: str) -> None:
        self.typed.append((selector, text))

    async def screenshot(self):
        return None

    async def get_cookies(self, urls=None):
        return []


@pytest.mark.asyncio
async def test_tokenharbor_creator_flow():
    cdp = MockCDP()
    mail = AsyncMock()
    mailbox = Mailbox(address="test@mail.tm", password="Password123!", domain="mail.tm")
    mail.create_mailbox.return_value = mailbox
    mail.wait_for_message.return_value = Message(
        id="m1",
        subject="Verify your Token Harbor email",
        sender="noreply@tokenharbor.ai",
        text="Click here to verify: https://tokenharbor.ai/verify-email?token=xyz123abc",
        html="<a href='https://tokenharbor.ai/verify-email?token=xyz123abc'>Verify</a>",
    )

    cfg = TokenHarborConfig(key_name_prefix="test-key", wait_seconds=10.0, max_retries=1)
    creator = TokenHarborCreator(cdp, mail, config=cfg)
    creator._sleep = AsyncMock()

    res = await creator.create_account()

    assert isinstance(res, HarvestedKey)
    assert res.ok
    assert res.platform == "tokenharbor"
    assert res.email == "test@mail.tm"
    assert res.api_key == "thk_live_1234567890abcdef"
    assert any("https://tokenharbor.ai/login?mode=signup" in u for u in cdp.navigated)
    assert any("https://tokenharbor.ai/verify-email?token=xyz123abc" in u for u in cdp.navigated)
    assert any("https://tokenharbor.ai/dashboard/api-keys" in u for u in cdp.navigated)
