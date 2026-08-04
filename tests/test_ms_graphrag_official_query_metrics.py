import csv
from pathlib import Path

from logicguard.ms_graphrag.official_query_metrics import (
    OfficialQueryMetricRow,
    summarize_defense_results,
    write_metric_artifacts,
)


def test_summarize_defense_results_groups_by_model_and_variant() -> None:
    rows = [
        _result(
            "deepseek-v4-flash",
            "poisoned",
            correct=False,
            abstained=False,
            incorrect=True,
            changed=1,
            recovered=0,
        ),
        _result(
            "deepseek-v4-flash",
            "poisoned",
            correct=False,
            abstained=True,
            incorrect=False,
            changed=0,
            recovered=0,
        ),
        _result(
            "deepseek-v4-flash",
            "recovered",
            correct=True,
            abstained=False,
            incorrect=False,
            changed=0,
            recovered=1,
        ),
    ]

    metrics = summarize_defense_results(rows)
    by_variant = {(row.model, row.variant): row for row in metrics}

    poisoned = by_variant[("deepseek-v4-flash", "poisoned")]
    recovered = by_variant[("deepseek-v4-flash", "recovered")]

    assert poisoned.calls == 2
    assert poisoned.correct_rate == 0.0
    assert poisoned.abstain_rate == 0.5
    assert poisoned.incorrect_non_abstain_rate == 0.5
    assert poisoned.avg_changed_doc_count == 0.5
    assert recovered.calls == 1
    assert recovered.correct_rate == 1.0
    assert recovered.avg_recovered_doc_count == 1.0


def test_write_metric_artifacts_outputs_csv_and_chinese_report(tmp_path: Path) -> None:
    metrics = [
        OfficialQueryMetricRow(
            model="deepseek-v4-flash",
            variant="recovered",
            calls=2,
            correct_count=2,
            abstained_count=0,
            incorrect_non_abstain_count=0,
            correct_rate=1.0,
            abstain_rate=0.0,
            incorrect_non_abstain_rate=0.0,
            avg_changed_doc_count=0.0,
            avg_recovered_doc_count=1.0,
        )
    ]
    csv_path = tmp_path / "metrics.csv"
    report_path = tmp_path / "report.md"

    write_metric_artifacts(
        csv_path=csv_path,
        report_path=report_path,
        metrics=metrics,
        source_results_path=Path("outputs/results.jsonl"),
        source_context_path=Path("outputs/contexts.jsonl"),
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        saved_rows = list(csv.DictReader(handle))
    report = report_path.read_text(encoding="utf-8")

    assert saved_rows[0]["variant"] == "recovered"
    assert saved_rows[0]["correct_rate"] == "1.0000"
    assert "指标说明" in report
    assert "错误非拒答率" in report
    assert "outputs/results.jsonl" in report


def _result(
    model: str,
    variant: str,
    *,
    correct: bool,
    abstained: bool,
    incorrect: bool,
    changed: int,
    recovered: int,
) -> dict[str, object]:
    return {
        "dataset": "toy",
        "model": model,
        "query_id": "q1",
        "query": "Who?",
        "expected_answer": "Alice",
        "variant": variant,
        "generated_answer": "Alice"
        if correct
        else "UNKNOWN"
        if abstained
        else "Mallory",
        "is_correct": correct,
        "is_abstained": abstained,
        "is_incorrect": incorrect,
        "changed_doc_count": changed,
        "recovered_doc_count": recovered,
        "evidence_doc_ids": ["d1"],
        "evidence_text_unit_ids": ["u1"],
        "latency_seconds": 0.1,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "error": None,
    }
