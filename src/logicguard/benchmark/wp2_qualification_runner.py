"""Immutable, provider-free WP2 mechanism and backend-trace qualification runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from logicguard.benchmark.attack_qualification import (
    audit_gragpoison_artifact,
    audit_poisonedrag_hotpotqa_asset,
)
from logicguard.benchmark.backend_trace_adapters import (
    normalize_lightrag_query_data,
    normalize_ms_graphrag_context,
)
from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file, write_jsonl
from logicguard.core.run_state import fingerprint_json


def run_from_config(config_path: Path) -> dict[str, Any]:
    """Execute or verify the frozen local qualification anchor."""

    resolved = resolve_config_path(config_path)
    root = find_project_root(resolved)
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if config.get("run_mode") != "local_asset_audit":
        raise ValueError("WP2 qualification runner is local-asset-audit only")
    inputs = {
        name: _project_input(root, config["inputs"][name])
        for name in (
            "a1_asset",
            "a3_artifact",
            "ms_graphrag_trace",
            "ms_clean_corpus",
            "lightrag_schema_fixture",
        )
    }
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")

    identity = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.2",
        "config_sha256": sha256_file(resolved),
        "input_sha256": {name: sha256_file(path) for name, path in inputs.items()},
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    summary_path = output / "summary.json"
    if summary_path.exists():
        return _verify_existing(summary_path, output, identity)

    a1_payload = json.loads(inputs["a1_asset"].read_text(encoding="utf-8"))
    a3_payload = json.loads(inputs["a3_artifact"].read_text(encoding="utf-8"))
    a1_summary, a1_rows = audit_poisonedrag_hotpotqa_asset(
        a1_payload,
        expected_records=int(config["expectations"]["a1_records"]),
        texts_per_record=int(config["parameters"]["a1_texts_per_record"]),
    )
    a3_summary, a3_rows = audit_gragpoison_artifact(
        a3_payload,
        n_alpha=int(config["parameters"]["a3_N_alpha"]),
        n_beta=int(config["parameters"]["a3_N_beta"]),
        word_budget=int(config["parameters"]["a3_word_budget"]),
    )
    _assert_expected_attack_counts(config["expectations"], a1_summary, a3_summary)

    clean_rows = load_jsonl(inputs["ms_clean_corpus"])
    clean_by_id = {str(row["_id"]): row for row in clean_rows}
    ms_rows = [
        normalize_ms_graphrag_context(
            row,
            dataset=str(config["datasets"]["microsoft"]),
            clean_documents=clean_by_id,
        )
        for row in load_jsonl(inputs["ms_graphrag_trace"])
    ]
    ms_hit_count = sum(len(row["live_hits"]) for row in ms_rows)
    ms_exact_count = sum(
        row["trace_metadata"]["clean_exact_matches"] for row in ms_rows
    )
    if len(ms_rows) != int(config["expectations"]["ms_trace_rows"]):
        raise ValueError("Microsoft GraphRAG trace row count mismatch")
    if ms_hit_count != int(config["expectations"]["ms_trace_hits"]):
        raise ValueError("Microsoft GraphRAG trace hit count mismatch")
    if ms_exact_count != ms_hit_count:
        raise ValueError(
            "Microsoft GraphRAG saved sources do not exactly match clean corpus"
        )

    light_fixture = json.loads(
        inputs["lightrag_schema_fixture"].read_text(encoding="utf-8")
    )
    light_row = normalize_lightrag_query_data(
        query_id=light_fixture["query_id"],
        question=light_fixture["question"],
        dataset=str(config["datasets"]["lightrag"]),
        payload=light_fixture["query_data"],
        chunk_to_group=light_fixture.get("chunk_to_group"),
    )

    output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output / "run_identity.json", identity)
    write_jsonl(output / "a1_asset_audit.jsonl", a1_rows)
    write_jsonl(output / "a3_artifact_audit.jsonl", a3_rows)
    write_jsonl(output / "ms_graphrag_normalized_traces.jsonl", ms_rows)
    write_jsonl(output / "lightrag_schema_normalized_trace.jsonl", [light_row])
    names = [
        "run_identity.json",
        "a1_asset_audit.jsonl",
        "a3_artifact_audit.jsonl",
        "ms_graphrag_normalized_traces.jsonl",
        "lightrag_schema_normalized_trace.jsonl",
    ]
    hashes = {name: sha256_file(output / name) for name in names}
    summary = {
        **identity,
        "status": "LOCAL_QUALIFICATION_PASSED_WITH_DECLARED_BOUNDARIES",
        "run_mode": "local_asset_audit",
        "evidence_scope": "mechanism_budget_and_adapter_qualification_not_attack_effect",
        "A1": a1_summary,
        "A3": a3_summary,
        "backend_traces": {
            "microsoft_graphrag": {
                "status": "HISTORICAL_REAL_CLEAN_TRACE_ADAPTER_PASSED",
                "rows": len(ms_rows),
                "hits": ms_hit_count,
                "clean_exact_matches": ms_exact_count,
                "new_experiment_trace": False,
            },
            "lightrag": {
                "status": "SCHEMA_FIXTURE_ADAPTER_PASSED_REAL_TRACE_PENDING",
                "fixture_rows": 1,
                "fixture_hits": len(light_row["live_hits"]),
                "real_trace_rows": 0,
            },
        },
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "artifact_hashes": hashes,
    }
    atomic_write_json(summary_path, summary)
    return summary


def _assert_expected_attack_counts(
    expected: dict[str, Any], a1: dict[str, Any], a3: dict[str, Any]
) -> None:
    checks = {
        "a1_texts": a1["generated_adversarial_texts"],
        "a3_records": a3["records"],
        "a3_raw_texts": sum(a3["raw_generated_texts"].values()),
        "a3_selected_occurrences": a3["selected_occurrences_total"],
        "a3_selected_unique": a3["selected_unique_texts_total"],
    }
    for name, actual in checks.items():
        if actual != int(expected[name]):
            raise ValueError(f"{name} mismatch: {actual}")


def _verify_existing(
    summary_path: Path, output: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("run_identity_sha256") != identity["run_identity_sha256"]:
        raise RuntimeError("existing qualification namespace has a different identity")
    for relative, expected in summary["artifact_hashes"].items():
        if sha256_file(output / relative) != expected:
            raise RuntimeError(f"qualification artifact hash mismatch: {relative}")
    return summary


def _project_input(root: Path, raw_path: str) -> Path:
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"input must be an existing project file: {raw_path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_from_config(args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
