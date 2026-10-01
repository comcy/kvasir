import subprocess
import sys
from pathlib import Path

import pytest

from kvasir import open_terminal as ot


def test_placeholder_is_one_arg_with_spaces():
    assert ot.build_command("kitty --directory {path}", "/a b/c") == ["kitty", "--directory", "/a b/c"]
    assert ot.build_command("x --cwd={path}", Path("/p q")) == ["x", "--cwd=/p q"]


@pytest.mark.parametrize(
    ("plat", "first"), [("win32", "wt.exe"), ("linux", "kitty"), ("darwin", "kitty")]
)
def test_default_per_platform(monkeypatch, plat, first):
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(ot.shutil, "which", lambda _: "/usr/bin/kitty")
    argv = ot.build_command(None, "/w t")
    assert argv[0] == first and argv[-1] == "/w t"


def test_mac_kitty_fallback(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ot.shutil, "which", lambda _: None)
    assert ot.build_command(None, "/w")[0] == ot.MAC_KITTY


def test_empty_template():
    with pytest.raises(ot.OpenTerminalError):
        ot.build_command("  ", "/w")


def test_popen_detached(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(sys, "platform", "linux")
    ot.open_terminal(tmp_path, "term {path}")
    argv, kw = calls[0]
    assert argv == ["term", str(tmp_path)] and kw["start_new_session"] and "shell" not in kw


def test_start_failure_has_help(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("kitty")

    monkeypatch.setattr(subprocess, "Popen", boom)
    with pytest.raises(ot.OpenTerminalError, match="wt.exe"):
        ot.open_terminal(tmp_path, "kitty {path}")
