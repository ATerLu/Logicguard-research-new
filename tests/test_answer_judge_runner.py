import json
from pathlib import Path

from logicguard.llm.run_answer_judge import AnswerJudgeRunConfig, _write_judged_outputs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_answer_judge_stage5.yaml"


def test_answer_judge_run_config_resolves_paths() -> None:
    config = AnswerJudgeRunConfig.from_yaml(CONFIG_PATH)

    assert config.judge_model == "qwen3.7-plus"
    assert config.input_results_path == (
        PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "logicpoison_answer"
        / "2wikimultihopqa"
        / "stage5_pilot_10"
        / "answer_results.jsonl"
    )
    assert config.output_results_path == (
        PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "logicpoison_answer"
        / "2wikimultihopqa"
        / "stage5_pilot_10"
        / "answer_judged_results.jsonl"
    )
    assert (
        config.report_path
        == PROJECT_ROOT
        / "outputs"
        / "reports"
        / "LogicPoison回答层Judge扩大实验报告.md"
    )


def test_write_judged_outputs_writes_jsonl_csv_and_chinese_report(
    tmp_path: Path,
) -> None:
    config = AnswerJudgeRunConfig(
        api_key_env="KEY",
        base_url_env="BASE",
        judge_model="judge-model",
        input_results_path=tmp_path / "answer_results.jsonl",
        output_results_path=tmp_path / "answer_judged_results.jsonl",
        output_csv_path=tmp_path / "answer_judged_results.csv",
        report_path=tmp_path / "report.md",
        temperature=0.0,
        max_tokens=96,
        timeout_seconds=30,
    )
    rows = [
        {
            "model": "m1",
            "context_variant": "clean",
            "query_id": "q1",
            "question": "Question?",
            "gold_answer": "Gold",
            "generated_answer": "Gold",
            "judge_label": "correct",
            "judge_reason": "local",
            "judge_model": "judge-model",
            "judge_total_tokens": 0,
            "judge_error": None,
        },
        {
            "model": "m1",
            "context_variant": "poisoned",
            "query_id": "q1",
            "question": "Question?",
            "gold_answer": "Gold",
            "generated_answer": "Wrong",
            "judge_label": "incorrect",
            "judge_reason": "wrong",
            "judge_model": "judge-model",
            "judge_total_tokens": 12,
            "judge_error": None,
        },
    ]

    _write_judged_outputs(config, rows)

    written_rows = [
        json.loads(line)
        for line in config.output_results_path.read_text(encoding="utf-8").splitlines()
    ]
    report = config.report_path.read_text(encoding="utf-8")

    assert written_rows == rows
    assert config.output_csv_path.exists()
    assert "LogicPoison 回答层 Judge 判分报告" in report
    assert "跨模型总体结果" in report
    assert "正确率" in report
    assert "错误非拒答率" in report
