from ztharvester.shim import split_model, ZeroTwoShim


def test_split_model_prefixed():
    assert split_model("anthropic/claude-sonnet-4.5") == ("anthropic", "claude-sonnet-4.5")


def test_split_model_heuristic():
    assert split_model("grok-4.1-fast") == ("xai", "grok-4.1-fast")


def test_extract_text_variants():
    assert ZeroTwoShim._extract_text({"content": "hi"}) == "hi"
    assert ZeroTwoShim._extract_text({"v": {"content": "yo"}}) == "yo"
    assert ZeroTwoShim._extract_text({"choices": [{"message": {"content": "z"}}]}) == "z"


def test_body_shape():
    body = ZeroTwoShim()._body({
        "model": "openai/gpt-5.2",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ],
    }, stream=True)
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5.2"
    assert body["contextData"]["message"] == "hello"
    assert body["stream"] is True
    assert body["messages"][-1]["role"] == "user"


def test_extract_jwt_claims():
    from ztharvester.shim import _extract_jwt_claims
    import base64
    import json
    import time

    payload = {"sub": "u123", "email": "test@example.com", "exp": int(time.time()) + 3600}
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    fake_jwt = f"header.{encoded_payload}.sig"

    claims = _extract_jwt_claims(fake_jwt)
    assert claims["sub"] == "u123"
    assert claims["email"] == "test@example.com"

    # Invalid tokens should return empty dict safely
    assert _extract_jwt_claims("not-a-jwt") == {}
    assert _extract_jwt_claims("") == {}


def test_find_session():
    from ztharvester.shim import _find_session
    import base64
    import json
    import time

    sessions = [
        {
            "email": "user1@example.com",
            "user_id": "uid-1",
            "access_token": "token-user-1",
            "refresh_token": "rt-1",
        },
        {
            "email": "user2@example.com",
            "user_id": "uid-2",
            "access_token": "token-user-2",
            "refresh_token": "rt-2",
        },
    ]

    # Exact token match
    assert _find_session("token-user-1", sessions)["email"] == "user1@example.com"
    # Email match
    assert _find_session("user2@example.com", sessions)["user_id"] == "uid-2"
    # User ID match
    assert _find_session("uid-1", sessions)["access_token"] == "token-user-1"

    # Old/expired JWT match by sub
    payload = {"sub": "uid-2", "email": "user2@example.com", "exp": 1000}
    enc = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    old_jwt = f"hdr.{enc}.sig"
    assert _find_session(old_jwt, sessions)["user_id"] == "uid-2"
    assert _find_session(old_jwt, sessions)["access_token"] == "token-user-2"

    # Non-matching token
    assert _find_session("unknown-token", sessions) is None


import pytest


@pytest.mark.asyncio
async def test_session_pool_load_and_atomic_save(tmp_path):
    from ztharvester.shim import SessionPool

    file_path = tmp_path / "sessions.jsonl"
    pool = SessionPool(file_path)
    sessions = [{"email": "a@example.com", "access_token": "tok-a"}]
    await pool.save(sessions)

    loaded = await pool.load()
    assert len(loaded) == 1
    assert loaded[0]["email"] == "a@example.com"
    # Ensure temporary file is cleaned up
    assert not file_path.with_suffix(".tmp").exists()


@pytest.mark.asyncio
async def test_session_pool_refresh_all(tmp_path, monkeypatch):
    import time
    from ztharvester.shim import SessionPool, _extract_jwt_claims
    import base64
    import json

    file_path = tmp_path / "sessions.jsonl"
    pool = SessionPool(file_path)

    now = int(time.time())
    # Session 1: expires in 5 minutes (needs refresh)
    payload1 = {"sub": "u1", "exp": now + 300}
    jwt1 = f"h.{base64.urlsafe_b64encode(json.dumps(payload1).encode()).decode().rstrip('=')}.s"
    # Session 2: expires in 50 minutes (still fresh)
    payload2 = {"sub": "u2", "exp": now + 3000}
    jwt2 = f"h.{base64.urlsafe_b64encode(json.dumps(payload2).encode()).decode().rstrip('=')}.s"

    sessions = [
        {"email": "u1@example.com", "access_token": jwt1, "refresh_token": "rt1"},
        {"email": "u2@example.com", "access_token": jwt2, "refresh_token": "rt2"},
    ]
    await pool.save(sessions)

    async def mock_refresh(rt):
        if rt == "rt1":
            return "new-jwt-1", "new-rt-1"
        return None, None

    monkeypatch.setattr("ztharvester.shim.refresh_supabase_token", mock_refresh)

    stats = await pool.refresh_all(threshold_seconds=1200.0)
    assert stats["refreshed"] == 1
    assert stats["total"] == 2

    loaded = await pool.load()
    assert loaded[0]["access_token"] == "new-jwt-1"
    assert loaded[0]["refresh_token"] == "new-rt-1"
    assert loaded[1]["access_token"] == jwt2


@pytest.mark.asyncio
async def test_session_pool_failover_to_healthy(tmp_path, monkeypatch):
    import time
    import json
    import base64
    from ztharvester.shim import SessionPool

    file_path = tmp_path / "sessions.jsonl"
    pool = SessionPool(file_path)

    now = int(time.time())
    payload = {"sub": "healthy_u", "exp": now + 3600}
    good_jwt = f"h.{base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')}.s"

    sessions = [
        {"email": "dead@example.com", "access_token": "expired-tok", "refresh_token": "bad-rt", "status": "expired"},
        {"email": "healthy@example.com", "access_token": good_jwt, "refresh_token": "good-rt", "status": "active"},
    ]
    await pool.save(sessions)

    async def mock_refresh(rt):
        return None, None

    monkeypatch.setattr("ztharvester.shim.refresh_supabase_token", mock_refresh)

    # Requesting dead token should failover to healthy session
    chosen = await pool.get_healthy_session("expired-tok")
    assert chosen is not None
    assert chosen["email"] == "healthy@example.com"


@pytest.mark.asyncio
async def test_build_app_lifespan_starts_auto_refresh(tmp_path, monkeypatch):
    import asyncio
    import time
    import json
    import base64
    from ztharvester.shim import SessionPool, build_app

    file_path = tmp_path / "sessions.jsonl"
    pool = SessionPool(file_path)

    now = int(time.time())
    payload = {"sub": "u1", "exp": now + 100}  # needs refresh
    jwt1 = f"h.{base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')}.s"

    sessions = [{"email": "u1@example.com", "access_token": jwt1, "refresh_token": "rt1"}]
    await pool.save(sessions)

    refreshed = False
    async def mock_refresh(rt):
        nonlocal refreshed
        refreshed = True
        return "new-jwt-1", "new-rt-1"

    monkeypatch.setattr("ztharvester.shim.refresh_supabase_token", mock_refresh)

    app = build_app(pool=pool)

    events = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent_events = []

    async def receive():
        if events:
            ev = events.pop(0)
            if ev["type"] == "lifespan.shutdown":
                await asyncio.sleep(0.05)
            return ev
        return {"type": "lifespan.shutdown"}

    async def send(msg):
        sent_events.append(msg["type"])

    await app({"type": "lifespan"}, receive, send)
    assert "lifespan.startup.complete" in sent_events
    assert "lifespan.shutdown.complete" in sent_events
    assert refreshed is True

