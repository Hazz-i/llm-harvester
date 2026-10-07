from llmharvester.cli import _resolve_target


def test_resolve_target_explicit():
    assert _resolve_target("zerotwo", "select") == "zerotwo"
    assert _resolve_target("tokenharbor", "select") == "tokenharbor"
    assert _resolve_target("tokenmix", "select") == "tokenmix"
    assert _resolve_target("elevenlabs", "select") == "elevenlabs"
    assert _resolve_target("el", "select") == "elevenlabs"
    assert _resolve_target("1", "select") == "zerotwo"
    assert _resolve_target("2", "select") == "tokenharbor"
    assert _resolve_target("3", "select") == "tokenmix"
    assert _resolve_target("4", "select") == "elevenlabs"


def test_resolve_target_config():
    assert _resolve_target(None, "tokenharbor") == "tokenharbor"
    assert _resolve_target(None, "tokenmix") == "tokenmix"
    assert _resolve_target(None, "elevenlabs") == "elevenlabs"
    assert _resolve_target(None, "zerotwo") == "zerotwo"


def test_resolve_target_interactive_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "2")
    assert _resolve_target(None, "select") == "tokenharbor"

    monkeypatch.setattr("builtins.input", lambda: "3")
    assert _resolve_target(None, "select") == "tokenmix"

    monkeypatch.setattr("builtins.input", lambda: "4")
    assert _resolve_target(None, "select") == "elevenlabs"

    monkeypatch.setattr("builtins.input", lambda: "1")
    assert _resolve_target(None, "select") == "zerotwo"


def test_cli_run_direct_flag():
    from typer.testing import CliRunner
    from llmharvester.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--direct" in result.stdout
    assert "--no-proxy" in result.stdout
    assert "--warp" in result.stdout
