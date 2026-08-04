"""Diagnose selected entities in official GraphRAG local contexts."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.official_context_recall import _extract_context_doc_ids
from logicguard.ms_graphrag.official_query_metrics import load_jsonl_records

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class OfficialEntityDiagnosticRow:
    """One query-level selected-entity diagnosis."""

    query_id: str
    query: str
    expected_answer: str
    support_doc_ids: list[str]
    support_titles: list[str]
    context_doc_ids: list[str]
    selected_entity_names: list[str]
    selected_entity_ids: list[str]
    selected_entity_ranks: list[str]
    top_entity_names: list[str]
    support_title_entity_hits: list[str]
    support_title_entity_hit_rate: float
    recall_diagnosis: str

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
class OfficialEntityDiagnosticSummary:
    """Aggregate selected-entity diagnosis."""

    query_count: int
    avg_support_title_entity_hit_rate: float
    zero_support_title_hit_count: int
    repeated_top_entity_query_count: int
    most_common_top_entities: list[tuple[str, int]]


def build_entity_diagnostic_rows(
    *,
    samples: list[NormalizedSample],
    context_rows: list[dict[str, Any]],
    recall_rows: list[dict[str, Any]],
) -> list[OfficialEntityDiagnosticRow]:
    """Build query-level rows from official context entities."""

    context_by_query = {
        str(row["query_id"]): row
        for row in context_rows
        if row.get("query_id") is not None
    }
    recall_by_query = {
        str(row["query_id"]): row
        for row in recall_rows
        if row.get("query_id") is not None
    }
    rows: list[OfficialEntityDiagnosticRow] = []
    for sample in samples:
        context = context_by_query.get(sample.query_id, {})
        entity_records = _extract_entity_records(context)
        selected_entity_names = [record["name"] for record in entity_records]
        support_titles = [doc.title for doc in sample.support_docs]
        title_hits = _support_title_hits(support_titles, selected_entity_names)
        rows.append(
            OfficialEntityDiagnosticRow(
                query_id=sample.query_id,
                query=sample.query,
                expected_answer=sample.answer,
                support_doc_ids=[str(doc_id) for doc_id in sample.support_doc_ids],
                support_titles=support_titles,
                context_doc_ids=_extract_context_doc_ids(context),
                selected_entity_names=selected_entity_names,
                selected_entity_ids=[record["id"] for record in entity_records],
                selected_entity_ranks=[record["rank"] for record in entity_records],
                top_entity_names=selected_entity_names[:5],
                support_title_entity_hits=title_hits,
                support_title_entity_hit_rate=len(title_hits) / len(support_titles)
                if support_titles
                else 0.0,
                recall_diagnosis=str(
                    recall_by_query.get(sample.query_id, {}).get("diagnosis", "")
                ),
            )
        )
    return rows


def summarize_entity_diagnostics(
    rows: list[OfficialEntityDiagnosticRow],
) -> OfficialEntityDiagnosticSummary:
    """Summarize selected-entity patterns across queries."""

    top_counter: Counter[str] = Counter()
    for row in rows:
        top_counter.update(row.top_entity_names[:1])
    repeated_top_entity_query_count = sum(
        count for _entity, count in top_counter.items() if count > 1
    )
    return OfficialEntityDiagnosticSummary(
        query_count=len(rows),
        avg_support_title_entity_hit_rate=_average(
            row.support_title_entity_hit_rate for row in rows
        ),
        zero_support_title_hit_count=sum(
            1 for row in rows if row.support_title_entity_hit_rate == 0
        ),
        repeated_top_entity_query_count=repeated_top_entity_query_count,
        most_common_top_entities=top_counter.most_common(10),
    )


def write_entity_diagnostic_artifacts(
    *,
    csv_path: Path,
    report_path: Path,
    rows: list[OfficialEntityDiagnosticRow],
    source_context_path: Path,
    source_recall_path: Path | None,
) -> None:
    """Write selected-entity CSV and Chinese markdown report."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(OfficialEntityDiagnosticRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())

    summary = summarize_entity_diagnostics(rows)
    table_lines = [
        "| query_id | recall_diagnosis | hit_rate | support_titles | top_entity_names | context_doc_ids |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.query_id,
                    row.recall_diagnosis,
                    f"{row.support_title_entity_hit_rate:.4f}",
                    ";".join(row.support_titles).replace("|", "/"),
                    ";".join(row.top_entity_names).replace("|", "/"),
                    ";".join(row.context_doc_ids),
                ]
            )
            + " |"
        )

    common_entities = (
        ", ".join(
            f"{name}({count})" for name, count in summary.most_common_top_entities
        )
        or "无"
    )
    content = "\n".join(
        [
            "# Microsoft GraphRAG selected entities 诊断报告",
            "",
            "## 实体诊断指标说明",
            "",
            "- `selected_entity_names`：official local context 中实际出现的实体名称。",
            "- `selected_entity_ranks`：实体表中的排序信号，当前主要来自 `number of relationships`。",
            "- `support_title_entity_hit_rate`：support document 标题是否出现在 selected entities 中的比例。",
            "- `most_common_top_entities`：多个 query 的第一实体是否反复集中到同一实体。",
            "",
            "## 汇总",
            "",
            f"- query_count：`{summary.query_count}`",
            f"- avg_support_title_entity_hit_rate：`{summary.avg_support_title_entity_hit_rate:.4f}`",
            f"- zero_support_title_hit_count：`{summary.zero_support_title_hit_count}`",
            f"- repeated_top_entity_query_count：`{summary.repeated_top_entity_query_count}`",
            f"- most_common_top_entities：`{common_entities}`",
            "",
            "## Query 明细",
            "",
            *table_lines,
            "",
            "## 产物路径",
            "",
            f"- source context：`{source_context_path.as_posix()}`",
            f"- source recall：`{source_recall_path.as_posix()}`"
            if source_recall_path
            else "- source recall：未提供",
            f"- CSV：`{csv_path.as_posix()}`",
            f"- report：`{report_path.as_posix()}`",
            "",
        ]
    )
    report_path.write_text(content, encoding="utf-8")


def _extract_entity_records(context_row: dict[str, Any]) -> list[dict[str, str]]:
    context_data = context_row.get("context_data", {})
    if not isinstance(context_data, dict):
        return []
    entities = context_data.get("entities", [])
    if not isinstance(entities, list):
        return []
    records: list[dict[str, str]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("entity") or entity.get("title") or "").strip()
        if not name:
            continue
        records.append(
            {
                "id": str(entity.get("id", "")),
                "name": name,
                "rank": str(
                    entity.get("number of relationships", entity.get("rank", ""))
                ),
            }
        )
    return records


def _support_title_hits(
    support_titles: list[str], selected_entities: list[str]
) -> list[str]:
    normalized_entities = {_normalize_text(entity) for entity in selected_entities}
    return [
        title
        for title in support_titles
        if _normalize_text(title) in normalized_entities
    ]


def _normalize_text(value: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(value.lower()))


def _average(values: Any) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


def _load_csv_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose selected entities in official GraphRAG local context."
    )
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--recall", type=Path, default=None)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    rows = build_entity_diagnostic_rows(
        samples=load_normalized_samples(args.samples),
        context_rows=load_jsonl_records(args.contexts),
        recall_rows=_load_csv_records(args.recall),
    )
    write_entity_diagnostic_artifacts(
        csv_path=args.csv,
        report_path=args.report,
        rows=rows,
        source_context_path=args.contexts,
        source_recall_path=args.recall,
    )
    summary = summarize_entity_diagnostics(rows)
    print(
        f"diagnosed {summary.query_count} queries: "
        f"avg_support_title_entity_hit_rate={summary.avg_support_title_entity_hit_rate:.4f}, "
        f"repeated_top_entity_query_count={summary.repeated_top_entity_query_count}"
    )


if __name__ == "__main__":
    main()
