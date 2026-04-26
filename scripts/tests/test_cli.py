from click.testing import CliRunner

from sqlscout.cli import main


class TestCliHelp:
    def test_main_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0

    def test_extract_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["extract", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output
        assert "--days" in result.output
        assert "--exclude-users" in result.output
        assert "--top-n" in result.output

    def test_analyze_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--provider" in result.output
        assert "--model" in result.output
        assert "--platform" in result.output

    def test_setup_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["setup", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output


class TestCliPlatformChoices:
    def test_extract_rejects_invalid_platform(self):
        runner = CliRunner()
        result = runner.invoke(main, ["extract", "--platform", "bigquery"])
        assert result.exit_code != 0

    def test_extract_rejects_invalid_days(self):
        runner = CliRunner()
        result = runner.invoke(main, ["extract", "--days", "5"])
        assert result.exit_code != 0
