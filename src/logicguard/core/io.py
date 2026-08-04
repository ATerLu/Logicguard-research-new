"""Small, dependency-free helpers for experiment artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSON Lines records from ``path``."""

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise TypeError(
                    f"Expected a JSON object at {path}:{line_number}, "
                    f"got {type(row).__name__}"
                )
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write JSON Lines records, creating the parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    """Append one JSON object to a JSON Lines artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> None:
    """Write mapping rows to CSV with a stable column order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def write_inferred_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write CSV rows using the first row's stable key order."""

    if not rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8-sig")
        return
    write_csv(path, rows, fieldnames=tuple(rows[0]))


def require_env(name: str) -> str:
    """Return a non-empty environment variable or raise a clear error."""

    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the hexadecimal SHA-256 digest of ``path``."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
