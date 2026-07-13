from pathlib import Path

from logicguard.defense.run_threshold_scan import ThresholdScanConfig, evaluate_threshold_pair
from logicguard.graph.schemas import EntityMention, PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_CONFIG_PATH = PROJECT_ROOT / "configs" / "logicguard_threshold_scan_full_500.yaml"


def _trace(query_id: str, answer: str, gold_doc_ids: list[str], candidates: list[PathCandidate]) -> RetrievalTrace:
    return RetrievalTrace(
        query_id=query_id,
        query=f"Question {query_id}?",
        answer=answer,
        gold_doc_ids=gold_doc_ids,
        query_entities=[EntityMention(text="Known Film", normalized="known film")],
        candidates=candidates,
    )


def test_threshold_scan_config_targets_full_500_artifacts() -> None:
    config = ThresholdScanConfig.from_yaml(SCAN_CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.run_name == "full_500"
    assert config.clean_trace_path == PROJECT_ROOT / "outputs" / "baseline" / "2wikimultihopqa" / "full_500_traces.jsonl"
    assert config.entity_swap_trace_path.name == "poisoned_full_500_traces.jsonl"
    assert config.bridge_trace_path.name == "bridge_poisoned_full_500_traces.jsonl"
    assert config.risk_penalties == [0.5, 0.75, 1.0]
    assert config.risk_thresholds == [0.8, 0.9, 1.0]


def test_evaluate_threshold_pair_reports_clean_and_poisoned_tradeoff() -> None:
    clean_trace = _trace(
        "clean-q",
        "Known Person",
        ["1"],
        [
            PathCandidate(
                doc_id="1",
                title="Known Film",
                score=1.0,
                path_nodes=["query:clean-q", "ent:known film", "doc:1"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )
    entity_trace = _trace(
        "entity-q",
        "Known Person",
        ["2"],
        [
            PathCandidate(
                doc_id="2",
                title="Known Film",
                score=1.0,
                path_nodes=["query:entity-q", "ent:known film", "doc:2"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )
    bridge_trace = _trace(
        "bridge-q",
        "Known Person",
        ["3"],
        [
            PathCandidate(
                doc_id="new-bridge",
                title="Known Film and Wrong Answer",
                score=1.0,
                path_nodes=["query:bridge-q", "ent:known film", "doc:new-bridge"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            ),
            PathCandidate(
                doc_id="3",
                title="Known Film",
                score=0.6,
                path_nodes=["query:bridge-q", "ent:known film", "doc:3"],
                matched_query_entities=["known film"],
                bridge_entities=[],
            )
        ],
    )

    row = evaluate_threshold_pair(
        dataset="toy",
        run_name="full_500",
        risk_penalty=0.75,
        risk_threshold=0.9,
        top_k=1,
        clean_traces=[clean_trace],
        entity_traces=[entity_trace],
        bridge_traces=[bridge_trace],
        reference_doc_ids={"1", "2", "3"},
        clean_global_support={"known film": 3},
        entity_global_support={"known film": 3},
        bridge_global_support={"known film": 1},
        entity_poisoned_doc_ids_by_query={"entity-q": {"2"}},
        bridge_poisoned_doc_ids_by_query={"bridge-q": {"new-bridge"}},
        clean_changed_doc_ids=set(),
        entity_changed_doc_ids={"2"},
        bridge_changed_doc_ids=set(),
    )

    assert row.clean_hit_guarded == 1.0
    assert row.clean_gold_recall_guarded == 1.0
    assert row.entity_exposure_before == 1.0
    assert row.entity_exposure_guarded == 0.0
    assert row.entity_trusted_gold_recall_before == 0.0
    assert row.entity_trusted_gold_recall_guarded == 0.0
    assert row.entity_corrupted_gold_docs == 1
    assert row.bridge_exposure_before == 1.0
    assert row.bridge_exposure_guarded == 0.0
    assert row.bridge_trusted_gold_recall_guarded == 1.0
    assert row.entity_suppressed_changed == 1
    assert row.bridge_suppressed_poisoned == 1
