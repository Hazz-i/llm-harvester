# Design Spec: Multi-Target Farming (ZeroTwo, Token Harbor, TokenMix)

## 1. Overview
Extend the `zt-harvester` (zt-farming) tool to support multi-target account provisioning and token/key harvesting across three platforms:
1. **ZeroTwo** (`app.zerotwo.ai`) - Existing driver (harvests Supabase JWTs, cookies, CSRF, 9Router integration).
2. **Token Harbor** (`tokenharbor.ai`) - New driver (registers accounts via `mail.tm`, verifies email link, generates `thk_live_...` API keys).
3. **TokenMix** (`tokenmix.ai`) - New driver (registers accounts via `mail.tm`, bypasses Turnstile via browser CDP, generates `sk-tm-...` API keys).

Both new drivers follow the **Unified CDP + `mail.tm` Driver Architecture**:
- Zero additional heavy dependencies (no separate Playwright binary installations required; uses existing `LocalCDP` / Chromium).
- Lightweight and fast mailbox handling purely through `mail.tm` REST API in the background.
- Interactive CLI target selection prompt when running without explicit flags.

---

## 2. Configuration Schema (`ztharvester/config.py`)

### 2.1 New Dataclasses
```python
@dataclass
class TokenHarborConfig:
    key_name_prefix: str = "prod-th"
    wait_seconds: float = 120.0
    max_retries: int = 2

@dataclass
class TokenMixConfig:
    key_name_prefix: str = "prod-tm"
    referral_code: str | None = None
    wait_seconds: float = 120.0
    max_retries: int = 2
```

### 2.2 Updated `HarvesterConfig`
- `target: str = "select"` (values: `"select"`, `"zerotwo"`, `"tokenharbor"`, `"tokenmix"`)
- `tokenharbor: TokenHarborConfig = field(default_factory=TokenHarborConfig)`
- `tokenmix: TokenMixConfig = field(default_factory=TokenMixConfig)`

### 2.3 File Configs (`config.toml` & `config.example.toml`)
Add:
```toml
target = "select"  # "select" prompts interactively, or specify "zerotwo" | "tokenharbor" | "tokenmix"

[tokenharbor]
key_name_prefix = "prod-th"
wait_seconds = 120.0
max_retries = 2

[tokenmix]
key_name_prefix = "prod-tm"
wait_seconds = 120.0
max_retries = 2
```

---

## 3. CLI Interaction & Selection (`ztharvester/cli.py`)

### 3.1 Option `--target` / `-t`
Add `--target` option with choices `["select", "zerotwo", "tokenharbor", "tokenmix"]` to `app.command() run`:
```python
target: str | None = typer.Option(
    None, "--target", "-t",
    help="Target platform to farm: zerotwo | tokenharbor | tokenmix | select"
)
```

### 3.2 Interactive Selection Prompt
If `target is None` or `cfg.target == "select"`:
Display an interactive menu:
```text
Select farming target:
  [1] ZeroTwo      (app.zerotwo.ai)    -> JWT Session, Cookies, 9Router Shim
  [2] Token Harbor (tokenharbor.ai)    -> API Key (thk_live_...), mail.tm
  [3] TokenMix     (tokenmix.ai)       -> API Key (sk-tm-...), mail.tm
Choice [1-3] (default 1):
```
Maps inputs `1`/`zerotwo`, `2`/`tokenharbor`, `3`/`tokenmix` to `cfg.target`.

---

## 4. Driver Implementations

### 4.1 Token Harbor Driver (`ztharvester/tokenharbor.py`)
- **Class:** `TokenHarborCreator`
- **Dependencies:** `cdp: CDP`, `mail: MailProvider`, `TokenHarborConfig`
- **Flow:**
  1. Generate disposable mailbox from `mail.tm`.
  2. Navigate to `https://tokenharbor.ai/login?mode=signup`.
  3. Fill `#email` and password (>= 12 chars), submit form.
  4. Wait for incoming verification email from `mail.tm` via `mail.wait_for_message(mailbox, timeout=wait_seconds)`.
  5. Extract `tokenharbor.ai/verify-email?token=...` link via regex.
  6. Navigate to verification link via CDP.
  7. Navigate to `https://tokenharbor.ai/dashboard/api-keys`.
  8. Click `+ New key`, input random key name, click `Create key`.
  9. Scrape `thk_live_...` API key.
  10. Return result record `HarvestedKey(platform="tokenharbor", email=..., password=..., api_key=...)`.

### 4.2 TokenMix Driver (`ztharvester/tokenmix.py`)
- **Class:** `TokenMixCreator`
- **Dependencies:** `cdp: CDP`, `mail: MailProvider`, `TokenMixConfig`
- **Flow:**
  1. Generate disposable mailbox from `mail.tm`.
  2. Navigate to `https://tokenmix.ai/register` (or signup page).
  3. Fill email, password, optional referral code.
  4. Wait for Cloudflare Turnstile token response in browser context.
  5. Submit registration form.
  6. Wait for verification email/code from `mail.tm`.
  7. Verify account, navigate to API key creation page.
  8. Create key, scrape `sk-tm-...` API key.
  9. Return result record `HarvestedKey(platform="tokenmix", email=..., password=..., api_key=...)`.

---

## 5. Storage & Results Ledger (`ztharvester/engine.py`)

Different targets write to distinct JSONL ledger files in `cfg.output_dir` (`harvest/`):
- `ZeroTwo`: `harvest/sessions.jsonl`
- `Token Harbor`: `harvest/tokenharbor_keys.jsonl`
- `TokenMix`: `harvest/tokenmix_keys.jsonl`

Crash-safe line-by-line append guarantees that interrupted batches do not lose already harvested accounts.

---

## 6. Testing & Verification

1. **Unit Tests (`tests/test_config.py`):**
   - Test TOML parsing for `[tokenharbor]` and `[tokenmix]`.
   - Test `target` selection defaulting and overriding.
2. **Driver Unit Tests (`tests/test_targets.py`):**
   - Mock CDP and `MailProvider` to test the state machine for `TokenHarborCreator` and `TokenMixCreator`.
   - Test regex verification link extraction.
3. **CLI Integration Test:**
   - Test `zt-farming run --target tokenharbor --help` and CLI parsing.
