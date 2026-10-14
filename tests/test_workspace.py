from pathlib import Path

import pytest

from kvasir import doctor, workspace
from kvasir.config import LocalConfig, load_local, save_local

P = Path("/w/r/feat-x")
AI = ["claude", "--continue"]


def test_parse_defaults_and_values():
    c = workspace.parse({})
    assert (c.layout, c.open_mode, c.ai_command, c.ai_resume_command) == ("columns", "terminal", ["claude"], AI)
    c = workspace.parse({"layout": "bottom", "open_mode": "workspace", "ai_command": "aider --x", "ai_resume_command": ["a", "b"]})
    assert (c.layout, c.open_mode, c.ai_command, c.ai_resume_command) == ("bottom", "workspace", ["aider", "--x"], ["a", "b"])


@pytest.mark.parametrize("raw", [{"layout": "x"}, {"open_mode": "x"}, {"ai_command": ""}, {"ai_command": []}, {"foo": 1}])
def test_parse_invalid(raw):
    with pytest.raises(ValueError):
        workspace.parse(raw)


def test_detect():
    assert workspace.detect({"KITTY_WINDOW_ID": "1"}) == "kitty"
    assert workspace.detect({"WT_SESSION": "x"}) == "wt"
    assert workspace.detect({}) is None


def test_wt_columns_and_bottom():
    a = workspace.wt_argv(P, "r · feat/x", AI)
    assert a.count(";") == 2 and a[:4] == ["wt", "-w", "0", "nt"]
    assert a[a.index("--title") + 1] == "r · feat/x"
    assert a[8:12] == ["kvasir", "tui", "--select", str(P)]
    i = a.index("sp")
    assert a[i:i + 4] == ["sp", "-V", "-s", "0.7"]
    assert a[-8:] == ["sp", "-H", "-s", "0.3", "-d", str(P), "--title", "git"]
    b = workspace.wt_argv(P, "t", AI, "bottom")
    assert b.index("-H") < b.index("mf") < b.index("-V") and b[-2:] == AI


def test_kitty_steps_columns_and_bottom():
    t, lay, ai, git = workspace.kitty_steps(P, "t", AI)
    assert t[:3] == ["kitten", "@", "launch"] and "--type=tab" in t and t[-4:] == ["kvasir", "tui", "--select", str(P)]
    assert lay[:3] == ["kitten", "@", "goto-layout"] and lay[-1] == "splits"
    assert "--location=vsplit" in ai and "window_id:{kvasir}" in ai and "id:{kvasir}" in ai and ai[-2:] == AI
    assert "--location=hsplit" in git and "id:{ai}" in git and "window_id:{kvasir}" in git
    _, _, git, ai = workspace.kitty_steps(P, "t", AI, "bottom")
    assert "--location=hsplit" in git and "id:{kvasir}" in git and "--location=vsplit" in ai


def test_run_kitty_feeds_window_ids_and_resume_default():
    calls = []
    ids = iter(["11", "", "12", "13", "21", "", "22", "23"])  # goto-layout prints nothing

    def fake(argv):
        calls.append(argv)
        return next(ids)

    cfg = workspace.parse({})
    env = {"KITTY_WINDOW_ID": "1"}
    assert workspace.open_workspace(P, "t", cfg, env=env, launch=fake) is None
    assert "window_id:11" in calls[1] and "window_id:11" in calls[2] and "id:11" in calls[2]
    assert "id:12" in calls[3] and "window_id:11" in calls[3]
    assert calls[2][-2:] == AI
    calls.clear()
    workspace.open_workspace(P, "t", cfg, resume=False, env=env, launch=fake)
    assert calls[2][-1] == "claude" and "--continue" not in calls[2]


def test_fallback_hint_without_known_terminal_or_on_error():
    assert "kitty" in workspace.open_workspace(P, "t", workspace.parse({}), env={})

    def boom(argv):
        raise OSError("no remote control")

    hint = workspace.open_workspace(P, "t", workspace.parse({}), env={"KITTY_WINDOW_ID": "1"}, launch=boom)
    assert "no remote control" in hint


def test_config_roundtrip_and_doctor(tmp_path, monkeypatch):
    monkeypatch.setenv("KVASIR_CONFIG_DIR", str(tmp_path))
    save_local(LocalConfig(workspace={"layout": "bottom", "ai_command": ["a", "b"]}))
    loc = load_local()
    assert loc.workspace == {"layout": "bottom", "ai_command": ["a", "b"]}
    assert doctor.check_workspace(LocalConfig()) == []
    assert doctor.check_workspace(loc, env={})[0].status == "ok"
    assert doctor.check_workspace(LocalConfig(workspace={"layout": "x"}))[0].status == "fail"
    monkeypatch.setattr(doctor, "_run", lambda argv, timeout=0: None)
    r = doctor.check_workspace(loc, env={"KITTY_WINDOW_ID": "1"})
    assert r[-1].status == "warn" and "allow_remote_control" in r[-1].fix
