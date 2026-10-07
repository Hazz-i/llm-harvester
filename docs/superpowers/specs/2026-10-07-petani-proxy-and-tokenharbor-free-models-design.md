# Design Spec: PetaniProxy File Pool Integration & Token Harbor Free Models Filter

## 1. Context & Objectives

1. **PetaniProxy Pool Integration**:
   - Integrate proxy lists from local repository `/home/kki-laptop-025/my-code/petani-proxy`.
   - Provide file-based auto-selection prioritizing:
     1. `output/webshare_residential.txt` (residential proxies with auth)
     2. `output/fast_elite.txt` (fastest validated public proxies)
     3. `output/live_urls.txt` / `output/live_all.txt` (verified alive HTTP proxies)
   - Ensure support for Chrome and Brave browser binaries (`brave-browser`).

2. **Token Harbor Free Models Whitelist**:
   - Restrict imported models for Token Harbor in 9Router exclusively to the 4 free models:
     - `mimo-v2.5:free` (prefixed as `tokenharbor/mimo-v2.5:free`)
     - `deepseek-v4-flash:free` (prefixed as `tokenharbor/deepseek-v4-flash:free`)
     - `deepseek-v4.1-flash:free` (prefixed as `tokenharbor/deepseek-v4.1-flash:free`)
     - `mimo-v2.6-flash:free` (prefixed as `tokenharbor/mimo-v2.6-flash:free`)
   - Filter `fetch_provider_models` so paid models from `https://tokenharbor.ai/v1/models` are omitted.
   - Clean up existing non-free custom models from the 9Router node.

---

## 2. Architecture & Detailed Changes

### A. PetaniProxy Pool (`src/ztharvester/proxy.py`, `src/ztharvester/config.py`, `src/ztharvester/browser.py`)

1. **Helper `load_petani_proxies` in `src/ztharvester/proxy.py`**:
   - Accepts `petani_path: Path | str | None` and `proxy_type: str = "auto"`.
   - If path is not specified, auto-discovers:
     - Environment variable `LLM_PETANI_PATH`
     - Sibling directory `../petani-proxy`
     - `/home/kki-laptop-025/my-code/petani-proxy`
   - File candidate selection:
     - `"auto"`: tries `output/webshare_residential.txt`, then `output/fast_elite.txt`, then `output/live_urls.txt`, then `output/live_all.txt`.
     - `"residential"`: `output/webshare_residential.txt`
     - `"fast"`: `output/fast_elite.txt`
     - `"live"`: `output/live_urls.txt`
   - Parses each line into a `Proxy` object (handling `http://user:pass@host:port` and `host:port:user:pass` and `host:port`).
   - Ignores blank lines and comments.

2. **`ProxyConfig` in `src/ztharvester/config.py`**:
   - Add fields:
     - `source: str = "auto"`  # "auto", "petani", "file", "inline"
     - `petani_path: str = ""`
     - `petani_type: str = "auto"`
   - `build_proxy_pool(self)`:
     - If `source == "petani"` or `petani_path` is configured, or if `source == "auto"` and PetaniProxy is discovered and no inline/file proxies configured, load via `ProxyPool.from_petani(...)`.

3. **`browser.py`**:
   - Add `"brave-browser"`, `"brave"` to `CHROME_CANDIDATES`.

4. **CLI in `cli.py`**:
   - Add flags:
     - `--petani`: enable PetaniProxy pool source.
     - `--petani-path PATH`: custom path to petani-proxy repo.
     - `--petani-type {auto,residential,fast,live}`: priority filter.

---

### B. Token Harbor Model Whitelist (`src/ztharvester/catalog.py`, `src/ztharvester/router9.py`, `src/ztharvester/engine.py`)

1. **`TOKENHARBOR_MODELS` in `src/ztharvester/catalog.py`**:
   - Set to exclusively the 4 free models:
     ```python
     TOKENHARBOR_MODELS = [
         {"id": "mimo-v2.5:free", "name": "MiMo v2.5 (Free)", "provider": "xiaomi", "type": "llm"},
         {"id": "deepseek-v4-flash:free", "name": "DeepSeek V4 Flash (Free)", "provider": "deepseek", "type": "llm"},
         {"id": "deepseek-v4.1-flash:free", "name": "DeepSeek V4.1 Flash (Free)", "provider": "deepseek", "type": "llm"},
         {"id": "mimo-v2.6-flash:free", "name": "MiMo v2.6 Flash (Free)", "provider": "xiaomi", "type": "llm"},
     ]
     ```
2. **`fetch_provider_models`**:
   - When `platform == "tokenharbor"`, filter results: only include models whose ID or normalized name ends with `:free` or matches the 4 target models.
3. **9Router Cleanup**:
   - Add helper in `router9.py` or script to prune existing non-free custom models from the node `openai-compatible-chat-b143a33e-efce-4d7e-885a-fad613ba6781`, leaving only the 4 specified models.

---

## 3. Verification & Testing

1. **Unit Tests**:
   - Test `load_petani_proxies` with mock file structure and priority fallback.
   - Test `ProxyPool.from_petani`.
   - Test Token Harbor model catalog filtering in `catalog.py`.
2. **Integration Verification**:
   - Verify `uv run pytest` passes (all existing + new tests).
   - Clean up 9Router node custom models and verify with `curl`/API that only the 4 free models remain.
