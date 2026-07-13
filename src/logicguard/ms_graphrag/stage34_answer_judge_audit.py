"""Stage34 judge-aware answer audit for Stage33 official GraphRAG answers."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import yaml

from logicguard.llm.answer_judge import AnswerJudgeConfig, judge_answer_with_client
from logicguard.llm.provider import ChatResponse, OpenAICompatibleChatClient
from logicguard.ms_graphrag.answer_level_llm_verification import _read_required_env

_METHOD_ORDER = {
    "full_query_guard": 1,
    "risk_non_oracle_guarded_sources": 2,
    "risk_non_oracle_title_entity_bm25": 3,
    "guarded_sources": 4,
    "recovered_sources_by_doc_id": 5,
    "non_oracle_title_entity_bm25": 6,
    "stage35_query_bm25_append_top12": 7,
}

_FINAL_LABELS = {"correct", "partial", "abstained", "incorrect", "api_error", "judge_error"}


class ChatClient(Protocol):
    """Protocol for the chat client used by Stage34."""

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse:
        """Return one chat completion."""


@dataclass(frozen=True, slots=True)
class Stage34AnswerJudgeAuditConfig:
    """Paths and settings for Stage34 judge-aware answer audit."""

    dataset: str
    audited_results_path: Path
    judged_results_output_path: Path
    summary_output_path: Path
    breakdown_output_path: Path
    examples_output_path: Path
    report_path: Path
    methods: list[str]
    judge_model: str
    judge_api_key_env: str = "DASHSCOPE_API_KEY"
    judge_base_url_env: str = "DASHSCOPE_BASE_URL"
    judge_temperature: float = 0.0
    judge_max_tokens: int = 96
    judge_timeout_seconds: int = 60
    max_examples: int = 8
    stage_label: str = "Stage34"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage34AnswerJudgeAuditConfig":
        """Load a project-relative YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            audited_results_path=resolve(payload["audited_results_path"]),
            judged_results_output_path=resolve(payload["judged_results_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            breakdown_output_path=resolve(payload["breakdown_output_path"]),
            examples_output_path=resolve(payload["examples_output_path"]),
            report_path=resolve(payload["report_path"]),
            methods=[str(method) for method in payload.get("methods", [])],
            judge_model=str(payload["judge_model"]),
            judge_api_key_env=str(payload.get("judge_api_key_env", "DASHSCOPE_API_KEY")),
            judge_base_url_env=str(payload.get("judge_base_url_env", "DASHSCOPE_BASE_URL")),
            judge_temperature=float(payload.get("judge_temperature", 0.0)),
            judge_max_tokens=int(payload.get("judge_max_tokens", 96)),
            judge_timeout_seconds=int(payload.get("judge_timeout_seconds", 60)),
            max_examples=int(payload.get("max_examples", 8)),
            stage_label=str(payload.get("stage_label", "Stage34")),
        )

    def judge_config(self) -> AnswerJudgeConfig:
        """Return judge runtime settings."""

        return AnswerJudgeConfig(
            model=self.judge_model,
            temperature=self.judge_temperature,
            max_tokens=self.judge_max_tokens,
            timeout_seconds=self.judge_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class Stage34JudgedAnswerRow:
    """One Stage33 audited answer after optional LLM judge adjudication."""

    dataset: str
    model: str
    query_id: str
    query: str
    method: str
    gold_answer: str
    generated_answer: str
    original_answer_label: str
    stage29_label: str
    audit_reason: str
    judge_called: bool
    judge_label: str
    judge_reason: str
    judge_model: str
    judge_prompt_tokens: int | None
    judge_completion_tokens: int | None
    judge_total_tokens: int | None
    judge_error: str | None
    final_label: str
    final_reason: str
    final_attack_success: bool
    context_has_gold_answer: bool
    support_doc_ids: list[str]
    context_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    source_count: int
    recovered_source_count: int
    source_summaries: list[dict[str, object]]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage34SummaryRow:
    """Method-level Stage34 judge-aware summary."""

    dataset: str
    model: str
    method: str
    query_count: int
    stage29_utility_rate: float
    final_correct_rate: float
    final_partial_rate: float
    final_utility_rate: float
    final_abstain_rate: float
    final_incorrect_rate: float
    final_attack_success_rate: float
    judge_call_rate: float
    judge_error_rate: float
    gold_answer_surface_rate: float
    support_hit_rate: float
    avg_judge_tokens: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage34BreakdownRow:
    """Final-label/reason breakdown for Stage34."""

    dataset: str
    model: str
    method: str
    final_label: str
    final_reason: str
    count: int
    rate: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(config: Stage34AnswerJudgeAuditConfig) -> list[Stage34JudgedAnswerRow]:
    """Run Stage34 judge-aware audit and write artifacts."""

    audited_rows = _load_jsonl(config.audited_results_path)
    api_key = _read_required_env(config.judge_api_key_env)
    base_url = _read_required_env(config.judge_base_url_env)
    client = OpenAICompatibleChatClient(base_url=base_url, api_key=api_key)
    rows = build_stage34_judge_rows(
        audited_rows=audited_rows,
        client=client,
        judge_model=config.judge_model,
        judge_temperature=config.judge_temperature,
        judge_max_tokens=config.judge_max_tokens,
        judge_timeout_seconds=config.judge_timeout_seconds,
        methods=config.methods,
    )
    write_stage34_outputs(config=config, rows=rows)
    print(
        f"stage34_judged_rows={len(rows)}, "
        f"judge_calls={sum(1 for row in rows if row.judge_called)}"
    )
    return rows


def build_stage34_judge_rows(
    *,
    audited_rows: list[dict[str, Any]],
    client: ChatClient,
    judge_model: str,
    judge_temperature: float,
    judge_max_tokens: int,
    judge_timeout_seconds: int,
    methods: list[str] | None = None,
) -> list[Stage34JudgedAnswerRow]:
    """Adjudicate locally-uncertain audited answer rows with an LLM judge."""

    allowed_methods = set(methods or [])
    judge_config = AnswerJudgeConfig(
        model=judge_model,
        temperature=judge_temperature,
        max_tokens=judge_max_tokens,
        timeout_seconds=judge_timeout_seconds,
    )
    rows: list[Stage34JudgedAnswerRow] = []
    for audited in audited_rows:
        method = str(audited.get("method", ""))
        if allowed_methods and method not in allowed_methods:
            continue
        rows.append(
            _build_judged_row(
                audited=audited,
                client=client,
                judge_config=judge_config,
            )
        )
    rows.sort(key=lambda row: (row.query_id, _METHOD_ORDER.get(row.method, 99), row.method))
    return rows


def summarize_stage34_judge_rows(
    rows: list[Stage34JudgedAnswerRow],
) -> list[Stage34SummaryRow]:
    """Aggregate Stage34 judge-aware rows by model and method."""

    grouped: dict[tuple[str, str], list[Stage34JudgedAnswerRow]] = {}
    for row in rows:
        grouped.setdefault((row.model, row.method), []).append(row)

    summaries: list[Stage34SummaryRow] = []
    for (model, method), group in grouped.items():
        total = len(group)
        summaries.append(
            Stage34SummaryRow(
                dataset=group[0].dataset,
                model=model,
                method=method,
                query_count=total,
                stage29_utility_rate=_ratio(
                    sum(1 for row in group if row.stage29_label in {"correct", "partial"}),
                    total,
                ),
                final_correct_rate=_ratio(
                    sum(1 for row in group if row.final_label == "correct"),
                    total,
                ),
                final_partial_rate=_ratio(
                    sum(1 for row in group if row.final_label == "partial"),
                    total,
                ),
                final_utility_rate=_ratio(
                    sum(1 for row in group if row.final_label in {"correct", "partial"}),
                    total,
                ),
                final_abstain_rate=_ratio(
                    sum(1 for row in group if row.final_label == "abstained"),
                    total,
                ),
                final_incorrect_rate=_ratio(
                    sum(1 for row in group if row.final_label == "incorrect"),
                    total,
                ),
                final_attack_success_rate=_ratio(
                    sum(1 for row in group if row.final_attack_success),
                    total,
                ),
                judge_call_rate=_ratio(sum(1 for row in group if row.judge_called), total),
                judge_error_rate=_ratio(sum(1 for row in group if row.judge_error), total),
                gold_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer),
                    total,
                ),
                support_hit_rate=_ratio(
                    sum(1 for row in group if row.support_hit_doc_ids),
                    total,
                ),
                avg_judge_tokens=_avg(row.judge_total_tokens or 0 for row in group),
            )
        )
    summaries.sort(key=lambda row: (row.model, _METHOD_ORDER.get(row.method, 99), row.method))
    return summaries


def build_stage34_breakdown(
    rows: list[Stage34JudgedAnswerRow],
) -> list[Stage34BreakdownRow]:
    """Count final label/reason pairs by model and method."""

    grouped: dict[tuple[str, str], list[Stage34JudgedAnswerRow]] = {}
    for row in rows:
        grouped.setdefault((row.model, row.method), []).append(row)

    breakdown: list[Stage34BreakdownRow] = []
    for (model, method), group in grouped.items():
        counts: dict[tuple[str, str], int] = {}
        for row in group:
            key = (row.final_label, row.final_reason)
            counts[key] = counts.get(key, 0) + 1
        for (label, reason), count in counts.items():
            breakdown.append(
                Stage34BreakdownRow(
                    dataset=group[0].dataset,
                    model=model,
                    method=method,
                    final_label=label,
                    final_reason=reason,
                    count=count,
                    rate=_ratio(count, len(group)),
                )
            )
    breakdown.sort(key=lambda row: (row.model, _METHOD_ORDER.get(row.method, 99), row.method, row.final_label, row.final_reason))
    return breakdown


def write_stage34_outputs(
    *,
    config: Stage34AnswerJudgeAuditConfig,
    rows: list[Stage34JudgedAnswerRow],
) -> None:
    """Write Stage34 JSONL/CSV/report artifacts."""

    summaries = summarize_stage34_judge_rows(rows)
    breakdown = build_stage34_breakdown(rows)
    examples = _select_examples(rows, max_examples=config.max_examples)

    _write_jsonl(config.judged_results_output_path, [row.to_json_dict() for row in rows])
    _write_csv(config.summary_output_path, [row.to_csv_row() for row in summaries])
    _write_csv(config.breakdown_output_path, [row.to_csv_row() for row in breakdown])
    _write_jsonl(config.examples_output_path, [row.to_json_dict() for row in examples])
    _write_stage34_report(
        config=config,
        rows=rows,
        summaries=summaries,
        breakdown=breakdown,
        examples=examples,
    )


def _build_judged_row(
    *,
    audited: dict[str, Any],
    client: ChatClient,
    judge_config: AnswerJudgeConfig,
) -> Stage34JudgedAnswerRow:
    stage29_label = str(audited.get("stage29_label", "incorrect"))
    judge_called = _should_call_judge(stage29_label)
    judged = None
    if judge_called:
        judged = judge_answer_with_client(
            client=client,
            config=judge_config,
            question=str(audited.get("query", "")),
            gold_answer=str(audited.get("gold_answer", "")),
            generated_answer=str(audited.get("generated_answer", "")),
        )
        final_label = judged.label if judged.label in _FINAL_LABELS else "judge_error"
        final_reason = f"llm_judge_{final_label}"
        if final_label == "judge_error":
            final_label = stage29_label
            final_reason = "judge_error_fallback_to_stage29"
    else:
        final_label = _final_label_without_judge(stage29_label)
        final_reason = str(audited.get("audit_reason", "stage29_label_kept"))

    unrecovered_changed = _string_list(audited.get("unrecovered_changed_doc_ids", []))
    return Stage34JudgedAnswerRow(
        dataset=str(audited.get("dataset", "")),
        model=str(audited.get("model", "")),
        query_id=str(audited.get("query_id", "")),
        query=str(audited.get("query", "")),
        method=str(audited.get("method", "")),
        gold_answer=str(audited.get("gold_answer", "")),
        generated_answer=str(audited.get("generated_answer", "")),
        original_answer_label=str(audited.get("original_answer_label", "")),
        stage29_label=stage29_label,
        audit_reason=str(audited.get("audit_reason", "")),
        judge_called=judge_called,
        judge_label=judged.label if judged is not None else f"stage29_{stage29_label}",
        judge_reason=judged.reason if judged is not None else "judge_not_needed",
        judge_model=judge_config.model,
        judge_prompt_tokens=judged.prompt_tokens if judged is not None else 0,
        judge_completion_tokens=judged.completion_tokens if judged is not None else 0,
        judge_total_tokens=judged.total_tokens if judged is not None else 0,
        judge_error=judged.error if judged is not None else None,
        final_label=final_label,
        final_reason=final_reason,
        final_attack_success=final_label == "incorrect" and bool(unrecovered_changed),
        context_has_gold_answer=_truthy(audited.get("context_has_gold_answer")),
        support_doc_ids=_string_list(audited.get("support_doc_ids", [])),
        context_doc_ids=_string_list(audited.get("context_doc_ids", [])),
        support_hit_doc_ids=_string_list(audited.get("support_hit_doc_ids", [])),
        unrecovered_changed_doc_ids=unrecovered_changed,
        recovered_support_doc_ids=_string_list(audited.get("recovered_support_doc_ids", [])),
        source_count=_optional_int(audited.get("source_count")) or 0,
        recovered_source_count=_optional_int(audited.get("recovered_source_count")) or 0,
        source_summaries=_source_summary_dicts(audited.get("source_summaries", [])),
    )


def _should_call_judge(stage29_label: str) -> bool:
    return stage29_label == "incorrect"


def _final_label_without_judge(stage29_label: str) -> str:
    if stage29_label == "api_error":
        return "api_error"
    if stage29_label in _FINAL_LABELS:
        return stage29_label
    return "incorrect"


def _select_examples(
    rows: list[Stage34JudgedAnswerRow],
    *,
    max_examples: int,
) -> list[Stage34JudgedAnswerRow]:
    selected: list[Stage34JudgedAnswerRow] = []
    for row in sorted(rows, key=_example_priority):
        selected.append(row)
        if len(selected) >= max_examples:
            break
    return selected


def _example_priority(row: Stage34JudgedAnswerRow) -> tuple[int, str]:
    if row.judge_called and row.final_label == "partial":
        bucket = 0
    elif row.judge_called:
        bucket = 1
    elif row.final_label == "correct":
        bucket = 2
    elif row.final_label == "abstained":
        bucket = 3
    else:
        bucket = 9
    return (bucket, row.query_id)


def _write_stage34_report(
    *,
    config: Stage34AnswerJudgeAuditConfig,
    rows: list[Stage34JudgedAnswerRow],
    summaries: list[Stage34SummaryRow],
    breakdown: list[Stage34BreakdownRow],
    examples: list[Stage34JudgedAnswerRow],
) -> None:
    summary_table = [
        "| 模型 | 方法 | query数 | 本地审计 utility | final correct | final partial | "
        "final utility | abstain | incorrect | attack success | judge call | "
        "judge error | answer surface | support hit |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        summary_table.append(
            f"| `{row.model}` | `{row.method}` | {row.query_count} | "
            f"{row.stage29_utility_rate:.4f} | {row.final_correct_rate:.4f} | "
            f"{row.final_partial_rate:.4f} | {row.final_utility_rate:.4f} | "
            f"{row.final_abstain_rate:.4f} | {row.final_incorrect_rate:.4f} | "
            f"{row.final_attack_success_rate:.4f} | {row.judge_call_rate:.4f} | "
            f"{row.judge_error_rate:.4f} | {row.gold_answer_surface_rate:.4f} | "
            f"{row.support_hit_rate:.4f} |"
        )

    breakdown_table = [
        "| final label | final reason | count | rate |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in breakdown:
        breakdown_table.append(
            f"| `{row.final_label}` | `{row.final_reason}` | {row.count} | {row.rate:.4f} |"
        )

    example_lines: list[str] = []
    for index, row in enumerate(examples, start=1):
        example_lines.extend(
            [
                f"### 样例 {index}: `{row.query_id}`",
                "",
                f"- 问题：{row.query}",
                f"- 标准答案：`{row.gold_answer}`",
                f"- 模型回答：`{_markdown_cell(row.generated_answer)}`",
                f"- 本地审计标签：`{row.stage29_label}` / `{row.audit_reason}`",
                f"- LLM judge：`{row.judge_label}`，called=`{row.judge_called}`，reason=`{_markdown_cell(row.judge_reason)}`",
                f"- {config.stage_label} final：`{row.final_label}` / `{row.final_reason}`",
                f"- support hit：`{';'.join(row.support_hit_doc_ids)}`",
                "",
            ]
        )
        if row.source_summaries:
            example_lines.extend(
                [
                    "| rank | doc_id | title | snippet |",
                    "| ---: | --- | --- | --- |",
                ]
            )
            for source in row.source_summaries[:3]:
                example_lines.append(
                    f"| {source.get('rank', '')} | {source.get('doc_id', '')} | "
                    f"{_markdown_cell(str(source.get('title', '')))} | "
                    f"{_markdown_cell(str(source.get('snippet', '')))} |"
                )
            example_lines.append("")

    content = "\n".join(
        [
            f"# {config.stage_label} 回答裁判增强审计",
            "",
            "## 实验目的",
            "",
            f"{config.stage_label} 在本地归一化审计之后增加 LLM judge。它只裁判本地审计后仍为 "
            "`incorrect` 的非拒答样本，避免对已正确、已拒答或 API 错误样本重复调用模型。",
            "",
            "## 实验设置",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 输入审计结果：`{config.audited_results_path.as_posix()}`",
            f"- judge model：`{config.judge_model}`",
            f"- rows：`{len(rows)}`",
            f"- judge calls：`{sum(1 for row in rows if row.judge_called)}`",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## 标签归因",
            "",
            *breakdown_table,
            "",
            "## 主要结论",
            "",
            _stage34_conclusion(summaries, stage_label=config.stage_label),
            "",
            "## 代表样例",
            "",
            *example_lines,
            "## 产物路径",
            "",
            f"- judged JSONL：`{config.judged_results_output_path.as_posix()}`",
            f"- summary CSV：`{config.summary_output_path.as_posix()}`",
            f"- breakdown CSV：`{config.breakdown_output_path.as_posix()}`",
            f"- examples JSONL：`{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _stage34_conclusion(
    summaries: list[Stage34SummaryRow],
    *,
    stage_label: str,
) -> str:
    if not summaries:
        return f"本次没有生成可汇总的 {stage_label} 结果。"
    row = summaries[0]
    return "\n\n".join(
        [
            f"{stage_label} 的 judge call rate 为 `{row.judge_call_rate:.4f}`，说明大多数样本可以由本地规则稳定处理，只需要对少数 uncertain rows 调用 LLM judge。",
            f"judge-aware utility 为 `{row.final_utility_rate:.4f}`，相比本地审计 utility `{row.stage29_utility_rate:.4f}` 的变化，反映了严格归一化之外的语义裁判收益。",
            f"attack success 仍为 `{row.final_attack_success_rate:.4f}`；因此该裁判层主要改进评估可信度，不改变 source-level 防御结论。",
        ]
    )


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
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return []


def _source_summary_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _avg(values: Iterable[float | int | None]) -> float:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else 0.0


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, list):
            output[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            output[key] = "1" if value else "0"
        elif isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def _markdown_cell(text: str, max_chars: int = 220) -> str:
    normalized = " ".join(str(text).split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage34 回答裁判增强审计。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage34_answer_judge_audit_poisoned20.yaml"),
    )
    args = parser.parse_args()
    run_from_config(Stage34AnswerJudgeAuditConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
