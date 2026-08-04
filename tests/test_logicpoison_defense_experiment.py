from pathlib import Path

from logicguard.defense.run_logicpoison_defense import (
    LogicPoisonDefenseConfig,
    apply_defense_mode,
    calculate_logicpoison_defense_metrics,
    run_from_config,
)
from logicguard.graph.schemas import PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_defense_stage3.yaml"


def _trace(
    query_id: str, gold_doc_ids: list[str], doc_ids: list[str]
) -> RetrievalTrace:
    return RetrievalTrace(
        query_id=query_id,
        query=f"Question {query_id}?",
        answer="Known Answer",
        gold_doc_ids=gold_doc_ids,
        query_entities=[],
        candidates=[
            PathCandidate(
                doc_id=doc_id,
                title=f"Doc {doc_id}",
                score=float(len(doc_ids) - index),
                path_nodes=[f"query:{query_id}", f"doc:{doc_id}"],
                matched_query_entities=[],
                bridge_entities=[],
            )
            for index, doc_id in enumerate(doc_ids)
        ],
    )


def test_logicpoison_defense_config_uses_stage2_retrieval_outputs() -> None:
    config = LogicPoisonDefenseConfig.from_yaml(CONFIG_PATH)

    assert (
        config.clean_data_root
        == PROJECT_ROOT / "data" / "logicpoison_official" / "clean"
    )
    assert (
        config.poisoned_data_root
        == PROJECT_ROOT / "data" / "logicpoison_official" / "poisoned"
    )
    assert (
        config.retrieval_root
        == PROJECT_ROOT / "outputs" / "retrieval" / "logicpoison_official"
    )
    assert (
        config.output_root
        == PROJECT_ROOT / "outputs" / "defense" / "logicpoison_official"
    )
    assert (
        config.report_path
        == PROJECT_ROOT / "outputs" / "reports" / "LogicPoison防御消融实验报告.md"
    )
    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.retrievers == ["naive_bm25", "graph_surrogate"]
    assert config.top_k == 10


def test_content_integrity_filters_changed_doc_and_recovery_backfills_clean_reference() -> (
    None
):
    poisoned = _trace("q1", ["g1"], ["g1", "d1"])
    clean_reference = _trace("q1", ["g1"], ["g1", "d2"])
    changed_doc_ids = {"g1"}
    changed_gold_by_query = {"q1": {"g1"}}
    reference_doc_ids = {"g1", "d1", "d2"}

    provenance = apply_defense_mode(
        mode="provenance_only",
        poisoned_trace=poisoned,
        clean_reference_trace=clean_reference,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=changed_doc_ids,
        top_k=2,
    )
    content = apply_defense_mode(
        mode="content_integrity_only",
        poisoned_trace=poisoned,
        clean_reference_trace=clean_reference,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=changed_doc_ids,
        top_k=2,
    )
    recovered = apply_defense_mode(
        mode="full_logicguard_recovery",
        poisoned_trace=poisoned,
        clean_reference_trace=clean_reference,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=changed_doc_ids,
        top_k=2,
    )

    assert [candidate.doc_id for candidate in provenance.candidates] == ["g1", "d1"]
    assert [candidate.doc_id for candidate in content.candidates] == ["d1"]
    assert [candidate.doc_id for candidate in recovered.candidates] == ["g1", "d2"]
    assert recovered.candidates[0].risk_reasons == ["trusted_reference_recovery"]

    content_metrics = calculate_logicpoison_defense_metrics(
        dataset="toy",
        retriever="naive_bm25",
        mode="content_integrity_only",
        before_traces=[poisoned],
        after_traces=[content],
        changed_doc_ids=changed_doc_ids,
        changed_gold_doc_ids_by_query=changed_gold_by_query,
        top_k=2,
    )
    recovered_metrics = calculate_logicpoison_defense_metrics(
        dataset="toy",
        retriever="naive_bm25",
        mode="full_logicguard_recovery",
        before_traces=[poisoned],
        after_traces=[recovered],
        changed_doc_ids=changed_doc_ids,
        changed_gold_doc_ids_by_query=changed_gold_by_query,
        top_k=2,
    )

    assert content_metrics.after_changed_doc_exposure_at_k == 0.0
    assert content_metrics.after_gold_recall_at_k == 0.0
    assert content_metrics.empty_context_rate == 0.0
    assert recovered_metrics.after_changed_doc_exposure_at_k == 0.0
    assert recovered_metrics.after_gold_recall_at_k == 1.0
    assert recovered_metrics.recovered_candidate_count == 2


def test_run_from_config_writes_small_defense_artifacts(tmp_path: Path) -> None:
    config = LogicPoisonDefenseConfig(
        clean_data_root=PROJECT_ROOT / "data" / "logicpoison_official" / "clean",
        poisoned_data_root=PROJECT_ROOT / "data" / "logicpoison_official" / "poisoned",
        retrieval_root=PROJECT_ROOT / "outputs" / "retrieval" / "logicpoison_official",
        output_root=tmp_path / "defense" / "logicpoison_official",
        report_path=tmp_path / "reports" / "LogicPoison防御消融实验报告.md",
        datasets=["2wikimultihopqa"],
        retrievers=["naive_bm25"],
        modes=["none", "content_integrity_only", "full_logicguard_recovery"],
        top_k=5,
    )

    rows = run_from_config(config)
    dataset_output = config.output_root / "2wikimultihopqa"

    assert len(rows) == 3
    assert (dataset_output / "naive_bm25_none_traces.jsonl").is_file()
    assert (dataset_output / "naive_bm25_content_integrity_only_traces.jsonl").is_file()
    assert (
        dataset_output / "naive_bm25_full_logicguard_recovery_traces.jsonl"
    ).is_file()
    assert (dataset_output / "defense_metrics.jsonl").is_file()
    assert config.report_path.is_file()
