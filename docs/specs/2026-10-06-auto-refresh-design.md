# Auto-Refresh & Session Pool Failover Design

## Context & Motivation
ZeroTwo accounts authenticate via Supabase JWT tokens (`access_token`), which expire after 1 hour. Each session contains a `refresh_token` that can be exchanged with Supabase (`SUPABASE_REFRESH_URL`) for a fresh token pair.

Currently, `src/ztharvester/shim.py`:
1. Only refreshes tokens reactively when a request arrives. If no requests arrive for >1 hour, all sessions become stale.
2. If two concurrent requests arrive for the same account, Supabase's Refresh Token Rotation can cause race conditions (`refresh_token_already_used`), invalidating the session.
3. If an account's token is invalid (401), the shim emits `[shim error: ZeroTwo API returned 401: ...]` inside an HTTP 200 SSE stream, preventing 9Router from failing over to another account.
4. The shim does not fail over to another healthy session in `harvest/sessions.jsonl`.

## Goals
1. **Background Auto-Refresh Worker**: Periodically (every 10 minutes) refresh all sessions in `harvest/sessions.jsonl` where token expiration is within 20 minutes, directly against Supabase REST API (no browser needed).
2. **Thread/Async-Safe Atomic File Updating**: Prevent concurrent refresh race conditions with an asyncio Lock and atomic write.
3. **Session Pool Failover**: If a specific session fails or returns 401, automatically rotate to the next healthy session in the pool.
4. **CLI Command `zt-harvester refresh`**: Allow manual inspection and refreshing of all harvested sessions anytime from CLI.

## Architecture

### 1. Auto-Refresh Worker
```python
class SessionManager:
    async def refresh_all(self, path: Path, threshold_seconds: float = 1200.0) -> dict[str, Any]
    async def get_healthy_session(self, preferred_token_or_id: str | None = None) -> dict[str, Any] | None
    async def mark_session_dead(self, token_or_id: str, error: str) -> None
```

- Background task runs every `interval_seconds` (default 600s = 10m).
- Compares JWT `exp` claim against `time.time()`.
- If `exp - time.time() < threshold_seconds`: calls `refresh_supabase_token()`.
- Updates `sessions.jsonl` atomically (`.tmp` -> replace).

### 2. Session Pool Failover
- When a request arrives at `POST /v1/chat/completions`:
  1. Find preferred session by token/id.
  2. If preferred session is invalid/expired and cannot be refreshed, pick the next healthy session from pool.
  3. If ZeroTwo returns 401 during connection initialization, mark session as dead and retry with another healthy session up to `max_retries = 3`.
  4. Only yield response chunks to client once upstream connection is confirmed healthy.

### 3. CLI Command
```bash
zt-harvester refresh [--file harvest/sessions.jsonl]
```
Outputs a summary table of refreshed, valid, and expired accounts.
