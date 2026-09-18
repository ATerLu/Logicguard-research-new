"""Build the frozen Stage48 reindex defense and matched-clean matrices.

This module deliberately reuses the unmodified Stage43, Stage44 and Stage45
implementations.  It only adapts Stage48 corpus-reindex contexts to their
existing interfaces, records attack provenance, and renders the exact answer
prompt for a pre-paid-call decision gate.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json
from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.defense.chain_completion import (
    build_stage38_chain_rows,
    build_stage38_targeted_context_rows,
)
from logicguard.defense.non_oracle_recovery import (
    NonOracleCandidateSource,
    load_candidate_sources,
)
from logicguard.defense.risk_aware_recovery import build_stage28_context_rows
from logicguard.defense.source_enrichment import (
    build_stage35_enriched_context_rows,
    build_stage35_enrichment_rows,
)
from logicguard.evaluation.answer_generation import (
    Stage27RenderingPolicy,
    build_stage27_answer_cases,
)

DEFENSE_METHODS = (
    "full_query_guard",
    "risk_non_oracle_title_entity_bm25",
    "stage35_query_bm25_append_top12",
    "stage38_second_hop_append_top14",
)
_METHOD_TO_STAGE = {
    "full_query_guard": "unprotected",
    "risk_non_oracle_title_entity_bm25": "stage43_recovery",
    "stage35_query_bm25_append_top12": "stage44_top12",
    "stage38_second_hop_append_top14": "stage45_top14",
}
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class Stage48DefenseMatrixConfig:
    """One attacked variant or matched-clean Stage48 matrix run."""

    dataset: str
    condition: str
    attack_family: str
    sample_path: Path
    source_context_path: Path
    clean_reference_output_dir: Path
    frozen_attacks_path: Path | None
    integrity_output_path: Path
    matrix_output_path: Path
    preflight_output_path: Path
    summary_output_path: Path
    manifest_output_path: Path
    max_queries: int = 20
    top_k_candidates: int = 5
    min_candidate_score: float = 0.01
    entity_drift_threshold: float = 0.10
    title_overlap_threshold: float = 0.80
    baseline_max_sources: int = 8
    stage44_max_sources: int = 12
    stage45_max_sources: int = 14
    max_chars_per_source: int = 450
    candidate_pool_top_k: int = 80
    prompt_policy: str = "evidence_compare"
    stage_label: str = "Stage48-paired-defense"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage48DefenseMatrixConfig":
        """Load a project-relative YAML configuration."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (project_root / candidate).resolve()
            )

        frozen = payload.get("frozen_attacks_path")
        return cls(
            dataset=str(payload["dataset"]),
            condition=str(payload["condition"]),
            attack_family=str(payload.get("attack_family", "clean")),
            sample_path=resolve(payload["sample_path"]),
            source_context_path=resolve(payload["source_context_path"]),
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),
            frozen_attacks_path=resolve(frozen) if frozen else None,
            integrity_output_path=resolve(payload["integrity_output_path"]),
            matrix_output_path=resolve(payload["matrix_output_path"]),
            preflight_output_path=resolve(payload["preflight_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            manifest_output_path=resolve(payload["manifest_output_path"]),
            max_queries=int(payload.get("max_queries", 20)),
            top_k_candidates=int(payload.get("top_k_candidates", 5)),
            min_candidate_score=float(payload.get("min_candidate_score", 0.01)),
            entity_drift_threshold=float(payload.get("entity_drift_threshold", 0.10)),
            title_overlap_threshold=float(payload.get("title_overlap_threshold", 0.80)),
            baseline_max_sources=int(payload.get("baseline_max_sources", 8)),
            stage44_max_sources=int(payload.get("stage44_max_sources", 12)),
            stage45_max_sources=int(payload.get("stage45_max_sources", 14)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 450)),
            candidate_pool_top_k=int(payload.get("candidate_pool_top_k", 80)),
            prompt_policy=str(payload.get("prompt_policy", "evidence_compare")),
            stage_label=str(payload.get("stage_label", "Stage48-paired-defense")),
        )


def run_from_config(config: Stage48DefenseMatrixConfig) -> list[dict[str, Any]]:
    """Build a four-method context matrix and exact-prompt preflight rows."""

    _validate_config(config)
    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    sample_ids = {sample.query_id for sample in samples}
    source_rows = [
        row
        for row in load_jsonl(config.source_context_path)
        if str(row.get("query_id", "")) in sample_ids
        and str(row.get("method", "full_query_guard")) == "full_query_guard"
    ]
    attack_by_query = _load_attacks(config, sample_ids)
    integrity_rows = _build_integrity_rows(samples, attack_by_query)
    candidates = load_candidate_sources(config.clean_reference_output_dir)
    matrix = build_stage48_defense_matrix(
        config=config,
        samples=samples,
        source_context_rows=source_rows,
        candidate_sources=candidates,
        attack_by_query=attack_by_query,
        integrity_rows=integrity_rows,
    )
    preflight = build_stage48_preflight_rows(
        config=config,
        samples=samples,
        integrity_rows=integrity_rows,
        matrix_rows=matrix,
        attack_by_query=attack_by_query,
    )
    summary = summarize_stage48_preflight(config=config, rows=preflight)

    write_jsonl(config.integrity_output_path, integrity_rows)
    write_jsonl(config.matrix_output_path, matrix)
    write_jsonl(config.preflight_output_path, preflight)
    atomic_write_json(config.summary_output_path, summary)
    atomic_write_json(
        config.manifest_output_path,
        _build_manifest(
            config=config,
            sample_count=len(samples),
            matrix_count=len(matrix),
            preflight_count=len(preflight),
        ),
    )
    print(
        f"stage48_condition={config.condition}, dataset={config.dataset}, "
        f"attack_family={config.attack_family}, samples={len(samples)}, "
        f"matrix_rows={len(matrix)}, preflight_rows={len(preflight)}"
    )
    return preflight


def build_stage48_defense_matrix(
    *,
    config: Stage48DefenseMatrixConfig,
    samples: list[NormalizedSample],
    source_context_rows: list[dict[str, Any]],
    candidate_sources: list[NonOracleCandidateSource],
    attack_by_query: dict[str, dict[str, Any]],
    integrity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the frozen Stage43/44/45 implementations to Stage48 contexts."""

    expected_ids = {sample.query_id for sample in samples}
    actual_ids = {str(row.get("query_id", "")) for row in source_context_rows}
    missing = sorted(expected_ids - actual_ids)
    if missing:
        raise ValueError(
            f"Stage48 source contexts missing {len(missing)} queries; first={missing[0]}"
        )
    if len(source_context_rows) != len(expected_ids):
        raise ValueError(
            "Stage48 requires exactly one full_query_guard context per sample"
        )

    stage43_all = build_stage28_context_rows(
        source_context_rows=source_context_rows,
        candidate_sources=candidate_sources,
        input_method_name="full_query_guard",
        top_k_candidates=config.top_k_candidates,
        min_candidate_score=config.min_candidate_score,
        entity_drift_threshold=config.entity_drift_threshold,
        title_overlap_threshold=config.title_overlap_threshold,
    )
    unprotected = [
        row for row in stage43_all if row.get("method") == "full_query_guard"
    ]
    recovered = [
        row
        for row in stage43_all
        if row.get("method") == "risk_non_oracle_title_entity_bm25"
    ]
    enrichment_rows = build_stage35_enrichment_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=recovered,
        candidate_sources=candidate_sources,
        audited_rows=[],
        dataset=config.dataset,
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["query_bm25_append"],
        max_sources_values=[config.stage44_max_sources],
        max_chars_per_source=config.max_chars_per_source,
        candidate_pool_top_k=config.candidate_pool_top_k,
        baseline_max_sources=config.baseline_max_sources,
    )
    stage44 = build_stage35_enriched_context_rows(
        context_rows=recovered,
        enrichment_rows=enrichment_rows,
        selected_policy="query_bm25_append",
        selected_max_sources=config.stage44_max_sources,
    )
    chain_rows = build_stage38_chain_rows(
        samples=samples,
        context_rows=stage44,
        candidate_sources=candidate_sources,
        judged_rows=[],
        dataset=config.dataset,
        methods=[f"stage35_query_bm25_append_top{config.stage44_max_sources}"],
        max_sources=config.stage45_max_sources,
        max_chars_per_source=config.max_chars_per_source,
        candidate_pool_top_k=config.candidate_pool_top_k,
    )
    stage45 = build_stage38_targeted_context_rows(
        context_rows=stage44,
        chain_rows=chain_rows,
        selected_max_sources=config.stage45_max_sources,
    )
    raw_matrix = [*unprotected, *recovered, *stage44, *stage45]
    expected_count = len(samples) * len(DEFENSE_METHODS)
    if len(raw_matrix) != expected_count:
        raise ValueError(
            f"Stage48 defense matrix incomplete: expected={expected_count}, "
            f"actual={len(raw_matrix)}"
        )

    output: list[dict[str, Any]] = []
    for row in raw_matrix:
        method = str(row.get("method", ""))
        query_id = str(row.get("query_id", ""))
        attack = attack_by_query.get(query_id, {})
        annotated = dict(row)
        annotated["stage48_condition"] = config.condition
        annotated["stage48_attack_family"] = config.attack_family
        annotated["stage48_attack_id"] = str(attack.get("attack_id", ""))
        annotated["stage48_attack_doc_ids"] = _attack_doc_ids(attack)
        annotated["stage48_malicious_answer"] = str(attack.get("malicious_answer", ""))
        annotated["stage48_defense_stage"] = _METHOD_TO_STAGE[method]
        output.append(annotated)
    return sorted(
        output,
        key=lambda row: (
            str(row.get("query_id", "")),
            DEFENSE_METHODS.index(str(row.get("method", ""))),
        ),
    )


def build_stage48_preflight_rows(
    *,
    config: Stage48DefenseMatrixConfig,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
    attack_by_query: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render exact answer inputs and record attack/utility surfaces."""

    policies = {
        method: Stage27RenderingPolicy(
            order_policy="official_order",
            prompt_policy=config.prompt_policy,
            max_sources=(
                config.stage45_max_sources
                if method == "stage38_second_hop_append_top14"
                else config.stage44_max_sources
            ),
            max_chars_per_source=config.max_chars_per_source,
        )
        for method in DEFENSE_METHODS
    }
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=matrix_rows,
        dataset=config.dataset,
        methods=list(DEFENSE_METHODS),
        max_sources=config.stage44_max_sources,
        max_chars_per_source=config.max_chars_per_source,
        rendering_policies=policies,
    )
    context_by_key = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row
        for row in matrix_rows
    }
    output: list[dict[str, Any]] = []
    for case in cases:
        attack = attack_by_query.get(case.query_id, {})
        attack_doc_ids = _attack_doc_ids(attack)
        context = context_by_key[(case.query_id, case.method)]
        risk_ids = [
            str(item) for item in context.get("risk_detected_source_doc_ids", [])
        ]
        recovered_ids = [
            str(item) for item in context.get("recovered_source_doc_ids", [])
        ]
        rendered_sources = _rendered_source_records(
            context,
            max_sources=(
                config.stage45_max_sources
                if case.method == "stage38_second_hop_append_top14"
                else config.stage44_max_sources
            ),
        )
        attack_source_unrecovered = any(
            _source_doc_id(source) in set(attack_doc_ids)
            and str(source.get("source_state", "")) != "clean_reference"
            for source in rendered_sources
        )
        risk_detected_attack = bool(set(attack_doc_ids) & set(risk_ids))
        output.append(
            {
                "dataset": config.dataset,
                "condition": config.condition,
                "query_id": case.query_id,
                "attack_family": config.attack_family,
                "attack_id": str(attack.get("attack_id", "")),
                "attack_doc_ids": attack_doc_ids,
                "malicious_answer": str(attack.get("malicious_answer", "")),
                "defense_stage": _METHOD_TO_STAGE[case.method],
                "method": case.method,
                "source_count": case.source_count,
                "context_doc_ids": case.context_doc_ids,
                "attack_source_exposed": attack_source_unrecovered,
                "attack_source_unrecovered": attack_source_unrecovered,
                "malicious_answer_exposed": _contains(
                    case.rendered_context, str(attack.get("malicious_answer", ""))
                ),
                "risk_detected_attack": risk_detected_attack,
                # A recovered candidate normally has a different document id
                # than a removed synthetic attack. Recovery is therefore
                # detection plus absence of the unrecovered attack source.
                "attack_recovered": bool(
                    risk_detected_attack and not attack_source_unrecovered
                ),
                "risk_detected_source_ids": risk_ids,
                "recovered_source_ids": recovered_ids,
                "risk_detected_source_count": len(risk_ids),
                "recovered_source_count": len(recovered_ids),
                "gold_answer_exposed": case.context_has_gold_answer,
                "support_hit_doc_ids": case.support_hit_doc_ids,
                "full_support_hit": set(case.support_doc_ids).issubset(
                    set(case.context_doc_ids)
                ),
                "rendered_char_count": len(case.rendered_context),
                "attack_source_identity_rule": (
                    "doc_id_and_non_clean_reference_source_state"
                ),
            }
        )
    return output


def summarize_stage48_preflight(
    *, config: Stage48DefenseMatrixConfig, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate exact-prompt diagnostics without changing denominators."""

    by_method: dict[str, dict[str, Any]] = {}
    for method in DEFENSE_METHODS:
        group = [row for row in rows if row["method"] == method]
        count = len(group)
        by_method[method] = {
            "defense_stage": _METHOD_TO_STAGE[method],
            "query_count": count,
            "attack_source_exposed_count": sum(
                bool(row["attack_source_exposed"]) for row in group
            ),
            "attack_source_unrecovered_count": sum(
                bool(row["attack_source_unrecovered"]) for row in group
            ),
            "malicious_answer_exposed_count": sum(
                bool(row["malicious_answer_exposed"]) for row in group
            ),
            "risk_detected_attack_count": sum(
                bool(row["risk_detected_attack"]) for row in group
            ),
            "attack_recovered_count": sum(
                bool(row["attack_recovered"]) for row in group
            ),
            "queries_with_any_risk_detection": sum(
                bool(row["risk_detected_source_count"]) for row in group
            ),
            "queries_with_any_source_recovery": sum(
                bool(row["recovered_source_count"]) for row in group
            ),
            "total_risk_detected_source_count": sum(
                int(row["risk_detected_source_count"]) for row in group
            ),
            "total_recovered_source_count": sum(
                int(row["recovered_source_count"]) for row in group
            ),
            "gold_answer_exposed_count": sum(
                bool(row["gold_answer_exposed"]) for row in group
            ),
            "full_support_hit_count": sum(
                bool(row["full_support_hit"]) for row in group
            ),
            "avg_source_count": (
                round(sum(int(row["source_count"]) for row in group) / count, 6)
                if count
                else 0.0
            ),
        }
    return {
        "schema_version": 1,
        "experiment": config.stage_label,
        "dataset": config.dataset,
        "condition": config.condition,
        "attack_family": config.attack_family,
        "attempt_unit": "frozen_attack"
        if config.condition == "attacked"
        else "unique_query",
        "query_count": len(rows) // len(DEFENSE_METHODS),
        "frozen_parameters": _frozen_parameters(config),
        "methods": by_method,
    }


def _load_attacks(
    config: Stage48DefenseMatrixConfig, sample_ids: set[str]
) -> dict[str, dict[str, Any]]:
    if config.frozen_attacks_path is None:
        return {}
    attacks = load_jsonl(config.frozen_attacks_path)
    selected = {
        str(row.get("query_id", "")): row
        for row in attacks
        if str(row.get("query_id", "")) in sample_ids
    }
    if len(selected) != len(sample_ids):
        raise ValueError(
            "Stage48 attacked condition requires exactly one frozen attack per sample"
        )
    wrong_family = [
        query_id
        for query_id, row in selected.items()
        if str(row.get("attack_family", "")) != config.attack_family
    ]
    if wrong_family:
        raise ValueError(f"Frozen attack family mismatch for query {wrong_family[0]}")
    return selected


def _build_integrity_rows(
    samples: list[NormalizedSample], attack_by_query: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "query_id": sample.query_id,
            "query": sample.query,
            "answer": sample.answer,
            "support_doc_ids": [str(item) for item in sample.support_doc_ids],
            "changed_support_doc_ids": _attack_doc_ids(
                attack_by_query.get(sample.query_id, {})
            ),
            "stage48_label_semantics": (
                "changed_support_doc_ids stores the frozen attack document id for "
                "legacy answer-case compatibility; Stage48 reports call it attack_doc_id."
            ),
        }
        for sample in samples
    ]


def _attack_doc_ids(attack: dict[str, Any]) -> list[str]:
    doc_id = str(attack.get("injected_doc_id", "")).strip()
    return [doc_id] if doc_id else []


def _rendered_source_records(
    context_row: dict[str, Any], *, max_sources: int
) -> list[dict[str, Any]]:
    context_data = context_row.get("context_data", {})
    if not isinstance(context_data, dict):
        return []
    sources = context_data.get("sources", [])
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)][:max_sources]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(source.get("logicguard_doc_id", ""))


def _frozen_parameters(config: Stage48DefenseMatrixConfig) -> dict[str, Any]:
    return {
        "top_k_candidates": config.top_k_candidates,
        "min_candidate_score": config.min_candidate_score,
        "entity_drift_threshold": config.entity_drift_threshold,
        "title_overlap_threshold": config.title_overlap_threshold,
        "baseline_max_sources": config.baseline_max_sources,
        "stage44_policy": "query_bm25_append",
        "stage44_max_sources": config.stage44_max_sources,
        "stage45_policy": "second_hop_append",
        "stage45_max_sources": config.stage45_max_sources,
        "max_chars_per_source": config.max_chars_per_source,
        "candidate_pool_top_k": config.candidate_pool_top_k,
        "prompt_policy": config.prompt_policy,
    }


def _build_manifest(
    *,
    config: Stage48DefenseMatrixConfig,
    sample_count: int,
    matrix_count: int,
    preflight_count: int,
) -> dict[str, Any]:
    inputs = [
        config.sample_path,
        config.source_context_path,
        *([config.frozen_attacks_path] if config.frozen_attacks_path else []),
        Path(__file__).resolve(),
    ]
    candidate_files = sorted(config.clean_reference_output_dir.glob("*.parquet"))
    artifacts = [
        {
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in [*inputs, *candidate_files]
    ]
    payload = {
        "schema_version": 1,
        "experiment": config.stage_label,
        "dataset": config.dataset,
        "condition": config.condition,
        "attack_family": config.attack_family,
        "sample_count": sample_count,
        "expected_matrix_count": sample_count * len(DEFENSE_METHODS),
        "matrix_count": matrix_count,
        "preflight_count": preflight_count,
        "methods": list(DEFENSE_METHODS),
        "frozen_parameters": _frozen_parameters(config),
        "inputs": artifacts,
        "credential_values_recorded": False,
    }
    payload["manifest_fingerprint"] = fingerprint_json(payload)
    return payload


def _validate_config(config: Stage48DefenseMatrixConfig) -> None:
    if config.condition not in {"attacked", "clean"}:
        raise ValueError("condition must be attacked or clean")
    if config.condition == "attacked" and config.frozen_attacks_path is None:
        raise ValueError("attacked condition requires frozen_attacks_path")
    if config.condition == "clean" and config.frozen_attacks_path is not None:
        raise ValueError("clean condition must not provide frozen_attacks_path")
    if config.stage44_max_sources != 12 or config.stage45_max_sources != 14:
        raise ValueError("Stage48 must preserve the frozen Stage44/45 source limits")


def _normalize(text: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(text.casefold()))


def _contains(text: str, phrase: str) -> bool:
    return bool(phrase.strip()) and _normalize(phrase) in _normalize(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run_from_config(Stage48DefenseMatrixConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
