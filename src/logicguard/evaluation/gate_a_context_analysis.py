"""Aggregate the preregistered Stage48 Gate A context-exposure cells."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    write_inferred_csv,
)


@dataclass(frozen=True, slots=True)
class GateAContextCell:
    dataset: str
    attack_family: str
    exposure_path: Path
    summary_path: Path


@dataclass(frozen=True, slots=True)
class GateAContextAnalysisConfig:
    inventory_summary_path: Path
    fixed50_cost_ledger_path: Path
    cells: tuple[GateAContextCell, ...]
    target_per_cell: int
    minimum_ready_datasets_per_family: int
    prompt_exposure_threshold: float
    minimum_passing_families: int
    query_embedding_max_tokens_each: int
    embedding_price_per_thousand_tokens_cny: float
    output_path: Path
    csv_output_path: Path
    cost_ledger_output_path: Path
    report_path: Path

    @classmethod
    def from_yaml(cls, path: Path) -> "GateAContextAnalysisConfig":
        path = resolve_config_path(path)
        root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: str) -> Path:
            candidate = Path(raw)
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )

        cells = tuple(
            GateAContextCell(
                dataset=str(row["dataset"]),
                attack_family=str(row["attack_family"]),
                exposure_path=resolve(str(row["exposure_path"])),
                summary_path=resolve(str(row["summary_path"])),
            )
            for row in payload["cells"]
        )
        return cls(
            inventory_summary_path=resolve(str(payload["inventory_summary_path"])),
            fixed50_cost_ledger_path=resolve(str(payload["fixed50_cost_ledger_path"])),
            cells=cells,
            target_per_cell=int(payload.get("target_per_cell", 10)),
            minimum_ready_datasets_per_family=int(
                payload.get("minimum_ready_datasets_per_family", 2)
            ),
            prompt_exposure_threshold=float(
                payload.get("prompt_exposure_threshold", 0.2)
            ),
            minimum_passing_families=int(payload.get("minimum_passing_families", 2)),
            query_embedding_max_tokens_each=int(
                payload.get("query_embedding_max_tokens_each", 128)
            ),
            embedding_price_per_thousand_tokens_cny=float(
                payload.get("embedding_price_per_thousand_tokens_cny", 0.0005)
            ),
            output_path=resolve(str(payload["output_path"])),
            csv_output_path=resolve(str(payload["csv_output_path"])),
            cost_ledger_output_path=resolve(str(payload["cost_ledger_output_path"])),
            report_path=resolve(str(payload["report_path"])),
        )


def wilson_interval(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Return a two-sided 95% Wilson score interval for a binomial rate."""

    if total <= 0:
        return (0.0, 1.0)
    if successes < 0 or successes > total:
        raise ValueError("successes must be between zero and total")
    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    centre = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def run_from_config(config: GateAContextAnalysisConfig) -> dict[str, Any]:
    """Aggregate fixed-denominator cells without success-conditioned resampling."""

    inventory = _read_csv(config.inventory_summary_path)
    seen: set[tuple[str, str]] = set()
    cell_rows: list[dict[str, Any]] = []
    for cell in config.cells:
        key = (cell.dataset, cell.attack_family)
        if key in seen:
            raise ValueError(f"Duplicate Gate A context cell: {key}")
        seen.add(key)
        rows = load_jsonl(cell.exposure_path)
        if len(rows) != config.target_per_cell:
            raise ValueError(
                f"Gate A cell {key} has {len(rows)} rows; expected {config.target_per_cell}"
            )
        if any(
            str(row.get("dataset")) != cell.dataset
            or str(row.get("attack_family")) != cell.attack_family
            for row in rows
        ):
            raise ValueError(f"Mismatched labels in Gate A context cell: {key}")
        included = sum(
            bool(row.get("index_document_included"))
            and bool(row.get("index_text_unit_included"))
            for row in rows
        )
        retrieved = sum(bool(row.get("retrieved")) for row in rows)
        exposed = sum(
            bool(row.get("prompt_source_exposed"))
            and bool(row.get("prompt_target_exposed"))
            for row in rows
        )
        cell_rows.append(
            _rate_row(
                dataset=cell.dataset,
                attack_family=cell.attack_family,
                attempted=len(rows),
                index_included=included,
                retrieved=retrieved,
                prompt_exposed=exposed,
            )
        )

    family_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "datasets": 0,
            "attempted": 0,
            "index_included": 0,
            "retrieved": 0,
            "prompt_exposed": 0,
        }
    )
    for row in cell_rows:
        counts = family_counts[str(row["attack_family"])]
        counts["datasets"] += 1
        for field in ("attempted", "index_included", "retrieved", "prompt_exposed"):
            counts[field] += int(row[field])

    family_rows: list[dict[str, Any]] = []
    qualifying: list[str] = []
    for family, counts in sorted(family_counts.items()):
        row = _rate_row(
            dataset="pooled_ready_datasets",
            attack_family=family,
            attempted=counts["attempted"],
            index_included=counts["index_included"],
            retrieved=counts["retrieved"],
            prompt_exposed=counts["prompt_exposed"],
        )
        row["ready_dataset_count"] = counts["datasets"]
        row["eligible_for_family_gate"] = (
            counts["datasets"] >= config.minimum_ready_datasets_per_family
        )
        row["passes_prompt_exposure_threshold"] = bool(
            row["eligible_for_family_gate"]
            and row["prompt_exposure_rate"] >= config.prompt_exposure_threshold
        )
        if row["passes_prompt_exposure_threshold"]:
            qualifying.append(family)
        family_rows.append(row)

    incomplete_cells = [
        row
        for row in inventory
        if str(row.get("gate_cell_ready", "")).casefold() != "true"
    ]
    fixed_cost = json.loads(config.fixed50_cost_ledger_path.read_text(encoding="utf-8"))
    index_cost = sum(
        float(
            json.loads(cell.summary_path.read_text(encoding="utf-8")).get(
                "catalog_cost_estimate_cny", 0.0
            )
        )
        for cell in config.cells
    )
    query_count = sum(int(row["attempted"]) for row in cell_rows)
    query_upper = (
        query_count
        * config.query_embedding_max_tokens_each
        * config.embedding_price_per_thousand_tokens_cny
        / 1000.0
    )
    cost_ledger = {
        "schema_version": 1,
        "price_basis": fixed_cost["price_basis"],
        "fixed50_generation_and_clean_context": fixed_cost,
        "full_corpus_index_catalog_cost_cny": round(index_cost, 6),
        "attacked_context_query_embedding_upper_bound": {
            "query_count": query_count,
            "max_tokens_per_query": config.query_embedding_max_tokens_each,
            "catalog_cost_upper_cny": round(query_upper, 6),
        },
        "gate_a_increment_exact_logged_cny": round(
            float(fixed_cost["gate_a_increment_exact_logged_cny"]) + index_cost, 6
        ),
        "gate_a_increment_upper_cny": round(
            float(fixed_cost["gate_a_increment_upper_cny"]) + index_cost + query_upper,
            6,
        ),
        "stage48_cumulative_exact_logged_cny": round(
            float(fixed_cost["stage48_cumulative_exact_logged_cny"]) + index_cost, 6
        ),
        "stage48_cumulative_upper_cny": round(
            float(fixed_cost["stage48_cumulative_upper_cny"])
            + index_cost
            + query_upper,
            6,
        ),
        "credential_values_recorded": False,
    }
    result = {
        "schema_version": 1,
        "experiment": "Stage48_GateA_fixed50_context_exposure",
        "denominator_policy": (
            "First 50 queries per dataset; exactly 10 preselected evaluation-valid "
            "attacks per ready cell; no exposure- or success-conditioned replacement."
        ),
        "interval_method": "two-sided_95_percent_Wilson_score",
        "cell_rows": cell_rows,
        "family_rows": family_rows,
        "incomplete_inventory_cells": incomplete_cells,
        "gate": {
            "prompt_exposure_threshold": config.prompt_exposure_threshold,
            "minimum_ready_datasets_per_family": config.minimum_ready_datasets_per_family,
            "minimum_passing_families": config.minimum_passing_families,
            "qualifying_attack_families": qualifying,
            "prompt_exposure_requirement_passed": (
                len(qualifying) >= config.minimum_passing_families
            ),
            "answer_stage_families": qualifying,
            "system_level_asr_requirement_evaluated": False,
            "gate_a_final_status": "pending_answer_stage",
        },
        "cost_ledger_path": str(config.cost_ledger_output_path),
    }
    atomic_write_json(config.output_path, result)
    csv_rows = [
        {
            **row,
            "ready_dataset_count": row.get("ready_dataset_count", ""),
            "eligible_for_family_gate": row.get("eligible_for_family_gate", ""),
            "passes_prompt_exposure_threshold": row.get(
                "passes_prompt_exposure_threshold", ""
            ),
        }
        for row in cell_rows + family_rows
    ]
    write_inferred_csv(config.csv_output_path, csv_rows)
    atomic_write_json(config.cost_ledger_output_path, cost_ledger)
    atomic_write_text(config.report_path, _render_report(result, cost_ledger))
    return result


def _rate_row(
    *,
    dataset: str,
    attack_family: str,
    attempted: int,
    index_included: int,
    retrieved: int,
    prompt_exposed: int,
) -> dict[str, Any]:
    low, high = wilson_interval(prompt_exposed, attempted)
    return {
        "dataset": dataset,
        "attack_family": attack_family,
        "attempted": attempted,
        "index_included": index_included,
        "index_inclusion_rate": index_included / attempted if attempted else 0.0,
        "retrieved": retrieved,
        "retrieval_rate": retrieved / attempted if attempted else 0.0,
        "prompt_exposed": prompt_exposed,
        "prompt_exposure_rate": prompt_exposed / attempted if attempted else 0.0,
        "prompt_exposure_wilson95_low": low,
        "prompt_exposure_wilson95_high": high,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _render_report(result: dict[str, Any], cost: dict[str, Any]) -> str:
    lines = [
        "# Stage48 Gate A Fixed-50 Context Exposure",
        "",
        result["denominator_policy"],
        "",
        "| Dataset | Attack | Prompt exposed | Rate | Wilson 95% CI |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in result["cell_rows"] + result["family_rows"]:
        lines.append(
            "| {dataset} | {attack_family} | {prompt_exposed}/{attempted} | "
            "{rate:.1%} | [{low:.1%}, {high:.1%}] |".format(
                **row,
                rate=row["prompt_exposure_rate"],
                low=row["prompt_exposure_wilson95_low"],
                high=row["prompt_exposure_wilson95_high"],
            )
        )
    gate = result["gate"]
    lines.extend(
        [
            "",
            f"Qualifying families: {', '.join(gate['qualifying_attack_families']) or 'none'}.",
            f"Context criterion passed: {gate['prompt_exposure_requirement_passed']}.",
            "System-level targeted ASR is not evaluated in this context-only report.",
            "",
            "## Cost",
            "",
            f"Stage48 cumulative exact logged/catalog cost: CNY {cost['stage48_cumulative_exact_logged_cny']:.6f}.",
            f"Stage48 cumulative conservative upper bound: CNY {cost['stage48_cumulative_upper_cny']:.6f}.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_from_config(GateAContextAnalysisConfig.from_yaml(args.config)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
