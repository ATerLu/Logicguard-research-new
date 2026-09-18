"""Crash-safe experiment manifests, fingerprints and stable case keys."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file

RUN_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_KEY_FIELDS = (
    "dataset",
    "query_id",
    "attack_family",
    "defense_stage",
    "model",
)


@dataclass(frozen=True, slots=True)
class FunnelCounts:
    """Accounting for the attack-to-answer experimental funnel."""

    attempted: int
    generated_valid: int
    evaluation_valid: int
    exposed: int
    judged: int
    successful: int

    def validate(self) -> None:
        """Reject impossible or denominator-inflating funnel counts."""

        values = asdict(self)
        if any(value < 0 for value in values.values()):
            raise ValueError(f"Funnel counts must be non-negative: {values}")
        if not (
            self.successful
            <= self.judged
            <= self.exposed
            <= self.evaluation_valid
            <= self.generated_valid
            <= self.attempted
        ):
            raise ValueError(f"Invalid experiment funnel ordering: {values}")


def stable_case_key(
    *,
    dataset: str,
    query_id: str,
    attack_family: str,
    defense_stage: str,
    model: str,
) -> str:
    """Return the canonical five-field case key used by paid experiments."""

    return json.dumps(
        [dataset, query_id, attack_family, defense_stage, model],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def fingerprint_json(payload: Any) -> str:
    """Return a deterministic SHA-256 fingerprint for JSON-compatible state."""

    encoded = json.dumps(
        _canonicalize(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def input_artifacts(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Describe immutable file inputs without reading secrets or output files."""

    artifacts: list[dict[str, Any]] = []
    for path in sorted({item.resolve() for item in paths}, key=str):
        if not path.is_file():
            raise FileNotFoundError(f"Run-manifest input does not exist: {path}")
        artifacts.append(
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def prepare_run_manifest(
    *,
    path: Path,
    experiment: str,
    config_payload: Mapping[str, Any],
    inputs: Sequence[Path],
    expected_count: int,
    checkpoint_path: Path,
    protected_outputs: Sequence[Path] = (),
    key_fields: Sequence[str] = DEFAULT_KEY_FIELDS,
) -> dict[str, Any]:
    """Create or validate a manifest before any paid call is attempted.

    A pre-existing checkpoint or final output without a matching manifest is
    intentionally rejected: legacy rows cannot prove which parameters produced
    them, so silently resuming would mix experimental conditions.
    """

    artifacts = input_artifacts(inputs)
    fingerprint_payload = {
        "experiment": experiment,
        "config": config_payload,
        "inputs": artifacts,
        "key_fields": list(key_fields),
    }
    fingerprint = fingerprint_json(fingerprint_payload)
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported run-manifest schema: {path}")
        if manifest.get("fingerprint") != fingerprint:
            raise RuntimeError(
                "Run fingerprint mismatch; use a new output/checkpoint namespace "
                f"instead of mixing parameters: {path}"
            )
        return manifest

    unverified = [checkpoint_path, *protected_outputs]
    existing = [item for item in unverified if item.exists() and item.stat().st_size]
    if existing:
        rendered = ", ".join(str(item) for item in existing)
        raise RuntimeError(
            "Existing experiment artifacts have no verifiable run manifest; "
            f"refusing implicit legacy resume: {rendered}"
        )

    now = _utc_now()
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "experiment": experiment,
        "fingerprint": fingerprint,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "key_fields": list(key_fields),
        "expected_count": expected_count,
        "completed_count": 0,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "config": _canonicalize(config_payload),
        "inputs": artifacts,
    }
    atomic_write_json(path, manifest)
    return manifest


def update_run_manifest(path: Path, **updates: Any) -> dict[str, Any]:
    """Atomically update progress or completion metadata."""

    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(_canonicalize(updates))
    manifest["updated_at"] = _utc_now()
    atomic_write_json(path, manifest)
    return manifest


def load_checkpoint_rows(path: Path, *, fingerprint: str) -> list[dict[str, Any]]:
    """Load durable checkpoint rows and enforce fingerprint consistency."""

    if not path.exists():
        return []
    rows = load_jsonl(path, tolerate_trailing_partial=True)
    for line_number, row in enumerate(rows, start=1):
        if row.get("run_fingerprint") != fingerprint:
            raise RuntimeError(
                "Checkpoint fingerprint mismatch at "
                f"{path}:{line_number}; refusing mixed-parameter resume"
            )
    return rows


def _canonicalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonicalize(asdict(value))
    if isinstance(value, Path):
        return str(value.resolve())
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonicalize(item) for item in value)
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
