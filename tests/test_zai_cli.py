from llmharvester.cli import _resolve_target, app
from typer.testing import CliRunner


def test_resolve_target_zai():
    assert _resolve_target("zai") == "zai"
    assert _resolve_target("zcode") == "zai"
    assert _resolve_target("glm") == "zai"
    assert _resolve_target("6") == "zai"


def test_cli_help_lists_zai():
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "zai" in result.stdout
