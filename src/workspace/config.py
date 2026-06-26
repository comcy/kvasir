"""Reads and writes config.toml (global) and workspace.toml (per workspace)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceConfig:
    name: str
    path: str
    sync_target: str = ""
    description: str = ""


@dataclass
class GlobalConfig:
    active_workspace: str = ""
    workspaces: list[WorkspaceConfig] = field(default_factory=list)


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _write_toml(path: Path, data: dict) -> None:
    import tomllib as _  # noqa: F401 – just to keep the import chain clear
    lines: list[str] = []

    def _write_value(v: object) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return f'"{v}"'

    for key, value in data.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"\n[[{key}]]")
                    for k, v in item.items():
                        lines.append(f"{k} = {_write_value(v)}")
        elif isinstance(value, dict):
            lines.append(f"\n[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {_write_value(v)}")
        else:
            lines.append(f"{key} = {_write_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_global_config(devtrack_dir: Path) -> GlobalConfig:
    raw = _load_toml(devtrack_dir / "config.toml")
    workspaces = [
        WorkspaceConfig(**ws)
        for ws in raw.get("workspaces", [])
    ]
    return GlobalConfig(
        active_workspace=raw.get("active_workspace", ""),
        workspaces=workspaces,
    )


def save_global_config(devtrack_dir: Path, config: GlobalConfig) -> None:
    data: dict = {"active_workspace": config.active_workspace}
    if config.workspaces:
        data["workspaces"] = [
            {
                "name": ws.name,
                "path": ws.path,
                "sync_target": ws.sync_target,
                "description": ws.description,
            }
            for ws in config.workspaces
        ]
    _write_toml(devtrack_dir / "config.toml", data)


def load_workspace_config(workspace_dir: Path) -> WorkspaceConfig:
    raw = _load_toml(workspace_dir / "workspace.toml")
    return WorkspaceConfig(
        name=raw.get("name", workspace_dir.name),
        path=str(workspace_dir),
        sync_target=raw.get("sync_target", ""),
        description=raw.get("description", ""),
    )
