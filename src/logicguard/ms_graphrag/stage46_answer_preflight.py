"""Stage46 paired answer-context matrix and prompt-exposure preflight.

Stage43--45 produced four complementary source-context variants for each
cross-dataset query.  This module freezes those variants into one answer input
and renders the exact contexts that the answer LLM will receive.  It does not
call an LLM; its job is to make the later answer-level comparison auditable.
"""

from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.answer_level_llm_verification import (
    Stage27AnswerCase,
    Stage27RenderingPolicy,
    build_stage27_answer_cases,
)


@dataclass(frozen=True, slots=True)
class Stage46ContextVariant:
    """One frozen source-context variant used in the paired answer comparison."""

    method: str
    context_input_path: Path
    source_method: str
    description: str

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, object],
        project_root: Path,
    ) -> "Stage46ContextVariant":
        raw_path = Path(str(payload["context_input_path"]))
        return cls(
            method=str(payload["method"]),
            context_input_path=(
                raw_path.resolve()
                if raw_path.is_absolute()
                else (project_root / raw_path).resolve()
            ),
            source_method=str(payload.get("source_method", payload["method"])),
            description=str(payload.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class Stage46AnswerPreflightConfig:
    """Configuration for context freezing and exact-prompt exposure diagnostics."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    variants: list[Stage46ContextVariant]
    context_matrix_output_path: Path
    preflight_cases_output_path: Path
    preflight_rows_output_path: Path
    preflight_summary_output_path: Path
    preflight_examples_output_path: Path
    report_path: Path
    rendering_policies: dict[str, Stage27RenderingPolicy]
    max_queries: int = 20
    max_sources: int = 12
    max_chars_per_source: int = 450
    stage_label: str = "Stage46"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage46AnswerPreflightConfig":
        """Load a project-relative Stage46 YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (project_root / candidate).resolve()
            )

        variants = [
            Stage46ContextVariant.from_mapping(dict(item), project_root)
            for item in payload["variants"]
        ]
        methods = [variant.method for variant in variants]
        if len(set(methods)) != len(methods):
            raise ValueError("Stage46 variants must use distinct method names")
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),
            query_integrity_path=resolve(payload["query_integrity_path"]),
            variants=variants,
            context_matrix_output_path=resolve(payload["context_matrix_output_path"]),
            preflight_cases_output_path=resolve(payload["preflight_cases_output_path"]),
            preflight_rows_output_path=resolve(payload["preflight_rows_output_path"]),
            preflight_summary_output_path=resolve(payload["preflight_summary_output_path"]),
            preflight_examples_output_path=resolve(payload["preflight_examples_output_path"]),
            report_path=resolve(payload["report_path"]),
            rendering_policies=_parse_rendering_policies(
                payload.get("rendering_policies", {})
            ),
            max_queries=int(payload.get("max_queries", 20)),
            max_sources=int(payload.get("max_sources", 12)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 450)),
            stage_label=str(payload.get("stage_label", "Stage46")),
        )


@dataclass(frozen=True, slots=True)
class Stage46PreflightRow:
    """One rendered answer context, including the evidence exposure used by ASR."""

    dataset: str
    query_id: str
    method: str
    max_sources: int
    max_chars_per_source: int
    source_count: int
    rendered_char_count: int
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    changed_hit_doc_ids: list[str]
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    full_support_hit: bool
    context_has_gold_answer: bool
    unrecovered_changed_source_exposed: bool

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage46PreflightSummaryRow:
    """Method-level prompt-exposure diagnostic for the frozen answer matrix."""

    dataset: str
    method: str
    query_count: int
    changed_support_query_count: int
    changed_support_hit_rate: float
    unrecovered_changed_exposure_rate: float
    recovered_support_query_rate: float
    full_support_hit_rate: float
    gold_answer_surface_rate: float
    avg_source_count: float
    avg_rendered_chars: float
    attack_pressure_status: str

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(
    config: Stage46AnswerPreflightConfig,
) -> tuple[list[dict[str, Any]], list[Stage46PreflightRow]]:
    """Freeze Stage46 contexts, render cases, and write non-LLM diagnostics."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    matrix_rows = build_stage46_context_matrix(
        samples=samples,
        variants=config.variants,
        stage_label=config.stage_label,
    )
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=matrix_rows,
        dataset=config.dataset,
        methods=[variant.method for variant in config.variants],
        max_sources=config.max_sources,
        max_chars_per_source=config.max_chars_per_source,
        rendering_policies=config.rendering_policies,
    )
    preflight_rows = build_stage46_preflight_rows(cases)
    summaries = summarize_stage46_preflight_rows(preflight_rows)
    write_stage46_preflight_outputs(
        config=config,
        matrix_rows=matrix_rows,
        cases=cases,
        preflight_rows=preflight_rows,
        summaries=summaries,
    )
    return matrix_rows, preflight_rows


def build_stage46_context_matrix(
    *,
    samples: list[NormalizedSample],
    variants: list[Stage46ContextVariant],
    stage_label: str = "Stage46",
) -> list[dict[str, Any]]:
    """Select exactly one source context for every query-variant pair."""

    query_ids = [sample.query_id for sample in samples]
    expected_query_ids = set(query_ids)
    rows: list[dict[str, Any]] = []
    for variant in variants:
        candidates = [
            row
            for row in _load_jsonl(variant.context_input_path)
            if str(row.get("method", "")) == variant.source_method
            and str(row.get("query_id", "")) in expected_query_ids
        ]
        by_query: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            query_id = str(candidate["query_id"])
            if query_id in by_query:
                raise ValueError(
                    "Stage46 expected one context row per query and source method: "
                    f"{variant.context_input_path} / {variant.source_method} / {query_id}"
                )
            by_query[query_id] = candidate
        missing = [query_id for query_id in query_ids if query_id not in by_query]
        if missing:
            raise ValueError(
                "Stage46 context matrix is incomplete for "
                f"{variant.method}: missing {len(missing)} query ids, first={missing[0]}"
            )
        for query_id in query_ids:
            selected = deepcopy(by_query[query_id])
            selected["method"] = variant.method
            selected["stage46_provenance"] = {
                "stage_label": stage_label,
                "variant_description": variant.description,
                "source_context_path": variant.context_input_path.as_posix(),
                "source_method": variant.source_method,
            }
            rows.append(selected)
    return rows


def build_stage46_preflight_rows(
    cases: list[Stage27AnswerCase],
) -> list[Stage46PreflightRow]:
    """Record the exact post-truncation context state passed to the answer model."""

    rows = [
        Stage46PreflightRow(
            dataset=case.dataset,
            query_id=case.query_id,
            method=case.method,
            max_sources=case.max_sources,
            max_chars_per_source=case.max_chars_per_source,
            source_count=case.source_count,
            rendered_char_count=len(case.rendered_context),
            support_doc_ids=case.support_doc_ids,
            changed_support_doc_ids=case.changed_support_doc_ids,
            support_hit_doc_ids=case.support_hit_doc_ids,
            changed_hit_doc_ids=case.changed_hit_doc_ids,
            unrecovered_changed_doc_ids=case.unrecovered_changed_doc_ids,
            recovered_support_doc_ids=case.recovered_support_doc_ids,
            full_support_hit=set(case.support_doc_ids).issubset(case.context_doc_ids),
            context_has_gold_answer=case.context_has_gold_answer,
            unrecovered_changed_source_exposed=bool(
                case.unrecovered_changed_doc_ids
            ),
        )
        for case in cases
    ]
    return sorted(rows, key=lambda row: (row.query_id, row.method))


def summarize_stage46_preflight_rows(
    rows: list[Stage46PreflightRow],
) -> list[Stage46PreflightSummaryRow]:
    """Aggregate context exposure without conflating stored and rendered sources."""

    grouped: dict[str, list[Stage46PreflightRow]] = {}
    for row in rows:
        grouped.setdefault(row.method, []).append(row)
    summaries: list[Stage46PreflightSummaryRow] = []
    for method, group in grouped.items():
        total = len(group)
        changed_query_count = sum(1 for row in group if row.changed_support_doc_ids)
        exposure_rate = _ratio(
            sum(1 for row in group if row.unrecovered_changed_source_exposed),
            changed_query_count,
        )
        summaries.append(
            Stage46PreflightSummaryRow(
                dataset=group[0].dataset,
                method=method,
                query_count=total,
                changed_support_query_count=changed_query_count,
                changed_support_hit_rate=_ratio(
                    sum(1 for row in group if row.changed_hit_doc_ids),
                    changed_query_count,
                ),
                unrecovered_changed_exposure_rate=exposure_rate,
                recovered_support_query_rate=_ratio(
                    sum(1 for row in group if row.recovered_support_doc_ids), total
                ),
                full_support_hit_rate=_ratio(
                    sum(1 for row in group if row.full_support_hit), total
                ),
                gold_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer), total
                ),
                avg_source_count=_avg(float(row.source_count) for row in group),
                avg_rendered_chars=_avg(float(row.rendered_char_count) for row in group),
                attack_pressure_status=_attack_pressure_status(
                    changed_query_count, exposure_rate
                ),
            )
        )
    return sorted(summaries, key=lambda row: row.method)


def write_stage46_preflight_outputs(
    *,
    config: Stage46AnswerPreflightConfig,
    matrix_rows: list[dict[str, Any]],
    cases: list[Stage27AnswerCase],
    preflight_rows: list[Stage46PreflightRow],
    summaries: list[Stage46PreflightSummaryRow],
) -> None:
    """Write frozen inputs and a Chinese preflight report before model calls."""

    _write_jsonl(config.context_matrix_output_path, matrix_rows)
    _write_jsonl(
        config.preflight_cases_output_path,
        [case.to_json_dict() for case in cases],
    )
    _write_jsonl(
        config.preflight_rows_output_path,
        [row.to_json_dict() for row in preflight_rows],
    )
    _write_csv(
        config.preflight_summary_output_path,
        [row.to_csv_row() for row in summaries],
    )
    examples = _select_examples(preflight_rows, max_examples=12)
    _write_jsonl(
        config.preflight_examples_output_path,
        [row.to_json_dict() for row in examples],
    )

    table = [
        "| 方法 | query数 | 实际未恢复污染源暴露率 | 完整支持率 | 标准答案表面率 | 平均sources | 攻击压力状态 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summaries:
        table.append(
            f"| `{row.method}` | {row.query_count} | "
            f"{row.unrecovered_changed_exposure_rate:.4f} | "
            f"{row.full_support_hit_rate:.4f} | {row.gold_answer_surface_rate:.4f} | "
            f"{row.avg_source_count:.2f} | {row.attack_pressure_status} |"
        )
    baseline = next(
        (row for row in summaries if row.method == "full_query_guard"), None
    )
    baseline_note = (
        "未找到 `full_query_guard` 基线；正式 ASR 不可解释。"
        if baseline is None
        else (
            "基线的实际未恢复污染源暴露率为 "
            f"`{baseline.unrecovered_changed_exposure_rate:.4f}`，"
            f"攻击压力判定为 `{baseline.attack_pressure_status}`。"
        )
    )
    content = "\n".join(
        [
            f"# {config.stage_label} {config.dataset} 回答上下文矩阵与提示词预检",
            "",
            "## 目的",
            "",
            "将 Stage43 风险恢复、Stage44 候选源扩展、Stage45 二跳补证与未恢复基线固定为同一批 query 的回答输入。预检依据实际渲染并截断后的 sources，而不是原始 JSONL 的全部 sources。",
            "",
            "## 冻结设置",
            "",
            f"- query 数：`{len({case.query_id for case in cases})}`",
            f"- 策略数：`{len(config.variants)}`",
            f"- answer case 数：`{len(cases)}`",
            f"- 默认单源截断：`{config.max_chars_per_source}` 字符",
            "- `unrecovered_changed_exposure_rate`：在发生过 support 文档变更的 query 中，实际提示词仍包含未恢复变更 source 的比例。只有该比例足够高时，基线的零 ASR 才可以被解释为面对攻击压力的结果。",
            "",
            "## 预检结果",
            "",
            *table,
            "",
            "## 攻击压力解释",
            "",
            baseline_note,
            "`充分`表示暴露率至少 0.50，`有限`表示大于 0 但低于 0.50，`缺失`表示没有未恢复污染源进入实际提示词。该标签只限定 ASR 的可解释范围，不替代后续真实 LLM 回答与裁决。",
            "",
            "## 产物",
            "",
            f"- 冻结上下文矩阵：`{config.context_matrix_output_path.as_posix()}`",
            f"- 实际提示词 cases：`{config.preflight_cases_output_path.as_posix()}`",
            f"- query 级预检：`{config.preflight_rows_output_path.as_posix()}`",
            f"- 方法汇总：`{config.preflight_summary_output_path.as_posix()}`",
            f"- 样例：`{config.preflight_examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _parse_rendering_policies(
    raw: object,
) -> dict[str, Stage27RenderingPolicy]:
    if not isinstance(raw, dict):
        return {}
    policies: dict[str, Stage27RenderingPolicy] = {}
    for method, value in raw.items():
        if not isinstance(value, dict):
            continue
        policies[str(method)] = Stage27RenderingPolicy(
            order_policy=str(value.get("order_policy", "official_order")),
            prompt_policy=str(value.get("prompt_policy", "default")),
            max_sources=_optional_int(value.get("max_sources")),
            max_chars_per_source=_optional_int(value.get("max_chars_per_source")),
        )
    return policies


def _select_examples(
    rows: list[Stage46PreflightRow],
    *,
    max_examples: int,
) -> list[Stage46PreflightRow]:
    exposed = [row for row in rows if row.unrecovered_changed_source_exposed]
    safe = [row for row in rows if not row.unrecovered_changed_source_exposed]
    return (exposed + safe)[:max_examples]


def _attack_pressure_status(changed_query_count: int, exposure_rate: float) -> str:
    if changed_query_count == 0:
        return "不适用"
    if exposure_rate >= 0.50:
        return "充分"
    if exposure_rate > 0.0:
        return "有限"
    return "缺失"


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


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, list):
            output[key] = ";".join(str(item) for item in value)
        elif isinstance(value, bool):
            output[key] = "1" if value else "0"
        elif isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def _optional_int(value: object) -> int | None:
    return int(value) if value not in (None, "") else None


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _avg(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze Stage46 answer contexts and audit prompt exposure."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage46_hotpotqa_answer_preflight.yaml"),
    )
    args = parser.parse_args()
    matrix_rows, preflight_rows = run_from_config(
        Stage46AnswerPreflightConfig.from_yaml(args.config)
    )
    print(
        f"stage46_context_rows={len(matrix_rows)}, "
        f"stage46_preflight_rows={len(preflight_rows)}"
    )


if __name__ == "__main__":
    main()
