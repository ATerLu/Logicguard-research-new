"""Transparent LogicGuard risk features for path-centric retrieval traces."""

from __future__ import annotations

from logicguard.defense.schemas import CandidateRiskScore
from logicguard.graph.schemas import PathCandidate, RetrievalTrace


def score_candidate_risk(
    trace: RetrievalTrace,
    candidate: PathCandidate,
    support_counts: dict[str, int],
    global_entity_support_counts: dict[str, int] | None = None,
    reference_doc_ids: set[str] | None = None,
    changed_doc_ids: set[str] | None = None,
) -> CandidateRiskScore:
    """Score one candidate with simple, inspectable risk rules.

    The MVP deliberately uses hand-written features because the project first
    needs a reliable attack-defense evaluation loop. The weights are not final
    paper claims; they are starting points for testing whether suspicious graph
    paths can be down-ranked without training a model.
    """

    risk_score = 0.0
    risk_reasons: list[str] = []
    path_length = max(len(candidate.path_nodes) - 1, 0)
    direct_query_match = bool(candidate.matched_query_entities) and not candidate.bridge_entities
    source_support_count = _candidate_source_support_count(candidate, support_counts)
    global_support_count = _candidate_global_support_count(candidate, global_entity_support_counts)
    known_source_document = (
        candidate.doc_id in reference_doc_ids if reference_doc_ids is not None else None
    )
    reference_content_changed = (
        candidate.doc_id in changed_doc_ids if changed_doc_ids is not None else None
    )

    if direct_query_match:
        risk_score += 0.60
        risk_reasons.append("direct_query_entity_match")

    if known_source_document is False:
        risk_score += 0.30
        risk_reasons.append("unseen_source_document")

    if reference_content_changed:
        risk_score += 0.90
        risk_reasons.append("reference_content_mismatch")

    if known_source_document is False and global_support_count is not None and global_support_count <= 2:
        risk_score += 0.10
        risk_reasons.append("low_global_entity_support")

    if known_source_document is False and source_support_count <= 1:
        risk_score += 0.20
        risk_reasons.append("low_source_redundancy")

    if candidate.bridge_entities:
        risk_score -= 0.10
        risk_reasons.append("bridge_entity_support")

    clipped_risk = round(_clip(risk_score, lower=0.0, upper=1.0), 10)
    return CandidateRiskScore(
        query_id=trace.query_id,
        doc_id=candidate.doc_id,
        base_score=candidate.score,
        risk_score=clipped_risk,
        adjusted_score=candidate.score,
        path_length=path_length,
        direct_query_match=direct_query_match,
        source_support_count=source_support_count,
        global_support_count=global_support_count,
        known_source_document=known_source_document,
        reference_content_changed=reference_content_changed,
        risk_reasons=risk_reasons,
    )


def _candidate_source_support_count(
    candidate: PathCandidate,
    support_counts: dict[str, int],
) -> int:
    """Return the strongest observed support count for matched query entities."""

    if not candidate.matched_query_entities:
        return 0
    return max(support_counts.get(entity, 0) for entity in candidate.matched_query_entities)


def _candidate_global_support_count(
    candidate: PathCandidate,
    global_entity_support_counts: dict[str, int] | None,
) -> int | None:
    """Return corpus-level support for the candidate's matched query entity."""

    if global_entity_support_counts is None or not candidate.matched_query_entities:
        return None
    return max(global_entity_support_counts.get(entity, 0) for entity in candidate.matched_query_entities)


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
