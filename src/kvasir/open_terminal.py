"""Open a terminal in a Worktree: build the argument list, start it detached. No shell."""
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from kvasir.config import default_open_command

MAC_KITTY = "/Applications/kitty.app/Contents/MacOS/kitty"

HELP = (
    "Terminal konnte nicht gestartet werden ({err}).\n"
    "open_command in local.toml setzen, z. B.:\n"
    '  Windows: open_command = "wt.exe -d {{path}}"\n'
    '  macOS:   open_command = "open -a Terminal {{path}}"\n'
    '  Linux:   open_command = "gnome-terminal --working-directory={{path}}"'
)


class OpenTerminalError(Exception):
    """Start failed; str() is a user-facing hint with examples per platform."""


def build_command(template: str | None, path: Path | str) -> list[str]:
    """Split the template first, then substitute: `{path}` stays ONE argument."""
    parts = shlex.split(template or default_open_command(), posix=sys.platform != "win32")
    if not parts:
        raise OpenTerminalError(HELP.format(err="open_command ist leer"))
    argv = [p.replace("{path}", str(path)) for p in parts]
    if argv[0] == "kitty" and sys.platform == "darwin" and not shutil.which("kitty"):
        argv[0] = MAC_KITTY
    return argv


def open_terminal(path: Path | str, template: str | None = None) -> None:
    argv = build_command(template, path)
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen(argv, cwd=str(path), **kw)
    except OSError as e:
        raise OpenTerminalError(HELP.format(err=e)) from e
