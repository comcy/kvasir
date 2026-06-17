"""Workspace lifecycle: create, list, switch, resolve active."""
from __future__ import annotations

from pathlib import Path

from .config import (
    GlobalConfig,
    WorkspaceConfig,
    load_global_config,
    save_global_config,
)
from devtrack.data.store import NdjsonStore


class WorkspaceError(Exception):
    pass


class WorkspaceManager:
    DEFAULT_DIR = Path.home() / ".devtrack"

    def __init__(self, devtrack_dir: Path | None = None) -> None:
        self.devtrack_dir = devtrack_dir or self.DEFAULT_DIR
        self._config: GlobalConfig | None = None

    # ------------------------------------------------------------------
    # Config access
    # ------------------------------------------------------------------

    @property
    def config(self) -> GlobalConfig:
        if self._config is None:
            self._config = load_global_config(self.devtrack_dir)
        return self._config

    def _save(self) -> None:
        save_global_config(self.devtrack_dir, self.config)
        self._config = None  # invalidate cache

    # ------------------------------------------------------------------
    # Workspace CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        path: Path | None = None,
        sync_target: str = "",
        description: str = "",
    ) -> WorkspaceConfig:
        if self._find(name):
            raise WorkspaceError(f"Workspace '{name}' already exists.")

        ws_path = path or (self.devtrack_dir / "workspaces" / name)
        ws_path = ws_path.expanduser().resolve()

        for subdir in ("data", "notes", "archive"):
            (ws_path / subdir).mkdir(parents=True, exist_ok=True)

        ws_cfg = WorkspaceConfig(
            name=name,
            path=str(ws_path),
            sync_target=sync_target,
            description=description,
        )
        self.config.workspaces.append(ws_cfg)

        if not self.config.active_workspace:
            self.config.active_workspace = name

        self._save()
        return ws_cfg

    def list(self) -> list[WorkspaceConfig]:
        return list(self.config.workspaces)

    def use(self, name: str) -> WorkspaceConfig:
        ws = self._find(name)
        if not ws:
            raise WorkspaceError(f"Workspace '{name}' not found.")
        self.config.active_workspace = name
        self._save()
        return ws

    def delete(self, name: str) -> None:
        ws = self._find(name)
        if not ws:
            raise WorkspaceError(f"Workspace '{name}' not found.")
        self.config.workspaces = [w for w in self.config.workspaces if w.name != name]
        if self.config.active_workspace == name:
            self.config.active_workspace = (
                self.config.workspaces[0].name if self.config.workspaces else ""
            )
        self._save()

    # ------------------------------------------------------------------
    # Active workspace helpers
    # ------------------------------------------------------------------

    def active(self) -> WorkspaceConfig:
        name = self.config.active_workspace
        if not name:
            raise WorkspaceError(
                "No active workspace. Run: devtrack workspace create <name>"
            )
        ws = self._find(name)
        if not ws:
            raise WorkspaceError(f"Active workspace '{name}' not found in config.")
        return ws

    def store(self) -> NdjsonStore:
        ws = self.active()
        return NdjsonStore(Path(ws.path) / "data")

    def notes_dir(self) -> Path:
        return Path(self.active().path) / "notes"

    def archive_dir(self) -> Path:
        return Path(self.active().path) / "archive"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find(self, name: str) -> WorkspaceConfig | None:
        return next((w for w in self.config.workspaces if w.name == name), None)
