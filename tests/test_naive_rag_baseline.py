import json
from pathlib import Path

import numpy as np

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.naive_rag.baseline import (
    NaiveRagOutputPaths,
    retrieve_naive_rag,
    run_naive_rag_baseline,
)
from logicguard.naive_rag.run_baseline import NaiveRagConfig


class ToyEncoder:
    """Small deterministic encoder for dense-retrieval tests."""

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    float("atomised" in lowered),
                    float("mother" in lowered or "gisela" in lowered),
                    float("germany" in lowered),
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


def _documents() -> list[CorpusDocument]:
    return [
        CorpusDocument(
            "d1", "Atomised Film", "Atomised was directed by Oskar Roehler."
        ),
        CorpusDocument(
            "d2", "Gisela Elsner", "Gisela Elsner was the mother of Oskar Roehler."
        ),
        CorpusDocument("d3", "Germany", "Germany has many films."),
    ]


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="Who is the mother of the director of Atomised?",
        answer="Gisela Elsner",
        support_doc_ids=["d1", "d2"],
        support_docs=_documents()[:2],
    )


def test_bm25_retrieval_returns_ranked_trace() -> None:
    trace = retrieve_naive_rag(_sample(), _documents(), mode="bm25", top_k=2)

    assert trace.query_id == "q1"
    assert len(trace.candidates) == 2
    assert {candidate.doc_id for candidate in trace.candidates}.intersection(
        {"d1", "d2"}
    )
    assert trace.candidates[0].path_nodes == [
        "query:q1",
        f"doc:{trace.candidates[0].doc_id}",
    ]


def test_dense_retrieval_uses_injected_encoder() -> None:
    trace = retrieve_naive_rag(
        _sample(), _documents(), mode="dense", top_k=2, encoder=ToyEncoder()
    )

    assert [candidate.doc_id for candidate in trace.candidates] == ["d2", "d1"]
    assert trace.candidates[0].score > trace.candidates[1].score


def test_hybrid_retrieval_combines_bm25_and_dense_scores() -> None:
    trace = retrieve_naive_rag(
        _sample(), _documents(), mode="hybrid", top_k=3, encoder=ToyEncoder()
    )

    assert len(trace.candidates) == 3
    assert trace.candidates[0].score <= 1.0
    assert "bm25" in trace.candidates[0].bridge_entities
    assert "dense" in trace.candidates[0].bridge_entities


def test_run_naive_rag_baseline_writes_outputs(tmp_path: Path) -> None:
    outputs = NaiveRagOutputPaths(
        trace_path=tmp_path / "traces.jsonl",
        report_path=tmp_path / "report.md",
    )

    summary = run_naive_rag_baseline(
        dataset_name="toy",
        samples=[_sample()],
        corpus_documents=_documents(),
        outputs=outputs,
        mode="hybrid",
        top_k=2,
        encoder=ToyEncoder(),
    )

    assert summary["query_count"] == 1
    assert summary["hit_at_k"] == 1.0
    assert outputs.trace_path.exists()
    assert outputs.report_path.exists()
    trace = json.loads(outputs.trace_path.read_text(encoding="utf-8").splitlines()[0])
    assert trace["query_id"] == "q1"
    assert "NaiveRAG" in outputs.report_path.read_text(encoding="utf-8")


def test_naive_rag_config_derives_mode_specific_outputs(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "naive.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        "\n".join(
            [
                "dataset: toy",
                "raw_data_root: raw",
                "sample_path: data/processed/toy/debug_50.jsonl",
                "corpus_path: outputs/attacks/toy/poisoned_corpus.jsonl",
                "output_root: outputs/naive_rag",
                "report_root: outputs/reports",
                "run_name: debug_50",
                "mode: bm25",
                "top_k: 3",
            ]
        ),
        encoding="utf-8",
    )

    config = NaiveRagConfig.from_yaml(config_path)
    outputs = config.output_paths()

    assert config.dataset == "toy"
    assert config.mode == "bm25"
    assert config.corpus_path is not None
    assert config.corpus_path.name == "poisoned_corpus.jsonl"
    assert outputs.trace_path.name == "debug_50_traces.jsonl"
    assert outputs.trace_path.parent.name == "toy"
    assert outputs.trace_path.parent.parent.name == "bm25"
    assert outputs.report_path.name == "naive_rag_bm25_toy_debug_50.md"
