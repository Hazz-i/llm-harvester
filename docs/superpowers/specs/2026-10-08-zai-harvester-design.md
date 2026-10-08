# Specification: Z.ai / ZCode GLM Harvester & 9Router Connector

## Overview
Automated registration of Z.ai (`chat.z.ai`) accounts, claiming the ZCode desktop free Start Plan (`zcode-v3-start-plan`), minting coding-plan API keys, and wiring them into 9Router under provider `glm`.

- Target ID: `zai`
- Quota: 
  - GLM-5.3: 3,000,000 tokens/day
  - GLM-5.3-Flash: 5,000,000 tokens/day
- Output Ledger: `harvest/zai_keys.jsonl`
- 9Router Provider: `glm` (Zai GLM Coding)

## Architecture & Data Flow

```text
[1. Mail Provisioning]
   ├── mail.tm (default)
   └── IMAP Catch-all (fallback)
         │
         ▼
[2. CDP Browser Registration]
   ├── Navigate https://chat.z.ai/auth
   ├── Fill email + strong password
   ├── Capture & submit 6-digit OTP from email
   └── Extract session JWT/cookies
         │
         ▼
[3. ZCode OAuth Consent]
   ├── GET https://chat.z.ai/api/oauth/authorize?client_id=client_P8X5CMWmlaRO9gyO-KSqtg...
   ├── Auto-consent POST action="approve"
   └── POST https://zcode.z.ai/api/v1/oauth/token -> zcodeJwtToken + zaiAccessToken
         │
         ▼
[4. Aliyun Captcha 2.0 & Billing Claim]
   ├── Trigger Aliyun interactive popup in visible browser window
   ├── User slides puzzle once -> captchaVerifyParam captured
   └── POST https://zcode.z.ai/api/v1/zcode-plan/billing/claim (plan_id: "zcode-v3-start-plan")
         │
         ▼
[5. API Key Minting]
   ├── POST https://api.z.ai/api/auth/z/login with zaiAccessToken -> Business JWT
   ├── GET /api/biz/customer/getCustomerInfo -> organizationId, projectId
   ├── POST /api/biz/v1/organization/{orgId}/projects/{pid}/api_keys -> "zcode-api-key"
   └── GET /copy/{apiKey} -> secretKey -> Format: {apiKey}.{secretKey}
         │
         ▼
[6. Persistence & 9Router Auto-Connect]
   ├── Append to harvest/zai_keys.jsonl
   └── POST http://localhost:20128/api/providers -> provider "glm"
```

## Components & Modules

1. `src/llmharvester/catalog.py`:
   - `TARGET_ZAI = "zai"`
   - Model mappings: `GLM-5.3`, `GLM-5.3-Flash`, `GLM-4.5-Flash`
2. `src/llmharvester/config.py`:
   - `ZaiConfig`:
     - `key_name_prefix: str = "zai-glm"`
     - `wait_seconds: float = 120.0`
     - `max_retries: int = 2`
     - `aliyun_timeout: float = 120.0`
3. `src/llmharvester/router9.py`:
   - Helper to register native `glm` provider connection (`NineRouterClient.register_glm_connection`).
4. `src/llmharvester/zai.py`:
   - `ZaiHarvester` / `ZaiCreator`:
     - `register()`: Automates email creation, form filling, OTP verification.
     - `claim_zcode_plan()`: Automates OAuth code exchange, handles Aliyun slider, claims billing plan.
     - `mint_api_key()`: Exchanges token for business JWT and creates API key.
     - `run()`: Orchestrates all steps, saves ledger, and connects to 9Router.
5. `src/llmharvester/engine.py` & `cli.py` & `main.py`:
   - Dispatcher entry point for target `zai`.
   - TUI dashboard menu option `[8] Harvest Z.ai (GLM-5.3 Coding Plan)`.

## Error Handling

- **Disposable Mail Rejection**: If `mail.tm` is flagged by Z.ai, automatically fall back to IMAP Catch-all domain if enabled.
- **Aliyun Captcha Timeout**: 120-second timeout for manual slide gesture; clean exit with clear log if expired.
- **Rate Limit (429) on Claim**: Saves registered account credentials to `harvest/zai_accounts.jsonl` so account is not lost even if claiming is delayed.
- **Already Claimed (3001/400)**: Bypasses claim and proceeds directly to API key minting.

## Testing Strategy

- `tests/test_zai.py`:
  - Unit tests for `ZaiConfig` parsing from env/config.
  - Regex OTP parser unit tests.
  - Mocked ZCode OAuth token exchange.
  - Mocked business login and API key minting logic.
  - Mocked 9Router `glm` provider registration.
