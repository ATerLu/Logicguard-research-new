from __future__ import annotations

import json
from pathlib import Path

import yaml

from logicguard.evaluation.gate_a_context_analysis import (
    GateAContextAnalysisConfig,
    run_from_config,
    wilson_interval,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_wilson_interval_known_boundary() -> None:
    low, high = wilson_interval(2, 10)
    assert round(low, 6) == 0.056682
    assert round(high, 6) == 0.509838


def test_gate_a_context_analysis_uses_fixed_attempted_denominator(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "dataset,attack_family,gate_cell_ready\n"
        "d1,natural_bridge,True\n"
        "d2,natural_bridge,True\n"
        "d1,candidate_collision,False\n",
        encoding="utf-8",
    )
    fixed_cost = tmp_path / "fixed_cost.json"
    fixed_cost.write_text(
        json.dumps(
            {
                "price_basis": "test",
                "gate_a_increment_exact_logged_cny": 1.0,
                "gate_a_increment_upper_cny": 1.1,
                "stage48_cumulative_exact_logged_cny": 2.0,
                "stage48_cumulative_upper_cny": 2.1,
            }
        ),
        encoding="utf-8",
    )
    cells = []
    for dataset, exposed in (("d1", 2), ("d2", 3)):
        exposure = tmp_path / f"{dataset}.jsonl"
        _write_jsonl(
            exposure,
            [
                {
                    "dataset": dataset,
                    "attack_family": "natural_bridge",
                    "index_document_included": True,
                    "index_text_unit_included": True,
                    "retrieved": index < 4,
                    "prompt_source_exposed": index < exposed,
                    "prompt_target_exposed": index < exposed,
                }
                for index in range(10)
            ],
        )
        summary = tmp_path / f"{dataset}_summary.json"
        summary.write_text(
            json.dumps({"catalog_cost_estimate_cny": 0.25}), encoding="utf-8"
        )
        cells.append(
            {
                "dataset": dataset,
                "attack_family": "natural_bridge",
                "exposure_path": str(exposure),
                "summary_path": str(summary),
            }
        )
    payload = {
        "inventory_summary_path": str(inventory),
        "fixed50_cost_ledger_path": str(fixed_cost),
        "target_per_cell": 10,
        "minimum_ready_datasets_per_family": 2,
        "prompt_exposure_threshold": 0.2,
        "minimum_passing_families": 1,
        "cells": cells,
        "output_path": str(tmp_path / "out.json"),
        "csv_output_path": str(tmp_path / "out.csv"),
        "cost_ledger_output_path": str(tmp_path / "cost.json"),
        "report_path": str(tmp_path / "report.md"),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = run_from_config(GateAContextAnalysisConfig.from_yaml(config_path))

    family = result["family_rows"][0]
    assert family["attempted"] == 20
    assert family["prompt_exposed"] == 5
    assert family["prompt_exposure_rate"] == 0.25
    assert result["gate"]["qualifying_attack_families"] == ["natural_bridge"]
    assert result["gate"]["prompt_exposure_requirement_passed"] is True
    assert (
        result["incomplete_inventory_cells"][0]["attack_family"]
        == "candidate_collision"
    )
