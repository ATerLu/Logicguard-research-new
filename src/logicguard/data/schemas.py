"""Typed data contracts shared by the LogicGuard data pipeline.

The project will later add graph construction, poisoning metadata, and retrieval
traces. Keeping these small schemas separate from file I/O makes those later
modules depend on stable Python objects instead of raw JSON dictionaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class QueryRecord:
    """A question from a multi-hop QA benchmark."""

    query_id: str
    text: str


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """The gold answer paired with one benchmark question."""

    query_id: str
    answer: str


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """One source document available to the retriever or graph builder."""

    doc_id: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class RawDataset:
    """A loaded benchmark split before LogicGuard-specific normalization."""

    name: str
    queries: dict[str, QueryRecord]
    answers: dict[str, AnswerRecord]
    corpus: dict[str, CorpusDocument]
    qrels: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class NormalizedSample:
    """One self-contained sample used by retrieval, poisoning, and evaluation.

    `support_doc_ids` preserves the benchmark qrels order. `support_docs` embeds
    the referenced document records so downstream code can build entity graphs
    without repeatedly joining query, answer, qrels, and corpus tables.
    """

    query_id: str
    query: str
    answer: str
    support_doc_ids: list[str]
    support_docs: list[CorpusDocument]

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation with stable field names."""

        return {
            "query_id": self.query_id,
            "query": self.query,
            "answer": self.answer,
            "support_doc_ids": self.support_doc_ids,
            "support_docs": [asdict(doc) for doc in self.support_docs],
        }
