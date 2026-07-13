from pathlib import Path

from logicguard.defense.features import score_candidate_risk
from logicguard.defense.reranker import build_guarded_trace, build_recovered_trace, rerank_trace
from logicguard.defense.run_logicguard import (
    LogicGuardRunConfig,
    calculate_poison_exposure_from_doc_ids,
    calculate_suppression_stats,
    calculate_trusted_retrieval_metrics_from_doc_ids,
)
from logicguard.graph.schemas import EntityMention, PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGICGUARD_CONFIG_PATH = PROJECT_ROOT / "configs" / "logicguard_mvp.yaml"


def _trace_with_direct_poison_and_supported_gold() -> RetrievalTrace:
    return RetrievalTrace(
        query_id="q1",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["gold_doc"],
        query_entities=[EntityMention(text="Atomised", normalized="atomised")],
        candidates=[
            PathCandidate(
                doc_id="9999",
                title="Atomised and Wrong Answer",
                score=1.0,
                path_nodes=["query:q1", "ent:atomised", "doc:9999"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
            PathCandidate(
                doc_id="gold_doc",
                title="Atomised",
                score=0.6,
                path_nodes=["query:q1", "ent:atomised", "doc:related_doc", "ent:oskar roehler", "doc:gold_doc"],
                matched_query_entities=["atomised"],
                bridge_entities=["oskar roehler"],
            ),
        ],
    )


def test_score_candidate_risk_marks_synthetic_direct_bridge_as_high_risk() -> None:
    trace = _trace_with_direct_poison_and_supported_gold()
    support_counts = {"atomised": 2}
    reference_doc_ids = {"gold_doc", "related_doc"}

    poison_score = score_candidate_risk(
        trace,
        trace.candidates[0],
        support_counts,
        reference_doc_ids=reference_doc_ids,
    )
    gold_score = score_candidate_risk(
        trace,
        trace.candidates[1],
        support_counts,
        reference_doc_ids=reference_doc_ids,
    )

    assert poison_score.doc_id == "9999"
    assert poison_score.direct_query_match is True
    assert poison_score.known_source_document is False
    assert poison_score.risk_score > gold_score.risk_score
    assert "direct_query_entity_match" in poison_score.risk_reasons
    assert "unseen_source_document" in poison_score.risk_reasons
    assert "non_numeric_doc_id" not in poison_score.risk_reasons
    assert "bridge_entity_support" in gold_score.risk_reasons


def test_score_candidate_risk_does_not_over_penalize_known_low_redundancy_source() -> None:
    trace = RetrievalTrace(
        query_id="q2",
        query="Who wrote Rare Film?",
        answer="Known Person",
        gold_doc_ids=["123"],
        query_entities=[EntityMention(text="Rare Film", normalized="rare film")],
        candidates=[
            PathCandidate(
                doc_id="123",
                title="Rare Film",
                score=1.0,
                path_nodes=["query:q2", "ent:rare film", "doc:123"],
                matched_query_entities=["rare film"],
                bridge_entities=[],
            )
        ],
    )

    score = score_candidate_risk(
        trace,
        trace.candidates[0],
        {"rare film": 1},
        global_entity_support_counts={"rare film": 1},
        reference_doc_ids={"123"},
    )

    assert score.known_source_document is True
    assert score.risk_score < 0.90
    assert "low_source_redundancy" not in score.risk_reasons
    assert "low_global_entity_support" not in score.risk_reasons


def test_score_candidate_risk_marks_reference_content_mismatch_as_high_risk() -> None:
    trace = RetrievalTrace(
        query_id="q3",
        query="Who is connected to Known Film?",
        answer="Known Person",
        gold_doc_ids=["123"],
        query_entities=[EntityMention(text="Known Film", normalized="known film")],
        candidates=[
            PathCandidate(
                doc_id="123",
                title="Known Film",
                score=1.0,
                path_nodes=["query:q3", "ent:known film", "doc:123"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )

    score = score_candidate_risk(
        trace,
        trace.candidates[0],
        {"known film": 1},
        reference_doc_ids={"123"},
        changed_doc_ids={"123"},
    )

    assert score.known_source_document is True
    assert score.reference_content_changed is True
    assert score.risk_score == 1.0
    assert "reference_content_mismatch" in score.risk_reasons


def test_rerank_trace_moves_high_risk_direct_bridge_below_supported_candidate() -> None:
    trace = _trace_with_direct_poison_and_supported_gold()

    reranked = rerank_trace(
        trace,
        risk_penalty=0.75,
        reference_doc_ids={"gold_doc", "related_doc"},
    )

    ordered_doc_ids = [candidate.doc_id for candidate in reranked.candidates]
    assert ordered_doc_ids == ["gold_doc", "9999"]
    assert reranked.candidates[0].new_rank == 1
    assert reranked.candidates[0].original_rank == 2
    assert reranked.candidates[1].new_rank == 2
    assert reranked.candidates[1].original_rank == 1
    assert reranked.candidates[1].risk_score > reranked.candidates[0].risk_score


def test_build_guarded_trace_filters_high_risk_candidate() -> None:
    trace = _trace_with_direct_poison_and_supported_gold()

    guarded = build_guarded_trace(
        trace,
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids={"gold_doc", "related_doc"},
    )

    assert [candidate.doc_id for candidate in guarded.candidates] == ["gold_doc"]
    assert guarded.candidates[0].new_rank == 1
    assert guarded.candidates[0].original_rank == 2


def test_build_guarded_trace_filters_changed_known_source() -> None:
    trace = RetrievalTrace(
        query_id="q4",
        query="Who is connected to Known Film?",
        answer="Known Person",
        gold_doc_ids=["123"],
        query_entities=[EntityMention(text="Known Film", normalized="known film")],
        candidates=[
            PathCandidate(
                doc_id="123",
                title="Known Film",
                score=1.0,
                path_nodes=["query:q4", "ent:known film", "doc:123"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )

    guarded = build_guarded_trace(
        trace,
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids={"123"},
        changed_doc_ids={"123"},
    )

    assert guarded.candidates == []


def test_build_recovered_trace_backfills_from_reference_trace() -> None:
    poisoned_trace = RetrievalTrace(
        query_id="q5",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["123"],
        query_entities=[EntityMention(text="Atomised", normalized="atomised")],
        candidates=[
            PathCandidate(
                doc_id="123",
                title="Atomised",
                score=1.0,
                path_nodes=["query:q5", "ent:atomised", "doc:123"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            )
        ],
    )
    reference_trace = RetrievalTrace(
        query_id="q5",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["123"],
        query_entities=[EntityMention(text="Atomised", normalized="atomised")],
        candidates=[
            PathCandidate(
                doc_id="123",
                title="Atomised",
                score=0.9,
                path_nodes=["query:q5", "ent:atomised", "doc:123"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            )
        ],
    )
    guarded = build_guarded_trace(
        poisoned_trace,
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids={"123"},
        changed_doc_ids={"123"},
    )

    recovered = build_recovered_trace(guarded, reference_trace, top_k=1)

    assert [candidate.doc_id for candidate in recovered.candidates] == ["123"]
    assert recovered.candidates[0].new_rank == 1
    assert recovered.candidates[0].risk_score == 0.0
    assert recovered.candidates[0].risk_reasons == ["trusted_reference_recovery"]


def test_build_recovered_trace_preserves_guarded_candidates_before_backfill() -> None:
    guarded = build_guarded_trace(
        _trace_with_direct_poison_and_supported_gold(),
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids={"gold_doc", "related_doc"},
    )
    reference_trace = RetrievalTrace(
        query_id="q1",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["gold_doc", "extra_doc"],
        query_entities=[EntityMention(text="Atomised", normalized="atomised")],
        candidates=[
            PathCandidate(
                doc_id="gold_doc",
                title="Atomised",
                score=1.0,
                path_nodes=["query:q1", "ent:atomised", "doc:gold_doc"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
            PathCandidate(
                doc_id="extra_doc",
                title="Director profile",
                score=0.8,
                path_nodes=["query:q1", "ent:atomised", "doc:extra_doc"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
        ],
    )

    recovered = build_recovered_trace(guarded, reference_trace, top_k=2)

    assert [candidate.doc_id for candidate in recovered.candidates] == ["gold_doc", "extra_doc"]
    assert recovered.candidates[0].risk_reasons == ["bridge_entity_support"]
    assert recovered.candidates[1].risk_reasons == ["trusted_reference_recovery"]


def test_build_recovered_trace_prioritizes_reference_candidates_for_answer_recovery() -> None:
    guarded = build_guarded_trace(
        _trace_with_direct_poison_and_supported_gold(),
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids={"gold_doc", "related_doc"},
    )
    reference_trace = RetrievalTrace(
        query_id="q1",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["gold_doc", "reference_gold"],
        query_entities=[EntityMention(text="Atomised", normalized="atomised")],
        candidates=[
            PathCandidate(
                doc_id="reference_gold",
                title="Reference answer",
                score=1.0,
                path_nodes=["query:q1", "ent:atomised", "doc:reference_gold"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
            PathCandidate(
                doc_id="gold_doc",
                title="Atomised",
                score=0.8,
                path_nodes=["query:q1", "ent:atomised", "doc:gold_doc"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
        ],
    )

    recovered = build_recovered_trace(guarded, reference_trace, top_k=2)

    assert [candidate.doc_id for candidate in recovered.candidates] == ["reference_gold", "gold_doc"]
    assert recovered.candidates[0].risk_reasons == ["trusted_reference_recovery"]


def test_logicguard_run_config_resolves_existing_debug_trace_paths() -> None:
    config = LogicGuardRunConfig.from_yaml(LOGICGUARD_CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.clean_trace_path == PROJECT_ROOT / "outputs" / "baseline" / "2wikimultihopqa" / "debug_50_traces.jsonl"
    assert (
        config.bridge_attack_metadata_path
        == PROJECT_ROOT
        / "outputs"
        / "attacks"
        / "bridge_injection"
        / "2wikimultihopqa"
        / "bridge_injection_metadata.jsonl"
    )
    assert (
        config.reference_corpus_entity_path
        == PROJECT_ROOT / "outputs" / "baseline" / "2wikimultihopqa" / "corpus_entities.jsonl"
    )
    assert (
        config.entity_swap_corpus_path
        == PROJECT_ROOT / "outputs" / "attacks" / "entity_swap" / "2wikimultihopqa" / "poisoned_corpus.jsonl"
    )
    assert config.risk_penalty == 0.75
    assert config.risk_threshold == 0.90
    assert config.top_k == 10


def test_calculate_poison_exposure_drops_after_reranking() -> None:
    trace = _trace_with_direct_poison_and_supported_gold()
    reranked = rerank_trace(
        trace,
        risk_penalty=0.75,
        reference_doc_ids={"gold_doc", "related_doc"},
    )
    poisoned_doc_ids_by_query = {"q1": {"9999"}}

    before = calculate_poison_exposure_from_doc_ids([trace], poisoned_doc_ids_by_query, top_k=1)
    after = calculate_poison_exposure_from_doc_ids([reranked], poisoned_doc_ids_by_query, top_k=1)

    assert before.exposure_rate == 1.0
    assert after.exposure_rate == 0.0


def test_calculate_suppression_stats_counts_removed_poison_without_gold_loss() -> None:
    trace = _trace_with_direct_poison_and_supported_gold()
    reference_doc_ids = {"gold_doc", "related_doc"}
    reranked = rerank_trace(trace, risk_penalty=0.75, reference_doc_ids=reference_doc_ids)
    guarded = build_guarded_trace(
        trace,
        risk_penalty=0.75,
        risk_threshold=0.90,
        reference_doc_ids=reference_doc_ids,
    )

    stats = calculate_suppression_stats(
        [reranked],
        [guarded],
        {"q1": {"9999"}},
        changed_doc_ids={"9999"},
    )

    assert stats["suppressed_candidates"] == 1
    assert stats["suppressed_gold_candidates"] == 0
    assert stats["suppressed_poisoned_candidates"] == 1
    assert stats["suppressed_changed_candidates"] == 1


def test_trusted_retrieval_metrics_exclude_changed_gold_from_recall_denominator() -> None:
    trace = RetrievalTrace(
        query_id="trusted-q",
        query="Question trusted-q?",
        answer="Known Person",
        gold_doc_ids=["clean-gold", "changed-gold"],
        query_entities=[EntityMention(text="Known Film", normalized="known film")],
        candidates=[
            PathCandidate(
                doc_id="changed-gold",
                title="Changed Gold",
                score=1.0,
                path_nodes=["query:trusted-q", "ent:known film", "doc:changed-gold"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )

    metrics = calculate_trusted_retrieval_metrics_from_doc_ids(
        [trace],
        top_k=1,
        untrusted_doc_ids={"changed-gold"},
    )

    assert metrics["trusted_gold_recall_at_k"] == 0.0
    assert metrics["trusted_hit_at_k"] == 0.0
    assert metrics["queries_with_trusted_gold"] == 1.0
    assert metrics["corrupted_gold_doc_count"] == 1.0
