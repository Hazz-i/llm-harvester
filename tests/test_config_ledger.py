import json
from ztharvester.config import HarvesterConfig
from ztharvester.engine import Ledger


def test_config_env(monkeypatch):
    monkeypatch.setenv("NINEROUTER_URL", "http://x:1")
    monkeypatch.setenv("ZT_CONCURRENCY", "3")
    cfg = HarvesterConfig.from_env()
    assert cfg.router.base_url == "http://x:1"
    assert cfg.concurrency == 3

    # LLM_ prefix takes precedence over ZT_
    monkeypatch.setenv("LLM_CONCURRENCY", "5")
    cfg2 = HarvesterConfig.from_env()
    assert cfg2.concurrency == 5


def test_ledger_append_and_summary(tmp_path):
    led = Ledger(tmp_path / "s.jsonl")
    led.append({"email": "a@b.c", "access_token": "t", "router": {"ok": True}})
    led.append({"email": "d@e.f", "access_token": "", "router": {"ok": False}})
    assert led.summary() == {"total": 2, "harvested": 1, "routed": 1}
    reloaded = Ledger(tmp_path / "s.jsonl")
    assert len(reloaded.records) == 2


def test_config_tokenharbor_and_tokenmix_toml(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text("""
target = "tokenharbor"
concurrency = 2

[tokenharbor]
key_name_prefix = "custom-th"
wait_seconds = 60.0
max_retries = 3

[tokenmix]
key_name_prefix = "custom-tm"
referral_code = "ref123"
wait_seconds = 90.0
max_retries = 4
""")
    cfg = HarvesterConfig.from_toml(toml_file)
    assert cfg.target == "tokenharbor"
    assert cfg.concurrency == 2
    assert cfg.tokenharbor.key_name_prefix == "custom-th"
    assert cfg.tokenharbor.wait_seconds == 60.0
    assert cfg.tokenharbor.max_retries == 3
    assert cfg.tokenmix.key_name_prefix == "custom-tm"
    assert cfg.tokenmix.referral_code == "ref123"
    assert cfg.tokenmix.wait_seconds == 90.0
    assert cfg.tokenmix.max_retries == 4

