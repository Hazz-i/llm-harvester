# Z.ai / ZCode GLM Harvester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated harvester for Z.ai (`chat.z.ai`), claiming the ZCode desktop free Start Plan (`zcode-v3-start-plan`) with flagship GLM-5.3 quota, minting coding-plan API keys, and wiring them into 9Router under provider `glm`.

**Architecture:** Native CDP browser controller automates `chat.z.ai` signup and OTP email verification via `MailProvider`, followed by ZCode OAuth token exchange, Aliyun Captcha 2.0 interactive solve prompt, plan claim, business API key generation, and registration into 9Router (`POST /api/providers`).

**Tech Stack:** Python 3.10+, Playwright/CDP (Chrome DevTools Protocol), HTTPX, Urllib, Pytest.

## Global Constraints

- Target ID: `zai`
- Quota: GLM-5.3 (3,000,000 tokens/day), GLM-5.3-Flash (5,000,000 tokens/day)
- Output Ledger: `harvest/zai_keys.jsonl`
- 9Router Provider: `glm` (Zai GLM Coding)
- Branch: `feat/zai-harvester` (in `.worktrees/feat-zai-harvester`)

---

### Task 1: Catalog & Config Definition for Z.ai

**Files:**
- Modify: `src/llmharvester/catalog.py`
- Modify: `src/llmharvester/config.py`
- Create: `tests/test_zai_config.py`

**Interfaces:**
- Consumes: `HarvesterConfig` and `TargetCatalog`
- Produces: `TARGET_ZAI = "zai"`, `ZaiConfig(key_name_prefix="zai-glm", wait_seconds=120.0, max_retries=2, aliyun_timeout=120.0)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_zai_config.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_config.py -v`
Expected: FAIL with `cannot import name 'TARGET_ZAI'`

- [ ] **Step 3: Modify `catalog.py` and `config.py`**

In `src/llmharvester/catalog.py`:
Add `TARGET_ZAI = "zai"` and register `TargetCatalog` entry:
```python
TARGET_ZAI: Final[str] = "zai"

# Add to ALL_TARGETS:
ALL_TARGETS: Final[tuple[str, ...]] = (
    TARGET_ZEROTWO,
    TARGET_TOKENHARBOR,
    TARGET_TOKENMIX,
    TARGET_ELEVENLABS,
    TARGET_GROK,
    TARGET_WEBSHARE,
    TARGET_WARP,
    TARGET_ZAI,
)

# In get_target_catalog:
if target == TARGET_ZAI:
    return TargetCatalog(
        name=TARGET_ZAI,
        display_name="Z.ai (GLM-5.3 Coding Plan)",
        category="oauth",
        models=["GLM-5.3", "GLM-5.3-Flash", "GLM-4.5-Flash"],
        default_port=20128,
        ledger_file="zai_keys.jsonl",
    )
```

In `src/llmharvester/config.py`:
Define `ZaiConfig` and add `zai: ZaiConfig = field(default_factory=ZaiConfig)` to `HarvesterConfig`.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llmharvester/catalog.py src/llmharvester/config.py tests/test_zai_config.py
git commit -m "feat(zai): add catalog and config definitions for target zai"
```

---

### Task 2: 9Router GLM Provider Registration Helper

**Files:**
- Modify: `src/llmharvester/router9.py`
- Create: `tests/test_router9_zai.py`

**Interfaces:**
- Consumes: `NineRouterClient`
- Produces: `NineRouterClient.register_glm_connection(api_key: str, name: str) -> RouterResult`

- [ ] **Step 1: Write the failing test**

Create `tests/test_router9_zai.py`:
```python
from unittest.mock import patch, MagicMock
from llmharvester.router9 import NineRouterClient


def test_register_glm_connection():
    client = NineRouterClient("http://localhost:20128")
    with patch.object(client, "_post", return_value=(200, {"id": "conn_123", "success": True})):
        res = client.register_glm_connection("test_api_key.secret_123", name="GLM-Zai-1")
        assert res.ok is True
        assert res.connection_id == "conn_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_router9_zai.py -v`
Expected: FAIL with `AttributeError: 'NineRouterClient' object has no attribute 'register_glm_connection'`

- [ ] **Step 3: Implement `register_glm_connection` in `router9.py`**

In `src/llmharvester/router9.py`, implement:
```python
def register_glm_connection(self, api_key: str, name: str = "GLM-Zai") -> RouterResult:
    """Register a Z.ai Coding Plan API key into 9Router under provider 'glm'."""
    payload = {
        "provider": "glm",
        "authMode": "apikey",
        "name": name,
        "apiKey": api_key,
        "models": ["GLM-5.3", "GLM-5.3-Flash", "GLM-4.5-Flash"],
    }
    status, data = self._post("/api/providers", payload)
    if status in (200, 201) and (data.get("id") or data.get("success")):
        return RouterResult(ok=True, connection_id=data.get("id", "glm_conn"), message="Registered GLM connection", raw=data)
    return RouterResult(ok=False, message=f"Failed to register GLM connection: {data}", raw=data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_router9_zai.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llmharvester/router9.py tests/test_router9_zai.py
git commit -m "feat(router9): add register_glm_connection for zai provider"
```

---

### Task 3: Core ZaiHarvester Module (`zai.py`)

**Files:**
- Create: `src/llmharvester/zai.py`
- Create: `tests/test_zai_core.py`

**Interfaces:**
- Consumes: `CDPSession`, `MailProvider`, `NineRouterClient`, `ZaiConfig`
- Produces: `class ZaiHarvester`:
  - `extract_otp(email_text: str) -> str | None`
  - `exchange_zcode_token(code: str, state: str) -> dict`
  - `mint_plan_api_key(zai_access_token: str) -> str`
  - `claim_start_plan(zcode_jwt: str, captcha_param: str) -> bool`
  - `harvest() -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/test_zai_core.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from llmharvester.zai import extract_otp, ZaiHarvester


def test_extract_otp():
    text = "Your Z.ai verification code is 849201. It will expire in 10 minutes."
    assert extract_otp(text) == "849201"
    assert extract_otp("Kode verifikasi Anda: 123456") == "123456"
    assert extract_otp("No code here") is None


def test_exchange_zcode_token_mock():
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"code": 0, "data": {"token": "jwt_token_abc", "zai": {"access_token": "zai_acc_123"}}}'
        mock_url.return_value.__enter__.return_value = mock_resp

        res = ZaiHarvester.exchange_zcode_token("code123", "state123")
        assert res["zcodeJwtToken"] == "jwt_token_abc"
        assert res["zaiAccessToken"] == "zai_acc_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llmharvester.zai'`

- [ ] **Step 3: Implement `src/llmharvester/zai.py`**

Implement complete `ZaiHarvester` module including:
- OTP regex extraction
- OAuth authorization code exchange (`exchange_zcode_token`)
- Aliyun captcha interactive solve prompt & verification
- Billing plan claim (`POST /api/v1/zcode-plan/billing/claim`)
- Business API key generation (`mint_plan_api_key`)
- CDP-based signup automation on `chat.z.ai`
- Persistence to `harvest/zai_keys.jsonl` and 9Router connection

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_core.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llmharvester/zai.py tests/test_zai_core.py
git commit -m "feat(zai): implement core ZaiHarvester module"
```

---

### Task 4: CLI, Engine & Interactive TUI Integration

**Files:**
- Modify: `src/llmharvester/engine.py`
- Modify: `src/llmharvester/cli.py`
- Modify: `main.py`
- Create: `tests/test_zai_cli.py`

**Interfaces:**
- Consumes: `ZaiHarvester`, `ALL_TARGETS`
- Produces: CLI `--target zai`, TUI menu item `[8] Harvest Z.ai (GLM-5.3 Coding Plan)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_zai_cli.py`:
```python
from llmharvester.cli import build_parser


def test_cli_accepts_target_zai():
    parser = build_parser()
    args = parser.parse_args(["--target", "zai"])
    assert args.target == "zai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_cli.py -v`
Expected: FAIL if `zai` is rejected as choices or not in parser.

- [ ] **Step 3: Integrate into `engine.py`, `cli.py`, and `main.py`**

- In `src/llmharvester/engine.py`: Wire target `"zai"` into `HarvestEngine.run()` calling `ZaiHarvester`.
- In `src/llmharvester/cli.py`: Include `zai` in argparse targets and status display.
- In `main.py`: Add menu choice for Z.ai in interactive terminal menu.

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llmharvester/engine.py src/llmharvester/cli.py main.py tests/test_zai_cli.py
git commit -m "feat(zai): integrate zai target into engine, cli, and interactive tui"
```

---

### Task 5: Comprehensive Verification & Regression Check

**Files:**
- Tests: `tests/test_zai_config.py`, `tests/test_router9_zai.py`, `tests/test_zai_core.py`, `tests/test_zai_cli.py`

- [ ] **Step 1: Run full test suite for Z.ai**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_zai*.py tests/test_router9_zai.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run existing non-regression test suite**

Run: `/home/kki-laptop-025/my-code/zt-harvester/.venv/bin/pytest tests/test_catalog.py tests/test_cli_target.py tests/test_compat.py tests/test_tokenharbor.py tests/test_tokenmix.py -v`
Expected: ALL PASS

- [ ] **Step 3: Verify CLI help message**

Run: `python main.py --help`
Verify that `zai` is listed under target options.

- [ ] **Step 4: Final commit and summary**

```bash
git status
```
Ensure branch `feat/zai-harvester` is clean.
