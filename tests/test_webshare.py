import pytest
from llmharvester.webshare import WebshareClient
from llmharvester.proxy import Proxy


@pytest.mark.asyncio
async def test_webshare_fetch_and_sync(tmp_path, monkeypatch):
    client = WebshareClient(api_key="test-key")

    dummy_proxies = [
        Proxy(host="1.2.3.4", port=8000, username="user1", password="pass1"),
        Proxy(host="5.6.7.8", port=9000, username="user2", password="pass2"),
    ]

    proxy_file = tmp_path / "proxies.txt"
    added = client.sync_to_file(dummy_proxies, filepath=proxy_file)
    assert added == 2
    assert "1.2.3.4:8000:user1:pass1" in proxy_file.read_text()
    assert "5.6.7.8:9000:user2:pass2" in proxy_file.read_text()

    # Re-syncing existing should not duplicate
    added_again = client.sync_to_file(dummy_proxies, filepath=proxy_file)
    assert added_again == 0
