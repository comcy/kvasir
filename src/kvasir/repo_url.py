"""Normalize git remote URLs to a stable repo identity: `host/owner/name`."""
import re

_SCP = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>(?!//).+)$")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?(?P<host>[^:/]*)(?::\d+)?/(?P<path>.+)$", re.IGNORECASE)


def normalize(url: str) -> str:
    """`git@github.com:o/r.git`, `https://github.com/o/r/` -> `github.com/o/r`."""
    url = url.strip()
    m = _URL.match(url) or _SCP.match(url)
    if not m:
        raise ValueError(f"unsupported remote URL: {url!r}")
    path = m["path"].strip("/").removesuffix(".git")
    return f"{m['host'].lower()}/{path}"
