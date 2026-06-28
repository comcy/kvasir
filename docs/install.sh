#!/usr/bin/env bash
# mimirlink installer — Linux & macOS
# Usage: curl -sSL https://comcy.github.io/kvasir/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/comcy/kvasir.git"
MIN_PY_MINOR=11

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}${BOLD}→${NC} $*"; }
success() { echo -e "${GREEN}${BOLD}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}${BOLD}!${NC} $*" >&2; }
die()     { echo -e "${RED}${BOLD}✗${NC} $*" >&2; exit 1; }

# ── Python 3.11+ ──────────────────────────────────────────────────────────────

check_python() {
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local ver major minor
            ver=$("$candidate" -c \
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" \
                2>/dev/null) || continue
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -eq 3 ] && [ "$minor" -ge "$MIN_PY_MINOR" ]; then
                success "Python $ver ($candidate)"
                return 0
            fi
        fi
    done

    die "Python 3.${MIN_PY_MINOR}+ required but not found.
  Install it first:
    macOS : brew install python@3.11
    Debian: sudo apt install python3.11
    Fedora: sudo dnf install python3.11
    Other : https://python.org/downloads"
}

# ── uv ────────────────────────────────────────────────────────────────────────

ensure_uv() {
    if command -v uv &>/dev/null; then
        success "uv $(uv --version 2>/dev/null | awk '{print $2}')"
        return 0
    fi

    info "Installing uv..."
    curl -sSL https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if ! command -v uv &>/dev/null; then
        warn "uv installed but not yet in PATH."
        echo "  Restart your shell, then run:"
        echo "    uv tool install \"git+${REPO_URL}\""
        exit 0
    fi
    success "uv installed"
}

# ── mimirlink ─────────────────────────────────────────────────────────────────

install_mimirlink() {
    info "Installing mimirlink (this clones and builds from GitHub)..."
    uv tool install "git+${REPO_URL}"
    success "mimirlink installed"
}

# ── PATH hint ─────────────────────────────────────────────────────────────────

check_path() {
    # uv tool update-shell adds the tools bin dir; try it silently
    uv tool update-shell 2>/dev/null || true

    if command -v mimirlink &>/dev/null; then
        success "mimirlink is in PATH"
    else
        warn "mimirlink not yet in PATH — add uv's tools dir:"
        echo '  echo '\''export PATH="$HOME/.local/bin:$PATH"'\'' >> ~/.bashrc'
        echo '  # zsh: append to ~/.zshrc instead'
        echo "  Then: source ~/.bashrc  (or restart your shell)"
    fi
}

# ── main ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}  mimirlink installer${NC}"
echo "  ─────────────────────"
echo ""

check_python
ensure_uv
install_mimirlink
check_path

echo ""
echo -e "  ${GREEN}${BOLD}Done!${NC} Quick start:"
echo ""
echo "    mimirlink workspace create private   # create your first workspace"
echo "    mimirlink tui                        # launch the TUI"
echo ""
