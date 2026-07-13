"""Stage23 sources-level recovery over official Microsoft GraphRAG contexts.

Stage22 showed that query-layer seeding can improve official local-search
support recall, but it can also pull changed LogicPoison sources into the
answer context. Stage23 keeps the official GraphRAG context builder untouched:
it reads serialized `context_data.sources`, marks risky source rows, filters
changed rows, and optionally replaces them with clean-reference text units.
"""

from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
    parse_title_from_source_text,
)

_METHOD_ORDER = {
    "mixed_baseline": 0,
    "full_query_guard": 1,
    "guarded_sources": 2,
    "recovered_sources_by_doc_id": 3,
}


@dataclass(frozen=True, slots=True)
class Stage23SourceRecoveryConfig:
    """Paths and settings for one Stage23 source-recovery run."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    source_context_path: Path
    baseline_context_path: Path | None
    clean_reference_output_dir: Path
    context_output_path: Path
    metrics_output_path: Path
    summary_output_path: Path
    report_path: Path
    input_method_name: str = "full_query_guard"
    max_queries: int = 5
    stage_label: str = "Stage23"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage23SourceRecoveryConfig":
        """Load a project-relative YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path | None:
            if raw in (None, ""):
                return None
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        baseline = resolve(payload.get("baseline_context_path"))
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),  # type: ignore[arg-type]
            query_integrity_path=resolve(payload["query_integrity_path"]),  # type: ignore[arg-type]
            source_context_path=resolve(payload["source_context_path"]),  # type: ignore[arg-type]
            baseline_context_path=baseline,
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),  # type: ignore[arg-type]
            context_output_path=resolve(payload["context_output_path"]),  # type: ignore[arg-type]
            metrics_output_path=resolve(payload["metrics_output_path"]),  # type: ignore[arg-type]
            summary_output_path=resolve(payload["summary_output_path"]),  # type: ignore[arg-type]
            report_path=resolve(payload["report_path"]),  # type: ignore[arg-type]
            input_method_name=str(payload.get("input_method_name", "full_query_guard")),
            max_queries=int(payload.get("max_queries", 5)),
            stage_label=str(payload.get("stage_label", "Stage23")),
        )


@dataclass(frozen=True, slots=True)
class Stage23MetricRow:
    """Query-level metrics for one official-source context variant."""

    dataset: str
    query_id: str
    query: str
    method: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    trusted_support_doc_ids: list[str]
    context_doc_ids: list[str]
    gold_support_hit_ids: list[str]
    changed_support_hit_ids: list[str]
    unrecovered_changed_support_hit_ids: list[str]
    recovered_support_hit_ids: list[str]
    trusted_support_hit_ids: list[str]
    gold_support_recall: float
    changed_support_exposure: float
    trusted_support_recall: float
    empty_context: int
    source_count: int
    source_row_count: int
    recovered_source_count: int
    filtered_source_count: int

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            elif isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class Stage23SummaryRow:
    """Method-level averages across Stage23 queries."""

    dataset: str
    method: str
    query_count: int
    avg_gold_support_recall: float
    avg_changed_support_exposure: float
    avg_trusted_support_recall: float
    empty_context_rate: float
    avg_source_count: float
    avg_source_row_count: float
    avg_recovered_source_count: float
    avg_filtered_source_count: float

    def to_csv_row(self) -> dict[str, str]:
        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in asdict(self).items()
        }


def load_clean_reference_sources(output_dir: Path) -> dict[str, dict[str, Any]]:
    """Load clean GraphRAG text units and expose one replacement source per doc id."""

    documents_path = output_dir / "documents.parquet"
    text_units_path = output_dir / "text_units.parquet"
    if not documents_path.exists():
        raise FileNotFoundError(f"Missing clean documents parquet: {documents_path}")
    if not text_units_path.exists():
        raise FileNotFoundError(f"Missing clean text_units parquet: {text_units_path}")

    documents = pd.read_parquet(documents_path)
    text_units = pd.read_parquet(text_units_path)
    document_lookup: dict[str, tuple[str, str]] = {}
    for row in documents.to_dict(orient="records"):
        official_document_id = str(row["id"])
        document_text = str(row.get("text", ""))
        doc_id = parse_doc_id_from_source_text(document_text)
        title = parse_title_from_source_text(document_text) or str(row.get("title", "")).removesuffix(".txt")
        if doc_id:
            document_lookup[official_document_id] = (doc_id, title)

    clean_by_doc_id: dict[str, dict[str, Any]] = {}
    for row in sorted(
        text_units.to_dict(orient="records"),
        key=lambda item: (int(item.get("human_readable_id", 0) or 0), str(item.get("id", ""))),
    ):
        official_document_id = str(row.get("document_id", ""))
        text = str(row.get("text", ""))
        doc_id = parse_doc_id_from_source_text(text)
        title = parse_title_from_source_text(text)
        if not doc_id and official_document_id in document_lookup:
            doc_id, fallback_title = document_lookup[official_document_id]
            title = title or fallback_title
        if not doc_id or doc_id in clean_by_doc_id:
            continue
        clean_by_doc_id[doc_id] = {
            "id": str(row.get("id", "")),
            "text_unit_id": str(row.get("id", "")),
            "official_document_id": official_document_id,
            "human_readable_id": int(row.get("human_readable_id", 0) or 0),
            "logicguard_doc_id": doc_id,
            "title": title,
            "text": text,
            "n_tokens": int(row.get("n_tokens", 0) or 0),
            "source_state": "clean_reference",
            "recovered_from_changed_doc": False,
            "risk_reasons": [],
        }
    return clean_by_doc_id


def build_stage23_context_rows(
    *,
    source_context_rows: list[dict[str, Any]],
    integrity_rows: list[dict[str, Any]],
    clean_reference_sources: dict[str, dict[str, Any]],
    input_method_name: str = "full_query_guard",
) -> list[dict[str, Any]]:
    """Create pass-through, guarded, and recovered source-level contexts."""

    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    output_rows: list[dict[str, Any]] = []
    for context_row in source_context_rows:
        row_method = str(context_row.get("method", input_method_name))
        if row_method != input_method_name:
            continue
        query_id = str(context_row["query_id"])
        changed_doc_ids = {
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        }
        annotated_sources = [
            _annotate_official_source(source, changed_doc_ids=changed_doc_ids)
            for source in _source_records(context_row)
        ]
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method=input_method_name,
                sources=annotated_sources,
                policy="source_passthrough",
                filtered_doc_ids=[],
                recovered_doc_ids=[],
            )
        )

        guarded_sources = [
            source
            for source in annotated_sources
            if str(source.get("logicguard_doc_id", "")) not in changed_doc_ids
        ]
        filtered_doc_ids = _dedupe(
            source.get("logicguard_doc_id", "")
            for source in annotated_sources
            if str(source.get("logicguard_doc_id", "")) in changed_doc_ids
        )
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method="guarded_sources",
                sources=guarded_sources,
                policy="filter_changed_sources",
                filtered_doc_ids=filtered_doc_ids,
                recovered_doc_ids=[],
            )
        )

        recovered_sources: list[dict[str, Any]] = []
        recovered_doc_ids: list[str] = []
        missing_doc_ids: list[str] = []
        for source in annotated_sources:
            doc_id = str(source.get("logicguard_doc_id", ""))
            if doc_id not in changed_doc_ids:
                recovered_sources.append(source)
                continue
            clean_source = clean_reference_sources.get(doc_id)
            if clean_source is None:
                missing_doc_ids.append(doc_id)
                continue
            recovered_sources.append(_recovered_source(clean_source, original_source=source))
            recovered_doc_ids.append(doc_id)
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method="recovered_sources_by_doc_id",
                sources=recovered_sources,
                policy="replace_changed_sources_with_clean_doc_id_reference",
                filtered_doc_ids=_dedupe(missing_doc_ids),
                recovered_doc_ids=_dedupe(recovered_doc_ids),
            )
        )
    return output_rows


def build_stage23_metric_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str = "",
) -> list[Stage23MetricRow]:
    """Evaluate source-level recall and exposure after contexts are built."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    rows: list[Stage23MetricRow] = []
    for context_row in context_rows:
        query_id = str(context_row["query_id"])
        sample = samples_by_query.get(query_id)
        if sample is None:
            continue
        sources = _source_records(context_row)
        support_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_ids = [
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        ]
        changed_set = set(changed_ids)
        trusted_ids = [doc_id for doc_id in support_ids if doc_id not in changed_set]
        context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
        gold_hits = _ordered_intersection(support_ids, context_doc_ids)
        changed_hits = _ordered_intersection(changed_ids, context_doc_ids)
        trusted_hits = _ordered_intersection(trusted_ids, context_doc_ids)
        unrecovered_changed = _dedupe(
            _source_doc_id(source)
            for source in sources
            if _source_doc_id(source) in changed_set and not _is_recovered_source(source)
        )
        recovered_hits = _ordered_intersection(
            changed_ids,
            _dedupe(
                _source_doc_id(source)
                for source in sources
                if _source_doc_id(source) in changed_set and _is_recovered_source(source)
            ),
        )
        rows.append(
            Stage23MetricRow(
                dataset=dataset,
                query_id=query_id,
                query=sample.query,
                method=str(context_row.get("method", "unknown")),
                support_doc_ids=support_ids,
                changed_support_doc_ids=changed_ids,
                trusted_support_doc_ids=trusted_ids,
                context_doc_ids=context_doc_ids,
                gold_support_hit_ids=gold_hits,
                changed_support_hit_ids=changed_hits,
                unrecovered_changed_support_hit_ids=_ordered_intersection(
                    changed_ids,
                    unrecovered_changed,
                ),
                recovered_support_hit_ids=recovered_hits,
                trusted_support_hit_ids=trusted_hits,
                gold_support_recall=_ratio(len(gold_hits), len(support_ids)),
                changed_support_exposure=_ratio(len(unrecovered_changed), len(changed_ids)),
                trusted_support_recall=_ratio(len(trusted_hits), len(trusted_ids)),
                empty_context=1 if not sources else 0,
                source_count=len(context_doc_ids),
                source_row_count=len(sources),
                recovered_source_count=sum(1 for source in sources if _is_recovered_source(source)),
                filtered_source_count=len(context_row.get("filtered_source_doc_ids", [])),
            )
        )
    return rows


def summarize_stage23_metrics(rows: list[Stage23MetricRow]) -> list[Stage23SummaryRow]:
    """Aggregate Stage23 metrics by method."""

    grouped: dict[str, list[Stage23MetricRow]] = {}
    for row in rows:
        grouped.setdefault(row.method, []).append(row)
    summaries: list[Stage23SummaryRow] = []
    for method, group in grouped.items():
        summaries.append(
            Stage23SummaryRow(
                dataset=group[0].dataset if group else "",
                method=method,
                query_count=len(group),
                avg_gold_support_recall=_avg(row.gold_support_recall for row in group),
                avg_changed_support_exposure=_avg(row.changed_support_exposure for row in group),
                avg_trusted_support_recall=_avg(row.trusted_support_recall for row in group),
                empty_context_rate=_avg(float(row.empty_context) for row in group),
                avg_source_count=_avg(float(row.source_count) for row in group),
                avg_source_row_count=_avg(float(row.source_row_count) for row in group),
                avg_recovered_source_count=_avg(float(row.recovered_source_count) for row in group),
                avg_filtered_source_count=_avg(float(row.filtered_source_count) for row in group),
            )
        )
    summaries.sort(key=lambda row: (_METHOD_ORDER.get(row.method, 99), row.method))
    return summaries


def run_from_config(config: Stage23SourceRecoveryConfig) -> list[Stage23MetricRow]:
    """Run Stage23 source recovery and write machine/human-readable outputs."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    clean_sources = load_clean_reference_sources(config.clean_reference_output_dir)
    source_context_rows = _load_jsonl(config.source_context_path)[: config.max_queries]
    context_rows: list[dict[str, Any]] = []
    if config.baseline_context_path is not None:
        context_rows.extend(
            _baseline_context_row(row)
            for row in _load_jsonl(config.baseline_context_path)[: config.max_queries]
        )
    context_rows.extend(
        build_stage23_context_rows(
            source_context_rows=source_context_rows,
            integrity_rows=integrity_rows,
            clean_reference_sources=clean_sources,
            input_method_name=config.input_method_name,
        )
    )
    metric_rows = build_stage23_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
    )
    write_stage23_outputs(config=config, context_rows=context_rows, metric_rows=metric_rows)
    return metric_rows


def write_stage23_outputs(
    *,
    config: Stage23SourceRecoveryConfig,
    context_rows: list[dict[str, Any]],
    metric_rows: list[Stage23MetricRow],
) -> None:
    """Write Stage23 context JSONL, metrics CSV, summary CSV, and report."""

    summaries = summarize_stage23_metrics(metric_rows)
    config.context_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    with config.context_output_path.open("w", encoding="utf-8") as handle:
        for row in context_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with config.metrics_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage23MetricRow.__dataclass_fields__))
        writer.writeheader()
        for row in metric_rows:
            writer.writerow(row.to_csv_row())
    with config.summary_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage23SummaryRow.__dataclass_fields__))
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.to_csv_row())
    _write_stage23_report(config, summaries)


def _build_context_row(
    *,
    base_row: dict[str, Any],
    method: str,
    sources: list[dict[str, Any]],
    policy: str,
    filtered_doc_ids: list[str],
    recovered_doc_ids: list[str],
) -> dict[str, Any]:
    row = deepcopy(base_row)
    context_data = row.get("context_data", {})
    if not isinstance(context_data, dict):
        context_data = {}
    context_data = deepcopy(context_data)
    context_data["sources"] = sources
    row["context_data"] = context_data
    row["method"] = method
    row["stage23_policy"] = policy
    row["filtered_source_doc_ids"] = filtered_doc_ids
    row["recovered_source_doc_ids"] = recovered_doc_ids
    row["context_text"] = _render_source_context(sources)
    return row


def _baseline_context_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(row)
    copied["method"] = "mixed_baseline"
    context_data = copied.get("context_data", {})
    if isinstance(context_data, dict):
        context_data = deepcopy(context_data)
        context_data["sources"] = [
            _annotate_official_source(source, changed_doc_ids=set())
            for source in context_data.get("sources", [])
            if isinstance(source, dict)
        ]
        copied["context_data"] = context_data
    copied.setdefault("stage23_policy", "baseline_passthrough")
    copied.setdefault("filtered_source_doc_ids", [])
    copied.setdefault("recovered_source_doc_ids", [])
    return copied


def _annotate_official_source(
    source: dict[str, Any],
    *,
    changed_doc_ids: set[str],
) -> dict[str, Any]:
    record = dict(source)
    text = str(record.get("text", ""))
    doc_id = str(record.get("logicguard_doc_id") or parse_doc_id_from_source_text(text))
    title = str(record.get("title") or parse_title_from_source_text(text))
    record["logicguard_doc_id"] = doc_id
    record["title"] = title
    record["source_state"] = str(record.get("source_state") or "official_poisoned_context")
    record["recovered_from_changed_doc"] = bool(record.get("recovered_from_changed_doc", False))
    risk_reasons = [str(reason) for reason in record.get("risk_reasons", [])]
    if doc_id in changed_doc_ids and not record["recovered_from_changed_doc"]:
        risk_reasons.append("changed_logicpoison_support")
    record["risk_reasons"] = _dedupe(risk_reasons)
    return record


def _recovered_source(
    clean_source: dict[str, Any],
    *,
    original_source: dict[str, Any],
) -> dict[str, Any]:
    record = dict(clean_source)
    record["id"] = f"stage23-recovered-{original_source.get('id', record.get('id', 'source'))}"
    record["source_state"] = "clean_reference"
    record["recovered_from_changed_doc"] = True
    record["recovered_from_source_id"] = str(original_source.get("id", ""))
    record["risk_reasons"] = [
        "changed_logicpoison_support",
        "sources_level_clean_reference_recovery",
    ]
    return record


def _source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    context_data = row.get("context_data", {})
    sources = context_data.get("sources", []) if isinstance(context_data, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(source.get("logicguard_doc_id") or parse_doc_id_from_source_text(str(source.get("text", ""))))


def _is_recovered_source(source: dict[str, Any]) -> bool:
    return bool(source.get("recovered_from_changed_doc")) or str(source.get("source_state")) == "clean_reference"


def _render_source_context(sources: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        doc_id = _source_doc_id(source)
        title = str(source.get("title") or parse_title_from_source_text(str(source.get("text", ""))))
        state = str(source.get("source_state", "official_poisoned_context"))
        text = " ".join(str(source.get("text", "")).split())
        blocks.append(
            "\n".join(
                [
                    f"[G{index}] doc_id={doc_id}; source_state={state}",
                    f"Title: {title}",
                    f"Text: {text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _write_stage23_report(config: Stage23SourceRecoveryConfig, summaries: list[Stage23SummaryRow]) -> None:
    summary_table = [
        "| method | queries | gold recall | changed exposure | trusted recall | empty context | avg sources | avg source rows | avg recovered | avg filtered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        summary_table.append(
            f"| {row.method} | {row.query_count} | {row.avg_gold_support_recall:.4f} | "
            f"{row.avg_changed_support_exposure:.4f} | {row.avg_trusted_support_recall:.4f} | "
            f"{row.empty_context_rate:.4f} | {row.avg_source_count:.2f} | "
            f"{row.avg_source_row_count:.2f} | {row.avg_recovered_source_count:.2f} | "
            f"{row.avg_filtered_source_count:.2f} |"
        )

    full = next((row for row in summaries if row.method == config.input_method_name), None)
    recovered = next((row for row in summaries if row.method == "recovered_sources_by_doc_id"), None)
    guarded = next((row for row in summaries if row.method == "guarded_sources"), None)
    delta_lines = ["- 缺少 full_query_guard、guarded_sources 或 recovered_sources_by_doc_id，无法计算主变化。"]
    if full and guarded and recovered:
        delta_lines = [
            f"- sources guard 后 changed exposure：{full.avg_changed_support_exposure:.4f} -> {guarded.avg_changed_support_exposure:.4f}。",
            f"- sources guard 后 gold recall：{full.avg_gold_support_recall:.4f} -> {guarded.avg_gold_support_recall:.4f}。",
            f"- sources recovery 后 changed exposure：{full.avg_changed_support_exposure:.4f} -> {recovered.avg_changed_support_exposure:.4f}。",
            f"- sources recovery 后 gold recall：{full.avg_gold_support_recall:.4f} -> {recovered.avg_gold_support_recall:.4f}。",
            f"- sources recovery 平均替换 source 数：{recovered.avg_recovered_source_count:.2f}。",
        ]

    content = "\n".join(
        [
            f"# Microsoft GraphRAG {config.stage_label} sources级Recovery实验报告",
            "",
            "## 实验目的",
            "",
            f"{config.stage_label} 直接读取 official GraphRAG local search 导出的 `context_data.sources`，在官方上下文已经生成之后，对 source 行执行污染标注、过滤与 clean-reference doc_id 替换。该阶段不修改 Microsoft GraphRAG 源码，也不调用回答模型。",
            "",
            "## 重要边界",
            "",
            "- 本阶段是 context-only 评估，回答层正确率和攻击成功率需要后续 LLM 实验验证。",
            "- `recovered_sources_by_doc_id` 是 oracle clean-reference recovery，上界意义强，不能等同于无干净库真实部署。",
            "- 当前只替换 `sources`，不重写 official context 中的 entities、relationships、reports 或 claims。",
            f"- gold support 只在 context 构建完成后用于指标计算，不参与 {config.stage_label} 的 source 替换决策。",
            "",
            "## 指标说明",
            "",
            "- gold recall：sources 中覆盖 gold support doc_id 的比例，越高越可答。",
            "- changed exposure：未恢复的 changed support source 进入 sources 的比例，越低越安全。",
            "- trusted recall：未改写 support 的召回比例；若样本 support 全部被改写，该项分母为空并记为 0。",
            "- empty context：source 过滤或恢复后 sources 是否为空。",
            "- avg recovered：每个 query 平均由 clean reference 替换回来的 source 数。",
            "- avg filtered：每个 query 平均被过滤且未替换的 source doc_id 数。",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## 主对照变化",
            "",
            *delta_lines,
            "",
            "## 产物路径",
            "",
            f"- context JSONL：`{config.context_output_path.as_posix()}`",
            f"- query 指标 CSV：`{config.metrics_output_path.as_posix()}`",
            f"- method 汇总 CSV：`{config.summary_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


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


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def _dedupe(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _avg(values: Any) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage23 source-level recovery over official GraphRAG contexts."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage23_sources_recovery_poisoned5.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(Stage23SourceRecoveryConfig.from_yaml(args.config))
    print(f"stage23_metric_rows={len(rows)}")


if __name__ == "__main__":
    main()
