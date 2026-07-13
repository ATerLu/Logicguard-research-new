from pathlib import Path

from logicguard.attack.bridge_injection import (
    apply_bridge_injection_attacks,
    apply_answer_aware_bridge_injection_attacks,
    build_answer_aware_bridge_documents,
    build_bridge_documents,
    calculate_bridge_injection_exposure,
    collect_bridge_injection_hit_details,
    select_answer_aware_bridge_injection_attacks,
    select_bridge_injection_attacks,
)
from logicguard.attack.run_bridge_injection import BridgeInjectionRunConfig
from logicguard.attack.run_bridge_injection_v2 import AnswerAwareBridgeInjectionRunConfig
from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.entities import RuleBasedEntityExtractor
from logicguard.graph.schemas import PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_CONFIG_PATH = PROJECT_ROOT / "configs" / "bridge_injection_attack.yaml"
BRIDGE_FULL_CONFIG_PATH = PROJECT_ROOT / "configs" / "bridge_injection_attack_full_500.yaml"
BRIDGE_V2_CONFIG_PATH = PROJECT_ROOT / "configs" / "bridge_injection_v2_debug.yaml"
BRIDGE_V2_FULL_CONFIG_PATH = PROJECT_ROOT / "configs" / "bridge_injection_v2_full_500.yaml"
BRIDGE_V2_NATURAL_FULL_CONFIG_PATH = PROJECT_ROOT / "configs" / "bridge_injection_v2_natural_full_500.yaml"


def _sample(query_id: str, query: str, answer: str, doc_id: str) -> NormalizedSample:
    return NormalizedSample(
        query_id=query_id,
        query=query,
        answer=answer,
        support_doc_ids=[doc_id],
        support_docs=[
            CorpusDocument(
                doc_id=doc_id,
                title=f"Doc {doc_id}",
                text=f"{answer} is the answer for {query_id}.",
            )
        ],
    )


def test_select_bridge_injection_attacks_uses_query_entity_and_replacement_answer() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]

    attacks = select_bridge_injection_attacks(samples, extractor, max_attacks=1)

    assert len(attacks) == 1
    attack = attacks[0]
    assert attack.query_id == "q1"
    assert attack.query_entity == "atomised"
    assert attack.replacement_answer == "London"
    assert attack.poisoned_doc_ids == ["poison_bridge_0000"]


def test_build_bridge_documents_mentions_query_entity_and_replacement_answer() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]
    attacks = select_bridge_injection_attacks(samples, extractor, max_attacks=1)

    bridge_docs = build_bridge_documents(attacks)

    assert len(bridge_docs) == 1
    bridge = bridge_docs[0]
    assert bridge.doc_id == "poison_bridge_0000"
    assert "Atomised" in bridge.title
    assert "London" in bridge.title
    assert "Atomised" in bridge.text
    assert "London" in bridge.text


def test_answer_aware_bridge_documents_include_explicit_wrong_answer_claim() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]

    attacks = select_answer_aware_bridge_injection_attacks(samples, extractor, max_attacks=1)
    bridge_docs = build_answer_aware_bridge_documents(attacks)

    assert len(attacks) == 1
    assert attacks[0].strategy == "answer_aware_bridge_injection"
    assert attacks[0].question == "Who directed Atomised?"
    assert attacks[0].poisoned_doc_ids == ["poison_bridge_v2_0000"]
    assert len(bridge_docs) == 1
    bridge = bridge_docs[0]
    assert bridge.doc_id == "poison_bridge_v2_0000"
    assert "Atomised" in bridge.title
    assert "London" in bridge.title
    assert "Who directed Atomised?" in bridge.text
    assert "answer is London" in bridge.text
    assert "Oskar Roehler" not in bridge.text


def test_natural_answer_aware_bridge_documents_keep_signal_without_answer_is_phrase() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]

    attacks = select_answer_aware_bridge_injection_attacks(samples, extractor, max_attacks=1)
    bridge_docs = build_answer_aware_bridge_documents(attacks, template_style="natural")

    bridge = bridge_docs[0]
    assert "Atomised" in bridge.title
    assert "London" in bridge.title
    assert "Who directed Atomised?" in bridge.text
    assert "London" in bridge.text
    assert "answer is London" not in bridge.text
    assert "listed London as the resolved entry" in bridge.text
    assert "Oskar Roehler" not in bridge.text


def test_apply_answer_aware_bridge_injection_attacks_appends_v2_documents() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]
    attacks = select_answer_aware_bridge_injection_attacks(samples, extractor, max_attacks=1)
    corpus = [CorpusDocument(doc_id="d1", title="Atomised", text="Atomised is a film.")]

    poisoned = apply_answer_aware_bridge_injection_attacks(corpus, attacks)

    assert [doc.doc_id for doc in poisoned] == ["d1", "poison_bridge_v2_0000"]
    assert poisoned[1].text != build_bridge_documents(attacks)[0].text


def test_apply_bridge_injection_attacks_appends_synthetic_documents() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]
    attacks = select_bridge_injection_attacks(samples, extractor, max_attacks=1)
    corpus = [CorpusDocument(doc_id="d1", title="Atomised", text="Atomised is a film.")]

    poisoned = apply_bridge_injection_attacks(corpus, attacks)

    assert [doc.doc_id for doc in poisoned] == ["d1", "poison_bridge_0000"]


def test_calculate_bridge_injection_exposure_counts_bridge_doc_hits() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]
    attacks = select_bridge_injection_attacks(samples, extractor, max_attacks=1)
    trace = RetrievalTrace(
        query_id="q1",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["d1"],
        query_entities=[],
        candidates=[
            PathCandidate(
                doc_id="poison_bridge_0000",
                title="Bridge",
                score=1.0,
                path_nodes=["query:q1", "ent:atomised", "doc:poison_bridge_0000"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            )
        ],
    )

    exposure = calculate_bridge_injection_exposure([trace], attacks, top_k=1)

    assert exposure.targeted_queries == 1
    assert exposure.exposed_queries == 1
    assert exposure.exposure_rate == 1.0


def test_collect_bridge_injection_hit_details_records_first_rank() -> None:
    extractor = RuleBasedEntityExtractor()
    samples = [
        _sample("q1", "Who directed Atomised?", "Oskar Roehler", "d1"),
        _sample("q2", "Where was Ada Lovelace born?", "London", "d2"),
    ]
    attacks = select_bridge_injection_attacks(samples, extractor, max_attacks=1)
    trace = RetrievalTrace(
        query_id="q1",
        query="Who directed Atomised?",
        answer="Oskar Roehler",
        gold_doc_ids=["d1"],
        query_entities=[],
        candidates=[
            PathCandidate(
                doc_id="d1",
                title="Gold",
                score=1.0,
                path_nodes=["query:q1", "ent:atomised", "doc:d1"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
            PathCandidate(
                doc_id="poison_bridge_0000",
                title="Bridge",
                score=0.8,
                path_nodes=["query:q1", "ent:atomised", "doc:poison_bridge_0000"],
                matched_query_entities=["atomised"],
                bridge_entities=[],
            ),
        ],
    )

    details = collect_bridge_injection_hit_details([trace], attacks, top_k=2)

    assert len(details) == 1
    assert details[0].attack_id == "bridge_injection_0000"
    assert details[0].poisoned_doc_id == "poison_bridge_0000"
    assert details[0].first_rank == 2
    assert details[0].retrieved_score == 0.8


def test_bridge_injection_run_config_targets_debug_50() -> None:
    config = BridgeInjectionRunConfig.from_yaml(BRIDGE_CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "debug_50.jsonl"
    assert config.max_attacks == 20
    assert config.top_k == 10
    assert config.max_depth == 3


def test_bridge_injection_full_config_uses_full_500_output_names() -> None:
    config = BridgeInjectionRunConfig.from_yaml(BRIDGE_FULL_CONFIG_PATH)
    outputs = config.baseline_outputs()

    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "samples.jsonl"
    assert config.run_name == "full_500"
    assert config.max_attacks == 500
    assert outputs.trace_path.name == "bridge_poisoned_full_500_traces.jsonl"
    assert outputs.query_entity_cache_path.name == "bridge_poisoned_full_500_query_entities.jsonl"


def test_answer_aware_bridge_injection_config_targets_v2_debug_outputs() -> None:
    config = AnswerAwareBridgeInjectionRunConfig.from_yaml(BRIDGE_V2_CONFIG_PATH)
    outputs = config.baseline_outputs()

    assert config.dataset == "2wikimultihopqa"
    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "debug_50.jsonl"
    assert config.output_root == PROJECT_ROOT / "outputs" / "attacks" / "bridge_injection_v2"
    assert config.max_attacks == 20
    assert outputs.trace_path.name == "answer_aware_bridge_poisoned_debug_50_traces.jsonl"
    assert config.exposure_report_path() == PROJECT_ROOT / "outputs" / "reports" / "bridge_injection_v2_exposure_2wikimultihopqa_debug_50.md"


def test_answer_aware_bridge_injection_full_config_uses_full_500_outputs() -> None:
    config = AnswerAwareBridgeInjectionRunConfig.from_yaml(BRIDGE_V2_FULL_CONFIG_PATH)
    outputs = config.baseline_outputs()

    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "samples.jsonl"
    assert config.output_root == PROJECT_ROOT / "outputs" / "attacks" / "bridge_injection_v2_full_500"
    assert config.run_name == "full_500"
    assert config.max_attacks == 500
    assert outputs.trace_path.name == "answer_aware_bridge_poisoned_full_500_traces.jsonl"
    assert config.exposure_report_path() == PROJECT_ROOT / "outputs" / "reports" / "bridge_injection_v2_exposure_2wikimultihopqa_full_500.md"


def test_natural_answer_aware_bridge_injection_config_uses_separate_outputs() -> None:
    config = AnswerAwareBridgeInjectionRunConfig.from_yaml(BRIDGE_V2_NATURAL_FULL_CONFIG_PATH)
    outputs = config.baseline_outputs()

    assert config.template_style == "natural"
    assert config.output_root == PROJECT_ROOT / "outputs" / "attacks" / "bridge_injection_v2_natural_full_500"
    assert outputs.trace_path.name == "answer_aware_bridge_poisoned_full_500_traces.jsonl"
    assert config.exposure_report_path() == PROJECT_ROOT / "outputs" / "reports" / "bridge_injection_v2_natural_exposure_2wikimultihopqa_full_500.md"
