"""Normalize git remote URLs to a stable repo identity: `host/owner/name`."""
import re
from urllib.parse import unquote

_SCP = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>(?!//).+)$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?(?P<host>[^:/]*)(?::\d+)?/(?P<path>.+)$", re.IGNORECASE)


def normalize(url: str) -> str:
    """`git@github.com:o/r.git`, `https://github.com/o/r/` -> `github.com/o/r`."""
    url = url.strip()
    m = _URL.match(url) or _SCP.match(url)
    if not m:
        raise ValueError(f"unsupported remote URL: {url!r}")
    host = m["host"].lower()
    path = m["path"].strip("/").removesuffix(".git")
    return _azure(host, path) or f"{host}/{path}"


def _azure(host: str, path: str) -> str | None:
    """Azure DevOps (all URL forms) -> `dev.azure.com/org/project/_git/repo`, lowercase, decoded."""
    parts = unquote(path).lower().split("/")
    if host in ("ssh.dev.azure.com", "vs-ssh.visualstudio.com") and len(parts) == 4 and parts[0] == "v3":
        org, project, repo = parts[1:]
    elif host == "dev.azure.com" and len(parts) == 4 and parts[2] == "_git":
        org, project, repo = parts[0], parts[1], parts[3]
    elif host.endswith(".visualstudio.com") and host != "vs-ssh.visualstudio.com":
        parts = parts[1:] if parts[0] == "defaultcollection" else parts
        if len(parts) != 3 or parts[1] != "_git":
            return None
        org, project, repo = host.removesuffix(".visualstudio.com"), parts[0], parts[2]
    else:
        return None
    return f"dev.azure.com/{org}/{project}/_git/{repo}"
