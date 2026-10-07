"""Shared repo-settings logic for CLI (`setup --reconfigure`) and TUI. No Typer/Textual."""
from kvasir.branch_names import compile_pattern
from kvasir.config import RepoConfig, load_repos, save_repos

PRESETS = {
    "1": ["{type}/{slug}"],
    "2": ["features/{id}-{slug}", "fixes/{id}-{slug}"],
    "3": ["{type}/{slug}", "features/{id}-{slug}", "fixes/{id}-{slug}"],
}


def preset_key(patterns: list[str]) -> str | None:
    """Key of the preset equal to `patterns`, else None (= custom)."""
    return next((k for k, v in PRESETS.items() if v == list(patterns)), None)


def validate_patterns(patterns: list[str]) -> list[str]:
    """Strip, drop blanks, check every template. ValueError with a readable message."""
    out = [p.strip() for p in patterns if p.strip()]
    if not out:
        raise ValueError("at least one branch template is required")
    for p in out:
        compile_pattern(p)  # unknown placeholder -> ValueError
    return out


def update_repo(
    url: str,
    patterns: list[str] | None = None,
    fetch_interval: int | None = None,
    platform_interval: int | None = None,
) -> RepoConfig:
    """Load repos.toml, change only the entry `url` (normalized remote URL), save, return it.
    Raises ValueError for an unregistered repo, invalid templates or intervals < 1."""
    repos = load_repos()
    if url not in repos:
        raise ValueError(f"{url} is not registered")
    cfg = repos[url]
    if patterns is not None:
        cfg.branch_patterns = validate_patterns(patterns)
        cfg.patterns_set = True
    for name, value in (("fetch_interval", fetch_interval), ("platform_interval", platform_interval)):
        if value is not None:
            if value < 1:
                raise ValueError(f"{name} must be at least 1 minute")
            setattr(cfg, name, value)
    save_repos(repos)
    return cfg
