"""Serializable contracts for LogicGuard defense reports.

The first LogicGuard version is intentionally model-free. These dataclasses
capture enough evidence to audit why a candidate was penalized, which is more
useful at this stage than a black-box risk score.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CandidateRiskScore:
    """Path-level risk score for one retrieved document candidate."""

    query_id: str
    doc_id: str
    base_score: float
    risk_score: float
    adjusted_score: float
    path_length: int
    direct_query_match: bool
    source_support_count: int
    global_support_count: int | None
    known_source_document: bool | None
    reference_content_changed: bool | None
    risk_reasons: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RerankedCandidate:
    """One candidate after LogicGuard applies a risk penalty."""

    doc_id: str
    title: str
    original_rank: int
    new_rank: int
    base_score: float
    risk_score: float
    adjusted_score: float
    path_length: int
    direct_query_match: bool
    source_support_count: int
    global_support_count: int | None
    known_source_document: bool | None
    reference_content_changed: bool | None
    matched_query_entities: list[str]
    bridge_entities: list[str]
    risk_reasons: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RerankedTrace:
    """Reranked retrieval trace used by offline defense evaluation."""

    query_id: str
    query: str
    answer: str
    gold_doc_ids: list[str]
    candidates: list[RerankedCandidate]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "answer": self.answer,
            "gold_doc_ids": self.gold_doc_ids,
            "candidates": [candidate.to_json_dict() for candidate in self.candidates],
        }
