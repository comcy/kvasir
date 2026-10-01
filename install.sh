#!/bin/sh
# kvasir installer (Linux/macOS): installs uv if missing, then kvasir from GitHub.
#   curl -LsSf https://raw.githubusercontent.com/comcy/kvasir/main/install.sh | sh
set -eu

REPO="git+https://github.com/comcy/kvasir"

command -v git >/dev/null 2>&1 || { echo "error: git is required but not installed" >&2; exit 1; }

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

# --force: also acts as update when kvasir is already installed
uv tool install --force "$REPO"

echo
echo "kvasir installed. If 'kvasir' is not found, restart your shell or run: uv tool update-shell"
echo "Next: kvasir setup <repo-url-or-path>   then   kvasir tui"
