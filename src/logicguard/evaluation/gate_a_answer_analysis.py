"""Aggregate Stage48 Gate A answer results over evaluation-valid denominators."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import atomic_write_json, atomic_write_text, write_inferred_csv
from logicguard.evaluation.gate_a_context_analysis import wilson_interval


@dataclass(frozen=True, slots=True)
class GateAAnswerCell:
    dataset: str
    attack_family: str
    answer_summary_path: Path
    answer_cost_ledger_path: Path


@dataclass(frozen=True, slots=True)
class GateAAnswerAnalysisConfig:
    context_summary_path: Path
    context_cost_ledger_path: Path
    cells: tuple[GateAAnswerCell, ...]
    targeted_asr_threshold: float
    minimum_passing_families: int
    output_path: Path
    csv_output_path: Path
    cost_ledger_output_path: Path
    report_path: Path

    @classmethod
    def from_yaml(cls, path: Path) -> "GateAAnswerAnalysisConfig":
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

        return cls(
            context_summary_path=resolve(str(payload["context_summary_path"])),
            context_cost_ledger_path=resolve(str(payload["context_cost_ledger_path"])),
            cells=tuple(
                GateAAnswerCell(
                    dataset=str(row["dataset"]),
                    attack_family=str(row["attack_family"]),
                    answer_summary_path=resolve(str(row["answer_summary_path"])),
                    answer_cost_ledger_path=resolve(
                        str(row["answer_cost_ledger_path"])
                    ),
                )
                for row in payload["cells"]
            ),
            targeted_asr_threshold=float(payload.get("targeted_asr_threshold", 0.1)),
            minimum_passing_families=int(payload.get("minimum_passing_families", 2)),
            output_path=resolve(str(payload["output_path"])),
            csv_output_path=resolve(str(payload["csv_output_path"])),
            cost_ledger_output_path=resolve(str(payload["cost_ledger_output_path"])),
            report_path=resolve(str(payload["report_path"])),
        )


def run_from_config(config: GateAAnswerAnalysisConfig) -> dict[str, Any]:
    """Compute system-level ASR only for context-qualified attack families."""

    context = json.loads(config.context_summary_path.read_text(encoding="utf-8"))
    qualifying = set(context["gate"]["answer_stage_families"])
    context_attempted = {
        (str(row["dataset"]), str(row["attack_family"])): int(row["attempted"])
        for row in context["cell_rows"]
    }
    cell_rows: list[dict[str, Any]] = []
    answer_cost = 0.0
    seen: set[tuple[str, str]] = set()
    for cell in config.cells:
        key = (cell.dataset, cell.attack_family)
        if key in seen:
            raise ValueError(f"Duplicate Gate A answer cell: {key}")
        seen.add(key)
        if cell.attack_family not in qualifying:
            continue
        summary = json.loads(cell.answer_summary_path.read_text(encoding="utf-8"))
        funnel = summary["funnel"]
        attempted = int(funnel["attempted"])
        if attempted != context_attempted.get(key):
            raise ValueError(
                f"Answer/context attempted denominator mismatch for {key}: "
                f"{attempted} != {context_attempted.get(key)}"
            )
        cell_rows.append(
            _answer_rate_row(
                dataset=cell.dataset,
                attack_family=cell.attack_family,
                attempted=attempted,
                prompt_exposed=int(funnel["prompt_exposed"]),
                answer_generated=int(funnel["answer_generated"]),
                targeted_success=int(funnel["targeted_attack_success"]),
            )
        )
        answer_cost += float(
            json.loads(cell.answer_cost_ledger_path.read_text(encoding="utf-8"))[
                "catalog_cost_estimate_cny"
            ]
        )

    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "datasets": 0,
            "attempted": 0,
            "prompt_exposed": 0,
            "answer_generated": 0,
            "targeted_success": 0,
        }
    )
    for row in cell_rows:
        family = counts[str(row["attack_family"])]
        family["datasets"] += 1
        for field in (
            "attempted",
            "prompt_exposed",
            "answer_generated",
            "targeted_success",
        ):
            family[field] += int(row[field])

    family_rows: list[dict[str, Any]] = []
    passing: list[str] = []
    for attack_family, family in sorted(counts.items()):
        row = _answer_rate_row(
            dataset="pooled_ready_datasets",
            attack_family=attack_family,
            attempted=family["attempted"],
            prompt_exposed=family["prompt_exposed"],
            answer_generated=family["answer_generated"],
            targeted_success=family["targeted_success"],
        )
        row["ready_dataset_count"] = family["datasets"]
        row["passes_system_targeted_asr_threshold"] = (
            row["system_targeted_asr"] >= config.targeted_asr_threshold
        )
        if row["passes_system_targeted_asr_threshold"]:
            passing.append(attack_family)
        family_rows.append(row)

    context_cost = json.loads(
        config.context_cost_ledger_path.read_text(encoding="utf-8")
    )
    cost = {
        "schema_version": 1,
        "price_basis": context_cost["price_basis"],
        "context_cost_ledger": context_cost,
        "answer_catalog_cost_cny": round(answer_cost, 6),
        "gate_a_increment_exact_logged_cny": round(
            float(context_cost["gate_a_increment_exact_logged_cny"]) + answer_cost, 6
        ),
        "gate_a_increment_upper_cny": round(
            float(context_cost["gate_a_increment_upper_cny"]) + answer_cost, 6
        ),
        "stage48_cumulative_exact_logged_cny": round(
            float(context_cost["stage48_cumulative_exact_logged_cny"]) + answer_cost,
            6,
        ),
        "stage48_cumulative_upper_cny": round(
            float(context_cost["stage48_cumulative_upper_cny"]) + answer_cost, 6
        ),
        "credential_values_recorded": False,
    }
    context_pass = bool(context["gate"]["prompt_exposure_requirement_passed"])
    result = {
        "schema_version": 1,
        "experiment": "Stage48_GateA_fixed50_system_targeted_asr",
        "denominator_policy": (
            "System-level targeted ASR uses every evaluation-valid attempted case "
            "in each ready cell; non-exposed cases remain failures in the denominator."
        ),
        "interval_method": "two-sided_95_percent_Wilson_score",
        "context_qualifying_attack_families": sorted(qualifying),
        "cell_rows": cell_rows,
        "family_rows": family_rows,
        "gate": {
            "context_requirement_passed": context_pass,
            "targeted_asr_threshold": config.targeted_asr_threshold,
            "minimum_passing_families": config.minimum_passing_families,
            "system_asr_passing_attack_families": passing,
            "system_asr_requirement_passed": (
                len(passing) >= config.minimum_passing_families
            ),
            "gate_a_passed": bool(
                context_pass and len(passing) >= config.minimum_passing_families
            ),
        },
        "cost_ledger_path": str(config.cost_ledger_output_path),
    }
    atomic_write_json(config.output_path, result)
    csv_rows = [
        {
            **row,
            "ready_dataset_count": row.get("ready_dataset_count", ""),
            "passes_system_targeted_asr_threshold": row.get(
                "passes_system_targeted_asr_threshold", ""
            ),
        }
        for row in cell_rows + family_rows
    ]
    write_inferred_csv(config.csv_output_path, csv_rows)
    atomic_write_json(config.cost_ledger_output_path, cost)
    atomic_write_text(config.report_path, _render_report(result, cost))
    return result


def _answer_rate_row(
    *,
    dataset: str,
    attack_family: str,
    attempted: int,
    prompt_exposed: int,
    answer_generated: int,
    targeted_success: int,
) -> dict[str, Any]:
    low, high = wilson_interval(targeted_success, attempted)
    return {
        "dataset": dataset,
        "attack_family": attack_family,
        "attempted": attempted,
        "prompt_exposed": prompt_exposed,
        "answer_generated": answer_generated,
        "targeted_success": targeted_success,
        "system_targeted_asr": targeted_success / attempted if attempted else 0.0,
        "system_targeted_asr_wilson95_low": low,
        "system_targeted_asr_wilson95_high": high,
        "targeted_asr_given_prompt_exposed": (
            targeted_success / prompt_exposed if prompt_exposed else 0.0
        ),
    }


def _render_report(result: dict[str, Any], cost: dict[str, Any]) -> str:
    lines = [
        "# Stage48 Gate A Fixed-50 System Targeted ASR",
        "",
        result["denominator_policy"],
        "",
        "| Dataset | Attack | Prompt exposed | Targeted success | System ASR | Wilson 95% CI |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in result["cell_rows"] + result["family_rows"]:
        lines.append(
            "| {dataset} | {attack_family} | {prompt_exposed}/{attempted} | "
            "{targeted_success}/{attempted} | {rate:.1%} | [{low:.1%}, {high:.1%}] |".format(
                **row,
                rate=row["system_targeted_asr"],
                low=row["system_targeted_asr_wilson95_low"],
                high=row["system_targeted_asr_wilson95_high"],
            )
        )
    gate = result["gate"]
    lines.extend(
        [
            "",
            f"Context requirement passed: {gate['context_requirement_passed']}.",
            f"System ASR passing families: {', '.join(gate['system_asr_passing_attack_families']) or 'none'}.",
            f"Gate A passed: {gate['gate_a_passed']}.",
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
            run_from_config(GateAAnswerAnalysisConfig.from_yaml(args.config)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
