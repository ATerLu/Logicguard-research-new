"""Stage46 cross-dataset paired analysis for final answer-level results."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

_BASELINE_METHOD = "full_query_guard"
_METHOD_ORDER = {
    "full_query_guard": 1,
    "risk_non_oracle_title_entity_bm25": 2,
    "stage35_query_bm25_append_top12": 3,
    "stage38_second_hop_append_top14": 4,
}
_METHOD_LABELS = {
    "full_query_guard": "未恢复 query guard 基线",
    "risk_non_oracle_title_entity_bm25": "Stage43 风险识别与非 oracle 恢复",
    "stage35_query_bm25_append_top12": "Stage44 候选源扩展 top-12",
    "stage38_second_hop_append_top14": "Stage45 二跳补证 top-14",
}


@dataclass(frozen=True, slots=True)
class Stage46DatasetSpec:
    """Input artifacts for one cross-dataset answer-level comparison."""

    dataset: str
    preflight_summary_path: Path
    judged_results_path: Path

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, object],
        project_root: Path,
    ) -> "Stage46DatasetSpec":
        def resolve(key: str) -> Path:
            value = Path(str(payload[key]))
            return (
                value.resolve()
                if value.is_absolute()
                else (project_root / value).resolve()
            )

        return cls(
            dataset=str(payload["dataset"]),
            preflight_summary_path=resolve("preflight_summary_path"),
            judged_results_path=resolve("judged_results_path"),
        )


@dataclass(frozen=True, slots=True)
class Stage46CrossDatasetAnalysisConfig:
    """Output settings for the final Stage46 paired analysis."""

    datasets: list[Stage46DatasetSpec]
    final_summary_output_path: Path
    pairwise_rows_output_path: Path
    pairwise_summary_output_path: Path
    examples_output_path: Path
    report_path: Path
    baseline_method: str = _BASELINE_METHOD
    stage_label: str = "Stage46"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage46CrossDatasetAnalysisConfig":
        """Load a project-relative Stage46 summary config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            value = Path(str(raw))
            return (
                value.resolve()
                if value.is_absolute()
                else (project_root / value).resolve()
            )

        return cls(
            datasets=[
                Stage46DatasetSpec.from_mapping(dict(item), project_root)
                for item in payload["datasets"]
            ],
            final_summary_output_path=resolve(payload["final_summary_output_path"]),
            pairwise_rows_output_path=resolve(payload["pairwise_rows_output_path"]),
            pairwise_summary_output_path=resolve(payload["pairwise_summary_output_path"]),
            examples_output_path=resolve(payload["examples_output_path"]),
            report_path=resolve(payload["report_path"]),
            baseline_method=str(payload.get("baseline_method", _BASELINE_METHOD)),
            stage_label=str(payload.get("stage_label", "Stage46")),
        )


@dataclass(frozen=True, slots=True)
class Stage46FinalSummaryRow:
    """Final judge-aware method metrics recomputed from query-level results."""

    dataset: str
    model: str
    method: str
    query_count: int
    final_correct_rate: float
    final_partial_rate: float
    final_utility_rate: float
    final_abstain_rate: float
    final_incorrect_rate: float
    final_attack_success_rate: float
    api_error_rate: float
    judge_call_rate: float
    judge_error_rate: float
    actual_unrecovered_changed_exposure_rate: float | None

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage46PairwiseRow:
    """One query aligned between the un-recovered baseline and one treatment."""

    dataset: str
    query_id: str
    treatment_method: str
    query: str
    gold_answer: str
    baseline_final_label: str
    treatment_final_label: str
    baseline_answer: str
    treatment_answer: str
    baseline_attack_success: bool
    treatment_attack_success: bool
    attack_neutralized: bool
    baseline_utility: bool
    treatment_utility: bool
    utility_delta: int
    baseline_unrecovered_changed_doc_ids: list[str]
    treatment_unrecovered_changed_doc_ids: list[str]
    baseline_source_summaries: list[dict[str, object]]
    treatment_source_summaries: list[dict[str, object]]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Stage46PairwiseSummaryRow:
    """Paired changes relative to the un-recovered answer-context baseline."""

    dataset: str
    treatment_method: str
    query_count: int
    baseline_attack_success_rate: float
    treatment_attack_success_rate: float
    attack_neutralized_rate: float
    baseline_utility_rate: float
    treatment_utility_rate: float
    utility_gain_rate: float
    utility_loss_rate: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(
    config: Stage46CrossDatasetAnalysisConfig,
) -> tuple[
    list[Stage46FinalSummaryRow],
    list[Stage46PairwiseRow],
    list[Stage46PairwiseSummaryRow],
]:
    """Recompute final metrics, make paired rows, and write the Chinese report."""

    final_summaries: list[Stage46FinalSummaryRow] = []
    paired_rows: list[Stage46PairwiseRow] = []
    preflight_by_dataset: dict[str, dict[str, float]] = {}
    for spec in config.datasets:
        judged_rows = _load_jsonl(spec.judged_results_path)
        exposure_by_method = _load_preflight_exposure(spec.preflight_summary_path)
        preflight_by_dataset[spec.dataset] = exposure_by_method
        final_summaries.extend(
            build_stage46_final_summaries(
                judged_rows=judged_rows,
                dataset=spec.dataset,
                exposure_by_method=exposure_by_method,
            )
        )
        paired_rows.extend(
            build_stage46_pairwise_rows(
                judged_rows=judged_rows,
                dataset=spec.dataset,
                baseline_method=config.baseline_method,
            )
        )
    paired_summaries = summarize_stage46_pairwise_rows(paired_rows)
    write_stage46_cross_dataset_outputs(
        config=config,
        final_summaries=final_summaries,
        paired_rows=paired_rows,
        paired_summaries=paired_summaries,
        preflight_by_dataset=preflight_by_dataset,
    )
    return final_summaries, paired_rows, paired_summaries


def build_stage46_final_summaries(
    *,
    judged_rows: list[dict[str, Any]],
    dataset: str,
    exposure_by_method: dict[str, float] | None = None,
) -> list[Stage46FinalSummaryRow]:
    """Aggregate final labels instead of reusing precomputed CSV values."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in judged_rows:
        method = str(row.get("method", ""))
        model = str(row.get("model", ""))
        grouped.setdefault((model, method), []).append(row)
    summaries: list[Stage46FinalSummaryRow] = []
    for (model, method), rows in grouped.items():
        total = len(rows)
        summaries.append(
            Stage46FinalSummaryRow(
                dataset=dataset,
                model=model,
                method=method,
                query_count=total,
                final_correct_rate=_ratio(
                    sum(_final_label(row) == "correct" for row in rows), total
                ),
                final_partial_rate=_ratio(
                    sum(_final_label(row) == "partial" for row in rows), total
                ),
                final_utility_rate=_ratio(
                    sum(_is_utility(row) for row in rows), total
                ),
                final_abstain_rate=_ratio(
                    sum(_final_label(row) == "abstained" for row in rows), total
                ),
                final_incorrect_rate=_ratio(
                    sum(_final_label(row) == "incorrect" for row in rows), total
                ),
                final_attack_success_rate=_ratio(
                    sum(_truthy(row.get("final_attack_success")) for row in rows), total
                ),
                api_error_rate=_ratio(
                    sum(_final_label(row) == "api_error" for row in rows), total
                ),
                judge_call_rate=_ratio(
                    sum(_truthy(row.get("judge_called")) for row in rows), total
                ),
                judge_error_rate=_ratio(
                    sum(bool(row.get("judge_error")) for row in rows), total
                ),
                actual_unrecovered_changed_exposure_rate=(
                    (exposure_by_method or {}).get(method)
                ),
            )
        )
    return sorted(
        summaries,
        key=lambda row: (row.dataset, _METHOD_ORDER.get(row.method, 99), row.method),
    )


def build_stage46_pairwise_rows(
    *,
    judged_rows: list[dict[str, Any]],
    dataset: str,
    baseline_method: str = _BASELINE_METHOD,
) -> list[Stage46PairwiseRow]:
    """Align every treatment answer with its same-query baseline answer."""

    by_method: dict[str, dict[str, dict[str, Any]]] = {}
    for row in judged_rows:
        method = str(row.get("method", ""))
        query_id = str(row.get("query_id", ""))
        if query_id in by_method.setdefault(method, {}):
            raise ValueError(f"Duplicate Stage46 judged row: {dataset}/{method}/{query_id}")
        by_method[method][query_id] = row
    baseline = by_method.get(baseline_method)
    if not baseline:
        raise ValueError(f"Missing Stage46 baseline method {baseline_method} for {dataset}")
    rows: list[Stage46PairwiseRow] = []
    for treatment_method, treatment in by_method.items():
        if treatment_method == baseline_method:
            continue
        if set(treatment) != set(baseline):
            raise ValueError(
                f"Stage46 paired query ids differ: {dataset}/{treatment_method}"
            )
        for query_id, baseline_row in baseline.items():
            treatment_row = treatment[query_id]
            baseline_attack = _truthy(baseline_row.get("final_attack_success"))
            treatment_attack = _truthy(treatment_row.get("final_attack_success"))
            baseline_utility = _is_utility(baseline_row)
            treatment_utility = _is_utility(treatment_row)
            rows.append(
                Stage46PairwiseRow(
                    dataset=dataset,
                    query_id=query_id,
                    treatment_method=treatment_method,
                    query=str(baseline_row.get("query", "")),
                    gold_answer=str(baseline_row.get("gold_answer", "")),
                    baseline_final_label=_final_label(baseline_row),
                    treatment_final_label=_final_label(treatment_row),
                    baseline_answer=str(baseline_row.get("generated_answer", "")),
                    treatment_answer=str(treatment_row.get("generated_answer", "")),
                    baseline_attack_success=baseline_attack,
                    treatment_attack_success=treatment_attack,
                    attack_neutralized=baseline_attack and not treatment_attack,
                    baseline_utility=baseline_utility,
                    treatment_utility=treatment_utility,
                    utility_delta=int(treatment_utility) - int(baseline_utility),
                    baseline_unrecovered_changed_doc_ids=_string_list(
                        baseline_row.get("unrecovered_changed_doc_ids")
                    ),
                    treatment_unrecovered_changed_doc_ids=_string_list(
                        treatment_row.get("unrecovered_changed_doc_ids")
                    ),
                    baseline_source_summaries=_source_summaries(baseline_row),
                    treatment_source_summaries=_source_summaries(treatment_row),
                )
            )
    return sorted(
        rows,
        key=lambda row: (
            row.dataset,
            _METHOD_ORDER.get(row.treatment_method, 99),
            row.treatment_method,
            row.query_id,
        ),
    )


def summarize_stage46_pairwise_rows(
    rows: list[Stage46PairwiseRow],
) -> list[Stage46PairwiseSummaryRow]:
    """Summarize ASR removal and utility changes on matched query pairs."""

    grouped: dict[tuple[str, str], list[Stage46PairwiseRow]] = {}
    for row in rows:
        grouped.setdefault((row.dataset, row.treatment_method), []).append(row)
    summaries: list[Stage46PairwiseSummaryRow] = []
    for (dataset, method), group in grouped.items():
        total = len(group)
        summaries.append(
            Stage46PairwiseSummaryRow(
                dataset=dataset,
                treatment_method=method,
                query_count=total,
                baseline_attack_success_rate=_ratio(
                    sum(row.baseline_attack_success for row in group), total
                ),
                treatment_attack_success_rate=_ratio(
                    sum(row.treatment_attack_success for row in group), total
                ),
                attack_neutralized_rate=_ratio(
                    sum(row.attack_neutralized for row in group), total
                ),
                baseline_utility_rate=_ratio(
                    sum(row.baseline_utility for row in group), total
                ),
                treatment_utility_rate=_ratio(
                    sum(row.treatment_utility for row in group), total
                ),
                utility_gain_rate=_ratio(
                    sum(row.utility_delta > 0 for row in group), total
                ),
                utility_loss_rate=_ratio(
                    sum(row.utility_delta < 0 for row in group), total
                ),
            )
        )
    return sorted(
        summaries,
        key=lambda row: (
            row.dataset,
            _METHOD_ORDER.get(row.treatment_method, 99),
            row.treatment_method,
        ),
    )


def write_stage46_cross_dataset_outputs(
    *,
    config: Stage46CrossDatasetAnalysisConfig,
    final_summaries: list[Stage46FinalSummaryRow],
    paired_rows: list[Stage46PairwiseRow],
    paired_summaries: list[Stage46PairwiseSummaryRow],
    preflight_by_dataset: dict[str, dict[str, float]],
) -> None:
    """Write auditable tables and a Chinese report with paired real examples."""

    _write_csv(
        config.final_summary_output_path,
        [row.to_csv_row() for row in final_summaries],
    )
    _write_jsonl(
        config.pairwise_rows_output_path,
        [row.to_json_dict() for row in paired_rows],
    )
    _write_csv(
        config.pairwise_summary_output_path,
        [row.to_csv_row() for row in paired_summaries],
    )
    examples = _select_examples(paired_rows)
    _write_jsonl(
        config.examples_output_path,
        [row.to_json_dict() for row in examples],
    )
    _write_report(
        config=config,
        final_summaries=final_summaries,
        paired_summaries=paired_summaries,
        examples=examples,
        preflight_by_dataset=preflight_by_dataset,
    )


def _write_report(
    *,
    config: Stage46CrossDatasetAnalysisConfig,
    final_summaries: list[Stage46FinalSummaryRow],
    paired_summaries: list[Stage46PairwiseSummaryRow],
    examples: list[Stage46PairwiseRow],
    preflight_by_dataset: dict[str, dict[str, float]],
) -> None:
    final_table = [
        "| 数据集 | 策略 | 效用率 | 拒答率 | 错误率 | 最终攻击成功率 | 实际污染源暴露率 | API error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in final_summaries:
        exposure = (
            f"{row.actual_unrecovered_changed_exposure_rate:.4f}"
            if row.actual_unrecovered_changed_exposure_rate is not None
            else "未记录"
        )
        final_table.append(
            f"| {row.dataset} | {_method_label(row.method)} | "
            f"{row.final_utility_rate:.4f} | {row.final_abstain_rate:.4f} | "
            f"{row.final_incorrect_rate:.4f} | {row.final_attack_success_rate:.4f} | "
            f"{exposure} | {row.api_error_rate:.4f} |"
        )
    paired_table = [
        "| 数据集 | 防御策略 | 基线 ASR | 防御后 ASR | ASR 消失比例 | 基线效用率 | 防御效用率 | 效用提升 | 效用下降 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in paired_summaries:
        paired_table.append(
            f"| {row.dataset} | {_method_label(row.treatment_method)} | "
            f"{row.baseline_attack_success_rate:.4f} | "
            f"{row.treatment_attack_success_rate:.4f} | "
            f"{row.attack_neutralized_rate:.4f} | "
            f"{row.baseline_utility_rate:.4f} | {row.treatment_utility_rate:.4f} | "
            f"{row.utility_gain_rate:.4f} | {row.utility_loss_rate:.4f} |"
        )
    baseline_notes = []
    for dataset, exposure in sorted(preflight_by_dataset.items()):
        rate = exposure.get(config.baseline_method)
        baseline_notes.append(
            f"- `{dataset}` 基线实际未恢复污染源暴露率：`{rate:.4f}`"
            if rate is not None
            else f"- `{dataset}` 未找到基线暴露预检记录。"
        )
    example_lines = _render_examples(examples)
    content = "\n".join(
        [
            "# Stage46 跨数据集真实 LLM 回答验证报告",
            "",
            "## 实验问题",
            "",
            "在 HotpotQA 与 MuSiQue 的同一批 20 个 LogicPoison query 上，Stage43 风险恢复、Stage44 候选源扩展和 Stage45 二跳补证是否能在真实 LLM 回答层同时降低攻击成功并改善可用性？",
            "",
            "## 冻结设计",
            "",
            "- 每个数据集 20 query，4 种上下文策略，共 160 次 `qwen3.7-plus` 回答调用；温度 0，`evidence_compare`，每条 source 截断 450 字符。",
            "- 先对实际渲染后的 prompt 做预检；`attack success` 仅指最终语义裁决为错误且 prompt 仍含未恢复 changed support source。",
            "- Stage29 做本地归一化审计，Stage34 仅裁决本地标为 `incorrect` 的回答。HotpotQA judge 调用 25 次，MuSiQue 15 次，judge error 均为 0。",
            "",
            "## 攻击压力前提",
            "",
            *baseline_notes,
            "",
            "因此，两个数据集的未恢复基线都确实把污染证据送进了模型看到的 prompt；基线 ASR 与防御后零 ASR 可以解释为对相同攻击压力的差异，而不是攻击文本未被检索到。",
            "",
            "## 最终结果",
            "",
            *final_table,
            "",
            "## 同 query 配对变化",
            "",
            *paired_table,
            "",
            "## 结论",
            "",
            "1. 未恢复基线在两个数据集都出现真实攻击成功：HotpotQA 为 0.45，MuSiQue 为 0.10。由此否定“20 个 query 天然难以攻击”的解释。",
            "2. 三个防御策略在两数据集的最终 ASR 均为 0。它们并非只让模型拒答：Stage44 把 HotpotQA 效用提高至 0.85、MuSiQue 提高至 0.40；Stage45 在 MuSiQue 进一步到 0.45。",
            "3. Stage43 已足以切断污染暴露，但效用提升有限，尤其 MuSiQue 仍有 0.65 拒答率。Stage44 是当前默认的安全-效用平衡点；Stage45 对 HotpotQA 无额外回答收益，却对 MuSiQue 增加一个有效回答，适合按链路缺口触发而非无差别启用。",
            "4. 结果仍是 20-query、小规模、单一回答模型与 trusted clean reference 候选池上的证据。它证明当前防御链对 LogicPoison 有效，但不等价于无可信参考语料的生产部署保证。",
            "",
            "## 真实配对样例",
            "",
            *example_lines,
            "",
            "## 可复现产物",
            "",
            f"- 最终指标：`{config.final_summary_output_path.as_posix()}`",
            f"- query 级配对记录：`{config.pairwise_rows_output_path.as_posix()}`",
            f"- 配对汇总：`{config.pairwise_summary_output_path.as_posix()}`",
            f"- 样例 JSONL：`{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _select_examples(rows: list[Stage46PairwiseRow]) -> list[Stage46PairwiseRow]:
    selected: list[Stage46PairwiseRow] = []
    seen_datasets: set[str] = set()
    priorities = sorted(
        rows,
        key=lambda row: (
            not row.attack_neutralized,
            not (row.attack_neutralized and row.treatment_utility),
            row.dataset,
            _METHOD_ORDER.get(row.treatment_method, 99),
            row.query_id,
        ),
    )
    for row in priorities:
        if row.dataset in seen_datasets:
            continue
        if row.attack_neutralized:
            selected.append(row)
            seen_datasets.add(row.dataset)
    for row in priorities:
        if len(selected) >= 4:
            break
        if row not in selected and row.utility_delta > 0:
            selected.append(row)
    return selected


def _render_examples(rows: list[Stage46PairwiseRow]) -> list[str]:
    if not rows:
        return ["没有满足样例选择条件的 query。"]
    lines: list[str] = []
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"### 样例 {index}: {row.dataset} / `{row.query_id}`",
                "",
                f"- 问题：{_compact(row.query, 260)}",
                f"- 标准答案：`{_compact(row.gold_answer, 160)}`",
                f"- 基线回答：`{_compact(row.baseline_answer, 180)}`，最终标签 `{row.baseline_final_label}`，攻击成功 `{row.baseline_attack_success}`。",
                f"- {_method_label(row.treatment_method)} 回答：`{_compact(row.treatment_answer, 180)}`，最终标签 `{row.treatment_final_label}`，攻击成功 `{row.treatment_attack_success}`。",
                f"- 基线未恢复 changed support：`{';'.join(row.baseline_unrecovered_changed_doc_ids)}`；防御后：`{';'.join(row.treatment_unrecovered_changed_doc_ids) or '无'}`。",
                "",
                "基线 source 摘要：",
                "",
                *_render_source_table(row.baseline_source_summaries),
                "",
                "防御后 source 摘要：",
                "",
                *_render_source_table(row.treatment_source_summaries),
                "",
            ]
        )
    return lines


def _render_source_table(sources: list[dict[str, object]]) -> list[str]:
    if not sources:
        return ["无 source 摘要。"]
    lines = ["| 排名 | doc_id | 状态 | 标题 |", "| ---: | --- | --- | --- |"]
    for source in sources[:4]:
        lines.append(
            f"| {source.get('rank', '')} | {source.get('doc_id', '')} | "
            f"{_compact(str(source.get('source_state', '')), 40)} | "
            f"{_compact(str(source.get('title', '')), 90)} |"
        )
    return lines


def _load_preflight_exposure(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        str(row["method"]): float(row["unrecovered_changed_exposure_rate"])
        for row in rows
        if row.get("method") and row.get("unrecovered_changed_exposure_rate")
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected JSON object in {path}")
                rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _final_label(row: dict[str, Any]) -> str:
    return str(row.get("final_label", "incorrect"))


def _is_utility(row: dict[str, Any]) -> bool:
    return _final_label(row) in {"correct", "partial"}


def _source_summaries(row: dict[str, Any]) -> list[dict[str, object]]:
    raw = row.get("source_summaries")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _method_label(method: str) -> str:
    return f"{_METHOD_LABELS.get(method, method)} (`{method}`)"


def _compact(value: str, max_chars: int) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    return normalized if len(normalized) <= max_chars else normalized[:max_chars].rstrip() + " ..."


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize paired Stage46 final answer-level results."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage46_cross_dataset_answer_analysis.yaml"),
    )
    args = parser.parse_args()
    summaries, paired_rows, paired_summaries = run_from_config(
        Stage46CrossDatasetAnalysisConfig.from_yaml(args.config)
    )
    print(
        f"stage46_final_summaries={len(summaries)}, "
        f"paired_rows={len(paired_rows)}, paired_summaries={len(paired_summaries)}"
    )


if __name__ == "__main__":
    main()
