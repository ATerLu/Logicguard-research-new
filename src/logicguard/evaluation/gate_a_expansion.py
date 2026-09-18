"""Freeze and audit the Stage48 Gate A fixed-budget attack expansion."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    sha256_file,
    write_inferred_csv,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json
from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.evaluation.stage48_failure_taxonomy import classify_attack_validity

ATTACK_FAMILIES = ("natural_bridge", "low_drift", "candidate_collision")


@dataclass(frozen=True, slots=True)
class GateABatchInputs:
    """One non-overlapping attack-generation batch."""

    label: str
    attack_records_path: Path
    attacked_context_path: Path
    attack_integrity_path: Path
    preflight_rows_path: Path


@dataclass(frozen=True, slots=True)
class GateADatasetInputs:
    """Frozen inputs and combined outputs for one dataset."""

    dataset: str
    sample_path: Path
    attempted_queries: int
    batches: list[GateABatchInputs]
    combined_attack_records_path: Path
    combined_attacked_context_path: Path
    combined_attack_integrity_path: Path
    combined_preflight_rows_path: Path


@dataclass(frozen=True, slots=True)
class GateAExpansionConfig:
    """Stage48 Gate A fixed-budget audit configuration."""

    datasets: list[GateADatasetInputs]
    attack_generation_run_manifest_paths: list[Path]
    inventory_rows_output_path: Path
    summary_output_path: Path
    cost_ledger_output_path: Path
    manifest_output_path: Path
    report_path: Path
    target_evaluation_valid_per_cell: int = 10
    attack_input_price_per_million_tokens_cny: float = 2.0
    attack_output_price_per_million_tokens_cny: float = 8.0
    context_query_embedding_count: int = 100
    context_query_embedding_max_tokens_each: int = 128
    embedding_price_per_thousand_tokens_cny: float = 0.0005
    prior_stage48_exact_logged_cny: float = 1.209554
    prior_stage48_upper_cny: float = 1.210900
    stage_label: str = "Stage48-GateA-fixed50-expansion"

    @classmethod
    def from_yaml(cls, path: Path) -> "GateAExpansionConfig":
        """Load a project-relative Gate A expansion config."""

        path = resolve_config_path(path)
        root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )

        datasets = []
        for row in payload["datasets"]:
            batches = [
                GateABatchInputs(
                    label=str(batch["label"]),
                    attack_records_path=resolve(batch["attack_records_path"]),
                    attacked_context_path=resolve(batch["attacked_context_path"]),
                    attack_integrity_path=resolve(batch["attack_integrity_path"]),
                    preflight_rows_path=resolve(batch["preflight_rows_path"]),
                )
                for batch in row["batches"]
            ]
            datasets.append(
                GateADatasetInputs(
                    dataset=str(row["dataset"]),
                    sample_path=resolve(row["sample_path"]),
                    attempted_queries=int(row["attempted_queries"]),
                    batches=batches,
                    combined_attack_records_path=resolve(
                        row["combined_attack_records_path"]
                    ),
                    combined_attacked_context_path=resolve(
                        row["combined_attacked_context_path"]
                    ),
                    combined_attack_integrity_path=resolve(
                        row["combined_attack_integrity_path"]
                    ),
                    combined_preflight_rows_path=resolve(
                        row["combined_preflight_rows_path"]
                    ),
                )
            )
        return cls(
            datasets=datasets,
            attack_generation_run_manifest_paths=[
                resolve(item)
                for item in payload["attack_generation_run_manifest_paths"]
            ],
            inventory_rows_output_path=resolve(payload["inventory_rows_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            cost_ledger_output_path=resolve(payload["cost_ledger_output_path"]),
            manifest_output_path=resolve(payload["manifest_output_path"]),
            report_path=resolve(payload["report_path"]),
            target_evaluation_valid_per_cell=int(
                payload.get("target_evaluation_valid_per_cell", 10)
            ),
            attack_input_price_per_million_tokens_cny=float(
                payload.get("attack_input_price_per_million_tokens_cny", 2.0)
            ),
            attack_output_price_per_million_tokens_cny=float(
                payload.get("attack_output_price_per_million_tokens_cny", 8.0)
            ),
            context_query_embedding_count=int(
                payload.get("context_query_embedding_count", 100)
            ),
            context_query_embedding_max_tokens_each=int(
                payload.get("context_query_embedding_max_tokens_each", 128)
            ),
            embedding_price_per_thousand_tokens_cny=float(
                payload.get("embedding_price_per_thousand_tokens_cny", 0.0005)
            ),
            prior_stage48_exact_logged_cny=float(
                payload.get("prior_stage48_exact_logged_cny", 1.209554)
            ),
            prior_stage48_upper_cny=float(
                payload.get("prior_stage48_upper_cny", 1.210900)
            ),
            stage_label=str(
                payload.get("stage_label", "Stage48-GateA-fixed50-expansion")
            ),
        )


def run_from_config(config: GateAExpansionConfig) -> dict[str, Any]:
    """Merge fixed batches and write the Gate A inventory, summary and costs."""

    inventory_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    input_paths: list[Path] = []
    for dataset_config in config.datasets:
        samples = load_normalized_samples(dataset_config.sample_path)[
            : dataset_config.attempted_queries
        ]
        if len(samples) != dataset_config.attempted_queries:
            raise ValueError(
                f"{dataset_config.dataset} has {len(samples)} samples; "
                f"expected {dataset_config.attempted_queries}"
            )
        samples_by_id = {sample.query_id: sample for sample in samples}
        sample_order = {sample.query_id: index for index, sample in enumerate(samples)}
        records: list[dict[str, Any]] = []
        contexts: list[dict[str, Any]] = []
        integrity: list[dict[str, Any]] = []
        preflight: list[dict[str, Any]] = []
        batch_by_key: dict[tuple[str, str], str] = {}
        for batch in dataset_config.batches:
            batch_records = load_jsonl(batch.attack_records_path)
            records.extend(batch_records)
            contexts.extend(load_jsonl(batch.attacked_context_path))
            integrity.extend(load_jsonl(batch.attack_integrity_path))
            preflight.extend(load_jsonl(batch.preflight_rows_path))
            input_paths.extend(
                [
                    batch.attack_records_path,
                    batch.attacked_context_path,
                    batch.attack_integrity_path,
                    batch.preflight_rows_path,
                ]
            )
            for row in batch_records:
                key = (str(row.get("query_id", "")), str(row.get("attack_family", "")))
                if key in batch_by_key:
                    raise ValueError(
                        f"Duplicate attack key for {dataset_config.dataset}: {key}"
                    )
                batch_by_key[key] = batch.label

        expected_records = dataset_config.attempted_queries * len(ATTACK_FAMILIES)
        if len(records) != expected_records:
            raise ValueError(
                f"{dataset_config.dataset} has {len(records)} attack records; "
                f"expected {expected_records}"
            )
        expected_keys = {
            (sample.query_id, family)
            for sample in samples
            for family in ATTACK_FAMILIES
        }
        if set(batch_by_key) != expected_keys:
            raise ValueError(f"{dataset_config.dataset} attack grid is incomplete")

        records.sort(
            key=lambda row: (
                sample_order[str(row["query_id"])],
                ATTACK_FAMILIES.index(str(row["attack_family"])),
            )
        )
        contexts = _sort_unique(
            contexts,
            key_fields=("query_id", "method"),
            sample_order=sample_order,
        )
        integrity = _sort_unique(
            integrity, key_fields=("query_id",), sample_order=sample_order
        )
        preflight = _sort_unique(
            preflight,
            key_fields=("query_id", "method"),
            sample_order=sample_order,
        )
        write_jsonl(dataset_config.combined_attack_records_path, records)
        write_jsonl(dataset_config.combined_attacked_context_path, contexts)
        write_jsonl(dataset_config.combined_attack_integrity_path, integrity)
        write_jsonl(dataset_config.combined_preflight_rows_path, preflight)

        dataset_rows = build_inventory_rows(
            dataset=dataset_config.dataset,
            samples_by_id=samples_by_id,
            attack_records=records,
            batch_by_key=batch_by_key,
            target_per_family=config.target_evaluation_valid_per_cell,
        )
        inventory_rows.extend(dataset_rows)
        for family in ATTACK_FAMILIES:
            family_rows = [
                row for row in dataset_rows if row["attack_family"] == family
            ]
            evaluation_valid = sum(bool(row["evaluation_valid"]) for row in family_rows)
            selected = sum(bool(row["selected_for_reindex"]) for row in family_rows)
            summaries.append(
                {
                    "dataset": dataset_config.dataset,
                    "attack_family": family,
                    "attempted": len(family_rows),
                    "generation_valid": sum(
                        bool(row["generation_valid"]) for row in family_rows
                    ),
                    "evaluation_valid": evaluation_valid,
                    "selected_for_reindex": selected,
                    "target": config.target_evaluation_valid_per_cell,
                    "gate_cell_ready": evaluation_valid
                    >= config.target_evaluation_valid_per_cell,
                }
            )
        input_paths.append(dataset_config.sample_path)

    write_jsonl(config.inventory_rows_output_path, inventory_rows)
    write_inferred_csv(config.summary_output_path, summaries)
    costs = _build_cost_ledger(config)
    atomic_write_json(config.cost_ledger_output_path, costs)
    manifest = {
        "schema_version": 1,
        "experiment": config.stage_label,
        "attempt_policy": "fixed first 50 queries per dataset; no success-conditioned retries",
        "target_evaluation_valid_per_cell": config.target_evaluation_valid_per_cell,
        "cell_count": len(summaries),
        "ready_cell_count": sum(bool(row["gate_cell_ready"]) for row in summaries),
        "inventory_row_count": len(inventory_rows),
        "inputs": [
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(set(input_paths))
        ],
        "credential_values_recorded": False,
    }
    atomic_write_json(config.manifest_output_path, manifest)
    _write_report(config, summaries, costs)
    return {
        "inventory_rows": inventory_rows,
        "summaries": summaries,
        "costs": costs,
        "manifest": manifest,
    }


def build_inventory_rows(
    *,
    dataset: str,
    samples_by_id: dict[str, NormalizedSample],
    attack_records: list[dict[str, Any]],
    batch_by_key: dict[tuple[str, str], str],
    target_per_family: int,
) -> list[dict[str, Any]]:
    """Classify every fixed-budget attempt and select a deterministic subset."""

    rows: list[dict[str, Any]] = []
    for attack in attack_records:
        query_id = str(attack.get("query_id", ""))
        family = str(attack.get("attack_family", ""))
        sample = samples_by_id[query_id]
        non_oracle = not any(
            bool(attack.get(key))
            for key in (
                "attacker_used_gold_answer",
                "attacker_used_support_ids",
                "attacker_used_changed_labels",
            )
        )
        target_is_wrong = _normalize(attack.get("malicious_answer")) != _normalize(
            sample.answer
        )
        collision_candidate_wrong = family != "candidate_collision" or str(
            attack.get("collision_candidate_doc_id", "")
        ) not in {str(item) for item in sample.support_doc_ids}
        generation_valid = bool(attack.get("valid"))
        evaluation_valid = (
            generation_valid
            and non_oracle
            and target_is_wrong
            and collision_candidate_wrong
        )
        row = {
            "dataset": dataset,
            "query_id": query_id,
            "hop_group": query_id.split("__", maxsplit=1)[0],
            "attack_family": family,
            "attack_id": str(attack.get("attack_id", "")),
            "batch": batch_by_key[(query_id, family)],
            "generation_valid": generation_valid,
            "non_oracle_generation": non_oracle,
            "target_is_wrong": target_is_wrong,
            "wrong_collision_candidate": collision_candidate_wrong,
            "evaluation_valid": evaluation_valid,
            "invalid_reason": str(attack.get("invalid_reason", "")),
            "selected_for_reindex": False,
        }
        failure = classify_attack_validity(row)
        row["validity_stage"] = failure.stage
        row["validity_category"] = failure.category
        rows.append(row)
    for family in ATTACK_FAMILIES:
        eligible = [
            row
            for row in rows
            if row["attack_family"] == family and row["evaluation_valid"]
        ]
        if len(eligible) < target_per_family:
            continue
        eligible.sort(key=lambda row: _sha_order(str(row["query_id"])))
        selected: list[dict[str, Any]] = []
        for hop_prefix in ("3hop", "4hop"):
            candidate = next(
                (
                    row
                    for row in eligible
                    if str(row["hop_group"]).startswith(hop_prefix)
                ),
                None,
            )
            if candidate is not None and len(selected) < target_per_family:
                selected.append(candidate)
        for row in eligible:
            if row not in selected and len(selected) < target_per_family:
                selected.append(row)
        for row in selected:
            row["selected_for_reindex"] = True
    return rows


def _sort_unique(
    rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    sample_order: dict[str, int],
) -> list[dict[str, Any]]:
    keyed: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        if key in keyed:
            raise ValueError(f"Duplicate combined artifact key: {key}")
        keyed[key] = row
    return sorted(
        keyed.values(),
        key=lambda row: (
            sample_order[str(row["query_id"])],
            *(str(row.get(field, "")) for field in key_fields[1:]),
        ),
    )


def _build_cost_ledger(config: GateAExpansionConfig) -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    completed_calls = 0
    for path in config.attack_generation_run_manifest_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload.get("status") != "complete":
            raise ValueError(f"Attack generation manifest is not complete: {path}")
        usage = payload.get("token_usage", {})
        prompt_tokens += int(usage.get("prompt_tokens", 0))
        completion_tokens += int(usage.get("completion_tokens", 0))
        completed_calls += int(payload.get("completed_count", 0)) // len(
            ATTACK_FAMILIES
        )
    attack_cost = round(
        (
            prompt_tokens * config.attack_input_price_per_million_tokens_cny
            + completion_tokens * config.attack_output_price_per_million_tokens_cny
        )
        / 1_000_000,
        6,
    )
    embedding_tokens_upper = (
        config.context_query_embedding_count
        * config.context_query_embedding_max_tokens_each
    )
    embedding_cost_upper = round(
        embedding_tokens_upper / 1000 * config.embedding_price_per_thousand_tokens_cny,
        6,
    )
    return {
        "schema_version": 1,
        "price_basis": "Stage48 frozen 2026-08-12 China-Beijing undiscounted catalog snapshot",
        "attack_generation": {
            "completed_calls": completed_calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "catalog_cost_cny": attack_cost,
        },
        "clean_context_query_embedding_upper_bound": {
            "query_count": config.context_query_embedding_count,
            "max_tokens_per_query": config.context_query_embedding_max_tokens_each,
            "max_tokens": embedding_tokens_upper,
            "catalog_cost_upper_cny": embedding_cost_upper,
        },
        "gate_a_increment_exact_logged_cny": attack_cost,
        "gate_a_increment_upper_cny": round(attack_cost + embedding_cost_upper, 6),
        "stage48_cumulative_exact_logged_cny": round(
            config.prior_stage48_exact_logged_cny + attack_cost, 6
        ),
        "stage48_cumulative_upper_cny": round(
            config.prior_stage48_upper_cny + attack_cost + embedding_cost_upper, 6
        ),
        "credential_values_recorded": False,
    }


def _write_report(
    config: GateAExpansionConfig,
    summaries: list[dict[str, Any]],
    costs: dict[str, Any],
) -> None:
    lines = [
        f"# {config.stage_label}",
        "",
        "固定尝试预算：每数据集前 50 个 query；生成失败保留且不按成功条件追加调用。",
        "",
        "| dataset | attack family | attempted | generation-valid | evaluation-valid | selected | cell ready |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['dataset']} | {row['attack_family']} | {row['attempted']} | "
            f"{row['generation_valid']} | {row['evaluation_valid']} | "
            f"{row['selected_for_reindex']} | {str(row['gate_cell_ready']).lower()} |"
        )
    lines.extend(
        [
            "",
            "只允许 `cell ready=true` 的格进入 10-sample full-corpus context-only reindex。",
            "未达门的格记录为攻击生成/评测有效性瓶颈，不得继续生成到凑满成功样本。",
            "",
            f"攻击生成精确日志成本：¥{costs['gate_a_increment_exact_logged_cny']:.6f}。",
            f"含 clean query embedding 保守上界：¥{costs['gate_a_increment_upper_cny']:.6f}。",
            "",
        ]
    )
    atomic_write_text(config.report_path, "\n".join(lines))


def _normalize(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _sha_order(value: str) -> str:
    return fingerprint_json(value)


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    result = run_from_config(GateAExpansionConfig.from_yaml(args.config))
    print(
        f"gate_a_inventory_rows={len(result['inventory_rows'])}, "
        f"ready_cells={result['manifest']['ready_cell_count']}/"
        f"{result['manifest']['cell_count']}"
    )


if __name__ == "__main__":
    main()
