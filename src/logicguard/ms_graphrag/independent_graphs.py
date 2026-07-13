"""Prepare and compare per-query independent Microsoft GraphRAG graphs.

Stage18 tests a concrete hypothesis from Stage17: the 5-query mixed official
GraphRAG index may hurt local-search recall because unrelated queries compete
inside one entity space.  This module keeps the experiment reproducible by
splitting the selected samples into one-query artifacts, preparing one
query-ready GraphRAG workspace per query, and summarizing mixed-vs-independent
recall/entity diagnostics after the official contexts are exported.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.minimal_workflow import (
    MsGraphRagMinimalConfig,
    prepare_ms_graphrag_query_ready_workspace,
)

_SAFE_SLUG_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class Stage18IndependentGraphConfig:
    """Configuration for preparing one official GraphRAG workspace per query."""

    dataset: str
    sample_path: Path
    poisoned_corpus_path: Path
    sample_output_root: Path
    workspace_root: Path
    template_root: Path
    manifest_path: Path
    max_queries: int = 5
    completion_model: str = "qwen3.7-plus"
    embedding_model: str = "text-embedding-v4"
    vector_size: int = 1024
    embedding_batch_size: int = 10


@dataclass(frozen=True, slots=True)
class Stage18ComparisonRow:
    """One query-level comparison between mixed and independent GraphRAG indexes."""

    query_id: str
    mixed_gold_support_recall: float
    independent_gold_support_recall: float
    gold_support_recall_delta: float
    mixed_support_title_entity_hit_rate: float
    independent_support_title_entity_hit_rate: float
    support_title_entity_hit_rate_delta: float
    mixed_diagnosis: str
    independent_diagnosis: str
    recall_status: str
    mixed_context_doc_ids: str
    independent_context_doc_ids: str
    mixed_top_entity_names: str
    independent_top_entity_names: str

    def to_csv_row(self) -> dict[str, str]:
        """Return stable string values so downstream reports stay deterministic."""

        row = asdict(self)
        output: dict[str, str] = {}
        for key, value in row.items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            else:
                output[key] = str(value)
        return output


def prepare_independent_query_ready_workspaces(config: Stage18IndependentGraphConfig) -> dict[str, Any]:
    """Split a multi-query sample file and prepare one poisoned workspace per query.

    The function does not run GraphRAG indexing.  It only creates deterministic
    inputs, prompts, settings, and manifests.  This separation makes it safe to
    rerun preparation without accidentally hiding indexing failures.
    """

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    if not samples:
        raise ValueError(f"No samples found in {config.sample_path}")

    config.sample_output_root.mkdir(parents=True, exist_ok=True)
    config.workspace_root.mkdir(parents=True, exist_ok=True)

    workspace_entries: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        query_slug = _query_slug(index, sample.query_id)
        per_query_sample_path = config.sample_output_root / f"{query_slug}.jsonl"
        per_query_workspace_root = config.workspace_root / f"{query_slug}_poisoned_query_ready"

        _write_single_sample(per_query_sample_path, sample)
        workspace_manifest = prepare_ms_graphrag_query_ready_workspace(
            MsGraphRagMinimalConfig(
                dataset=config.dataset,
                sample_path=per_query_sample_path,
                corpus_path=config.poisoned_corpus_path,
                workspace_root=per_query_workspace_root,
                template_root=config.template_root,
                doc_scope="sample_support",
                # In a poisoned-corpus experiment, silently falling back to
                # embedded clean text would make recall look better than it is.
                missing_support_policy="skip",
                completion_model=config.completion_model,
                embedding_model=config.embedding_model,
                vector_size=config.vector_size,
                embedding_batch_size=config.embedding_batch_size,
            )
        )
        workspace_entries.append(
            {
                "index": index,
                "query_id": sample.query_id,
                "query": sample.query,
                "answer": sample.answer,
                "support_doc_ids": [str(doc_id) for doc_id in sample.support_doc_ids],
                "sample_path": str(per_query_sample_path.resolve()),
                "workspace_root": str(per_query_workspace_root.resolve()),
                "input_doc_count": workspace_manifest["input_doc_count"],
                "ms_graphrag_workflow": workspace_manifest["ms_graphrag_workflow"],
            }
        )

    manifest = {
        "stage": "Stage18",
        "dataset": config.dataset,
        "source_sample_path": str(config.sample_path.resolve()),
        "poisoned_corpus_path": str(config.poisoned_corpus_path.resolve()),
        "sample_output_root": str(config.sample_output_root.resolve()),
        "workspace_root": str(config.workspace_root.resolve()),
        "selected_query_count": len(workspace_entries),
        "completion_model": config.completion_model,
        "embedding_model": config.embedding_model,
        "vector_size": config.vector_size,
        "embedding_batch_size": config.embedding_batch_size,
        "workspaces": workspace_entries,
        "notes": [
            "Each workspace contains exactly one query's support documents from the poisoned corpus.",
            "Run GraphRAG indexing separately with `graphrag index --root <workspace>`.",
            "After indexing, export official local contexts and compare recall/entity diagnostics.",
        ],
    }
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    config.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_independent_graph_comparison_rows(
    *,
    mixed_recall_rows: list[dict[str, Any]],
    independent_recall_rows: list[dict[str, Any]],
    mixed_entity_rows: list[dict[str, Any]],
    independent_entity_rows: list[dict[str, Any]],
) -> list[Stage18ComparisonRow]:
    """Join mixed and independent diagnostics into query-level comparison rows."""

    independent_recall_by_query = _index_by_query_id(independent_recall_rows)
    mixed_entity_by_query = _index_by_query_id(mixed_entity_rows)
    independent_entity_by_query = _index_by_query_id(independent_entity_rows)

    rows: list[Stage18ComparisonRow] = []
    for mixed_recall in mixed_recall_rows:
        query_id = str(mixed_recall.get("query_id", ""))
        independent_recall = independent_recall_by_query.get(query_id, {})
        mixed_entity = mixed_entity_by_query.get(query_id, {})
        independent_entity = independent_entity_by_query.get(query_id, {})

        mixed_recall_value = _float_field(mixed_recall, "gold_support_recall")
        independent_recall_value = _float_field(independent_recall, "gold_support_recall")
        mixed_entity_hit_rate = _float_field(mixed_entity, "support_title_entity_hit_rate")
        independent_entity_hit_rate = _float_field(independent_entity, "support_title_entity_hit_rate")

        recall_delta = independent_recall_value - mixed_recall_value
        entity_delta = independent_entity_hit_rate - mixed_entity_hit_rate
        rows.append(
            Stage18ComparisonRow(
                query_id=query_id,
                mixed_gold_support_recall=mixed_recall_value,
                independent_gold_support_recall=independent_recall_value,
                gold_support_recall_delta=recall_delta,
                mixed_support_title_entity_hit_rate=mixed_entity_hit_rate,
                independent_support_title_entity_hit_rate=independent_entity_hit_rate,
                support_title_entity_hit_rate_delta=entity_delta,
                mixed_diagnosis=str(mixed_recall.get("diagnosis", "")),
                independent_diagnosis=str(independent_recall.get("diagnosis", "")),
                recall_status=_recall_status(recall_delta),
                mixed_context_doc_ids=str(mixed_recall.get("context_doc_ids", "")),
                independent_context_doc_ids=str(independent_recall.get("context_doc_ids", "")),
                mixed_top_entity_names=str(mixed_entity.get("top_entity_names", "")),
                independent_top_entity_names=str(independent_entity.get("top_entity_names", "")),
            )
        )
    return rows


def write_stage18_comparison_artifacts(
    *,
    csv_path: Path,
    report_path: Path,
    rows: list[Stage18ComparisonRow],
    mixed_context_label: str,
    independent_context_label: str,
) -> None:
    """Write Stage18 comparison CSV and a readable Chinese markdown report."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(Stage18ComparisonRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())

    query_count = len(rows)
    avg_mixed_recall = _average(row.mixed_gold_support_recall for row in rows)
    avg_independent_recall = _average(row.independent_gold_support_recall for row in rows)
    avg_mixed_entity_hit = _average(row.mixed_support_title_entity_hit_rate for row in rows)
    avg_independent_entity_hit = _average(row.independent_support_title_entity_hit_rate for row in rows)
    improved_count = sum(1 for row in rows if row.recall_status == "improved")
    unchanged_count = sum(1 for row in rows if row.recall_status == "unchanged")
    worse_count = sum(1 for row in rows if row.recall_status == "worse")

    table_lines = [
        "| query_id | recall变化 | mixed recall | independent recall | mixed实体命中 | independent实体命中 | mixed top entities | independent top entities |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.query_id,
                    row.recall_status,
                    f"{row.mixed_gold_support_recall:.4f}",
                    f"{row.independent_gold_support_recall:.4f}",
                    f"{row.mixed_support_title_entity_hit_rate:.4f}",
                    f"{row.independent_support_title_entity_hit_rate:.4f}",
                    _compact_cell(row.mixed_top_entity_names),
                    _compact_cell(row.independent_top_entity_names),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Stage18 Microsoft GraphRAG 独立图对比报告",
            "",
            "## 实验目的",
            "",
            (
                "Stage18 用来验证一个具体假设：5-query mixed graph 的召回失败，"
                "是否主要来自多个问题混在同一个 GraphRAG 实体空间后产生的实体映射偏移。"
                "因此本阶段把同一批 query 拆成 per-query independent graph，再和 mixed graph 对比。"
            ),
            "",
            "## 指标说明",
            "",
            "- `gold_support_recall`：official local context 中命中的 gold support doc 比例，越高说明正确证据越容易进入回答上下文。",
            "- `support_title_entity_hit_rate`：support 文档标题是否进入 selected entities，越高说明 query-to-entity mapping 越贴近目标问题。",
            "- `recall变化`：independent graph 相比 mixed graph 的召回变化，`improved` 表示独立建图后召回更好。",
            "",
            "## 汇总结果",
            "",
            f"- mixed graph：`{mixed_context_label}`",
            f"- independent graph：`{independent_context_label}`",
            f"- query_count：`{query_count}`",
            f"- avg_mixed_gold_support_recall：`{avg_mixed_recall:.4f}`",
            f"- avg_independent_gold_support_recall：`{avg_independent_recall:.4f}`",
            f"- avg_mixed_support_title_entity_hit_rate：`{avg_mixed_entity_hit:.4f}`",
            f"- avg_independent_support_title_entity_hit_rate：`{avg_independent_entity_hit:.4f}`",
            f"- improved_count：`{improved_count}`",
            f"- unchanged_count：`{unchanged_count}`",
            f"- worse_count：`{worse_count}`",
            "",
            "## Query 明细",
            "",
            *table_lines,
            "",
            "## 初步解释",
            "",
            (
                "如果 independent graph 的召回明显高于 mixed graph，说明当前瓶颈更偏向 GraphRAG "
                "local search 的实体映射和实体竞争，而不是 LogicGuard 的 recovery 规则本身。"
            ),
            "",
            "## 产物路径",
            "",
            f"- CSV：`{csv_path.as_posix()}`",
            f"- 报告：`{report_path.as_posix()}`",
            "",
        ]
    )
    report_path.write_text(content, encoding="utf-8")


def _write_single_sample(path: Path, sample: NormalizedSample) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sample.to_json_dict(), ensure_ascii=False) + "\n", encoding="utf-8")


def _query_slug(index: int, query_id: str) -> str:
    safe = _SAFE_SLUG_PATTERN.sub("_", query_id).strip("._")
    return f"{index:02d}_{safe or 'query'}"


def _index_by_query_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["query_id"]): row for row in rows if row.get("query_id") is not None}


def _float_field(row: dict[str, Any], field_name: str) -> float:
    raw_value = row.get(field_name, 0.0)
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 0.0


def _recall_status(delta: float) -> str:
    if delta > 1e-9:
        return "improved"
    if delta < -1e-9:
        return "worse"
    return "unchanged"


def _average(values: Any) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


def _compact_cell(value: str, max_chars: int = 120) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _load_csv_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage18 per-query independent GraphRAG utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Prepare one query-ready workspace per query.")
    prepare_parser.add_argument("--dataset", required=True)
    prepare_parser.add_argument("--samples", type=Path, required=True)
    prepare_parser.add_argument("--poisoned-corpus", type=Path, required=True)
    prepare_parser.add_argument("--sample-output-root", type=Path, required=True)
    prepare_parser.add_argument("--workspace-root", type=Path, required=True)
    prepare_parser.add_argument("--template-root", type=Path, default=Path("outputs/ms_graphrag/template"))
    prepare_parser.add_argument("--manifest", type=Path, required=True)
    prepare_parser.add_argument("--max-queries", type=int, default=5)
    prepare_parser.add_argument("--completion-model", default="qwen3.7-plus")
    prepare_parser.add_argument("--embedding-model", default="text-embedding-v4")
    prepare_parser.add_argument("--vector-size", type=int, default=1024)
    prepare_parser.add_argument("--embedding-batch-size", type=int, default=10)

    compare_parser = subparsers.add_parser("compare", help="Compare mixed and independent recall/entity CSVs.")
    compare_parser.add_argument("--mixed-recall", type=Path, required=True)
    compare_parser.add_argument("--independent-recall", type=Path, required=True)
    compare_parser.add_argument("--mixed-entities", type=Path, required=True)
    compare_parser.add_argument("--independent-entities", type=Path, required=True)
    compare_parser.add_argument("--csv", type=Path, required=True)
    compare_parser.add_argument("--report", type=Path, required=True)
    compare_parser.add_argument("--mixed-label", default="5-query mixed graph")
    compare_parser.add_argument("--independent-label", default="per-query independent graph")

    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare_independent_query_ready_workspaces(
            Stage18IndependentGraphConfig(
                dataset=args.dataset,
                sample_path=args.samples,
                poisoned_corpus_path=args.poisoned_corpus,
                sample_output_root=args.sample_output_root,
                workspace_root=args.workspace_root,
                template_root=args.template_root,
                manifest_path=args.manifest,
                max_queries=args.max_queries,
                completion_model=args.completion_model,
                embedding_model=args.embedding_model,
                vector_size=args.vector_size,
                embedding_batch_size=args.embedding_batch_size,
            )
        )
        print(
            f"prepared Stage18 independent workspaces: "
            f"queries={manifest['selected_query_count']}, root={manifest['workspace_root']}"
        )
    else:
        rows = build_independent_graph_comparison_rows(
            mixed_recall_rows=_load_csv_records(args.mixed_recall),
            independent_recall_rows=_load_csv_records(args.independent_recall),
            mixed_entity_rows=_load_csv_records(args.mixed_entities),
            independent_entity_rows=_load_csv_records(args.independent_entities),
        )
        write_stage18_comparison_artifacts(
            csv_path=args.csv,
            report_path=args.report,
            rows=rows,
            mixed_context_label=args.mixed_label,
            independent_context_label=args.independent_label,
        )
        print(f"wrote Stage18 comparison rows={len(rows)} csv={args.csv}")


if __name__ == "__main__":
    main()
