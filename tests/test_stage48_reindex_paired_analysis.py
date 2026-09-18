from pathlib import Path

from logicguard.evaluation.reindex_paired_analysis import (
    Stage48PairedAnalysisConfig,
    build_paired_summary,
)


def test_paired_summary_separates_attempted_and_exposed_denominators() -> None:
    rows = [
        _row("q1", target_exposed=True, targeted=True, attacked=False, clean=True),
        _row("q2", target_exposed=False, targeted=False, attacked=True, clean=True),
    ]
    summary = build_paired_summary(config=_config(), rows=rows)
    result = summary["overall_by_method"][0]

    assert result["attempted"] == 2
    assert result["target_exposed"] == 1
    assert result["targeted_asr_attempted"] == 0.5
    assert result["targeted_asr_given_target_exposed"] == 1.0
    assert result["attacked_accuracy"] == 0.5
    assert result["clean_accuracy"] == 1.0
    assert result["paired_accuracy_delta"] == -0.5


def _row(
    query_id: str,
    *,
    target_exposed: bool,
    targeted: bool,
    attacked: bool,
    clean: bool,
) -> dict[str, object]:
    return {
        "dataset": "toy",
        "attack_family": "natural_bridge",
        "query_id": query_id,
        "method": "full_query_guard",
        "defense_stage": "unprotected",
        "attack_source_exposed": target_exposed,
        "malicious_answer_exposed": target_exposed,
        "attacked_targeted_success": targeted,
        "attacked_correct": attacked,
        "clean_correct": clean,
        "attacked_abstained": False,
        "clean_abstained": False,
        "attack_recovered": False,
        "clean_risk_detected_source_count": 0,
        "clean_recovered_source_count": 0,
    }


def _config() -> Stage48PairedAnalysisConfig:
    root = Path(".").resolve()
    return Stage48PairedAnalysisConfig(
        pairs=[],
        paired_rows_output_path=root / "rows.jsonl",
        summary_output_path=root / "summary.json",
        cost_ledger_output_path=root / "cost.json",
        report_path=root / "report.md",
        clean_index_workspace_roots=[],
    )
