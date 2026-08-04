import json
from pathlib import Path

from logicguard.llm.merge_stage8_recovery import (
    Stage8MergeConfig,
    Stage8MergeDatasetConfig,
    merge_stage8_recovery_outputs,
)


def test_merge_stage8_recovery_replaces_only_recovered_rows(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline_judged.jsonl"
    recovered_path = tmp_path / "stage8_recovered_judged.jsonl"
    merged_path = tmp_path / "merged_judged.jsonl"
    combined_path = tmp_path / "combined.jsonl"
    report_path = tmp_path / "report.md"

    _write_jsonl(
        baseline_path,
        [
            _row("clean", "correct"),
            _row("poisoned", "incorrect"),
            _row("guarded", "abstained"),
            _row("recovered", "correct", answer="oracle recovered"),
        ],
    )
    _write_jsonl(
        recovered_path, [_row("recovered", "partial", answer="non oracle recovered")]
    )

    config = Stage8MergeConfig(
        datasets=[
            Stage8MergeDatasetConfig(
                name="demo",
                baseline_judged_path=baseline_path,
                recovered_judged_path=recovered_path,
                merged_output_path=merged_path,
            )
        ],
        combined_jsonl_path=combined_path,
        report_path=report_path,
        report_title="阶段8测试报告",
        experiment_description="阶段8测试说明。",
    )

    rows = merge_stage8_recovery_outputs(config)
    merged_rows = [
        json.loads(line)
        for line in merged_path.read_text(encoding="utf-8").splitlines()
    ]
    report = report_path.read_text(encoding="utf-8")

    assert [row["context_variant"] for row in merged_rows] == [
        "clean",
        "poisoned",
        "guarded",
        "recovered",
    ]
    assert merged_rows[-1]["generated_answer"] == "non oracle recovered"
    assert rows[-1]["dataset"] == "demo"
    assert "阶段8测试报告" in report
    assert "阶段8测试说明。" in report


def _row(
    context_variant: str, judge_label: str, answer: str = "answer"
) -> dict[str, object]:
    return {
        "model": "m1",
        "context_variant": context_variant,
        "query_id": "q1",
        "question": "Question?",
        "gold_answer": "Gold",
        "generated_answer": answer,
        "judge_label": judge_label,
        "judge_reason": "reason",
        "judge_model": "judge",
        "judge_total_tokens": 0,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8"
    )
