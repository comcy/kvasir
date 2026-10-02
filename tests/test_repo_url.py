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


AZ = "dev.azure.com/org/projekt/_git/repo"


@pytest.mark.parametrize("url", [
    "https://dev.azure.com/org/projekt/_git/repo",
    "https://org@dev.azure.com/org/projekt/_git/repo",
    "git@ssh.dev.azure.com:v3/org/projekt/repo",
    "ssh://git@ssh.dev.azure.com:22/v3/org/projekt/repo",
    "https://org.visualstudio.com/projekt/_git/repo",
    "https://org.visualstudio.com/DefaultCollection/projekt/_git/repo",
    "org@vs-ssh.visualstudio.com:v3/org/projekt/repo",
    "https://dev.azure.com/Org/Projekt/_git/Repo.git/",
    "git@ssh.dev.azure.com:v3/ORG/Projekt/REPO.git",
])
def test_azure_same_identity(url):
    assert normalize(url) == AZ


@pytest.mark.parametrize("url", [
    "https://dev.azure.com/org/My%20Proj/_git/repo",
    "git@ssh.dev.azure.com:v3/org/My%20Proj/repo",
    "https://org.visualstudio.com/My Proj/_git/repo",
])
def test_azure_project_with_space(url):
    assert normalize(url) == "dev.azure.com/org/my proj/_git/repo"


def test_rejects_local_path():
    with pytest.raises(ValueError):
        normalize("/home/cy/repo")


def test_file_url():
    assert normalize("file:///tmp/x/r.git") == "/tmp/x/r"
