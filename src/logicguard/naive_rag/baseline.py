"""Auditable NaiveRAG retrieval baseline.

This module implements three conventional retrieval modes that are common in
non-graph RAG systems:

- BM25: sparse lexical retrieval over title + passage text.
- dense: vector retrieval with an injected encoder or SentenceTransformer.
- hybrid: a normalized weighted combination of BM25 and dense scores.

The important design choice is that the output is still a RetrievalTrace. A
NaiveRAG candidate does not have a graph path, so we represent the evidence as a
simple query-to-document edge. That lets the later LogicGuard defense and LLM
answer stages consume NaiveRAG and GraphRAG-like retrieval artifacts through the
same interface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.schemas import PathCandidate, RetrievalTrace

NaiveRagMode = Literal["bm25", "dense", "hybrid"]
DEFAULT_ENCODER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class TextEncoder(Protocol):
    """Small protocol shared by SentenceTransformer and test encoders."""

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return one dense vector per input text."""


@dataclass(frozen=True, slots=True)
class NaiveRagOutputPaths:
    """All files written by one NaiveRAG run."""

    trace_path: Path
    report_path: Path

    def ensure_parent_dirs(self) -> None:
        """Create output directories before writing trace/report artifacts."""

        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class NaiveRagRunSummary:
    """Compact retrieval metrics for one NaiveRAG run."""

    dataset: str
    mode: str
    query_count: int
    corpus_doc_count: int
    top_k: int
    hit_at_k: float
    gold_recall_at_k: float
    avg_candidates: float

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable representation for tests and future CSV export."""

        return {
            "dataset": self.dataset,
            "mode": self.mode,
            "query_count": self.query_count,
            "corpus_doc_count": self.corpus_doc_count,
            "top_k": self.top_k,
            "hit_at_k": self.hit_at_k,
            "gold_recall_at_k": self.gold_recall_at_k,
            "avg_candidates": self.avg_candidates,
        }


@dataclass(slots=True)
class NaiveRagIndex:
    """In-memory sparse/dense indexes reused across many queries.

    The index is intentionally lightweight: BM25 keeps tokenized text in memory,
    and dense retrieval keeps a normalized document matrix. This is sufficient
    for the current 500-query benchmark scale while leaving a clear replacement
    point for FAISS, Chroma, Milvus, or another vector database later.
    """

    documents: list[CorpusDocument]
    doc_texts: list[str]
    tokenized_docs: list[list[str]]
    bm25: BM25Okapi
    encoder: TextEncoder | None = None
    dense_doc_matrix: np.ndarray | None = None

    @classmethod
    def build(
        cls,
        documents: list[CorpusDocument],
        mode: NaiveRagMode,
        encoder: TextEncoder | None = None,
    ) -> "NaiveRagIndex":
        """Build reusable retrieval state for one corpus.

        BM25 is always built because it is cheap and also gives dense mode a
        deterministic lexical tie-breaker. Dense vectors are only materialized
        when the selected mode needs them.
        """

        if not documents:
            raise ValueError("NaiveRAG requires at least one corpus document")
        doc_texts = [_document_text(document) for document in documents]
        tokenized_docs = [_tokenize(text) for text in doc_texts]
        bm25 = BM25Okapi(tokenized_docs)
        dense_doc_matrix = None
        if mode in {"dense", "hybrid"}:
            if encoder is None:
                encoder = load_sentence_transformer_encoder()
            dense_doc_matrix = _normalize_vectors(_encode_texts(encoder, doc_texts))
        return cls(
            documents=documents,
            doc_texts=doc_texts,
            tokenized_docs=tokenized_docs,
            bm25=bm25,
            encoder=encoder,
            dense_doc_matrix=dense_doc_matrix,
        )

    def score(
        self,
        query: str,
        mode: NaiveRagMode,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
    ) -> tuple[np.ndarray, list[str]]:
        """Score all documents for a query and return score-source labels."""

        bm25_scores = np.asarray(
            self.bm25.get_scores(_tokenize(query)), dtype=np.float32
        )
        if mode == "bm25":
            return bm25_scores, ["bm25"]

        if self.encoder is None or self.dense_doc_matrix is None:
            raise ValueError("Dense retrieval requires an encoder-backed NaiveRagIndex")

        query_vector = _normalize_vectors(_encode_texts(self.encoder, [query]))
        dense_scores = np.asarray(
            query_vector @ self.dense_doc_matrix.T, dtype=np.float32
        ).reshape(-1)
        if mode == "dense":
            # A tiny BM25 term is only used to make equal cosine scores stable in
            # small corpora; it is too small to dominate dense similarity.
            return dense_scores + (_normalize_scores(bm25_scores) * 1e-6), ["dense"]

        if mode == "hybrid":
            if bm25_weight < 0 or dense_weight < 0:
                raise ValueError("Hybrid weights must be non-negative")
            total_weight = bm25_weight + dense_weight
            if total_weight <= 0:
                raise ValueError("At least one hybrid weight must be positive")
            bm25_part = _normalize_scores(bm25_scores) * (bm25_weight / total_weight)
            dense_part = _normalize_scores(dense_scores) * (dense_weight / total_weight)
            return bm25_part + dense_part, ["bm25", "dense"]

        raise ValueError(f"Unsupported NaiveRAG mode: {mode}")


def retrieve_naive_rag(
    sample: NormalizedSample,
    corpus_documents: list[CorpusDocument],
    mode: NaiveRagMode = "bm25",
    top_k: int = 10,
    encoder: TextEncoder | None = None,
    bm25_weight: float = 0.5,
    dense_weight: float = 0.5,
) -> RetrievalTrace:
    """Retrieve top-k documents for one sample.

    This convenience function is used by unit tests and small experiments. For
    full dataset runs, build NaiveRagIndex once and call `_retrieve_with_index`
    repeatedly through `run_naive_rag_baseline`.
    """

    index = NaiveRagIndex.build(corpus_documents, mode=mode, encoder=encoder)
    return _retrieve_with_index(
        sample=sample,
        index=index,
        mode=mode,
        top_k=top_k,
        bm25_weight=bm25_weight,
        dense_weight=dense_weight,
    )


def run_naive_rag_baseline(
    dataset_name: str,
    samples: list[NormalizedSample],
    corpus_documents: list[CorpusDocument],
    outputs: NaiveRagOutputPaths,
    mode: NaiveRagMode = "bm25",
    top_k: int = 10,
    encoder: TextEncoder | None = None,
    bm25_weight: float = 0.5,
    dense_weight: float = 0.5,
) -> dict[str, object]:
    """Run NaiveRAG over a sample list and write traces plus a Chinese report."""

    outputs.ensure_parent_dirs()
    index = NaiveRagIndex.build(corpus_documents, mode=mode, encoder=encoder)
    traces = [
        _retrieve_with_index(
            sample=sample,
            index=index,
            mode=mode,
            top_k=top_k,
            bm25_weight=bm25_weight,
            dense_weight=dense_weight,
        )
        for sample in samples
    ]
    _write_traces(outputs.trace_path, traces)

    summary = _summarize_run(
        dataset_name=dataset_name,
        mode=mode,
        traces=traces,
        corpus_documents=corpus_documents,
        top_k=top_k,
    )
    _write_report(outputs.report_path, summary)
    return summary.to_json_dict()


def load_sentence_transformer_encoder(
    model_name: str = DEFAULT_ENCODER_MODEL,
) -> TextEncoder:
    """Load a SentenceTransformer encoder lazily.

    Importing sentence-transformers can be slow and may download model files, so
    the dependency is only imported when a dense/hybrid run actually needs it.
    """

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _retrieve_with_index(
    sample: NormalizedSample,
    index: NaiveRagIndex,
    mode: NaiveRagMode,
    top_k: int,
    bm25_weight: float,
    dense_weight: float,
) -> RetrievalTrace:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    scores, sources = index.score(
        sample.query,
        mode=mode,
        bm25_weight=bm25_weight,
        dense_weight=dense_weight,
    )
    ranked_indices = _top_indices(scores, top_k=top_k)
    candidates = [
        _make_candidate(
            index.documents[index_position],
            float(scores[index_position]),
            sample.query_id,
            sources,
        )
        for index_position in ranked_indices
    ]
    return RetrievalTrace(
        query_id=sample.query_id,
        query=sample.query,
        answer=sample.answer,
        gold_doc_ids=list(sample.support_doc_ids),
        query_entities=[],
        candidates=candidates,
    )


def _make_candidate(
    document: CorpusDocument,
    score: float,
    query_id: str,
    sources: list[str],
) -> PathCandidate:
    """Create the shared trace candidate object for a NaiveRAG hit."""

    return PathCandidate(
        doc_id=document.doc_id,
        title=document.title,
        score=score,
        path_nodes=[f"query:{query_id}", f"doc:{document.doc_id}"],
        matched_query_entities=[],
        bridge_entities=list(sources),
    )


def _top_indices(scores: np.ndarray, top_k: int) -> list[int]:
    """Return top indices with deterministic document-order tie-breaking."""

    ranked = sorted(
        range(len(scores)), key=lambda index: (-float(scores[index]), index)
    )
    return ranked[: min(top_k, len(ranked))]


def _summarize_run(
    dataset_name: str,
    mode: str,
    traces: list[RetrievalTrace],
    corpus_documents: list[CorpusDocument],
    top_k: int,
) -> NaiveRagRunSummary:
    hit_values: list[float] = []
    recall_values: list[float] = []
    candidate_counts: list[int] = []
    for trace in traces:
        gold_ids = set(trace.gold_doc_ids)
        retrieved_ids = [candidate.doc_id for candidate in trace.candidates[:top_k]]
        retrieved_set = set(retrieved_ids)
        hit_values.append(1.0 if gold_ids.intersection(retrieved_set) else 0.0)
        recall_values.append(
            (len(gold_ids.intersection(retrieved_set)) / len(gold_ids))
            if gold_ids
            else 0.0
        )
        candidate_counts.append(len(retrieved_ids))
    return NaiveRagRunSummary(
        dataset=dataset_name,
        mode=mode,
        query_count=len(traces),
        corpus_doc_count=len(corpus_documents),
        top_k=top_k,
        hit_at_k=_mean(hit_values),
        gold_recall_at_k=_mean(recall_values),
        avg_candidates=_mean([float(count) for count in candidate_counts]),
    )


def _write_traces(path: Path, traces: list[RetrievalTrace]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace.to_json_dict(), ensure_ascii=False) + "\n")


def _write_report(path: Path, summary: NaiveRagRunSummary) -> None:
    content = "\n".join(
        [
            f"# NaiveRAG 检索基线报告：{summary.dataset}",
            "",
            "<!-- logicguard:chinese-report:v1 -->",
            "",
            "## 实验设置",
            "",
            f"- 检索模式：`{summary.mode}`",
            f"- 查询数量：`{summary.query_count}`",
            f"- 语料文档数：`{summary.corpus_doc_count}`",
            f"- Top-k：`{summary.top_k}`",
            "",
            "## 指标说明",
            "",
            f"- `hit@{summary.top_k}`：每个问题的前 {summary.top_k} 个检索结果中，只要命中至少一个金标准支撑文档就记为 1。",
            f"- `gold_recall@{summary.top_k}`：每个问题的前 {summary.top_k} 个检索结果覆盖了多少比例的金标准支撑文档。",
            "- `average candidates/query`：每个问题平均实际返回的候选文档数量。",
            "",
            "## 实验结果",
            "",
            f"- hit@{summary.top_k}: `{summary.hit_at_k:.4f}`",
            f"- gold_recall@{summary.top_k}: `{summary.gold_recall_at_k:.4f}`",
            f"- average candidates/query: `{summary.avg_candidates:.2f}`",
            "",
            "## 结论",
            "",
            "该报告刻画的是标准文本/向量 RAG 检索阶段的证据召回能力，后续可与 GraphRAG 路径检索、污染语料检索和防御后检索进行同口径比较。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _document_text(document: CorpusDocument) -> str:
    return f"{document.title}\n{document.text}".strip()


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]


def _encode_texts(encoder: TextEncoder, texts: list[str]) -> np.ndarray:
    vectors = np.asarray(encoder.encode(texts), dtype=np.float32)
    if vectors.ndim != 2:
        raise ValueError(
            f"Encoder returned {vectors.ndim}D output; expected a 2D matrix"
        )
    if vectors.shape[0] != len(texts):
        raise ValueError("Encoder output row count does not match input text count")
    return vectors


def _normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    safe_norms = np.where(norms == 0.0, 1.0, norms)
    return vectors / safe_norms


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    min_score = float(np.min(scores))
    max_score = float(np.max(scores))
    if max_score - min_score <= 1e-12:
        return np.zeros_like(scores, dtype=np.float32)
    return ((scores - min_score) / (max_score - min_score)).astype(np.float32)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
