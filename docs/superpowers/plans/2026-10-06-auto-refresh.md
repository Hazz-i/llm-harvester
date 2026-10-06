# Auto-Refresh & Session Pool Failover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide zero-touch automated Supabase token refreshing and smart session pool failover for the ZeroTwo shim, plus a CLI refresh command.

**Architecture:** A thread-safe, lock-protected `SessionPool` manages `harvest/sessions.jsonl`. A periodic background task automatically refreshes approaching-expiry JWTs directly against Supabase REST API without needing a browser. On 401 errors, requests transparently rotate to another healthy session in the pool.

**Tech Stack:** Python 3.10+, asyncio, httpx, uvicorn, typer.

---

### Task 1: SessionPool and Atomic Refresh Mechanism

**Files:**
- Modify: `src/ztharvester/shim.py`
- Test: `tests/test_shim.py`

**Interfaces:**
- `refresh_supabase_token(refresh_token: str) -> tuple[str | None, str | None]`
- `SessionPool`:
  - `load(path: Path | str) -> list[dict[str, Any]]`
  - `save(path: Path | str, sessions: list[dict[str, Any]]) -> None`
  - `refresh_all(path: Path | str, threshold_seconds: float = 1200.0) -> dict[str, int]`
  - `get_healthy_session(token_or_id: str | None = None) -> dict[str, Any] | None`
  - `mark_dead(token_or_id: str, reason: str = "") -> None`

- [ ] **Step 1: Write failing unit test for `SessionPool`**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Implement `SessionPool` with lock and atomic file update**
- [ ] **Step 4: Run pytest to verify tests pass**

---

### Task 2: Background Auto-Refresh Loop & Failover in Shim

**Files:**
- Modify: `src/ztharvester/shim.py`
- Test: `tests/test_shim.py`

- [ ] **Step 1: Write failing test for background loop & failover**
- [ ] **Step 2: Run pytest to verify test failure**
- [ ] **Step 3: Implement background task runner & multi-session failover in `stream` and `chat`**
- [ ] **Step 4: Run pytest to verify tests pass**

---

### Task 3: CLI `zt-harvester refresh` Command

**Files:**
- Modify: `src/ztharvester/cli.py`
- Test: `tests/test_cli.py` (or `tests/test_shim.py`)

- [ ] **Step 1: Add unit test for CLI refresh command**
- [ ] **Step 2: Implement `@app.command() def refresh(...)` in `cli.py`**
- [ ] **Step 3: Run pytest to verify CLI refresh command**

---

### Task 4: Deployment & Verification on NAS

**Files:**
- NAS: `/home/wahid/my-projects/gratisan/zt-farming/`

- [ ] **Step 1: Git commit local changes**
- [ ] **Step 2: Deploy updated code to NAS & restart `zt-shim`**
- [ ] **Step 3: Verify shim healthz and background logs**
