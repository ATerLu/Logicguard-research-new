"""Runnable lightweight GraphRAG baseline.

This module wires together the small graph components:

1. extract entities from corpus documents,
2. build a document-entity bipartite graph,
3. retrieve path-centric candidates for each query,
4. write trace artifacts and a compact Markdown report.

The implementation is intentionally transparent rather than clever. The goal is
to create auditable traces that LogicGuard can score in later phases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.builder import build_document_entity_graph
from logicguard.graph.entities import RuleBasedEntityExtractor
from logicguard.graph.retriever import (
    calculate_retrieval_metrics,
    collect_bridge_entity_counts,
    retrieve_paths_for_query,
    summarize_query_entity_coverage,
)
from logicguard.graph.schemas import DocumentEntities, QueryEntities, RetrievalTrace


@dataclass(frozen=True, slots=True)
class BaselineOutputPaths:
    """All files written by one baseline run."""

    trace_path: Path
    corpus_entity_cache_path: Path
    query_entity_cache_path: Path
    report_path: Path

    def ensure_parent_dirs(self) -> None:
        for path in (
            self.trace_path,
            self.corpus_entity_cache_path,
            self.query_entity_cache_path,
            self.report_path,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class BaselineRunSummary:
    """High-level metrics for a baseline run."""

    dataset: str
    query_count: int
    corpus_doc_count: int
    graph_nodes: int
    graph_edges: int
    top_k: int
    max_depth: int
    hit_at_k: float
    gold_recall_at_k: float
    avg_candidates: float
    queries_with_entities: float
    queries_with_candidates: float


def run_graphrag_baseline(
    dataset_name: str,
    samples: list[NormalizedSample],
    corpus_documents: list[CorpusDocument],
    outputs: BaselineOutputPaths,
    top_k: int = 10,
    max_depth: int = 3,
) -> BaselineRunSummary:
    """Run the lightweight GraphRAG baseline and write all artifacts."""

    outputs.ensure_parent_dirs()
    extractor = RuleBasedEntityExtractor()
    graph_index = build_document_entity_graph(corpus_documents, extractor)
    traces = [
        retrieve_paths_for_query(
            sample, graph_index, extractor, top_k=top_k, max_depth=max_depth
        )
        for sample in samples
    ]

    query_entity_cache = [
        QueryEntities(
            query_id=trace.query_id,
            query=trace.query,
            entities=trace.query_entities,
        )
        for trace in traces
    ]

    _write_document_entities(
        outputs.corpus_entity_cache_path, graph_index.document_entities.values()
    )
    _write_query_entities(outputs.query_entity_cache_path, query_entity_cache)
    _write_traces(outputs.trace_path, traces)

    metrics = calculate_retrieval_metrics(traces, top_k=top_k)
    coverage = summarize_query_entity_coverage(traces)
    summary = BaselineRunSummary(
        dataset=dataset_name,
        query_count=len(samples),
        corpus_doc_count=len(corpus_documents),
        graph_nodes=graph_index.graph.number_of_nodes(),
        graph_edges=graph_index.graph.number_of_edges(),
        top_k=top_k,
        max_depth=max_depth,
        hit_at_k=metrics["hit_at_k"],
        gold_recall_at_k=metrics["gold_recall_at_k"],
        avg_candidates=metrics["avg_candidates"],
        queries_with_entities=coverage["queries_with_entities"],
        queries_with_candidates=coverage["queries_with_candidates"],
    )
    _write_report(outputs.report_path, summary, collect_bridge_entity_counts(traces))
    return summary


def _write_document_entities(path: Path, document_entities: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in document_entities:
            if not isinstance(item, DocumentEntities):
                raise TypeError(f"Expected DocumentEntities, got {type(item)!r}")
            handle.write(json.dumps(item.to_json_dict(), ensure_ascii=False) + "\n")


def _write_query_entities(path: Path, query_entities: list[QueryEntities]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in query_entities:
            handle.write(json.dumps(item.to_json_dict(), ensure_ascii=False) + "\n")


def _write_traces(path: Path, traces: list[RetrievalTrace]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace.to_json_dict(), ensure_ascii=False) + "\n")


def _write_report(
    path: Path,
    summary: BaselineRunSummary,
    bridge_entity_counts: dict[str, int],
) -> None:
    top_bridges = list(bridge_entity_counts.items())[:10]
    bridge_lines = (
        [f"- `{entity}`: {count}" for entity, count in top_bridges]
        if top_bridges
        else ["- 未观察到桥接实体。"]
    )
    content = "\n".join(
        [
            f"# 轻量 GraphRAG 检索基线报告：{summary.dataset}",
            "",
            "## 实验设置",
            "",
            f"- Query 数量：`{summary.query_count}`",
            f"- 已索引语料文档数：`{summary.corpus_doc_count}`",
            f"- Top-k：`{summary.top_k}`",
            f"- 最大图搜索深度：`{summary.max_depth}`",
            "",
            "## 图结构统计",
            "",
            f"- 节点数：`{summary.graph_nodes}`",
            f"- 边数：`{summary.graph_edges}`",
            "",
            "## 检索指标",
            "",
            f"- hit@{summary.top_k}: `{summary.hit_at_k:.4f}`",
            f"- gold_recall@{summary.top_k}: `{summary.gold_recall_at_k:.4f}`",
            f"- 平均候选数/Query：`{summary.avg_candidates:.2f}`",
            f"- 成功抽取实体的 Query 比例：`{summary.queries_with_entities:.4f}`",
            f"- 有候选证据的 Query 比例：`{summary.queries_with_candidates:.4f}`",
            "",
            "## 高频桥接实体",
            "",
            *bridge_lines,
            "",
            "## 指标说明",
            "",
            f"- `hit@{summary.top_k}`：top-{summary.top_k} 中是否命中至少一个 gold support。",
            f"- `gold_recall@{summary.top_k}`：top-{summary.top_k} 覆盖 gold support 的平均比例。",
            "- `平均候选数/Query`：每个问题平均返回的路径候选文档数量。",
            "- `桥接实体`：查询实体与候选文档之间路径中出现的中间实体，用于后续 LogicGuard 路径风险分析。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
