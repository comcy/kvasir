import pytest

from kvasir.repo_url import normalize


@pytest.mark.parametrize("url", [
    "git@github.com:comcy/kvasir.git",
    "https://github.com/comcy/kvasir",
    "https://user@GitHub.com/comcy/kvasir.git/",
    "ssh://git@github.com:22/comcy/kvasir.git",
])
def test_same_identity(url):
    assert normalize(url) == "github.com/comcy/kvasir"


def test_nested_path():
    assert normalize("git@ssh.dev.azure.com:v3/org/proj/repo") == "ssh.dev.azure.com/v3/org/proj/repo"


def test_rejects_local_path():
    with pytest.raises(ValueError):
        normalize("/home/cy/repo")


def test_file_url():
    assert normalize("file:///tmp/x/r.git") == "/tmp/x/r"
