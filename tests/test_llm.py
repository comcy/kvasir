"""LLM client against a fake HTTP server on localhost and fake commands. No network."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kvasir import doctor, llm
from kvasir.config import LocalConfig, RepoConfig, load_local, load_repos, save_local, save_repos
from kvasir.platform.models import ErrorKind

SEEN: list[dict] = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        SEEN.append({"path": self.path, "auth": self.headers.get("Authorization")})
        self._send(200, {"data": [{"id": "llama3:latest"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if body["model"] == "missing":
            return self._send(404, {"error": {"message": "model 'missing' not found"}})
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": "hi"}}]})


@pytest.fixture
def server():
    SEEN.clear()
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/v1"
    s.shutdown()


def cfg(url, **kw):
    return llm.parse({"provider": "openai", "base_url": url, "model": "llama3", **kw})


def cmd(*argv):
    c = llm.parse({"provider": "command", "command": list(argv)})
    c.confirmed.append(llm.target(c))  # skip the confirmation, tested separately
    return c


MSG = [{"role": "user", "content": "hello"}]


def test_openai_complete_sends_key_from_env(server, monkeypatch):
    monkeypatch.setenv("MY_KEY", "s3cret")
    res = llm.complete(MSG, cfg(server, api_key_env="MY_KEY"))
    assert res.ok and res.data == "hi"
    assert SEEN[0]["path"] == "/v1/chat/completions" and SEEN[0]["auth"] == "Bearer s3cret"
    assert SEEN[0]["body"]["messages"] == MSG


def test_openai_errors_are_results(server):
    c = cfg(server)
    c.model = "missing"
    assert "model not found" in llm.complete(MSG, c).error.message
    assert llm.complete(MSG, cfg("http://127.0.0.1:1/v1")).error.kind == ErrorKind.NETWORK


def test_command_provider(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text("import sys\nprint('echo:' + sys.stdin.read())\n")
    assert llm.complete(MSG, cmd(sys.executable, str(script))).data == "echo:hello"
    assert not llm.complete(MSG, cmd(sys.executable, "-c", "import sys; sys.exit(3)")).ok
    assert llm.complete(MSG, cmd("kvasir-no-such-cmd")).error.kind == ErrorKind.MISSING_CLI


@pytest.mark.parametrize("raw", [
    {}, {"provider": "x"}, {"provider": "openai", "base_url": "ftp://h", "model": "m"},
    {"provider": "openai", "base_url": "http://h/v1"}, {"provider": "command", "command": "claude -p"},
    {"provider": "command", "command": []},
])
def test_parse_rejects(raw):
    with pytest.raises(ValueError):
        llm.parse(raw)


def test_disabled_without_llm_section():
    assert llm.load() is None
    assert llm.complete(MSG).error.message.startswith("no [llm]")


def test_local_toml_roundtrip_keeps_llm():
    save_local(LocalConfig(open_command="x", paths={"a/b": "/p"},
                           llm={"provider": "command", "command": ["claude", "-p"]}))
    c = load_local()
    assert c.llm == {"provider": "command", "command": ["claude", "-p"]} and c.paths == {"a/b": "/p"}


def test_doctor_reports_llm(server):
    def status(raw):
        return [c.status for c in doctor.check_llm(LocalConfig(llm=raw))]

    assert doctor.check_llm(LocalConfig()) == []
    assert status({"provider": "openai", "base_url": server, "model": "llama3"}) == ["ok", "ok"]
    assert status({"provider": "openai", "base_url": server, "model": "other"}) == ["ok", "fail"]
    assert status({"provider": "openai", "base_url": "http://127.0.0.1:1", "model": "m"}) == ["fail"]
    assert status({"provider": "command", "command": ["kvasir-no-such-cmd"]}) == ["fail"]
    assert status({"provider": "command", "command": [sys.executable]}) == ["ok"]
    assert status({"provider": "nope"}) == ["fail"]


def test_confirmation_for_non_local():
    assert not llm.needs_confirmation(cfg("http://localhost:11434/v1"))
    assert not llm.needs_confirmation(cfg("http://192.168.1.5:8000/v1"))
    remote = cfg("https://api.example.com/v1")
    assert llm.needs_confirmation(remote)
    assert "not confirmed" in llm.complete(MSG, remote).error.message
    assert llm.needs_confirmation(llm.parse({"provider": "command", "command": ["claude", "-p"]}))


def test_confirm_is_persisted():
    save_local(LocalConfig(llm={"provider": "openai", "base_url": "https://api.example.com/v1", "model": "m"}))
    llm.confirm(llm.load())
    assert not llm.needs_confirmation(llm.load())
    assert load_local().llm["confirmed"] == ["api.example.com"]


def test_repo_opt_out(server):
    save_repos({"github.com/o/r": RepoConfig(llm=False), "github.com/o/s": RepoConfig()})
    assert load_repos()["github.com/o/r"].llm is False
    assert llm.repo_enabled("github.com/o/s") and llm.repo_enabled("github.com/unknown/x")
    res = llm.complete(MSG, cfg(server), repo="github.com/o/r")
    assert not res.ok and "opted out" in res.error.message and not SEEN
    assert llm.complete(MSG, cfg(server), repo="github.com/o/s").ok
