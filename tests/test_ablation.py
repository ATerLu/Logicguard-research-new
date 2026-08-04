from pathlib import Path

from logicguard.defense.run_ablation import AblationConfig, evaluate_ablation_mode
from logicguard.graph.schemas import EntityMention, PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicguard_ablation_full_500.yaml"


def _trace(
    query_id: str, gold_doc_ids: list[str], candidates: list[PathCandidate]
) -> RetrievalTrace:
    return RetrievalTrace(
        query_id=query_id,
        query=f"Question {query_id}?",
        answer="Known Person",
        gold_doc_ids=gold_doc_ids,
        query_entities=[EntityMention(text="Known Film", normalized="known film")],
        candidates=candidates,
    )


def test_ablation_config_resolves_full_500_artifacts() -> None:
    config = AblationConfig.from_yaml(CONFIG_PATH)

    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.run_name == "full_500"
    assert config.risk_penalty == 0.50
    assert config.risk_threshold == 0.80
    assert (
        config.clean_trace_path("hotpotqa")
        == PROJECT_ROOT / "outputs" / "baseline" / "hotpotqa" / "full_500_traces.jsonl"
    )
    assert (
        config.entity_swap_trace_path("hotpotqa")
        == PROJECT_ROOT
        / "outputs"
        / "attacks"
        / "entity_swap_full_500"
        / "hotpotqa"
        / "poisoned_full_500_traces.jsonl"
    )


def test_ablation_modes_isolate_provenance_and_content_integrity_signals() -> None:
    clean_trace = _trace(
        "clean-q",
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
            ),
        ],
    )

    common_kwargs = dict(
        dataset="toy",
        run_name="full_500",
        risk_penalty=0.5,
        risk_threshold=0.8,
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

    none = evaluate_ablation_mode(mode="none", **common_kwargs)
    provenance = evaluate_ablation_mode(mode="provenance_only", **common_kwargs)
    content = evaluate_ablation_mode(mode="content_integrity_only", **common_kwargs)
    full = evaluate_ablation_mode(mode="full", **common_kwargs)

    assert none.entity_exposure_guarded == 1.0
    assert none.bridge_exposure_guarded == 1.0

    assert provenance.entity_exposure_guarded == 1.0
    assert provenance.bridge_exposure_guarded == 0.0

    assert content.entity_exposure_guarded == 0.0
    assert content.bridge_exposure_guarded == 1.0

    assert full.entity_exposure_guarded == 0.0
    assert full.bridge_exposure_guarded == 0.0
