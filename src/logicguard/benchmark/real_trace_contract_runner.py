"""Admit real backend traces into the shared T0/T1 contract at zero coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from logicguard.benchmark.backend_trace_adapters import normalize_ms_graphrag_context
from logicguard.benchmark.trust_manifest import (
    build_trust_manifest,
    validate_clean_documents,
)
from logicguard.benchmark.trusted_controls import (
    RetrievalBudget,
    build_t0_context,
    build_t1_context,
)
from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file, write_jsonl
from logicguard.core.run_state import fingerprint_json


def run_from_config(config_path: Path) -> dict[str, Any]:
    """Run or verify a provider-free real-trace schema/contract anchor."""

    resolved = resolve_config_path(config_path)
    root = find_project_root(resolved)
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if config.get("run_mode") != "real_trace_zero_coverage_contract_anchor":
        raise ValueError(
            "real trace contract runner requires zero-coverage anchor mode"
        )
    inputs = {name: _project_input(root, raw) for name, raw in config["inputs"].items()}
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")
    identity = {
        "schema_version": 1,
        "protocol_version": "comparison-v1.2",
        "config_sha256": sha256_file(resolved),
        "implementation_sha256": sha256_file(Path(__file__)),
        "input_sha256": {name: sha256_file(path) for name, path in inputs.items()},
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    summary_path = output / "summary.json"
    if summary_path.exists():
        return _verify_existing(summary_path, output, identity)

    ms_clean = validate_clean_documents(load_jsonl(inputs["ms_clean_corpus"]))
    light_clean = validate_clean_documents(load_jsonl(inputs["lightrag_clean_corpus"]))
    ms_clean_by_id = {row["_id"]: row for row in ms_clean}
    light_clean_by_id = {row["_id"]: row for row in light_clean}
    ms_raw = load_jsonl(inputs["ms_trace"])
    if not ms_raw:
        raise ValueError("Microsoft GraphRAG trace input is empty")
    ms = normalize_ms_graphrag_context(
        ms_raw[0],
        dataset=str(config["datasets"]["microsoft"]),
        clean_documents=ms_clean_by_id,
    )
    light_rows = load_jsonl(inputs["lightrag_trace"])
    if len(light_rows) != 1:
        raise ValueError("LightRAG real trace anchor requires exactly one row")
    light = light_rows[0]
    _validate_normalized_trace(light, backend="S2_lightrag")
    light_exact = sum(
        _lightrag_hit_matches_clean(hit, light_clean_by_id)
        for hit in light["live_hits"]
    )
    if light_exact != len(light["live_hits"]):
        raise ValueError("LightRAG trace chunks do not exactly match the clean corpus")

    budget = RetrievalBudget(**config["budget"])
    budget.validate()
    contexts: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for trace, clean in ((ms, ms_clean), (light, light_clean)):
        manifest = build_trust_manifest(
            clean_documents=clean,
            dataset=str(trace["dataset"]),
            dataset_revision=str(config["dataset_revision"]),
            assignment_seed=str(config["assignment_seed"]),
            coverage_levels=[1.0, 0.0],
        )
        query = {
            name: trace[name] for name in ("dataset", "query_id", "question", "backend")
        }
        t0 = build_t0_context(
            query=query,
            trusted_hits=[],
            budget=budget,
            coverage=0.0,
            manifest_sha256=manifest["manifest_sha256"],
        )
        t1 = build_t1_context(
            query=query,
            live_hits=trace["live_hits"],
            trusted_hits=[],
            budget=budget,
            coverage=0.0,
            manifest_sha256=manifest["manifest_sha256"],
        )
        checks = {
            "t0_is_unverifiable": t0["status"] == "UNVERIFIABLE",
            "t0_has_no_sources": t0["selected_source_count"] == 0,
            "t1_has_real_sources": t1["selected_source_count"] > 0,
            "same_budget": t0["budget_sha256"] == t1["budget_sha256"],
            "same_manifest": t0["trust_manifest_sha256"] == t1["trust_manifest_sha256"],
            "context_budget_respected": t1["context_tokens_used"]
            <= budget.max_context_tokens,
            "source_limit_respected": t1["selected_source_count"]
            <= budget.final_source_limit,
        }
        contexts.extend((t0, t1))
        audits.append(
            {
                "dataset": trace["dataset"],
                "query_id": trace["query_id"],
                "backend": trace["backend"],
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    if not all(row["passed"] for row in audits):
        raise RuntimeError("real trace zero-coverage contract audit failed")

    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "run_identity.json", identity)
    write_jsonl(output / "contexts.jsonl", contexts)
    write_jsonl(output / "contract_audit.jsonl", audits)
    artifact_hashes = {
        name: sha256_file(output / name)
        for name in ("run_identity.json", "contexts.jsonl", "contract_audit.jsonl")
    }
    summary = {
        **identity,
        "status": "REAL_TRACE_ZERO_COVERAGE_CONTRACT_ANCHOR_PASSED",
        "evidence_scope": "schema_admission_not_real_trusted_pool_retrieval_or_effect",
        "backends": ["S1_microsoft_graphrag", "S2_lightrag"],
        "real_trace_rows": 2,
        "source_hits": {
            "S1_microsoft_graphrag": len(ms["live_hits"]),
            "S2_lightrag": len(light["live_hits"]),
        },
        "clean_exact_matches": {
            "S1_microsoft_graphrag": ms["trace_metadata"]["clean_exact_matches"],
            "S2_lightrag": light_exact,
        },
        "context_rows": len(contexts),
        "audit_rows": len(audits),
        "audit_failures": 0,
        "trusted_pool_retrieval_executed": False,
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "artifact_hashes": artifact_hashes,
    }
    atomic_write_json(summary_path, summary)
    return summary


def _validate_normalized_trace(row: dict[str, Any], *, backend: str) -> None:
    required = {
        "dataset",
        "query_id",
        "question",
        "backend",
        "live_hits",
        "trace_metadata",
    }
    if (
        set(row) != required
        or row.get("backend") != backend
        or not row.get("live_hits")
    ):
        raise ValueError("normalized backend trace has an invalid schema")


def _lightrag_hit_matches_clean(
    hit: dict[str, Any], clean: dict[str, dict[str, str]]
) -> bool:
    source = clean.get(str(hit["source_group_id"]))
    if source is None:
        return False
    text = str(hit["text"]).strip()
    body = text.split("\n\n", 1)[1].strip() if "\n\n" in text else text
    return body == source["text"].strip()


def _verify_existing(
    summary_path: Path, output: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("run_identity_sha256") != identity["run_identity_sha256"]:
        raise RuntimeError("existing contract namespace has a different identity")
    for relative, expected in summary["artifact_hashes"].items():
        if sha256_file(output / relative) != expected:
            raise RuntimeError(
                f"real trace contract artifact hash mismatch: {relative}"
            )
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
