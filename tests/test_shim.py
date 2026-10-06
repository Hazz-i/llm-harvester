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

