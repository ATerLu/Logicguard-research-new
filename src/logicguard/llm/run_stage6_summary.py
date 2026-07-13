"""Aggregate stage-6 multidataset LogicPoison answer-level judge results."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import yaml


LABELS = ("correct", "partial", "incorrect", "abstained", "judge_error")
CONTEXT_ORDER = {"clean": 0, "poisoned": 1, "guarded": 2, "recovered": 3}


@dataclass(frozen=True, slots=True)
class Stage6DatasetConfig:
    """One dataset entry in the stage-6 summary config."""

    name: str
    judged_results_path: Path


@dataclass(frozen=True, slots=True)
class Stage6SummaryConfig:
    """Configuration for stage-6 multidataset aggregation."""

    datasets: list[Stage6DatasetConfig]
    combined_jsonl_path: Path
    report_path: Path
    report_title: str = "LogicPoison 阶段6多数据集回答层综合报告"
    experiment_description: str = (
        "本报告聚合 2WikiMultiHopQA、HotpotQA 与 MuSiQue 的回答层 LLM + Judge 结果，"
        "用于判断 LogicGuard 在多个多跳问答数据集上是否稳定抵抗 LogicPoison。"
    )

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage6SummaryConfig":
        """Load project-relative YAML configuration."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        datasets = [
            Stage6DatasetConfig(
                name=str(item["name"]),
                judged_results_path=resolve_project_path(item["judged_results_path"]),
            )
            for item in payload["datasets"]
        ]
        return cls(
            datasets=datasets,
            combined_jsonl_path=resolve_project_path(payload["combined_jsonl_path"]),
            report_path=resolve_project_path(payload["report_path"]),
            report_title=str(payload.get("report_title", "LogicPoison 阶段6多数据集回答层综合报告")),
            experiment_description=str(
                payload.get(
                    "experiment_description",
                    "本报告聚合 2WikiMultiHopQA、HotpotQA 与 MuSiQue 的回答层 LLM + Judge 结果，"
                    "用于判断 LogicGuard 在多个多跳问答数据集上是否稳定抵抗 LogicPoison。",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class Stage6Summary:
    """Aggregated stage-6 metrics."""

    by_dataset_context: dict[tuple[str, str], dict[str, int]]
    by_dataset_model_context: dict[tuple[str, str, str], dict[str, int]]
    overall_by_context: dict[str, dict[str, int]]


def write_stage6_summary_outputs(config: Stage6SummaryConfig) -> list[dict[str, object]]:
    """Load all judged rows, write combined JSONL, and write the report."""

    rows = _load_stage6_rows(config.datasets)
    config.combined_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with config.combined_jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_stage6_report(config, rows)
    print(f"summary_rows={len(rows)}, datasets={len(config.datasets)}")
    return rows


def summarize_stage6_rows(rows: list[dict[str, object]]) -> Stage6Summary:
    """Summarize judged rows by dataset/context, model/context, and context."""

    by_dataset_context: dict[tuple[str, str], dict[str, int]] = {}
    by_dataset_model_context: dict[tuple[str, str, str], dict[str, int]] = {}
    overall_by_context: dict[str, dict[str, int]] = {}
    for row in rows:
        dataset = str(row["dataset"])
        model = str(row["model"])
        context = str(row["context_variant"])
        _add_label(by_dataset_context, (dataset, context), row)
        _add_label(by_dataset_model_context, (dataset, model, context), row)
        _add_label(overall_by_context, context, row)
    return Stage6Summary(
        by_dataset_context=by_dataset_context,
        by_dataset_model_context=by_dataset_model_context,
        overall_by_context=overall_by_context,
    )


def write_stage6_report(config: Stage6SummaryConfig, rows: list[dict[str, object]]) -> None:
    """Write a Chinese Markdown report for stage-6 multidataset results."""

    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize_stage6_rows(rows)
    overall_lines = _metrics_table(
        header_label="上下文条件",
        rows=[
            (context, metrics)
            for context, metrics in sorted(
                summary.overall_by_context.items(),
                key=lambda item: CONTEXT_ORDER.get(item[0], 99),
            )
        ],
    )
    dataset_lines = _metrics_table(
        header_label="数据集 / 上下文条件",
        rows=[
            (f"{dataset} / {context}", metrics)
            for (dataset, context), metrics in sorted(
                summary.by_dataset_context.items(),
                key=lambda item: (item[0][0], CONTEXT_ORDER.get(item[0][1], 99)),
            )
        ],
    )
    model_lines = _metrics_table(
        header_label="数据集 / 模型 / 上下文条件",
        rows=[
            (f"{dataset} / {model} / {context}", metrics)
            for (dataset, model, context), metrics in sorted(
                summary.by_dataset_model_context.items(),
                key=lambda item: (item[0][0], item[0][1], CONTEXT_ORDER.get(item[0][2], 99)),
            )
        ],
    )
    conclusion_lines = _comparison_lines(summary.overall_by_context)
    content = "\n".join(
        [
            f"# {config.report_title}",
            "",
            "## 实验目的",
            "",
            config.experiment_description,
            "",
            "## 指标说明",
            "",
            "- `正确率`：judge 判为 `correct` 的比例。",
            "- `部分正确率`：judge 判为 `partial` 的比例，表示答案相关但不完整或限定不足。",
            "- `Utility`：`correct + partial` 的比例，用于衡量回答可用性。",
            "- `UNKNOWN率`：judge 判为 `abstained` 的比例。",
            "- `错误非拒答率`：judge 判为 `incorrect` 的比例，可近似视作 answer-level ASR。",
            "- `judge错误率`：judge 调用或解析失败比例。",
            "",
            "## 跨数据集总体结果",
            "",
            *overall_lines,
            "",
            "## 按数据集结果",
            "",
            *dataset_lines,
            "",
            "## 按数据集和模型结果",
            "",
            *model_lines,
            "",
            "## 结果解读",
            "",
            *conclusion_lines,
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


def _load_stage6_rows(dataset_configs: list[Stage6DatasetConfig]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dataset_config in dataset_configs:
        for row in _load_jsonl(dataset_config.judged_results_path):
            enriched = dict(row)
            enriched["dataset"] = dataset_config.name
            rows.append(enriched)
    return rows


def _metrics_table(header_label: str, rows: list[tuple[str, dict[str, int]]]) -> list[str]:
    table = [
        f"| {header_label} | 调用数 | 正确率 | 部分正确率 | Utility | UNKNOWN率 | 错误非拒答率 | judge错误率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, metrics in rows:
        calls = metrics["calls"]
        correct_rate = _safe_rate(metrics["correct"], calls)
        partial_rate = _safe_rate(metrics["partial"], calls)
        utility = _safe_rate(metrics["correct"] + metrics["partial"], calls)
        table.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(calls),
                    f"{correct_rate:.4f}",
                    f"{partial_rate:.4f}",
                    f"{utility:.4f}",
                    f"{_safe_rate(metrics['abstained'], calls):.4f}",
                    f"{_safe_rate(metrics['incorrect'], calls):.4f}",
                    f"{_safe_rate(metrics['judge_error'], calls):.4f}",
                ]
            )
            + " |"
        )
    return table


def _comparison_lines(overall_by_context: dict[str, dict[str, int]]) -> list[str]:
    clean = overall_by_context.get("clean")
    poisoned = overall_by_context.get("poisoned")
    guarded = overall_by_context.get("guarded")
    recovered = overall_by_context.get("recovered")
    if not clean or not poisoned or not guarded or not recovered:
        return ["- 缺少 clean/poisoned/guarded/recovered 中的某些上下文，暂不能形成完整比较。"]

    poisoned_asr = _rate_for(poisoned, "incorrect")
    recovered_asr = _rate_for(recovered, "incorrect")
    guarded_unknown = _rate_for(guarded, "abstained")
    recovered_utility = _utility_rate(recovered)
    clean_utility = _utility_rate(clean)
    poisoned_utility = _utility_rate(poisoned)
    return [
        f"- LogicPoison 攻击效果：`poisoned` 的错误非拒答率为 {poisoned_asr:.4f}，Utility 为 {poisoned_utility:.4f}。",
        f"- 只过滤版本：`guarded` 的 UNKNOWN率为 {guarded_unknown:.4f}，可用于观察过滤导致的缺证问题。",
        f"- Recovery 效果：`recovered` 的错误非拒答率为 {recovered_asr:.4f}，Utility 为 {recovered_utility:.4f}；clean Utility 为 {clean_utility:.4f}。",
        "- 如果 recovered 同时降低错误非拒答率并接近 clean Utility，说明 LogicGuard 的过滤 + recovery 在回答层有效。",
    ]


def _add_label(container: dict[object, dict[str, int]], key: object, row: dict[str, object]) -> None:
    metrics = container.setdefault(
        key,
        {"calls": 0, "correct": 0, "partial": 0, "incorrect": 0, "abstained": 0, "judge_error": 0},
    )
    label = str(row.get("judge_label", "judge_error"))
    if label not in LABELS:
        label = "judge_error"
    metrics["calls"] += 1
    metrics[label] += 1


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _rate_for(metrics: dict[str, int], label: str) -> float:
    return _safe_rate(metrics[label], metrics["calls"])


def _utility_rate(metrics: dict[str, int]) -> float:
    return _safe_rate(metrics["correct"] + metrics["partial"], metrics["calls"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate stage-6 multidataset answer judge results.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_stage6_summary.yaml"),
        help="Path to the stage-6 summary YAML config.",
    )
    args = parser.parse_args()
    write_stage6_summary_outputs(Stage6SummaryConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
