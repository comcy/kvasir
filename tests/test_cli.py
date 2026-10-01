from typer.testing import CliRunner

from kvasir import __version__
from kvasir.cli import app


def test_version():
    r = CliRunner().invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == __version__
