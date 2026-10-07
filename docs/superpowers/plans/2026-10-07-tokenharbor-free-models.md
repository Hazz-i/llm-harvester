# Token Harbor Free Models Whitelist & 9Router Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict Token Harbor imported models strictly to the 4 free models (`tokenharbor/mimo-v2.5:free`, `tokenharbor/deepseek-v4-flash:free`, `tokenharbor/deepseek-v4.1-flash:free`, and `tokenharbor/mimo-v2.6-flash:free`), filter live discovery, add model pruning to 9Router client, and prune existing unwanted models from 9Router.

**Architecture:**
1. Update `TOKENHARBOR_MODELS` in `catalog.py` to only contain the 4 free models.
2. In `fetch_provider_models`, apply a filter when platform is `tokenharbor` so only whitelist / `:free` models are returned.
3. In `router9.py`, add `prune_unwanted_models` to remove non-whitelisted custom models via `DELETE /api/models/custom`.
4. Run tests and clean up active 9Router instance.

**Tech Stack:** Python 3.11, pytest, httpx, asyncio

## Global Constraints
- Only the 4 free models for Token Harbor should be exposed or registered in 9Router.
- Backward compatibility: ZeroTwo and TokenMix model behavior remains unchanged.
- All 35+ pytest tests must pass.

---

### Task 1: Update `catalog.py` with Token Harbor Free Models and Filter

**Files:**
- Modify: `src/ztharvester/catalog.py:24-46, 110-130`
- Test: `tests/test_catalog.py`

**Interfaces:**
- `TOKENHARBOR_MODELS`: list of dict with `id` in `{"mimo-v2.5:free", "deepseek-v4-flash:free", "deepseek-v4.1-flash:free", "mimo-v2.6-flash:free"}`.
- `fetch_provider_models(platform, api_key, api_base)`: filters models for `tokenharbor` against whitelist.

- [ ] **Step 1: Update tests in `tests/test_catalog.py` to assert the 4 free models**
- [ ] **Step 2: Update `TOKENHARBOR_MODELS` and `fetch_provider_models` in `src/ztharvester/catalog.py`**
- [ ] **Step 3: Run `uv run pytest tests/test_catalog.py` and verify all pass**

---

### Task 2: Add Pruning Method to `NineRouterClient` and Auto-Prune Unwanted Models

**Files:**
- Modify: `src/ztharvester/router9.py`
- Modify: `src/ztharvester/engine.py:288-296`
- Test: `tests/test_router9.py`

**Interfaces:**
- `NineRouterClient.prune_unwanted_models(node_id: str, allowed_model_ids: set[str]) -> int`
- Deletes models via `DELETE /api/models/custom?providerAlias={node_id}&id={model_id}`.

- [ ] **Step 1: Add `prune_unwanted_models` method to `NineRouterClient` in `router9.py`**
- [ ] **Step 2: Call `prune_unwanted_models` during `run()` in `engine.py` for Token Harbor node**
- [ ] **Step 3: Add unit test in `tests/test_router9.py`**
- [ ] **Step 4: Run `uv run pytest` to ensure all tests pass**

---

### Task 3: Clean Up Existing 9Router Node Custom Models & Verify

**Files:**
- Execute script to prune unwanted models from live 9Router instance

- [ ] **Step 1: Execute pruning script against `nine.hazz.biz.id` to clean up the 73 unwanted models**
- [ ] **Step 2: Verify custom models list under Token Harbor node now contains exactly the 4 free models**
- [ ] **Step 3: Commit and push changes to `origin main`**
