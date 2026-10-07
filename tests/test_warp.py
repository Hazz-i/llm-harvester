"""Unit tests for Cloudflare WARP manager."""

import pytest
from llmharvester.warp import (
    generate_x25519_keypair,
    build_wireguard_conf,
    build_singbox_config,
    save_warp_profile,
    load_warp_profile,
    find_singbox,
    is_warp_running,
)


def test_generate_x25519_keypair():
    priv, pub = generate_x25519_keypair()
    assert isinstance(priv, str) and len(priv) > 30
    assert isinstance(pub, str) and len(pub) > 30
    assert priv != pub


def test_build_wireguard_conf():
    profile = {
        "private_key": "PRIVKEY==",
        "peer_public_key": "PUBKEY==",
        "endpoint": "engage.cloudflareclient.com:2408",
        "v4_address": "172.16.0.2",
        "v6_address": "2606:4700:110:8edb::1",
    }
    conf = build_wireguard_conf(profile)
    assert "[Interface]" in conf
    assert "PrivateKey = PRIVKEY==" in conf
    assert "Address = 172.16.0.2, 2606:4700:110:8edb::1" in conf
    assert "[Peer]" in conf
    assert "PublicKey = PUBKEY==" in conf
    assert "Endpoint = engage.cloudflareclient.com:2408" in conf


def test_build_singbox_config():
    profile = {
        "private_key": "PRIVKEY==",
        "peer_public_key": "PUBKEY==",
        "endpoint": "162.159.192.1:2408",
        "v4_address": "172.16.0.2",
    }
    cfg = build_singbox_config(profile, local_port=10808)
    assert "inbounds" in cfg
    assert cfg["inbounds"][0]["listen_port"] == 10808
    assert cfg["inbounds"][0]["type"] == "mixed"
    assert "endpoints" in cfg
    ep = cfg["endpoints"][0]
    assert ep["type"] == "wireguard"
    assert ep["tag"] == "warp-out"
    assert ep["peers"][0]["address"] == "162.159.192.1"
    assert ep["peers"][0]["port"] == 2408
    assert cfg["route"]["final"] == "warp-out"


def test_save_and_load_warp_profile(tmp_path):
    profile = {
        "account_id": "test-acc-123",
        "private_key": "TESTPRIV==",
        "public_key": "TESTPUB==",
        "peer_public_key": "PEERPUB==",
        "endpoint": "162.159.192.1:2408",
        "v4_address": "172.16.0.2",
        "v6_address": "",
    }
    wg_file, sb_file = save_warp_profile(profile, output_dir=tmp_path, local_port=10808)
    assert wg_file.exists()
    assert sb_file.exists()

    loaded = load_warp_profile(output_dir=tmp_path)
    assert loaded is not None
    assert loaded["private_key"] == "TESTPRIV=="
    assert loaded["peer_public_key"] == "PEERPUB=="


def test_find_singbox_or_none():
    binary = find_singbox()
    # On this system sing-box is installed at ~/.local/bin/sing-box
    assert binary is not None


def test_is_warp_running_unreachable_port():
    stat = is_warp_running(port=29999, timeout=0.1)
    assert stat is None
