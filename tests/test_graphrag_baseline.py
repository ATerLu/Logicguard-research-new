import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.baseline import BaselineOutputPaths, run_graphrag_baseline
from logicguard.graph.builder import build_document_entity_graph
from logicguard.graph.entities import RuleBasedEntityExtractor, normalize_entity
from logicguard.graph.retriever import retrieve_paths_for_query
from logicguard.graph.run_baseline import BaselineConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_CONFIG_PATH = PROJECT_ROOT / "configs" / "graphrag_baseline.yaml"
BASELINE_FULL_CONFIG_PATH = PROJECT_ROOT / "configs" / "graphrag_baseline_full_500.yaml"


def test_rule_based_entity_extractor_finds_stable_capitalized_entities() -> None:
    extractor = RuleBasedEntityExtractor()

    entities = extractor.extract("Atomised was directed by Oskar Roehler in Germany.")
    normalized = {entity.normalized for entity in entities}

    assert "atomised" in normalized
    assert "oskar roehler" in normalized
    assert "germany" in normalized


def test_rule_based_entity_extractor_filters_sentence_initial_noise() -> None:
    extractor = RuleBasedEntityExtractor()

    entities = extractor.extract(
        "He visited American Museum in July. It was founded by Ada Lovelace. "
        "Are the directors of both films from the same country?"
    )
    normalized = {entity.normalized for entity in entities}

    assert "he" not in normalized
    assert "it" not in normalized
    assert "are" not in normalized
    assert "july" not in normalized
    assert "american" not in normalized
    assert "american museum" in normalized
    assert "ada lovelace" in normalized


def test_normalize_entity_collapses_case_and_punctuation() -> None:
    assert normalize_entity(" Atomised (Film)! ") == "atomised film"


def test_document_entity_graph_connects_documents_to_entities() -> None:
    extractor = RuleBasedEntityExtractor()
    documents = [
        CorpusDocument(
            doc_id="d1",
            title="Atomised Film",
            text="Atomised was directed by Oskar Roehler.",
        ),
        CorpusDocument(
            doc_id="d2",
            title="Gisela Elsner",
            text="Gisela Elsner was the mother of Oskar Roehler.",
        ),
    ]

    graph_index = build_document_entity_graph(documents, extractor)

    assert graph_index.graph.has_edge("doc:d1", "ent:atomised")
    assert graph_index.graph.has_edge("doc:d1", "ent:oskar roehler")
    assert graph_index.graph.has_edge("doc:d2", "ent:gisela elsner")
    assert graph_index.entity_to_docs["oskar roehler"] == {"d1", "d2"}


def test_retriever_can_follow_bridge_entity_to_second_support_document() -> None:
    extractor = RuleBasedEntityExtractor()
    documents = [
        CorpusDocument(
            doc_id="d1",
            title="Atomised Film",
            text="Atomised was directed by Oskar Roehler.",
        ),
        CorpusDocument(
            doc_id="d2",
            title="Gisela Elsner",
            text="Gisela Elsner was the mother of Oskar Roehler.",
        ),
        CorpusDocument(
            doc_id="d3",
            title="Unrelated Germany",
            text="Germany has many films and directors.",
        ),
    ]
    graph_index = build_document_entity_graph(documents, extractor)
    sample = NormalizedSample(
        query_id="q1",
        query="Who is the mother of the director of Atomised?",
        answer="Gisela Elsner",
        support_doc_ids=["d1", "d2"],
        support_docs=documents[:2],
    )

    trace = retrieve_paths_for_query(sample, graph_index, extractor, top_k=5, max_depth=3)

    retrieved_ids = [candidate.doc_id for candidate in trace.candidates]
    assert "d1" in retrieved_ids
    assert "d2" in retrieved_ids
    d2_candidate = next(candidate for candidate in trace.candidates if candidate.doc_id == "d2")
    assert "oskar roehler" in d2_candidate.bridge_entities
    assert d2_candidate.path_nodes[0] == "query:q1"
    assert d2_candidate.path_nodes[-1] == "doc:d2"


def test_run_graphrag_baseline_writes_trace_cache_and_report(tmp_path) -> None:
    documents = [
        CorpusDocument(
            doc_id="d1",
            title="Atomised Film",
            text="Atomised was directed by Oskar Roehler.",
        ),
        CorpusDocument(
            doc_id="d2",
            title="Gisela Elsner",
            text="Gisela Elsner was the mother of Oskar Roehler.",
        ),
    ]
    sample = NormalizedSample(
        query_id="q1",
        query="Who is the mother of the director of Atomised?",
        answer="Gisela Elsner",
        support_doc_ids=["d1", "d2"],
        support_docs=documents,
    )
    outputs = BaselineOutputPaths(
        trace_path=tmp_path / "traces.jsonl",
        corpus_entity_cache_path=tmp_path / "corpus_entities.jsonl",
        query_entity_cache_path=tmp_path / "query_entities.jsonl",
        report_path=tmp_path / "report.md",
    )

    summary = run_graphrag_baseline(
        dataset_name="toy",
        samples=[sample],
        corpus_documents=documents,
        outputs=outputs,
        top_k=5,
        max_depth=3,
    )

    assert summary.dataset == "toy"
    assert summary.query_count == 1
    assert summary.hit_at_k == 1.0
    assert outputs.trace_path.exists()
    assert outputs.corpus_entity_cache_path.exists()
    assert outputs.query_entity_cache_path.exists()
    assert outputs.report_path.exists()

    trace = json.loads(outputs.trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert trace["query_id"] == "q1"
    assert "d2" in [candidate["doc_id"] for candidate in trace["candidates"]]
    assert "hit@5" in outputs.report_path.read_text(encoding="utf-8")


def test_baseline_config_targets_debug_50_run() -> None:
    config = BaselineConfig.from_yaml(BASELINE_CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "debug_50.jsonl"
    assert config.raw_data_root == PROJECT_ROOT.parent / "external_repos" / "logicPoison" / "datasets"
    assert config.output_root == PROJECT_ROOT / "outputs" / "baseline"
    assert config.top_k == 10
    assert config.max_depth == 3


def test_baseline_full_config_uses_full_500_output_names() -> None:
    config = BaselineConfig.from_yaml(BASELINE_FULL_CONFIG_PATH)
    outputs = config.output_paths()

    assert config.sample_path == PROJECT_ROOT / "data" / "processed" / "2wikimultihopqa" / "samples.jsonl"
    assert config.run_name == "full_500"
    assert outputs.trace_path == PROJECT_ROOT / "outputs" / "baseline" / "2wikimultihopqa" / "full_500_traces.jsonl"
    assert (
        outputs.query_entity_cache_path
        == PROJECT_ROOT / "outputs" / "baseline" / "2wikimultihopqa" / "full_500_query_entities.jsonl"
    )
