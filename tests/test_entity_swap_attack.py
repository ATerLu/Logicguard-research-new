from logicguard.attack.entity_swap import (
    apply_entity_swap_attacks,
    calculate_poisoned_evidence_exposure,
    select_entity_swap_attacks,
)
from logicguard.attack.run_entity_swap import EntitySwapRunConfig
from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.schemas import PathCandidate, RetrievalTrace

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTITY_SWAP_CONFIG_PATH = PROJECT_ROOT / "configs" / "entity_swap_attack.yaml"
ENTITY_SWAP_FULL_CONFIG_PATH = PROJECT_ROOT / "configs" / "entity_swap_attack_full_500.yaml"


def _sample(
    query_id: str,
    answer: str,
    support_doc_id: str,
    support_text: str,
) -> NormalizedSample:
    return NormalizedSample(
        query_id=query_id,
        query=f"Question for {query_id}?",
        answer=answer,
        support_doc_ids=[support_doc_id],
        support_docs=[
            CorpusDocument(
                doc_id=support_doc_id,
                title=f"Doc {support_doc_id}",
                text=support_text,
            )
        ],
    )


def test_select_entity_swap_attacks_uses_next_answer_as_replacement() -> None:
    samples = [
        _sample("q1", "Gisela Elsner", "d1", "Gisela Elsner was a writer."),
        _sample("q2", "Ada Lovelace", "d2", "Ada Lovelace wrote notes."),
    ]

    attacks = select_entity_swap_attacks(samples, max_attacks=1)

    assert len(attacks) == 1
    attack = attacks[0]
    assert attack.query_id == "q1"
    assert attack.original_answer == "Gisela Elsner"
    assert attack.replacement_answer == "Ada Lovelace"
    assert attack.poisoned_doc_ids == ["d1"]


def test_select_entity_swap_prefers_same_answer_shape() -> None:
    samples = [
        _sample("q1", "Gisela Elsner", "d1", "Gisela Elsner was a writer."),
        _sample("q2", "Polish-Lithuanian Commonwealth", "d2", "Polish-Lithuanian Commonwealth existed."),
        _sample("q3", "Ada Lovelace", "d3", "Ada Lovelace wrote notes."),
    ]

    attacks = select_entity_swap_attacks(samples, max_attacks=1)

    assert attacks[0].replacement_answer == "Ada Lovelace"


def test_apply_entity_swap_attacks_rewrites_only_target_documents() -> None:
    samples = [
        _sample("q1", "Gisela Elsner", "d1", "Gisela Elsner was a writer."),
        _sample("q2", "Ada Lovelace", "d2", "Ada Lovelace wrote notes."),
    ]
    attacks = select_entity_swap_attacks(samples, max_attacks=1)
    corpus = [
        CorpusDocument(doc_id="d1", title="Gisela Elsner", text="Gisela Elsner was a writer."),
        CorpusDocument(doc_id="d2", title="Ada Lovelace", text="Ada Lovelace wrote notes."),
    ]

    poisoned = apply_entity_swap_attacks(corpus, attacks)

    assert poisoned["d1"].title == "Ada Lovelace"
    assert poisoned["d1"].text == "Ada Lovelace was a writer."
    assert poisoned["d2"].text == "Ada Lovelace wrote notes."


def test_calculate_poisoned_evidence_exposure_counts_target_hits() -> None:
    samples = [
        _sample("q1", "Gisela Elsner", "d1", "Gisela Elsner was a writer."),
        _sample("q2", "Ada Lovelace", "d2", "Ada Lovelace wrote notes."),
    ]
    attacks = select_entity_swap_attacks(samples, max_attacks=1)
    trace = RetrievalTrace(
        query_id="q1",
        query="Question for q1?",
        answer="Gisela Elsner",
        gold_doc_ids=["d1"],
        query_entities=[],
        candidates=[
            PathCandidate(
                doc_id="d1",
                title="Poisoned",
                score=1.0,
                path_nodes=["query:q1", "ent:x", "doc:d1"],
                matched_query_entities=["x"],
                bridge_entities=[],
            )
        ],
    )

    exposure = calculate_poisoned_evidence_exposure([trace], attacks, top_k=1)

    assert exposure.targeted_queries == 1
    assert exposure.exposed_queries == 1
    assert exposure.exposure_rate == 1.0


def test_entity_swap_run_config_targets_debug_50() -> None:
    config = EntitySwapRunConfig.from_yaml(ENTITY_SWAP_CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "debug_50.jsonl"
    assert config.max_attacks == 20
    assert config.top_k == 10
    assert config.max_depth == 3


def test_entity_swap_full_config_uses_full_500_output_names() -> None:
    config = EntitySwapRunConfig.from_yaml(ENTITY_SWAP_FULL_CONFIG_PATH)
    outputs = config.baseline_outputs()

    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "samples.jsonl"
    assert config.run_name == "full_500"
    assert config.max_attacks == 500
    assert outputs.trace_path.name == "poisoned_full_500_traces.jsonl"
    assert outputs.query_entity_cache_path.name == "poisoned_full_500_query_entities.jsonl"
