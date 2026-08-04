import json
from pathlib import Path

from logicguard.llm.run_stage6_summary import (
    Stage6DatasetConfig,
    Stage6SummaryConfig,
    summarize_stage6_rows,
    write_stage6_summary_outputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_stage6_summary.yaml"


def test_stage6_summary_config_resolves_dataset_paths() -> None:
    config = Stage6SummaryConfig.from_yaml(CONFIG_PATH)

    assert [dataset.name for dataset in config.datasets] == [
        "2wikimultihopqa",
        "hotpotqa",
        "musique",
    ]
    assert config.report_title == "LogicPoison 阶段6多数据集回答层综合报告"
    assert (
        config.report_path
        == PROJECT_ROOT
        / "outputs"
        / "reports"
        / "LogicPoison阶段6多数据集回答层综合报告.md"
    )
    assert config.combined_jsonl_path == (
        PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "logicpoison_answer"
        / "stage6_multidataset_judged_results.jsonl"
    )
    assert config.datasets[1].judged_results_path == (
        PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "logicpoison_answer"
        / "hotpotqa"
        / "stage6_pilot_20"
        / "answer_judged_results.jsonl"
    )


def test_stage_summary_config_can_customize_report_title(tmp_path: Path) -> None:
    config_path = tmp_path / "stage7.yaml"
    judged_path = tmp_path / "judged.jsonl"
    config_path.write_text(
        "\n".join(
            [
                "report_title: LogicPoison 阶段7 Graph Surrogate回答层综合报告",
                "experiment_description: graph surrogate description",
                "datasets:",
                "  - name: demo",
                f"    judged_results_path: {judged_path}",
                f"combined_jsonl_path: {tmp_path / 'combined.jsonl'}",
                f"report_path: {tmp_path / 'report.md'}",
            ]
        ),
        encoding="utf-8",
    )

    config = Stage6SummaryConfig.from_yaml(config_path)

    assert config.report_title == "LogicPoison 阶段7 Graph Surrogate回答层综合报告"
    assert config.experiment_description == "graph surrogate description"


def test_summarize_stage6_rows_groups_by_dataset_and_context() -> None:
    rows = [
        _row("2wiki", "m1", "clean", "correct"),
        _row("2wiki", "m1", "clean", "partial"),
        _row("2wiki", "m1", "poisoned", "incorrect"),
        _row("hotpot", "m1", "poisoned", "abstained"),
        _row("hotpot", "m2", "recovered", "correct"),
    ]

    summary = summarize_stage6_rows(rows)

    assert summary.by_dataset_context[("2wiki", "clean")] == {
        "calls": 2,
        "correct": 1,
        "partial": 1,
        "incorrect": 0,
        "abstained": 0,
        "judge_error": 0,
    }
    assert summary.by_dataset_context[("2wiki", "poisoned")]["incorrect"] == 1
    assert summary.by_dataset_context[("hotpot", "poisoned")]["abstained"] == 1
    assert summary.overall_by_context["clean"]["calls"] == 2
    assert summary.overall_by_context["poisoned"]["calls"] == 2
    assert summary.overall_by_context["recovered"]["correct"] == 1


def test_write_stage6_summary_outputs_writes_combined_jsonl_and_chinese_report(
    tmp_path: Path,
) -> None:
    dataset_path = tmp_path / "2wiki_judged.jsonl"
    dataset_rows = [
        _row("placeholder", "m1", "clean", "correct"),
        _row("placeholder", "m1", "poisoned", "incorrect"),
        _row("placeholder", "m1", "recovered", "correct"),
    ]
    dataset_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in dataset_rows),
        encoding="utf-8",
    )
    config = Stage6SummaryConfig(
        datasets=[Stage6DatasetConfig(name="2wiki", judged_results_path=dataset_path)],
        combined_jsonl_path=tmp_path / "combined.jsonl",
        report_path=tmp_path / "report.md",
        report_title="LogicPoison 阶段7 Graph Surrogate回答层综合报告",
        experiment_description="阶段7测试说明。",
    )

    rows = write_stage6_summary_outputs(config)

    combined_rows = [
        json.loads(line)
        for line in config.combined_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    report = config.report_path.read_text(encoding="utf-8")

    assert len(rows) == 3
    assert {row["dataset"] for row in combined_rows} == {"2wiki"}
    assert "LogicPoison 阶段7 Graph Surrogate回答层综合报告" in report
    assert "阶段7测试说明。" in report
    assert "跨数据集总体结果" in report
    assert "按数据集结果" in report


def _row(dataset: str, model: str, context: str, label: str) -> dict[str, object]:
    return {
        "dataset": dataset,
        "model": model,
        "context_variant": context,
        "query_id": "q1",
        "question": "Question?",
        "gold_answer": "Gold",
        "generated_answer": "Gold" if label == "correct" else "Wrong",
        "judge_label": label,
        "judge_reason": "reason",
        "judge_total_tokens": 0,
    }
