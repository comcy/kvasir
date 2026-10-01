# kvasir installer (Windows PowerShell): installs uv if missing, then kvasir from GitHub.
#   irm https://raw.githubusercontent.com/comcy/kvasir/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo = "git+https://github.com/comcy/kvasir"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required but not installed (https://git-scm.com/download/win)"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv ..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# --force: also acts as update when kvasir is already installed
uv tool install --force $Repo
if ($LASTEXITCODE -ne 0) { throw "uv tool install failed" }

Write-Host ""
Write-Host "kvasir installed. If 'kvasir' is not found, restart your terminal or run: uv tool update-shell"
Write-Host "Next: kvasir setup <repo-url-or-path>   then   kvasir tui"
