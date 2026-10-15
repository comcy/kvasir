from typer.testing import CliRunner

from kvasir import __version__
from kvasir.cli import app


def test_version():
    r = CliRunner().invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == __version__


import pytest

from kvasir.config import ConfigError, load_local, load_repos


@pytest.fixture
def broken(tmp_path, monkeypatch):
    monkeypatch.setenv("KVASIR_CONFIG_DIR", str(tmp_path))

    def write(name):
        (tmp_path / name).write_text('[llm]\nmodel = "abc\n', encoding="utf-8")
    return write


@pytest.mark.parametrize("name,load", [("local.toml", load_local), ("repos.toml", load_repos)])
def test_broken_toml_raises_config_error(broken, name, load):
    broken(name)
    with pytest.raises(ConfigError, match=rf"{name}.*line 2"):
        load()


@pytest.mark.parametrize("name", ["local.toml", "repos.toml"])
@pytest.mark.parametrize("cmd", [["tui"], ["version"]])
def test_cli_broken_config_exit_1(broken, name, cmd):
    broken(name)
    r = CliRunner().invoke(app, cmd)
    assert r.exit_code == 1 and name in r.stderr and "line 2" in r.stderr
    assert "Traceback" not in r.output and not isinstance(r.exception, ConfigError)


@pytest.mark.parametrize("name", ["local.toml", "repos.toml"])
def test_doctor_reports_broken_config(broken, name):
    broken(name)
    r = CliRunner().invoke(app, ["doctor"])
    assert name in r.output and not isinstance(r.exception, ConfigError)
