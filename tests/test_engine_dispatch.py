import pytest
from unittest.mock import AsyncMock, patch
from llmharvester.config import HarvesterConfig, TokenHarborConfig, TokenMixConfig
from llmharvester.engine import Harvester
from llmharvester.tokenharbor import HarvestedKey


@pytest.mark.asyncio
async def test_engine_dispatch_tokenharbor(tmp_path):
    cfg = HarvesterConfig(
        target="tokenharbor",
        output_dir=str(tmp_path),
        tokenharbor=TokenHarborConfig(key_name_prefix="test-th"),
    )
    harvester = Harvester(cfg)
    assert harvester.ledger.path.name == "tokenharbor_keys.jsonl"

    fake_key = HarvestedKey(
        platform="tokenharbor",
        email="test@mail.tm",
        password="Pass",
        api_key="thk_live_test123",
    )

    with patch.object(harvester, "_make_cdp", new_callable=AsyncMock) as mock_cdp, \
         patch("llmharvester.engine.TokenHarborCreator") as MockCreator, \
         patch("llmharvester.engine.MailProvider") as MockMail:
        
        instance = MockCreator.return_value
        instance.create_account = AsyncMock(return_value=fake_key)

        summary = await harvester.run(count=1, target="tokenharbor")
        assert summary["total"] == 1
        assert summary["harvested"] == 1
        assert harvester.ledger.records[0]["api_key"] == "thk_live_test123"


@pytest.mark.asyncio
async def test_engine_dispatch_tokenmix(tmp_path):
    cfg = HarvesterConfig(
        target="tokenmix",
        output_dir=str(tmp_path),
        tokenmix=TokenMixConfig(key_name_prefix="test-tm"),
    )
    harvester = Harvester(cfg)
    assert harvester.ledger.path.name == "tokenmix_keys.jsonl"

    fake_key = HarvestedKey(
        platform="tokenmix",
        email="tm@mail.tm",
        password="Pass",
        api_key="sk-tm-test123",
    )

    with patch.object(harvester, "_make_cdp", new_callable=AsyncMock) as mock_cdp, \
         patch("llmharvester.engine.TokenMixCreator") as MockCreator, \
         patch("llmharvester.engine.MailProvider") as MockMail:
        
        instance = MockCreator.return_value
        instance.create_account = AsyncMock(return_value=fake_key)

        summary = await harvester.run(count=1, target="tokenmix")
        assert summary["total"] == 1
        assert summary["harvested"] == 1
        assert harvester.ledger.records[0]["api_key"] == "sk-tm-test123"
