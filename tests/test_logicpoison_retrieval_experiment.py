from pathlib import Path

from logicguard.experiments.run_logicpoison_retrieval import (
    LogicPoisonRetrievalConfig,
    calculate_logicpoison_retrieval_metrics,
    run_from_config,
)
from logicguard.graph.schemas import PathCandidate, RetrievalTrace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_retrieval_stage2.yaml"


def test_logicpoison_retrieval_config_uses_project_local_inputs() -> None:
    config = LogicPoisonRetrievalConfig.from_yaml(CONFIG_PATH)

    assert (
        config.clean_data_root
        == PROJECT_ROOT / "data" / "logicpoison_official" / "clean"
    )
    assert (
        config.poisoned_data_root
        == PROJECT_ROOT / "data" / "logicpoison_official" / "poisoned"
    )
    assert (
        config.output_root
        == PROJECT_ROOT / "outputs" / "retrieval" / "logicpoison_official"
    )
    assert (
        config.report_path
        == PROJECT_ROOT / "outputs" / "reports" / "LogicPoison检索层影响实验报告.md"
    )
    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.retrievers == ["naive_bm25", "graph_surrogate"]
    assert config.top_k == 10
    assert config.max_depth == 3
    assert config.sample_limit is None


def test_calculate_logicpoison_retrieval_metrics_counts_changed_exposure() -> None:
    traces = [
        RetrievalTrace(
            query_id="q1",
            query="question one",
            answer="answer",
            gold_doc_ids=["g1", "g2"],
            query_entities=[],
            candidates=[
                PathCandidate(
                    doc_id="g1",
                    title="Changed gold",
                    score=3.0,
                    path_nodes=["query:q1", "doc:g1"],
                    matched_query_entities=[],
                    bridge_entities=[],
                ),
                PathCandidate(
                    doc_id="d1",
                    title="Distractor",
                    score=2.0,
                    path_nodes=["query:q1", "doc:d1"],
                    matched_query_entities=[],
                    bridge_entities=[],
                ),
            ],
        ),
        RetrievalTrace(
            query_id="q2",
            query="question two",
            answer="answer",
            gold_doc_ids=["g3"],
            query_entities=[],
            candidates=[
                PathCandidate(
                    doc_id="d2",
                    title="Distractor",
                    score=1.0,
                    path_nodes=["query:q2", "doc:d2"],
                    matched_query_entities=[],
                    bridge_entities=[],
                )
            ],
        ),
    ]

    metrics = calculate_logicpoison_retrieval_metrics(
        dataset="toy",
        retriever="naive_bm25",
        corpus_state="poisoned",
        traces=traces,
        changed_doc_ids={"g1", "p1"},
        changed_gold_doc_ids_by_query={"q1": {"g1"}, "q2": set()},
        top_k=2,
    )

    assert metrics.query_count == 2
    assert metrics.hit_at_k == 0.5
    assert metrics.gold_recall_at_k == 0.25
    assert metrics.changed_doc_retrieval_at_k == 0.5
    assert metrics.changed_gold_exposure_at_k == 0.5
    assert metrics.trusted_gold_recall_at_k == 0.0
    assert metrics.average_changed_docs_at_k == 0.5


def test_run_from_config_writes_small_naive_retrieval_artifacts(tmp_path: Path) -> None:
    config = LogicPoisonRetrievalConfig(
        clean_data_root=PROJECT_ROOT / "data" / "logicpoison_official" / "clean",
        poisoned_data_root=PROJECT_ROOT / "data" / "logicpoison_official" / "poisoned",
        output_root=tmp_path / "retrieval" / "logicpoison_official",
        report_path=tmp_path / "reports" / "LogicPoison检索层影响实验报告.md",
        datasets=["2wikimultihopqa"],
        retrievers=["naive_bm25"],
        top_k=5,
        max_depth=3,
        sample_limit=5,
    )

    metrics = run_from_config(config)
    dataset_output = config.output_root / "2wikimultihopqa"

    assert len(metrics) == 2
    assert {item.corpus_state for item in metrics} == {"clean", "poisoned"}
    assert (dataset_output / "naive_bm25_clean_traces.jsonl").is_file()
    assert (dataset_output / "naive_bm25_poisoned_traces.jsonl").is_file()
    assert (dataset_output / "retrieval_metrics.jsonl").is_file()
    assert config.report_path.is_file()
