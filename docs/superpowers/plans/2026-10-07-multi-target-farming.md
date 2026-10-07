# Multi-Target Farming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configuration and harvesting drivers for Token Harbor (`tokenharbor.ai`) and TokenMix (`tokenmix.ai`), with an interactive CLI prompt to select the target platform to farm.

**Architecture:** Extend existing `HarvesterConfig` with `[tokenharbor]` and `[tokenmix]` sections and a `target` attribute. Implement modular drivers `TokenHarborCreator` and `TokenMixCreator` reusing `MailProvider` (`mail.tm`) and `CDP` protocols. Update `Harvester` engine to dispatch runs and output to corresponding ledgers, with CLI interactive selection.

**Tech Stack:** Python 3.10+, `dataclasses`, `httpx`, `typer`, `rich`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Retain full backward compatibility for existing ZeroTwo harvesting and 9Router integration.
- Zero new heavy dependencies (no external Playwright binaries required; reuse `LocalCDP` / Chromium).
- All tests run via `.venv/bin/pytest`.

---

### Task 1: Configuration Schema & Parsing for Token Harbor and TokenMix

**Files:**
- Modify: `src/ztharvester/config.py`
- Modify: `config.toml`
- Modify: `config.example.toml`
- Test: `tests/test_config_ledger.py`

**Interfaces:**
- Produces:
  - `TokenHarborConfig(key_name_prefix: str = "prod-th", wait_seconds: float = 120.0, max_retries: int = 2)`
  - `TokenMixConfig(key_name_prefix: str = "prod-tm", referral_code: str | None = None, wait_seconds: float = 120.0, max_retries: int = 2)`
  - `HarvesterConfig.target: str = "select"`
  - `HarvesterConfig.tokenharbor: TokenHarborConfig`
  - `HarvesterConfig.tokenmix: TokenMixConfig`

- [x] **Step 1: Write failing test in `tests/test_config_ledger.py`**
  Add unit tests validating `TokenHarborConfig`, `TokenMixConfig`, and TOML parsing for `[tokenharbor]` and `[tokenmix]` sections.
- [x] **Step 2: Run pytest to verify failure**
  Run `.venv/bin/pytest tests/test_config_ledger.py` and confirm failure.
- [x] **Step 3: Implement config dataclasses and parsing in `src/ztharvester/config.py`**
  Add `TokenHarborConfig`, `TokenMixConfig`, update `HarvesterConfig.from_dict` and `from_env`.
- [x] **Step 4: Update `config.toml` and `config.example.toml`**
  Add `target = "select"`, `[tokenharbor]`, and `[tokenmix]` blocks.
- [x] **Step 5: Run pytest to verify passes**
  Run `.venv/bin/pytest tests/test_config_ledger.py`.
- [x] **Step 6: Commit changes**
  Commit Task 1 changes.

---

### Task 2: Token Harbor Harvester Driver (`TokenHarborCreator`)

**Files:**
- Create: `src/ztharvester/tokenharbor.py`
- Create: `tests/test_tokenharbor.py`

**Interfaces:**
- Consumes:
  - `ztharvester.zerotwo.CDP` (CDP protocol)
  - `ztharvester.mail.MailProvider`
  - `ztharvester.config.TokenHarborConfig`
- Produces:
  - `HarvestedKey(platform: str, email: str, password: str, api_key: str, created_at: float, error: str | None = None)`
  - `TokenHarborCreator(cdp: CDP, mail: MailProvider, config: TokenHarborConfig, log: Any = print)`
  - `TokenHarborCreator.create_account() -> HarvestedKey`

- [x] **Step 1: Write failing mock test in `tests/test_tokenharbor.py`**
  Create unit test with a mock CDP client and mock MailProvider testing the full sequence: email entry -> verify link extraction -> dashboard API key creation.
- [x] **Step 2: Run pytest to verify failure**
  Run `.venv/bin/pytest tests/test_tokenharbor.py` and confirm failure.
- [x] **Step 3: Implement `src/ztharvester/tokenharbor.py`**
  Implement `TokenHarborCreator` with registration, email polling, link extraction, and API key generation.
- [x] **Step 4: Run pytest to verify test passes**
  Run `.venv/bin/pytest tests/test_tokenharbor.py`.
- [x] **Step 5: Commit changes**
  Commit Task 2 changes.

---

### Task 3: TokenMix Harvester Driver (`TokenMixCreator`)

**Files:**
- Create: `src/ztharvester/tokenmix.py`
- Create: `tests/test_tokenmix.py`

**Interfaces:**
- Consumes:
  - `ztharvester.zerotwo.CDP`
  - `ztharvester.mail.MailProvider`
  - `ztharvester.config.TokenMixConfig`
- Produces:
  - `TokenMixCreator(cdp: CDP, mail: MailProvider, config: TokenMixConfig, log: Any = print)`
  - `TokenMixCreator.create_account() -> HarvestedKey`

- [x] **Step 1: Write failing mock test in `tests/test_tokenmix.py`**
  Create unit test testing the TokenMix flow: registration submission with Turnstile solve detection -> email verification -> API key retrieval (`sk-tm-...`).
- [x] **Step 2: Run pytest to verify failure**
  Run `.venv/bin/pytest tests/test_tokenmix.py` and confirm failure.
- [x] **Step 3: Implement `src/ztharvester/tokenmix.py`**
  Implement `TokenMixCreator` with Turnstile waiting logic and API key creation.
- [x] **Step 4: Run pytest to verify test passes**
  Run `.venv/bin/pytest tests/test_tokenmix.py`.
- [x] **Step 5: Commit changes**
  Commit Task 3 changes.

---

### Task 4: Engine Multi-Target Dispatch and Ledger Logging

**Files:**
- Modify: `src/ztharvester/engine.py`
- Create: `tests/test_engine_dispatch.py`

**Interfaces:**
- Consumes:
  - `HarvesterConfig.target`
  - `ZeroTwoCreator`, `TokenHarborCreator`, `TokenMixCreator`
- Produces:
  - `Harvester.run(count: int, target: str | None = None) -> dict[str, Any]`
  - Output files:
    - ZeroTwo: `harvest/sessions.jsonl`
    - Token Harbor: `harvest/tokenharbor_keys.jsonl`
    - TokenMix: `harvest/tokenmix_keys.jsonl`

- [x] **Step 1: Write failing test in `tests/test_engine_dispatch.py`**
  Test engine target dispatching and ledger output selection.
- [x] **Step 2: Run pytest to verify failure**
  Run `.venv/bin/pytest tests/test_engine_dispatch.py`.
- [x] **Step 3: Implement dispatching logic in `src/ztharvester/engine.py`**
  Add target handling for `tokenharbor` and `tokenmix`, writing to their respective ledger files.
- [x] **Step 4: Run pytest to verify test passes**
  Run `.venv/bin/pytest tests/test_engine_dispatch.py`.
- [x] **Step 5: Commit changes**
  Commit Task 4 changes.

---

### Task 5: CLI Target Selection Flag and Interactive Menu

**Files:**
- Modify: `src/ztharvester/cli.py`
- Create: `tests/test_cli_target.py`

**Interfaces:**
- Consumes:
  - CLI flag `--target` / `-t`
  - Interactive selection prompt via `rich.prompt.Prompt`
- Produces:
  - Dynamic target resolution prior to running `harvester.run(...)`

- [x] **Step 1: Write failing test in `tests/test_cli_target.py`**
  Test CLI target flag resolution (`--target tokenharbor`, `--target tokenmix`).
- [x] **Step 2: Run pytest to verify failure**
  Run `.venv/bin/pytest tests/test_cli_target.py`.
- [x] **Step 3: Implement CLI `--target` flag and interactive prompt in `src/ztharvester/cli.py`**
  Add `--target` option to `run` command. If target is `"select"` or not specified, present prompt:
  ```text
  [?] Select farming target:
    1. ZeroTwo (app.zerotwo.ai)
    2. Token Harbor (tokenharbor.ai)
    3. TokenMix (tokenmix.ai)
  ```
- [x] **Step 4: Run pytest across the entire test suite**
  Run `.venv/bin/pytest`.
- [x] **Step 5: Commit changes**
  Commit Task 5 changes.
