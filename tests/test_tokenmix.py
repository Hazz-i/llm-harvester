import pytest
from unittest.mock import AsyncMock
from llmharvester.config import TokenMixConfig
from llmharvester.tokenmix import TokenMixCreator
from llmharvester.tokenharbor import HarvestedKey
from llmharvester.mail import Mailbox, Message


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
        if "cf-turnstile-response" in expression:
            return True
        if "sk-tm-" in expression:
            return "sk-tm-abcdef1234567890"
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
async def test_tokenmix_creator_flow():
    cdp = MockCDP()
    mail = AsyncMock()
    mailbox = Mailbox(address="tm_user@mail.tm", password="Password123!", domain="mail.tm")
    mail.create_mailbox.return_value = mailbox
    mail.wait_for_message.return_value = Message(
        id="m2",
        subject="Your TokenMix Verification Code",
        sender="noreply@tokenmix.ai",
        text="Your verification code is 654321 or click https://tokenmix.ai/verify?token=abc987",
        html="<p>Code: 654321</p>",
    )

    cfg = TokenMixConfig(key_name_prefix="tm-test", wait_seconds=10.0, max_retries=1)
    creator = TokenMixCreator(cdp, mail, config=cfg)
    creator._sleep = AsyncMock()

    res = await creator.create_account()

    assert isinstance(res, HarvestedKey)
    assert res.ok
    assert res.platform == "tokenmix"
    assert res.email == "tm_user@mail.tm"
    assert res.api_key == "sk-tm-abcdef1234567890"
    assert any("tokenmix.ai" in u for u in cdp.navigated)
