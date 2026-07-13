"""Typed objects for the lightweight GraphRAG baseline.

These classes are intentionally small and serializable. Later phases can attach
poison labels, risk scores, or provenance without changing the raw data loader.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import networkx as nx

from logicguard.data.schemas import CorpusDocument


@dataclass(frozen=True, slots=True)
class EntityMention:
    """One extracted entity-like phrase.

    `text` preserves the surface form for reports. `normalized` is the stable
    graph key used for matching query entities to document entities.
    """

    text: str
    normalized: str
    label: str = "RULE"


@dataclass(frozen=True, slots=True)
class DocumentEntities:
    """Entity extraction result for one corpus document."""

    doc_id: str
    title: str
    entities: list[EntityMention]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "entities": [asdict(entity) for entity in self.entities],
        }


@dataclass(frozen=True, slots=True)
class QueryEntities:
    """Entity extraction result for one benchmark query."""

    query_id: str
    query: str
    entities: list[EntityMention]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "entities": [asdict(entity) for entity in self.entities],
        }


@dataclass(slots=True)
class GraphIndex:
    """Document-entity bipartite graph plus lookup tables for retrieval."""

    graph: nx.Graph
    documents: dict[str, CorpusDocument]
    document_entities: dict[str, DocumentEntities]
    entity_to_docs: dict[str, set[str]]


@dataclass(frozen=True, slots=True)
class PathCandidate:
    """One retrieved document with the best graph path found for a query."""

    doc_id: str
    title: str
    score: float
    path_nodes: list[str]
    matched_query_entities: list[str]
    bridge_entities: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    """Full retrieval trace for one query.

    The trace is the key audit artifact for LogicGuard. Defense modules will
    score these paths instead of treating retrieval as a black box.
    """

    query_id: str
    query: str
    answer: str
    gold_doc_ids: list[str]
    query_entities: list[EntityMention]
    candidates: list[PathCandidate]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "answer": self.answer,
            "gold_doc_ids": self.gold_doc_ids,
            "query_entities": [asdict(entity) for entity in self.query_entities],
            "candidates": [candidate.to_json_dict() for candidate in self.candidates],
        }
