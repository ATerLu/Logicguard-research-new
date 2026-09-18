import copy

import pytest

from logicguard.benchmark.trust_manifest import (
    build_trust_manifest,
    materialize_protected_snapshot,
    trusted_group_ids,
)


def _documents() -> list[dict[str, str]]:
    return [
        {"_id": "a-1", "source_group_id": "a", "title": "A", "text": "alpha"},
        {"_id": "a-2", "source_group_id": "a", "title": "A2", "text": "alpha two"},
        {"_id": "b", "title": "B", "text": "bravo"},
        {"_id": "c", "title": "C", "text": "charlie"},
        {"_id": "d", "title": "D", "text": "delta"},
        {"_id": "e", "title": "E", "text": "echo"},
    ]


def test_trust_assignment_is_deterministic_nested_and_group_level() -> None:
    manifest = build_trust_manifest(
        clean_documents=_documents(),
        dataset="toy",
        dataset_revision="r1",
        assignment_seed="frozen-seed",
        coverage_levels=[1.0, 0.5, 0.2, 0.0],
    )
    repeated = build_trust_manifest(
        clean_documents=list(reversed(_documents())),
        dataset="toy",
        dataset_revision="r1",
        assignment_seed="frozen-seed",
        coverage_levels=[0.0, 0.2, 0.5, 1.0],
    )

    assert manifest == repeated
    groups_100 = trusted_group_ids(manifest, 1.0)
    groups_50 = trusted_group_ids(manifest, 0.5)
    groups_20 = trusted_group_ids(manifest, 0.2)
    groups_0 = trusted_group_ids(manifest, 0.0)
    assert groups_100 > groups_50 > groups_20 > groups_0
    assert len(groups_100) == 5
    assert len(groups_50) == 2
    assert len(groups_20) == 1
    assert groups_0 == set()

    snapshot = materialize_protected_snapshot(
        clean_documents=_documents(), manifest=manifest, coverage=1.0
    )
    assert {row["_id"] for row in snapshot if row["source_group_id"] == "a"} == {
        "a-1",
        "a-2",
    }


def test_trust_assignment_rejects_evaluator_fields() -> None:
    leaked = copy.deepcopy(_documents())
    leaked[0]["gold_answer"] = "secret"
    with pytest.raises(ValueError, match="evaluator-only"):
        build_trust_manifest(
            clean_documents=leaked,
            dataset="toy",
            dataset_revision="r1",
            assignment_seed="seed",
            coverage_levels=[1.0, 0.0],
        )
