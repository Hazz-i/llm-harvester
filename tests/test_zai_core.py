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
        mock_resp.read.return_value = (
            b'{"code": 0, "data": {"token": "jwt_token_abc", "zai": {"access_token": "zai_acc_123"}}}'
        )
        mock_url.return_value.__enter__.return_value = mock_resp

        res = ZaiHarvester.exchange_zcode_token("code123", "state123")
        assert res["zcodeJwtToken"] == "jwt_token_abc"
        assert res["zaiAccessToken"] == "zai_acc_123"


def test_claim_start_plan_mock():
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"code": 0, "msg": "success", "data": {"status": "active"}}'
        mock_url.return_value.__enter__.return_value = mock_resp

        ok, msg = ZaiHarvester.claim_start_plan("jwt_token_abc", "sample_captcha_param")
        assert ok is True
        assert "success" in msg


def test_mint_plan_api_key_mock():
    with patch("urllib.request.urlopen") as mock_url:
        def side_effect(req, timeout=30):
            url = req.full_url
            m = MagicMock()
            m.__enter__.return_value = m
            if "login" in url:
                m.read.return_value = b'{"code": 0, "data": {"access_token": "biz_token_xyz"}}'
            elif "getCustomerInfo" in url:
                m.read.return_value = b'{"code": 0, "data": {"organizations": [{"organizationId": "org1", "organizationName": "MyOrg", "projects": [{"projectId": "proj1", "projectName": "Default", "projectType": "1"}]}]}}'
            elif "copy" in url:
                m.read.return_value = b'{"code": 0, "data": {"secretKey": "secret_abc"}}'
            elif "api_keys" in url:
                m.read.return_value = b'{"code": 0, "data": [{"name": "zcode-api-key", "apiKey": "key_123"}]}'
            return m

        mock_url.side_effect = side_effect

        key_info = ZaiHarvester.mint_plan_api_key("zai_acc_123")
        assert key_info["planApiKey"] == "key_123.secret_abc"
