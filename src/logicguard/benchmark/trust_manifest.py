"""Gold-free source-group trust assignment for comparison-v1.2 controls."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from logicguard.core.run_state import fingerprint_json

_CLEAN_DOCUMENT_FIELDS = {"_id", "text", "title", "source_group_id"}
_EVALUATOR_FIELD_FRAGMENTS = (
    "gold",
    "answer",
    "support",
    "attack_success",
    "defense_success",
    "recovery_outcome",
    "changed_doc",
    "evaluation_valid",
    "targeted_success",
)


def assert_no_evaluator_fields(payload: Any, *, location: str = "payload") -> None:
    """Reject evaluator-only fields before trust assignment or retrieval."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = str(key).strip().lower()
            if any(fragment in normalized for fragment in _EVALUATOR_FIELD_FRAGMENTS):
                raise ValueError(f"evaluator-only field at {location}.{key}")
            assert_no_evaluator_fields(value, location=f"{location}.{key}")
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        for index, value in enumerate(payload):
            assert_no_evaluator_fields(value, location=f"{location}[{index}]")


def validate_clean_documents(
    documents: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Return a strict, normalized clean corpus without evaluator metadata."""

    if not documents:
        raise ValueError("clean corpus must not be empty")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, document in enumerate(documents):
        assert_no_evaluator_fields(document, location=f"documents[{index}]")
        extra = set(document) - _CLEAN_DOCUMENT_FIELDS
        if extra or not {"_id", "text"} <= set(document):
            raise ValueError(
                "clean document requires _id/text and only optional title/source_group_id"
            )
        if any(not isinstance(value, str) for value in document.values()):
            raise ValueError("all clean document fields must be strings")
        document_id = document["_id"].strip()
        text = document["text"].strip()
        group_id = document.get("source_group_id", document_id).strip()
        if not document_id or not text or not group_id:
            raise ValueError("document ID, source group, and text must be nonempty")
        if document_id in seen:
            raise ValueError(f"duplicate clean document ID: {document_id}")
        seen.add(document_id)
        normalized.append(
            {
                "_id": document_id,
                "title": document.get("title", "").strip(),
                "text": text,
                "source_group_id": group_id,
            }
        )
    return normalized


def build_trust_manifest(
    *,
    clean_documents: Sequence[Mapping[str, Any]],
    dataset: str,
    dataset_revision: str,
    assignment_seed: str,
    coverage_levels: Sequence[float],
) -> dict[str, Any]:
    """Assign deterministic, nested trusted coverage at source-group level."""

    documents = validate_clean_documents(clean_documents)
    if not all(value.strip() for value in (dataset, dataset_revision, assignment_seed)):
        raise ValueError("dataset, revision, and assignment seed must be nonempty")
    coverages = sorted({float(value) for value in coverage_levels}, reverse=True)
    if not coverages or any(
        not math.isfinite(value) or value < 0 or value > 1 for value in coverages
    ):
        raise ValueError("coverage levels must be finite values in [0, 1]")
    if 1.0 not in coverages or 0.0 not in coverages:
        raise ValueError("coverage levels must include 1.0 and 0.0")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for document in documents:
        grouped[document["source_group_id"]].append(document)
    ranked_groups = sorted(
        grouped,
        key=lambda group_id: (
            fingerprint_json(
                {
                    "dataset": dataset,
                    "dataset_revision": dataset_revision,
                    "assignment_seed": assignment_seed,
                    "source_group_id": group_id,
                }
            ),
            group_id,
        ),
    )
    counts = {
        str(coverage): (
            len(ranked_groups)
            if coverage == 1.0
            else math.floor(len(ranked_groups) * coverage)
        )
        for coverage in coverages
    }
    rows: list[dict[str, Any]] = []
    for rank, group_id in enumerate(ranked_groups, start=1):
        group_documents = sorted(grouped[group_id], key=lambda row: row["_id"])
        rows.append(
            {
                "source_group_id": group_id,
                "assignment_rank": rank,
                "document_ids": [row["_id"] for row in group_documents],
                "clean_group_sha256": fingerprint_json(group_documents),
                "trusted_at_coverages": [
                    coverage for coverage in coverages if rank <= counts[str(coverage)]
                ],
            }
        )
    manifest = {
        "schema_version": 1,
        "protocol_version": "comparison-v1.2",
        "dataset": dataset,
        "dataset_revision": dataset_revision,
        "assignment_seed": assignment_seed,
        "assignment_unit": "source_group",
        "assignment_uses_gold": False,
        "coverage_levels": coverages,
        "coverage_group_counts": counts,
        "source_group_count": len(rows),
        "groups": rows,
    }
    manifest["manifest_sha256"] = fingerprint_json(manifest)
    return manifest


def trusted_group_ids(manifest: Mapping[str, Any], coverage: float) -> set[str]:
    """Return groups in one frozen coverage prefix."""

    requested = float(coverage)
    if requested not in manifest["coverage_levels"]:
        raise ValueError(f"coverage is not declared in manifest: {requested}")
    return {
        str(row["source_group_id"])
        for row in manifest["groups"]
        if requested in row["trusted_at_coverages"]
    }


def materialize_protected_snapshot(
    *,
    clean_documents: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    coverage: float,
) -> list[dict[str, str]]:
    """Materialize only pre-poison clean documents in trusted source groups."""

    documents = validate_clean_documents(clean_documents)
    allowed = trusted_group_ids(manifest, coverage)
    snapshot = [row for row in documents if row["source_group_id"] in allowed]
    actual = {row["source_group_id"] for row in snapshot}
    if actual != allowed:
        raise ValueError("manifest refers to source groups absent from clean corpus")
    return snapshot


def coverage_slug(coverage: float) -> str:
    """Return a stable path-safe coverage label."""

    return f"{float(coverage):g}".replace(".", "p")
