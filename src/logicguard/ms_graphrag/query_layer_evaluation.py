"""Evaluate Stage20 query-layer contexts after retrieval has completed."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.official_local_context import parse_doc_id_from_source_text


_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class QueryLayerMetricRow:
    """One method/query retrieval and safety evaluation row."""

    query_id: str
    query: str
    method: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    trusted_support_doc_ids: list[str]
    context_doc_ids: list[str]
    selected_entities: list[str]
    gold_support_hit_ids: list[str]
    changed_support_hit_ids: list[str]
    trusted_support_hit_ids: list[str]
    support_title_entity_hits: list[str]
    gold_support_recall: float
    changed_support_exposure: float
    trusted_support_recall: float
    support_title_entity_hit_rate: float
    context_recall_failure: bool
    source_count: int
    include_entity_count: int
    exclude_entity_count: int

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            elif isinstance(value, bool):
                output[key] = str(int(value))
            elif isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class QueryLayerMethodSummary:
    """Aggregate Stage20 metrics for one method."""

    method: str
    query_count: int
    avg_gold_support_recall: float
    avg_changed_support_exposure: float
    avg_trusted_support_recall: float
    avg_support_title_entity_hit_rate: float
    context_recall_failure_count: int
    avg_source_count: float
    avg_include_entity_count: float
    avg_exclude_entity_count: float

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            output[key] = f"{value:.4f}" if isinstance(value, float) else str(value)
        return output


@dataclass(frozen=True, slots=True)
class QueryLayerEvaluationConfig:
    """Paths needed to compare baseline, budget, and Stage20 contexts."""

    sample_path: Path
    query_integrity_path: Path
    baseline_context_path: Path
    budget_context_path: Path
    stage20_context_path: Path
    metrics_path: Path
    summary_path: Path
    report_path: Path
    max_queries: int

    @classmethod
    def from_yaml(cls, path: Path) -> "QueryLayerEvaluationConfig":
        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: str) -> Path:
            candidate = Path(raw)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            sample_path=resolve(str(payload["sample_path"])),
            query_integrity_path=resolve(str(payload["query_integrity_path"])),
            baseline_context_path=resolve(str(payload["baseline_context_path"])),
            budget_context_path=resolve(str(payload["budget_expansion_context_path"])),
            stage20_context_path=resolve(str(payload["context_output_path"])),
            metrics_path=resolve(str(payload["metrics_output_path"])),
            summary_path=resolve(str(payload["summary_output_path"])),
            report_path=resolve(str(payload["evaluation_report_path"])),
            max_queries=int(payload.get("max_queries", 5)),
        )


def build_query_layer_metric_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
) -> list[QueryLayerMetricRow]:
    """Compute gold metrics only after contexts have been independently built."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    metric_rows: list[QueryLayerMetricRow] = []
    for context_row in context_rows:
        query_id = str(context_row["query_id"])
        sample = samples_by_query.get(query_id)
        if sample is None:
            raise ValueError(f"Missing evaluation sample for query_id={query_id}")
        integrity = integrity_by_query.get(query_id, {})
        support_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_ids = [str(doc_id) for doc_id in integrity.get("changed_support_doc_ids", [])]
        changed_set = set(changed_ids)
        trusted_ids = [doc_id for doc_id in support_ids if doc_id not in changed_set]
        context_ids = _context_doc_ids(context_row)
        selected_entities = _selected_entities(context_row)
        gold_hits = _ordered_intersection(support_ids, context_ids)
        changed_hits = _ordered_intersection(changed_ids, context_ids)
        trusted_hits = _ordered_intersection(trusted_ids, context_ids)
        support_titles = [doc.title for doc in sample.support_docs]
        title_hits = _title_entity_hits(support_titles, selected_entities)
        metric_rows.append(
            QueryLayerMetricRow(
                query_id=query_id,
                query=sample.query,
                method=str(context_row.get("method", "unknown")),
                support_doc_ids=support_ids,
                changed_support_doc_ids=changed_ids,
                trusted_support_doc_ids=trusted_ids,
                context_doc_ids=context_ids,
                selected_entities=selected_entities,
                gold_support_hit_ids=gold_hits,
                changed_support_hit_ids=changed_hits,
                trusted_support_hit_ids=trusted_hits,
                support_title_entity_hits=title_hits,
                gold_support_recall=_ratio(len(gold_hits), len(support_ids)),
                changed_support_exposure=_ratio(len(changed_hits), len(changed_ids)),
                trusted_support_recall=_ratio(len(trusted_hits), len(trusted_ids)),
                support_title_entity_hit_rate=_ratio(len(title_hits), len(support_titles)),
                context_recall_failure=not gold_hits,
                source_count=len(context_ids),
                include_entity_count=len(context_row.get("include_entity_names", [])),
                exclude_entity_count=len(context_row.get("exclude_entity_names", [])),
            )
        )
    return metric_rows


def summarize_query_layer_metrics(
    rows: list[QueryLayerMetricRow],
) -> list[QueryLayerMethodSummary]:
    grouped: dict[str, list[QueryLayerMetricRow]] = defaultdict(list)
    for row in rows:
        grouped[row.method].append(row)
    summaries: list[QueryLayerMethodSummary] = []
    for method, method_rows in grouped.items():
        summaries.append(
            QueryLayerMethodSummary(
                method=method,
                query_count=len(method_rows),
                avg_gold_support_recall=_average([row.gold_support_recall for row in method_rows]),
                avg_changed_support_exposure=_average(
                    [row.changed_support_exposure for row in method_rows]
                ),
                avg_trusted_support_recall=_average(
                    [row.trusted_support_recall for row in method_rows]
                ),
                avg_support_title_entity_hit_rate=_average(
                    [row.support_title_entity_hit_rate for row in method_rows]
                ),
                context_recall_failure_count=sum(row.context_recall_failure for row in method_rows),
                avg_source_count=_average([float(row.source_count) for row in method_rows]),
                avg_include_entity_count=_average(
                    [float(row.include_entity_count) for row in method_rows]
                ),
                avg_exclude_entity_count=_average(
                    [float(row.exclude_entity_count) for row in method_rows]
                ),
            )
        )
    order = {
        "mixed_baseline": 0,
        "budget_expansion": 1,
        "all_entities_baseline": 2,
        "title_seeding": 3,
        "entity_rerank": 4,
        "cluster_suppression": 5,
        "full_query_guard": 6,
    }
    summaries.sort(key=lambda row: (order.get(row.method, 99), row.method))
    return summaries


def write_query_layer_evaluation(
    *,
    rows: list[QueryLayerMetricRow],
    metrics_path: Path,
    summary_path: Path,
    report_path: Path,
) -> None:
    """Write machine-readable metrics and a Chinese evidence report."""

    summaries = summarize_query_layer_metrics(rows)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with metrics_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(QueryLayerMetricRow.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(QueryLayerMethodSummary.__dataclass_fields__))
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary.to_csv_row())
    _write_evaluation_report(report_path, rows, summaries, metrics_path, summary_path)


def run_from_config(config: QueryLayerEvaluationConfig) -> list[QueryLayerMetricRow]:
    """Merge frozen baseline contexts with new Stage20 variants and evaluate."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    context_rows = [
        _with_method(row, "mixed_baseline")
        for row in _load_jsonl(config.baseline_context_path)
    ]
    context_rows.extend(
        _with_method(row, "budget_expansion")
        for row in _load_jsonl(config.budget_context_path)
    )
    context_rows.extend(_load_jsonl(config.stage20_context_path))
    rows = build_query_layer_metric_rows(
        samples=samples,
        integrity_rows=_load_jsonl(config.query_integrity_path),
        context_rows=context_rows,
    )
    write_query_layer_evaluation(
        rows=rows,
        metrics_path=config.metrics_path,
        summary_path=config.summary_path,
        report_path=config.report_path,
    )
    return rows


def _write_evaluation_report(
    path: Path,
    rows: list[QueryLayerMetricRow],
    summaries: list[QueryLayerMethodSummary],
    metrics_path: Path,
    summary_path: Path,
) -> None:
    summary_table = [
        "| method | queries | gold recall | changed exposure | trusted recall | entity hit | failures | avg sources |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summaries:
        summary_table.append(
            f"| {item.method} | {item.query_count} | {item.avg_gold_support_recall:.4f} | "
            f"{item.avg_changed_support_exposure:.4f} | {item.avg_trusted_support_recall:.4f} | "
            f"{item.avg_support_title_entity_hit_rate:.4f} | "
            f"{item.context_recall_failure_count} | {item.avg_source_count:.2f} |"
        )
    query_table = [
        "| method | query_id | gold recall | changed exposure | trusted recall | entity hit | context docs |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        query_table.append(
            f"| {row.method} | {row.query_id} | {row.gold_support_recall:.4f} | "
            f"{row.changed_support_exposure:.4f} | {row.trusted_support_recall:.4f} | "
            f"{row.support_title_entity_hit_rate:.4f} | {';'.join(row.context_doc_ids)} |"
        )
    baseline = next((item for item in summaries if item.method == "mixed_baseline"), None)
    full = next((item for item in summaries if item.method == "full_query_guard"), None)
    delta_lines = ["- 缺少mixed_baseline或full_query_guard，无法计算主对照。"]
    if baseline and full:
        delta_lines = [
            f"- gold recall变化：{baseline.avg_gold_support_recall:.4f} -> {full.avg_gold_support_recall:.4f}。",
            f"- trusted recall变化：{baseline.avg_trusted_support_recall:.4f} -> {full.avg_trusted_support_recall:.4f}。",
            f"- changed exposure变化：{baseline.avg_changed_support_exposure:.4f} -> {full.avg_changed_support_exposure:.4f}。",
            f"- context完全失败数：{baseline.context_recall_failure_count} -> {full.context_recall_failure_count}。",
        ]
    content = "\n".join([
        "# Microsoft GraphRAG Stage20 Query-layer检索实验报告",
        "",
        "## 实验目的",
        "",
        "在同一poisoned mixed graph上比较原始local search、仅扩大预算和四种Query Guard消融。候选生成不读取gold；本报告仅在context生成后使用gold计算指标。",
        "",
        "## 指标说明",
        "",
        "- gold recall：official sources覆盖全部gold support的平均比例。",
        "- changed exposure：已改写support进入context的比例；越低越安全，但必须结合recovery解释。",
        "- trusted recall：未改写support进入context的比例。",
        "- entity hit：support标题进入selected entities的比例。",
        "- failures：完全没有gold support的query数。",
        "",
        "## 方法汇总",
        "",
        *summary_table,
        "",
        "## 主对照变化",
        "",
        *delta_lines,
        "",
        "## Query级结果",
        "",
        *query_table,
        "",
        "## 证据与限制",
        "",
        "- 证据：所有方法使用相同五个query和同一个mixed graph。",
        "- 推断：若seeding提高recall，说明错误主要位于query-to-entity mapping，而不是context token不足。",
        "- 限制：五Query只能验证原型机制，不能支持统计外推。",
        "- 限制：changed exposure上升可能是Recovery获得可替换文档的前提，不可单独解释为安全性退化或提升。",
        "",
        f"- query级CSV：{metrics_path.as_posix()}",
        f"- 汇总CSV：{summary_path.as_posix()}",
        "",
    ])
    path.write_text(content, encoding="utf-8")


def _context_doc_ids(row: dict[str, Any]) -> list[str]:
    context = row.get("context_data", {})
    sources = context.get("sources", []) if isinstance(context, dict) else []
    doc_ids: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        doc_id = str(
            source.get("logicguard_doc_id")
            or parse_doc_id_from_source_text(str(source.get("text", "")))
        )
        if doc_id and doc_id not in doc_ids:
            doc_ids.append(doc_id)
    return doc_ids


def _selected_entities(row: dict[str, Any]) -> list[str]:
    context = row.get("context_data", {})
    entities = context.get("entities", []) if isinstance(context, dict) else []
    names: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("entity") or entity.get("title") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _title_entity_hits(titles: list[str], entities: list[str]) -> list[str]:
    normalized_entities = {_normalize(entity) for entity in entities}
    return [title for title in titles if _normalize(title) in normalized_entities]


def _normalize(value: str) -> str:
    return " ".join(token.casefold() for token in _TOKEN_PATTERN.findall(value))


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _with_method(row: dict[str, Any], method: str) -> dict[str, Any]:
    return {**row, "method": method}


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage20 query-layer contexts.")
    parser.add_argument("--config", type=Path, default=Path("configs/ms_graphrag_query_layer_stage20.yaml"))
    args = parser.parse_args()
    rows = run_from_config(QueryLayerEvaluationConfig.from_yaml(args.config))
    print(f"stage20_metric_rows={len(rows)}")


if __name__ == "__main__":
    main()
