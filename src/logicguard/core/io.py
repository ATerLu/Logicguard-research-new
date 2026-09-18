"""Small, dependency-free helpers for experiment artifacts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def load_jsonl(
    path: Path, *, tolerate_trailing_partial: bool = False
) -> list[dict[str, Any]]:
    """Load non-empty JSON Lines records from ``path``."""

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                is_partial_tail = (
                    tolerate_trailing_partial
                    and line_number == len(lines)
                    and not line.endswith(("\n", "\r"))
                )
                if is_partial_tail:
                    break
                raise
            if not isinstance(row, dict):
                raise TypeError(
                    f"Expected a JSON object at {path}:{line_number}, "
                    f"got {type(row).__name__}"
                )
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Atomically write JSON Lines records, creating the parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    """Durably append one JSON object to a JSON Lines artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> None:
    """Atomically write mapping rows to CSV with a stable column order."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames))
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig")


def write_inferred_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write CSV rows using the first row's stable key order."""

    if not rows:
        atomic_write_text(path, "", encoding="utf-8-sig")
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


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text through a same-directory temporary file and atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path)
    try:
        with temporary.open("w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write an indented JSON object."""

    atomic_write_text(
        path,
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
    )


def _temporary_path(path: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    return Path(raw_path)
