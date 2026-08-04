"""Path-centric retrieval over the lightweight document-entity graph."""

from __future__ import annotations

from collections import defaultdict

import networkx as nx

from logicguard.data.schemas import NormalizedSample
from logicguard.graph.builder import _entity_node
from logicguard.graph.entities import RuleBasedEntityExtractor
from logicguard.graph.schemas import (
    EntityMention,
    GraphIndex,
    PathCandidate,
    RetrievalTrace,
)


def retrieve_paths_for_query(
    sample: NormalizedSample,
    graph_index: GraphIndex,
    extractor: RuleBasedEntityExtractor,
    top_k: int = 10,
    max_depth: int = 3,
) -> RetrievalTrace:
    """Retrieve candidate documents and paths for one normalized sample.

    `max_depth` counts graph edges after the query entity enters the graph. In a
    document-entity bipartite graph, depth 1 retrieves direct entity mentions,
    while depth 3 can retrieve a second document through a bridge entity:
    `query entity -> doc A -> bridge entity -> doc B`.
    """

    query_entities = extractor.extract(sample.query)
    best_by_doc: dict[str, PathCandidate] = {}

    for query_entity in query_entities:
        start_node = _entity_node(query_entity.normalized)
        if start_node not in graph_index.graph:
            continue
        lengths = nx.single_source_shortest_path_length(
            graph_index.graph,
            start_node,
            cutoff=max_depth,
        )
        paths = nx.single_source_shortest_path(
            graph_index.graph,
            start_node,
            cutoff=max_depth,
        )
        for node, distance in lengths.items():
            if distance == 0 or not node.startswith("doc:"):
                continue
            doc_id = node.removeprefix("doc:")
            candidate = _candidate_from_path(
                sample=sample,
                graph_index=graph_index,
                query_entity=query_entity,
                doc_id=doc_id,
                path=paths[node],
            )
            current = best_by_doc.get(doc_id)
            if current is None or _candidate_sort_key(candidate) > _candidate_sort_key(
                current
            ):
                best_by_doc[doc_id] = candidate

    candidates = sorted(best_by_doc.values(), key=_candidate_sort_key, reverse=True)[
        :top_k
    ]
    return RetrievalTrace(
        query_id=sample.query_id,
        query=sample.query,
        answer=sample.answer,
        gold_doc_ids=sample.support_doc_ids,
        query_entities=query_entities,
        candidates=candidates,
    )


def calculate_retrieval_metrics(
    traces: list[RetrievalTrace],
    top_k: int,
) -> dict[str, float]:
    """Calculate first-pass retrieval metrics for a trace collection."""

    if not traces:
        return {
            "queries": 0.0,
            "hit_at_k": 0.0,
            "gold_recall_at_k": 0.0,
            "avg_candidates": 0.0,
        }

    hit_count = 0
    recall_values: list[float] = []
    candidate_counts: list[int] = []
    for trace in traces:
        retrieved_doc_ids = [candidate.doc_id for candidate in trace.candidates[:top_k]]
        gold_doc_ids = set(trace.gold_doc_ids)
        overlap = gold_doc_ids.intersection(retrieved_doc_ids)
        if overlap:
            hit_count += 1
        recall_values.append(len(overlap) / len(gold_doc_ids) if gold_doc_ids else 0.0)
        candidate_counts.append(len(trace.candidates))

    query_count = len(traces)
    return {
        "queries": float(query_count),
        "hit_at_k": hit_count / query_count,
        "gold_recall_at_k": sum(recall_values) / query_count,
        "avg_candidates": sum(candidate_counts) / query_count,
    }


def summarize_query_entity_coverage(traces: list[RetrievalTrace]) -> dict[str, float]:
    """Report how often the rule extractor found graph-matching query entities."""

    if not traces:
        return {"queries_with_entities": 0.0, "queries_with_candidates": 0.0}
    with_entities = sum(1 for trace in traces if trace.query_entities)
    with_candidates = sum(1 for trace in traces if trace.candidates)
    return {
        "queries_with_entities": with_entities / len(traces),
        "queries_with_candidates": with_candidates / len(traces),
    }


def collect_bridge_entity_counts(traces: list[RetrievalTrace]) -> dict[str, int]:
    """Count bridge entities used by retrieved paths.

    These counts are useful for later LogicGuard BridgeRisk features: entities
    that repeatedly bridge many paths may become suspicious under poisoning.
    """

    counts: dict[str, int] = defaultdict(int)
    for trace in traces:
        for candidate in trace.candidates:
            for entity in candidate.bridge_entities:
                counts[entity] += 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _candidate_from_path(
    sample: NormalizedSample,
    graph_index: GraphIndex,
    query_entity: EntityMention,
    doc_id: str,
    path: list[str],
) -> PathCandidate:
    bridge_entities = [
        node.removeprefix("ent:")
        for node in path[1:-1]
        if node.startswith("ent:") and node != _entity_node(query_entity.normalized)
    ]
    graph_path = [f"query:{sample.query_id}", *path]
    document = graph_index.documents[doc_id]
    score = _score_path(doc_id, sample.support_doc_ids, path, bridge_entities)
    return PathCandidate(
        doc_id=doc_id,
        title=document.title,
        score=score,
        path_nodes=graph_path,
        matched_query_entities=[query_entity.normalized],
        bridge_entities=bridge_entities,
    )


def _score_path(
    doc_id: str,
    gold_doc_ids: list[str],
    path: list[str],
    bridge_entities: list[str],
) -> float:
    """Rank shorter, bridge-rich paths first.

    Gold ids are only used for tie-free debug reporting in this prototype? No:
    avoid leaking gold labels into ranking. The `gold_doc_ids` parameter stays
    unused intentionally for future evaluators and is referenced to make that
    decision explicit.
    """

    _ = gold_doc_ids
    path_length = max(len(path) - 1, 1)
    bridge_bonus = min(len(bridge_entities), 3) * 0.05
    return (1.0 / path_length) + bridge_bonus


def _candidate_sort_key(candidate: PathCandidate) -> tuple[float, int, str]:
    # Higher score first; then prefer shorter paths; then stable document id
    # ordering for deterministic JSONL outputs.
    return (candidate.score, -len(candidate.path_nodes), candidate.doc_id)
