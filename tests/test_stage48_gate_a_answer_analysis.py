from __future__ import annotations

import json
from pathlib import Path

import yaml

from logicguard.evaluation.gate_a_answer_analysis import (
    GateAAnswerAnalysisConfig,
    run_from_config,
)


def test_answer_analysis_keeps_non_exposed_cases_in_system_denominator(
    tmp_path: Path,
) -> None:
    context_summary = tmp_path / "context.json"
    context_summary.write_text(
        json.dumps(
            {
                "cell_rows": [
                    {
                        "dataset": dataset,
                        "attack_family": "natural_bridge",
                        "attempted": 10,
                    }
                    for dataset in ("d1", "d2")
                ],
                "gate": {
                    "answer_stage_families": ["natural_bridge"],
                    "prompt_exposure_requirement_passed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    context_cost = tmp_path / "context_cost.json"
    context_cost.write_text(
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
    for dataset, exposed, success in (("d1", 3, 2), ("d2", 2, 1)):
        summary = tmp_path / f"{dataset}_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "funnel": {
                        "attempted": 10,
                        "prompt_exposed": exposed,
                        "answer_generated": exposed,
                        "targeted_attack_success": success,
                    }
                }
            ),
            encoding="utf-8",
        )
        cost = tmp_path / f"{dataset}_cost.json"
        cost.write_text(
            json.dumps({"catalog_cost_estimate_cny": 0.2}), encoding="utf-8"
        )
        cells.append(
            {
                "dataset": dataset,
                "attack_family": "natural_bridge",
                "answer_summary_path": str(summary),
                "answer_cost_ledger_path": str(cost),
            }
        )
    payload = {
        "context_summary_path": str(context_summary),
        "context_cost_ledger_path": str(context_cost),
        "targeted_asr_threshold": 0.1,
        "minimum_passing_families": 1,
        "cells": cells,
        "output_path": str(tmp_path / "out.json"),
        "csv_output_path": str(tmp_path / "out.csv"),
        "cost_ledger_output_path": str(tmp_path / "out_cost.json"),
        "report_path": str(tmp_path / "report.md"),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = run_from_config(GateAAnswerAnalysisConfig.from_yaml(config_path))

    family = result["family_rows"][0]
    assert family["attempted"] == 20
    assert family["prompt_exposed"] == 5
    assert family["targeted_success"] == 3
    assert family["system_targeted_asr"] == 0.15
    assert family["targeted_asr_given_prompt_exposed"] == 0.6
    assert result["gate"]["gate_a_passed"] is True
