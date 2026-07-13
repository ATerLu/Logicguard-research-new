"""Deterministic LogicGuard reranking for retrieval traces."""

from __future__ import annotations

from collections import defaultdict

from logicguard.defense.features import score_candidate_risk
from logicguard.defense.schemas import RerankedCandidate, RerankedTrace
from logicguard.graph.schemas import RetrievalTrace


def rerank_trace(
    trace: RetrievalTrace,
    risk_penalty: float,
    global_entity_support_counts: dict[str, int] | None = None,
    reference_doc_ids: set[str] | None = None,
    changed_doc_ids: set[str] | None = None,
) -> RerankedTrace:
    """Return a trace whose candidates are sorted by risk-adjusted score.

    The reranker does not remove evidence. It simply lowers candidates whose
    graph path looks suspicious, so downstream evaluation can compare exposure
    before and after LogicGuard without changing the retriever itself.
    """

    support_counts = _matched_entity_support_counts(trace)
    scored_candidates: list[tuple[int, RerankedCandidate]] = []

    for original_rank, candidate in enumerate(trace.candidates, start=1):
        risk = score_candidate_risk(
            trace,
            candidate,
            support_counts,
            global_entity_support_counts=global_entity_support_counts,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=changed_doc_ids,
        )
        adjusted_score = candidate.score - (risk_penalty * risk.risk_score)
        scored_candidates.append(
            (
                original_rank,
                RerankedCandidate(
                    doc_id=candidate.doc_id,
                    title=candidate.title,
                    original_rank=original_rank,
                    new_rank=0,
                    base_score=candidate.score,
                    risk_score=risk.risk_score,
                    adjusted_score=adjusted_score,
                    path_length=risk.path_length,
                    direct_query_match=risk.direct_query_match,
                    source_support_count=risk.source_support_count,
                    global_support_count=risk.global_support_count,
                    known_source_document=risk.known_source_document,
                    reference_content_changed=risk.reference_content_changed,
                    matched_query_entities=candidate.matched_query_entities,
                    bridge_entities=candidate.bridge_entities,
                    risk_reasons=risk.risk_reasons,
                ),
            )
        )

    ordered = sorted(
        scored_candidates,
        key=lambda item: (
            item[1].adjusted_score,
            item[1].base_score,
            -item[0],
            item[1].doc_id,
        ),
        reverse=True,
    )
    reranked_candidates = [
        _with_new_rank(candidate, new_rank=index)
        for index, (_, candidate) in enumerate(ordered, start=1)
    ]
    return RerankedTrace(
        query_id=trace.query_id,
        query=trace.query,
        answer=trace.answer,
        gold_doc_ids=trace.gold_doc_ids,
        candidates=reranked_candidates,
    )


def build_guarded_trace(
    trace: RetrievalTrace,
    risk_penalty: float,
    risk_threshold: float,
    global_entity_support_counts: dict[str, int] | None = None,
    reference_doc_ids: set[str] | None = None,
    changed_doc_ids: set[str] | None = None,
) -> RerankedTrace:
    """Build the final guarded context by suppressing high-risk candidates."""

    reranked = rerank_trace(
        trace,
        risk_penalty=risk_penalty,
        global_entity_support_counts=global_entity_support_counts,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=changed_doc_ids,
    )
    kept_candidates = [
        candidate for candidate in reranked.candidates if candidate.risk_score < risk_threshold
    ]
    guarded_candidates = [
        _with_new_rank(candidate, new_rank=index)
        for index, candidate in enumerate(kept_candidates, start=1)
    ]
    return RerankedTrace(
        query_id=reranked.query_id,
        query=reranked.query,
        answer=reranked.answer,
        gold_doc_ids=reranked.gold_doc_ids,
        candidates=guarded_candidates,
    )


def build_recovered_trace(
    guarded_trace: RerankedTrace,
    reference_trace: RetrievalTrace,
    top_k: int,
) -> RerankedTrace:
    """Backfill guarded context with candidates from a trusted reference trace.

    Guarded context prioritizes safety and may remove corrupted gold evidence.
    Recovery keeps the guarded candidates first, then fills remaining slots from
    the clean/reference retrieval trace. The LLM stage should render recovered
    doc ids against the trusted reference corpus, not the poisoned corpus.
    """

    guarded_by_doc_id = {candidate.doc_id: candidate for candidate in guarded_trace.candidates}
    recovered_candidates: list[RerankedCandidate] = []
    seen_doc_ids: set[str] = set()

    for original_rank, candidate in enumerate(reference_trace.candidates, start=1):
        if len(recovered_candidates) >= top_k:
            break
        if candidate.doc_id in seen_doc_ids:
            continue
        guarded_candidate = guarded_by_doc_id.get(candidate.doc_id)
        if guarded_candidate is not None:
            recovered_candidates.append(guarded_candidate)
        else:
            recovered_candidates.append(
                RerankedCandidate(
                    doc_id=candidate.doc_id,
                    title=candidate.title,
                    original_rank=original_rank,
                    new_rank=0,
                    base_score=candidate.score,
                    risk_score=0.0,
                    adjusted_score=candidate.score,
                    path_length=len(candidate.path_nodes),
                    direct_query_match=bool(candidate.matched_query_entities),
                    source_support_count=1,
                    global_support_count=None,
                    known_source_document=True,
                    reference_content_changed=False,
                    matched_query_entities=candidate.matched_query_entities,
                    bridge_entities=candidate.bridge_entities,
                    risk_reasons=["trusted_reference_recovery"],
                )
            )
        seen_doc_ids.add(candidate.doc_id)

    for guarded_candidate in guarded_trace.candidates:
        if len(recovered_candidates) >= top_k:
            break
        if guarded_candidate.doc_id in seen_doc_ids:
            continue
        recovered_candidates.append(guarded_candidate)
        seen_doc_ids.add(guarded_candidate.doc_id)

    return RerankedTrace(
        query_id=guarded_trace.query_id,
        query=guarded_trace.query,
        answer=guarded_trace.answer,
        gold_doc_ids=guarded_trace.gold_doc_ids,
        candidates=[
            _with_new_rank(candidate, new_rank=index)
            for index, candidate in enumerate(recovered_candidates, start=1)
        ],
    )


def _matched_entity_support_counts(trace: RetrievalTrace) -> dict[str, int]:
    """Count how many retrieved sources support each matched query entity."""

    support_doc_ids: dict[str, set[str]] = defaultdict(set)
    for candidate in trace.candidates:
        for entity in candidate.matched_query_entities:
            support_doc_ids[entity].add(candidate.doc_id)
    return {entity: len(doc_ids) for entity, doc_ids in support_doc_ids.items()}


def _with_new_rank(candidate: RerankedCandidate, new_rank: int) -> RerankedCandidate:
    return RerankedCandidate(
        doc_id=candidate.doc_id,
        title=candidate.title,
        original_rank=candidate.original_rank,
        new_rank=new_rank,
        base_score=candidate.base_score,
        risk_score=candidate.risk_score,
        adjusted_score=candidate.adjusted_score,
        path_length=candidate.path_length,
        direct_query_match=candidate.direct_query_match,
        source_support_count=candidate.source_support_count,
        global_support_count=candidate.global_support_count,
        known_source_document=candidate.known_source_document,
        reference_content_changed=candidate.reference_content_changed,
        matched_query_entities=candidate.matched_query_entities,
        bridge_entities=candidate.bridge_entities,
        risk_reasons=candidate.risk_reasons,
    )
