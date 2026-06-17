"""NDJSON read/write layer. Each table is one .ndjson file; one JSON object per line."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Callable, Iterator, Type, TypeVar

T = TypeVar("T")


class NdjsonStore:
    """Thin wrapper around NDJSON files that keeps relations consistent."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _path(self, table: str) -> Path:
        return self.data_dir / f"{table}.ndjson"

    def _read_raw(self, table: str) -> list[dict[str, Any]]:
        p = self._path(table)
        if not p.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def _write_raw(self, table: str, rows: list[dict[str, Any]]) -> None:
        p = self._path(table)
        p.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Generic CRUD
    # ------------------------------------------------------------------

    def all(self, table: str) -> list[dict[str, Any]]:
        return self._read_raw(table)

    def find(self, table: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [r for r in self._read_raw(table) if all(r.get(k) == v for k, v in kwargs.items())]

    def get(self, table: str, id: str) -> dict[str, Any] | None:
        hits = self.find(table, id=id)
        return hits[0] if hits else None

    def insert(self, table: str, record: dict[str, Any]) -> dict[str, Any]:
        if "id" not in record:
            record = {"id": str(uuid.uuid4()), **record}
        rows = self._read_raw(table)
        rows.append(record)
        self._write_raw(table, rows)
        return record

    def update(self, table: str, id: str, **kwargs: Any) -> dict[str, Any] | None:
        rows = self._read_raw(table)
        updated = None
        for i, row in enumerate(rows):
            if row.get("id") == id:
                rows[i] = {**row, **kwargs}
                updated = rows[i]
                break
        if updated:
            self._write_raw(table, rows)
        return updated

    def delete(self, table: str, id: str) -> bool:
        rows = self._read_raw(table)
        filtered = [r for r in rows if r.get("id") != id]
        if len(filtered) == len(rows):
            return False
        self._write_raw(table, filtered)
        return True

    def delete_where(self, table: str, **kwargs: Any) -> int:
        """Delete all rows matching kwargs; returns count removed."""
        rows = self._read_raw(table)
        kept = [r for r in rows if not all(r.get(k) == v for k, v in kwargs.items())]
        removed = len(rows) - len(kept)
        if removed:
            self._write_raw(table, kept)
        return removed

    # ------------------------------------------------------------------
    # Consistency helpers for n:m relations
    # ------------------------------------------------------------------

    def delete_with_relations(
        self,
        table: str,
        id: str,
        relation_tables: list[tuple[str, str]],
    ) -> bool:
        """
        Delete a record and clean up its mapping rows.
        relation_tables: [(mapping_table, foreign_key_field), ...]
        """
        ok = self.delete(table, id)
        if ok:
            for mapping_table, fk_field in relation_tables:
                self.delete_where(mapping_table, **{fk_field: id})
        return ok

    # ------------------------------------------------------------------
    # Typed helpers (dataclass ↔ dict)
    # ------------------------------------------------------------------

    @staticmethod
    def to_dict(obj: Any) -> dict[str, Any]:
        return asdict(obj)

    @staticmethod
    def from_dict(cls: Type[T], data: dict[str, Any]) -> T:
        valid_keys = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{k: v for k, v in data.items() if k in valid_keys})  # type: ignore[call-arg]
