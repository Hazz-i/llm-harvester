import pytest
from unittest.mock import AsyncMock, patch
from ztharvester.config import HarvesterConfig, TokenHarborConfig, TokenMixConfig
from ztharvester.engine import Harvester
from ztharvester.router9 import NineRouterClient, RouterResult
from ztharvester.tokenharbor import HarvestedKey


@pytest.mark.asyncio
async def test_router_connect_session_multi_platform():
    client = NineRouterClient("http://127.0.0.1:20128")

    with patch.object(client, "add_connection", new_callable=AsyncMock) as mock_add:
        mock_add.return_value = RouterResult(ok=True, connection_id="conn-th-1")

        # Token Harbor
        res_th = await client.connect_session(
            email="user@mail.tm",
            access_token="thk_live_12345",
            node_id="node-th-id",
            node_prefix="tokenharbor",
            extra={
                "base_url": "https://tokenharbor.ai/v1",
                "node_name": "Token Harbor",
                "display_name": "Token Harbor",
                "account_type": "tokenharbor",
            },
        )
        assert res_th.ok is True
        call_kwargs = mock_add.call_args.kwargs
        assert call_kwargs["provider"] == "node-th-id"
        assert call_kwargs["api_key"] == "thk_live_12345"
        assert "Token Harbor · user@mail.tm" == call_kwargs["name"]
        assert call_kwargs["provider_specific"]["accountType"] == "tokenharbor"

        # TokenMix
        res_tm = await client.connect_session(
            email="tm@mail.tm",
            access_token="sk-tm-abcde",
            node_id="node-tm-id",
            node_prefix="tokenmix",
            extra={
                "base_url": "https://api.tokenmix.ai/v1",
                "node_name": "TokenMix",
                "display_name": "TokenMix",
                "account_type": "tokenmix",
            },
        )
        assert res_tm.ok is True
        call_kwargs_tm = mock_add.call_args.kwargs
        assert call_kwargs_tm["provider"] == "node-tm-id"
        assert call_kwargs_tm["api_key"] == "sk-tm-abcde"
        assert "TokenMix · tm@mail.tm" == call_kwargs_tm["name"]
        assert call_kwargs_tm["provider_specific"]["accountType"] == "tokenmix"


@pytest.mark.asyncio
async def test_engine_pushes_tokenharbor_to_router(tmp_path):
    cfg = HarvesterConfig(
        target="tokenharbor",
        output_dir=str(tmp_path),
        tokenharbor=TokenHarborConfig(key_name_prefix="test-th"),
    )
    cfg.router.enabled = True
    harvester = Harvester(cfg)

    fake_key = HarvestedKey(
        platform="tokenharbor",
        email="test@mail.tm",
        password="Pass",
        api_key="thk_live_router_test",
    )

    fake_router = NineRouterClient("http://127.0.0.1:20128")
    fake_router.health = AsyncMock(return_value=True)
    fake_router.ensure_node = AsyncMock(return_value="node-th-123")
    fake_router.sync_custom_models = AsyncMock(return_value=5)
    fake_router.connect_session = AsyncMock(return_value=RouterResult(ok=True, connection_id="c1"))

    with patch.object(harvester, "_make_cdp", new_callable=AsyncMock), \
         patch("ztharvester.engine.TokenHarborCreator") as MockCreator, \
         patch("ztharvester.engine.MailProvider"), \
         patch("ztharvester.engine.NineRouterClient", return_value=fake_router):

        instance = MockCreator.return_value
        instance.create_account = AsyncMock(return_value=fake_key)

        summary = await harvester.run(count=1, target="tokenharbor")
        assert summary["harvested"] == 1

        rec = harvester.ledger.records[0]
        assert rec["api_key"] == "thk_live_router_test"
        assert "router" in rec
        assert rec["router"]["ok"] is True
        assert "models" in rec
        assert len(rec["models"]) > 0

        # Verify sync_custom_models and connect_session were invoked
        assert fake_router.sync_custom_models.called
        assert fake_router.connect_session.called


@pytest.mark.asyncio
async def test_engine_pushes_tokenmix_to_router(tmp_path):
    cfg = HarvesterConfig(
        target="tokenmix",
        output_dir=str(tmp_path),
        tokenmix=TokenMixConfig(key_name_prefix="test-tm"),
    )
    cfg.router.enabled = True
    harvester = Harvester(cfg)

    fake_key = HarvestedKey(
        platform="tokenmix",
        email="tm@mail.tm",
        password="Pass",
        api_key="sk-tm-router_test",
    )

    fake_router = NineRouterClient("http://127.0.0.1:20128")
    fake_router.health = AsyncMock(return_value=True)
    fake_router.ensure_node = AsyncMock(return_value="node-tm-456")
    fake_router.sync_custom_models = AsyncMock(return_value=10)
    fake_router.connect_session = AsyncMock(return_value=RouterResult(ok=True, connection_id="c2"))

    with patch.object(harvester, "_make_cdp", new_callable=AsyncMock), \
         patch("ztharvester.engine.TokenMixCreator") as MockCreator, \
         patch("ztharvester.engine.MailProvider"), \
         patch("ztharvester.engine.NineRouterClient", return_value=fake_router):

        instance = MockCreator.return_value
        instance.create_account = AsyncMock(return_value=fake_key)

        summary = await harvester.run(count=1, target="tokenmix")
        assert summary["harvested"] == 1

        rec = harvester.ledger.records[0]
        assert rec["api_key"] == "sk-tm-router_test"
        assert "router" in rec
        assert rec["router"]["ok"] is True
        assert "models" in rec
        assert len(rec["models"]) > 0

        assert fake_router.sync_custom_models.called
        assert fake_router.connect_session.called
