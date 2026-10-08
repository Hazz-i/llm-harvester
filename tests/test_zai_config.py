from llmharvester.catalog import TARGET_ZAI, get_target_catalog
from llmharvester.config import HarvesterConfig, ZaiConfig


def test_catalog_zai():
    assert TARGET_ZAI == "zai"
    catalog = get_target_catalog(TARGET_ZAI)
    assert catalog.name == "zai"
    assert "GLM-5.3" in catalog.models
    assert "GLM-5.3-Flash" in catalog.models


def test_config_zai_defaults():
    cfg = HarvesterConfig.from_env()
    assert hasattr(cfg, "zai")
    assert isinstance(cfg.zai, ZaiConfig)
    assert cfg.zai.key_name_prefix == "zai-glm"
    assert cfg.zai.aliyun_timeout == 120.0
