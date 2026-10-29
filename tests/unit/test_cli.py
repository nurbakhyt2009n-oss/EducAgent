from typer.testing import CliRunner

from educa_agent.interfaces.cli import app

runner = CliRunner()


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "doctor", "ingest", "plan", "study", "exam", "report"):
        assert command in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_doctor_before_init_reports_missing_db():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "educa init" in result.output


def test_init_then_doctor_passes(config):
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert config.paths.db.exists()
    result = runner.invoke(app, ["doctor"])
    # Ollama в тестах может быть не запущена — это предупреждение, а не ошибка
    assert result.exit_code == 0, result.output
    assert "Ollama" in result.output


def test_future_commands_say_when_they_arrive():
    result = runner.invoke(app, ["study"])
    assert result.exit_code == 1
    assert "этапе 3" in result.output
