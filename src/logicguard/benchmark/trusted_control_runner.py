"""Offline T0/T1 acceptance runner with immutable trust and budget contracts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from logicguard.benchmark.trust_manifest import (
    build_trust_manifest,
    coverage_slug,
    materialize_protected_snapshot,
    trusted_group_ids,
    validate_clean_documents,
)
from logicguard.benchmark.trusted_controls import (
    RetrievalBudget,
    build_t0_context,
    build_t1_context,
)
from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json


def run_from_config(config_path: Path) -> dict[str, Any]:
    """Run or verify a deterministic, provider-free T0/T1 anchor."""

    resolved = resolve_config_path(config_path)
    root = find_project_root(resolved)
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if config.get("run_mode") != "fixture":
        raise ValueError("trusted-control acceptance runner is fixture-only")
    clean_path = _project_input(root, config["clean_corpus"])
    retrieval_path = _project_input(root, config["retrieval_fixture"])
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")

    documents = validate_clean_documents(load_jsonl(clean_path))
    retrieval_rows = load_jsonl(retrieval_path)
    coverages = [float(value) for value in config["coverage_levels"]]
    manifest = build_trust_manifest(
        clean_documents=documents,
        dataset=str(config["dataset"]),
        dataset_revision=str(config["dataset_revision"]),
        assignment_seed=str(config["assignment_seed"]),
        coverage_levels=coverages,
    )
    budget = RetrievalBudget(**config["budget"])
    budget.validate()
    _validate_retrieval_rows(config, retrieval_rows, documents)

    identity = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.2",
        "config_sha256": sha256_file(resolved),
        "clean_corpus_sha256": sha256_file(clean_path),
        "retrieval_fixture_sha256": sha256_file(retrieval_path),
        "trust_manifest_sha256": manifest["manifest_sha256"],
        "budget_sha256": budget.fingerprint,
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    summary_path = output / "summary.json"
    if summary_path.exists():
        summary = yaml.safe_load(summary_path.read_text(encoding="utf-8"))
        if summary.get("run_identity_sha256") != identity["run_identity_sha256"]:
            raise RuntimeError(
                "existing trusted-control namespace has a different identity"
            )
        for relative, expected in summary["artifact_hashes"].items():
            if sha256_file(output / relative) != expected:
                raise RuntimeError(
                    f"trusted-control artifact hash mismatch: {relative}"
                )
        return summary

    output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output / "run_identity.json", identity)
    atomic_write_json(output / "trust_manifest.json", manifest)
    snapshots: dict[float, list[dict[str, str]]] = {}
    for coverage in coverages:
        snapshots[coverage] = materialize_protected_snapshot(
            clean_documents=documents, manifest=manifest, coverage=coverage
        )
        write_jsonl(
            output / f"protected_snapshot_{coverage_slug(coverage)}.jsonl",
            snapshots[coverage],
        )

    contexts: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for fixture in retrieval_rows:
        query = {
            name: fixture[name]
            for name in ("dataset", "query_id", "question", "backend")
        }
        for coverage in coverages:
            allowed = trusted_group_ids(manifest, coverage)
            trusted_hits = [
                hit
                for hit in fixture["trusted_catalog_hits"]
                if hit["source_group_id"] in allowed
            ]
            t0 = build_t0_context(
                query=query,
                trusted_hits=trusted_hits,
                budget=budget,
                coverage=coverage,
                manifest_sha256=manifest["manifest_sha256"],
            )
            t1 = build_t1_context(
                query=query,
                live_hits=fixture["live_hits"],
                trusted_hits=trusted_hits,
                budget=budget,
                coverage=coverage,
                manifest_sha256=manifest["manifest_sha256"],
            )
            contexts.extend((t0, t1))
            audits.append(_audit_pair(t0=t0, t1=t1, allowed=allowed, budget=budget))
    if not all(row["passed"] for row in audits):
        raise RuntimeError("T0/T1 acceptance audit failed")

    write_jsonl(output / "contexts.jsonl", contexts)
    write_jsonl(output / "equal_budget_audit.jsonl", audits)
    artifact_names = [
        "run_identity.json",
        "trust_manifest.json",
        "contexts.jsonl",
        "equal_budget_audit.jsonl",
        *[f"protected_snapshot_{coverage_slug(value)}.jsonl" for value in coverages],
    ]
    hashes = {name: sha256_file(output / name) for name in sorted(artifact_names)}
    summary = {
        **identity,
        "status": "LOCAL_ACCEPTANCE_PASSED",
        "run_mode": "fixture",
        "evidence_scope": "engineering_acceptance_not_defense_effect",
        "dataset": config["dataset"],
        "query_backend_pairs": len(retrieval_rows),
        "coverage_levels": coverages,
        "context_rows": len(contexts),
        "audit_rows": len(audits),
        "audit_failures": 0,
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "D6_equal_information_integration": "pending",
        "artifact_hashes": hashes,
    }
    atomic_write_json(summary_path, summary)
    return summary


def _project_input(root: Path, raw_path: str) -> Path:
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"input must be an existing project file: {raw_path}")
    return path


def _validate_retrieval_rows(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    documents: list[dict[str, str]],
) -> None:
    expected_fields = {
        "dataset",
        "query_id",
        "question",
        "backend",
        "live_hits",
        "trusted_catalog_hits",
    }
    expected_backends = set(config["backends"])
    clean_by_id = {row["_id"]: row for row in documents}
    pairs: set[tuple[str, str]] = set()
    for row in rows:
        if set(row) != expected_fields or row["dataset"] != config["dataset"]:
            raise ValueError("retrieval fixture schema or dataset mismatch")
        if row["backend"] not in expected_backends:
            raise ValueError("retrieval fixture contains an undeclared backend")
        key = (row["query_id"], row["backend"])
        if key in pairs:
            raise ValueError(f"duplicate query-backend pair: {key}")
        pairs.add(key)
        for hit in row["trusted_catalog_hits"]:
            clean = clean_by_id.get(hit.get("document_id"))
            if clean is None or any(
                hit.get(name) != clean[clean_name]
                for name, clean_name in (
                    ("source_group_id", "source_group_id"),
                    ("title", "title"),
                    ("text", "text"),
                )
            ):
                raise ValueError(
                    "trusted hit is not an exact pre-poison clean document"
                )
    expected_pairs = int(config["expected_queries"]) * len(expected_backends)
    if len(rows) != expected_pairs:
        raise ValueError("retrieval fixture does not cover every query-backend pair")
    if {backend for _, backend in pairs} != expected_backends:
        raise ValueError("retrieval fixture is missing a backend")


def _audit_pair(
    *,
    t0: dict[str, Any],
    t1: dict[str, Any],
    allowed: set[str],
    budget: RetrievalBudget,
) -> dict[str, Any]:
    checks = {
        "same_budget_sha256": t0["budget_sha256"] == t1["budget_sha256"],
        "same_manifest_sha256": t0["trust_manifest_sha256"]
        == t1["trust_manifest_sha256"],
        "t0_uses_only_trusted_pool": all(
            hit["pool"] == "trusted" for hit in t0["selected_sources"]
        ),
        "t0_groups_within_coverage": all(
            hit["source_group_id"] in allowed for hit in t0["selected_sources"]
        ),
        "t1_trusted_groups_within_coverage": all(
            hit["source_group_id"] in allowed
            for hit in t1["selected_sources"]
            if hit["pool"] == "trusted"
        ),
        "source_limits_respected": all(
            row["selected_source_count"] <= budget.final_source_limit
            for row in (t0, t1)
        ),
        "token_limits_respected": all(
            row["context_tokens_used"] <= budget.max_context_tokens for row in (t0, t1)
        ),
        "call_limits_respected": all(
            row["retrieval_calls_used"] <= budget.max_retrieval_calls
            for row in (t0, t1)
        ),
        "model_call_limits_respected": all(
            row["model_calls_used"] <= budget.max_model_calls for row in (t0, t1)
        ),
        "zero_provider_calls": t0["provider_calls_made"]
        == t1["provider_calls_made"]
        == 0,
    }
    return {
        "dataset": t0["dataset"],
        "query_id": t0["query_id"],
        "backend": t0["backend"],
        "trust_coverage": t0["trust_coverage"],
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args()
    summary = run_from_config(arguments.config)
    print(yaml.safe_dump(summary, allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    main()
