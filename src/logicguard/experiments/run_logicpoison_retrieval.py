"""Stage-2 retrieval experiments for official LogicPoison corpora.

This runner compares clean and official LogicPoison-poisoned corpora under two
retrieval families:

1. NaiveRAG BM25, a conventional sparse lexical RAG baseline.
2. The project lightweight GraphRAG surrogate, which emits path-centric traces.

The runner deliberately keeps attack/defense logic out of retrieval. Its job is
to answer whether LogicPoison's in-place entity swaps enter top-k evidence and
how much clean gold support remains available before any LogicGuard filtering.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import yaml

from logicguard.data.logicpoison_official import (
    LogicPoisonOfficialConfig,
    build_corpus_diff_records,
    build_query_integrity_records,
    load_logicpoison_pair,
)
from logicguard.data.prepare import build_samples
from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.baseline import BaselineOutputPaths, run_graphrag_baseline
from logicguard.graph.schemas import EntityMention, PathCandidate, RetrievalTrace
from logicguard.naive_rag.baseline import NaiveRagOutputPaths, run_naive_rag_baseline

RetrieverName = Literal["naive_bm25", "graph_surrogate"]
CorpusState = Literal["clean", "poisoned"]


@dataclass(frozen=True, slots=True)
class LogicPoisonRetrievalConfig:
    """Configuration for the retrieval-only LogicPoison comparison stage."""

    clean_data_root: Path
    poisoned_data_root: Path
    output_root: Path
    report_path: Path
    datasets: list[str]
    retrievers: list[str]
    top_k: int
    max_depth: int
    sample_limit: int | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "LogicPoisonRetrievalConfig":
        """Load YAML configuration with paths relative to the project root."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            clean_data_root=resolve_project_path(payload["clean_data_root"]),
            poisoned_data_root=resolve_project_path(payload["poisoned_data_root"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            datasets=list(payload["datasets"]),
            retrievers=list(payload.get("retrievers", ["naive_bm25", "graph_surrogate"])),
            top_k=int(payload.get("top_k", 10)),
            max_depth=int(payload.get("max_depth", 3)),
            sample_limit=(
                int(payload["sample_limit"])
                if payload.get("sample_limit") is not None
                else None
            ),
        )

    def to_logicpoison_official_config(self) -> LogicPoisonOfficialConfig:
        """Reuse the stage-0 pair loader without duplicating path handling."""

        return LogicPoisonOfficialConfig(
            clean_data_root=self.clean_data_root,
            poisoned_data_root=self.poisoned_data_root,
            output_root=self.output_root,
            report_path=self.report_path,
            datasets=self.datasets,
        )


@dataclass(frozen=True, slots=True)
class LogicPoisonRetrievalMetrics:
    """Retrieval and LogicPoison exposure metrics for one run."""

    dataset: str
    retriever: str
    corpus_state: str
    query_count: int
    corpus_doc_count: int
    top_k: int
    hit_at_k: float
    gold_recall_at_k: float
    changed_doc_retrieval_at_k: float
    changed_gold_exposure_at_k: float
    trusted_gold_recall_at_k: float
    queries_with_trusted_gold: int
    queries_with_changed_gold_support: int
    average_changed_docs_at_k: float
    average_changed_gold_docs_at_k: float
    avg_candidates: float

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation used by reports and tests."""

        return asdict(self)


def run_from_config(
    config: LogicPoisonRetrievalConfig,
) -> list[LogicPoisonRetrievalMetrics]:
    """Run stage-2 retrieval comparisons and write traces, metrics, and report."""

    official_config = config.to_logicpoison_official_config()
    all_metrics: list[LogicPoisonRetrievalMetrics] = []
    for dataset_name in config.datasets:
        pair = load_logicpoison_pair(official_config, dataset_name)
        samples = build_samples(pair.clean)
        if config.sample_limit is not None:
            samples = samples[: config.sample_limit]

        diff_records = build_corpus_diff_records(pair)
        changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
        integrity_records = build_query_integrity_records(pair, changed_doc_ids)
        changed_gold_doc_ids_by_query = {
            record.query_id: set(record.changed_support_doc_ids)
            for record in integrity_records
        }

        dataset_metrics: list[LogicPoisonRetrievalMetrics] = []
        if "naive_bm25" in config.retrievers:
            dataset_metrics.extend(
                _run_naive_bm25_pair(
                    dataset=dataset_name,
                    samples=samples,
                    clean_corpus=list(pair.clean.corpus.values()),
                    poisoned_corpus=list(pair.poisoned.corpus.values()),
                    config=config,
                    changed_doc_ids=changed_doc_ids,
                    changed_gold_doc_ids_by_query=changed_gold_doc_ids_by_query,
                )
            )
        if "graph_surrogate" in config.retrievers:
            dataset_metrics.extend(
                _run_graph_surrogate_pair(
                    dataset=dataset_name,
                    samples=samples,
                    clean_corpus=list(pair.clean.corpus.values()),
                    poisoned_corpus=list(pair.poisoned.corpus.values()),
                    config=config,
                    changed_doc_ids=changed_doc_ids,
                    changed_gold_doc_ids_by_query=changed_gold_doc_ids_by_query,
                )
            )

        _write_metrics_jsonl(
            config.output_root / dataset_name / "retrieval_metrics.jsonl",
            dataset_metrics,
        )
        all_metrics.extend(dataset_metrics)

    _write_metrics_jsonl(config.output_root / "retrieval_metrics.jsonl", all_metrics)
    write_retrieval_report(config.report_path, all_metrics)
    return all_metrics


def calculate_logicpoison_retrieval_metrics(
    dataset: str,
    retriever: str,
    corpus_state: str,
    traces: list[RetrievalTrace],
    changed_doc_ids: set[str],
    changed_gold_doc_ids_by_query: dict[str, set[str]],
    top_k: int,
) -> LogicPoisonRetrievalMetrics:
    """Calculate retrieval quality and changed-document exposure metrics.

    `changed_doc_ids` is derived by comparing official poisoned corpus against
    clean corpus. For clean runs it means "documents that would be changed under
    the poisoned corpus"; for poisoned runs it means actual modified evidence.
    The report labels this distinction so the metric is not over-interpreted.
    """

    hit_values: list[float] = []
    recall_values: list[float] = []
    trusted_recall_values: list[float] = []
    queries_with_trusted_gold = 0
    changed_doc_exposure_values: list[float] = []
    changed_gold_exposure_values: list[float] = []
    changed_doc_counts: list[float] = []
    changed_gold_counts: list[float] = []
    candidate_counts: list[float] = []

    for trace in traces:
        retrieved_doc_ids = [candidate.doc_id for candidate in trace.candidates[:top_k]]
        retrieved_doc_id_set = set(retrieved_doc_ids)
        gold_doc_ids = set(trace.gold_doc_ids)
        changed_gold_doc_ids = changed_gold_doc_ids_by_query.get(trace.query_id, set())
        trusted_gold_doc_ids = gold_doc_ids.difference(changed_gold_doc_ids)
        changed_retrieved_doc_ids = retrieved_doc_id_set.intersection(changed_doc_ids)
        changed_retrieved_gold_doc_ids = retrieved_doc_id_set.intersection(changed_gold_doc_ids)
        gold_overlap = retrieved_doc_id_set.intersection(gold_doc_ids)
        trusted_overlap = retrieved_doc_id_set.intersection(trusted_gold_doc_ids)

        hit_values.append(1.0 if gold_overlap else 0.0)
        recall_values.append(len(gold_overlap) / len(gold_doc_ids) if gold_doc_ids else 0.0)
        if trusted_gold_doc_ids:
            queries_with_trusted_gold += 1
            trusted_recall_values.append(len(trusted_overlap) / len(trusted_gold_doc_ids))
        changed_doc_exposure_values.append(1.0 if changed_retrieved_doc_ids else 0.0)
        changed_gold_exposure_values.append(1.0 if changed_retrieved_gold_doc_ids else 0.0)
        changed_doc_counts.append(float(len(changed_retrieved_doc_ids)))
        changed_gold_counts.append(float(len(changed_retrieved_gold_doc_ids)))
        candidate_counts.append(float(len(retrieved_doc_ids)))

    return LogicPoisonRetrievalMetrics(
        dataset=dataset,
        retriever=retriever,
        corpus_state=corpus_state,
        query_count=len(traces),
        corpus_doc_count=_infer_corpus_doc_count(traces),
        top_k=top_k,
        hit_at_k=_mean(hit_values),
        gold_recall_at_k=_mean(recall_values),
        changed_doc_retrieval_at_k=_mean(changed_doc_exposure_values),
        changed_gold_exposure_at_k=_mean(changed_gold_exposure_values),
        trusted_gold_recall_at_k=_mean(trusted_recall_values),
        queries_with_trusted_gold=queries_with_trusted_gold,
        queries_with_changed_gold_support=sum(
            1 for trace in traces if changed_gold_doc_ids_by_query.get(trace.query_id)
        ),
        average_changed_docs_at_k=_mean(changed_doc_counts),
        average_changed_gold_docs_at_k=_mean(changed_gold_counts),
        avg_candidates=_mean(candidate_counts),
    )


def write_retrieval_report(
    path: Path,
    metrics: list[LogicPoisonRetrievalMetrics],
) -> None:
    """Write the stage-2 Chinese Markdown report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "| 数据集 | 检索器 | 语料状态 | Query数 | hit@k | gold_recall@k | changed_doc_retrieval@k | changed_gold_exposure@k | trusted_gold_recall@k | trusted gold Query数 | 平均changed docs@k |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in metrics:
        rows.append(
            "| "
            + " | ".join(
                [
                    item.dataset,
                    item.retriever,
                    item.corpus_state,
                    str(item.query_count),
                    f"{item.hit_at_k:.4f}",
                    f"{item.gold_recall_at_k:.4f}",
                    f"{item.changed_doc_retrieval_at_k:.4f}",
                    f"{item.changed_gold_exposure_at_k:.4f}",
                    f"{item.trusted_gold_recall_at_k:.4f}",
                    str(item.queries_with_trusted_gold),
                    f"{item.average_changed_docs_at_k:.2f}",
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicPoison 检索层影响实验报告",
            "",
            "## 实验目的",
            "",
            "本阶段只评估检索层，不启用 LogicGuard 防御，也不调用 LLM 回答。实验目标是比较 clean corpus 与 LogicPoison official poisoned corpus 在相同 query/qrels 下的 top-k 证据召回差异，并观察被改写文档是否进入检索上下文。",
            "",
            "## 指标说明",
            "",
            "- `hit@k`：top-k 中是否命中至少一个 gold support，越高表示检索能找到相关证据。",
            "- `gold_recall@k`：top-k 覆盖 gold support 的平均比例，越高表示证据覆盖更完整。",
            "- `changed_doc_retrieval@k`：top-k 中是否出现被 LogicPoison 改写过的 doc_id。clean 语料下表示潜在暴露位置，poisoned 语料下表示实际污染证据暴露。",
            "- `changed_gold_exposure@k`：top-k 中是否出现被改写过的 gold support。该指标越高，说明污染直接进入标准答案所依赖的证据链。",
            "- `trusted_gold_recall@k`：排除被改写 gold support 后，top-k 对仍可信 gold support 的召回比例。若该值很低，说明单纯过滤污染证据后容易缺证。",
            "- `trusted gold Query数`：仍然至少有一个未改写 gold support 的 query 数量，也是 `trusted_gold_recall@k` 的有效分母。",
            "- `平均changed docs@k`：每个 query 的 top-k 中平均出现多少个被改写文档。",
            "",
            "## 实验结果",
            "",
            *rows,
            "",
            "## 当前解读",
            "",
            "- LogicPoison 是原位实体替换攻击，因此 clean/poisoned 的文档 ID 一致；检索指标下降不一定明显，但 poisoned 语料中同一 doc_id 的内容已经变成不可信证据。",
            "- 如果 `changed_gold_exposure@k` 高，说明攻击污染的是原本就会被检索出来的 gold support，后续防御必须结合 content-integrity 与 answer recovery。",
            "- 如果 `trusted_gold_recall@k` 低，说明过滤改写文档后可用 gold support 不足，后续 LLM 可能输出 UNKNOWN，需要从 clean reference 回填证据。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _run_naive_bm25_pair(
    dataset: str,
    samples: list[NormalizedSample],
    clean_corpus: list[CorpusDocument],
    poisoned_corpus: list[CorpusDocument],
    config: LogicPoisonRetrievalConfig,
    changed_doc_ids: set[str],
    changed_gold_doc_ids_by_query: dict[str, set[str]],
) -> list[LogicPoisonRetrievalMetrics]:
    metrics: list[LogicPoisonRetrievalMetrics] = []
    for corpus_state, corpus_documents in (
        ("clean", clean_corpus),
        ("poisoned", poisoned_corpus),
    ):
        trace_path = config.output_root / dataset / f"naive_bm25_{corpus_state}_traces.jsonl"
        report_path = config.output_root / dataset / "reports" / f"naive_bm25_{corpus_state}.md"
        run_naive_rag_baseline(
            dataset_name=dataset,
            samples=samples,
            corpus_documents=corpus_documents,
            outputs=NaiveRagOutputPaths(trace_path=trace_path, report_path=report_path),
            mode="bm25",
            top_k=config.top_k,
        )
        traces = load_retrieval_traces(trace_path)
        metric = calculate_logicpoison_retrieval_metrics(
            dataset=dataset,
            retriever="naive_bm25",
            corpus_state=corpus_state,
            traces=traces,
            changed_doc_ids=changed_doc_ids,
            changed_gold_doc_ids_by_query=changed_gold_doc_ids_by_query,
            top_k=config.top_k,
        )
        metrics.append(_with_corpus_doc_count(metric, len(corpus_documents)))
    return metrics


def _run_graph_surrogate_pair(
    dataset: str,
    samples: list[NormalizedSample],
    clean_corpus: list[CorpusDocument],
    poisoned_corpus: list[CorpusDocument],
    config: LogicPoisonRetrievalConfig,
    changed_doc_ids: set[str],
    changed_gold_doc_ids_by_query: dict[str, set[str]],
) -> list[LogicPoisonRetrievalMetrics]:
    metrics: list[LogicPoisonRetrievalMetrics] = []
    for corpus_state, corpus_documents in (
        ("clean", clean_corpus),
        ("poisoned", poisoned_corpus),
    ):
        output_dir = config.output_root / dataset
        trace_path = output_dir / f"graph_surrogate_{corpus_state}_traces.jsonl"
        outputs = BaselineOutputPaths(
            trace_path=trace_path,
            corpus_entity_cache_path=output_dir / f"graph_surrogate_{corpus_state}_corpus_entities.jsonl",
            query_entity_cache_path=output_dir / f"graph_surrogate_{corpus_state}_query_entities.jsonl",
            report_path=output_dir / "reports" / f"graph_surrogate_{corpus_state}.md",
        )
        run_graphrag_baseline(
            dataset_name=dataset,
            samples=samples,
            corpus_documents=corpus_documents,
            outputs=outputs,
            top_k=config.top_k,
            max_depth=config.max_depth,
        )
        traces = load_retrieval_traces(trace_path)
        metric = calculate_logicpoison_retrieval_metrics(
            dataset=dataset,
            retriever="graph_surrogate",
            corpus_state=corpus_state,
            traces=traces,
            changed_doc_ids=changed_doc_ids,
            changed_gold_doc_ids_by_query=changed_gold_doc_ids_by_query,
            top_k=config.top_k,
        )
        metrics.append(_with_corpus_doc_count(metric, len(corpus_documents)))
    return metrics


def load_retrieval_traces(path: Path) -> list[RetrievalTrace]:
    """Load trace JSONL emitted by either NaiveRAG or the graph surrogate."""

    traces: list[RetrievalTrace] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            traces.append(
                RetrievalTrace(
                    query_id=str(payload["query_id"]),
                    query=str(payload["query"]),
                    answer=str(payload["answer"]),
                    gold_doc_ids=[str(doc_id) for doc_id in payload["gold_doc_ids"]],
                    query_entities=[
                        EntityMention(
                            text=str(item["text"]),
                            normalized=str(item["normalized"]),
                            label=str(item.get("label", "RULE")),
                        )
                        for item in payload.get("query_entities", [])
                    ],
                    candidates=[
                        PathCandidate(
                            doc_id=str(item["doc_id"]),
                            title=str(item["title"]),
                            score=float(item["score"]),
                            path_nodes=[str(node) for node in item["path_nodes"]],
                            matched_query_entities=[
                                str(entity) for entity in item["matched_query_entities"]
                            ],
                            bridge_entities=[
                                str(entity) for entity in item["bridge_entities"]
                            ],
                        )
                        for item in payload["candidates"]
                    ],
                )
            )
    return traces


def _write_metrics_jsonl(
    path: Path,
    metrics: list[LogicPoisonRetrievalMetrics],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in metrics:
            handle.write(json.dumps(item.to_json_dict(), ensure_ascii=False) + "\n")


def _with_corpus_doc_count(
    metric: LogicPoisonRetrievalMetrics,
    corpus_doc_count: int,
) -> LogicPoisonRetrievalMetrics:
    """Patch corpus count after running from traces.

    The trace file intentionally stores only top-k candidates, not the full
    indexed corpus. Keeping this as a small helper avoids adding corpus-wide
    metadata to every trace line.
    """

    return LogicPoisonRetrievalMetrics(
        dataset=metric.dataset,
        retriever=metric.retriever,
        corpus_state=metric.corpus_state,
        query_count=metric.query_count,
        corpus_doc_count=corpus_doc_count,
        top_k=metric.top_k,
        hit_at_k=metric.hit_at_k,
        gold_recall_at_k=metric.gold_recall_at_k,
        changed_doc_retrieval_at_k=metric.changed_doc_retrieval_at_k,
        changed_gold_exposure_at_k=metric.changed_gold_exposure_at_k,
        trusted_gold_recall_at_k=metric.trusted_gold_recall_at_k,
        queries_with_trusted_gold=metric.queries_with_trusted_gold,
        queries_with_changed_gold_support=metric.queries_with_changed_gold_support,
        average_changed_docs_at_k=metric.average_changed_docs_at_k,
        average_changed_gold_docs_at_k=metric.average_changed_gold_docs_at_k,
        avg_candidates=metric.avg_candidates,
    )


def _infer_corpus_doc_count(traces: list[RetrievalTrace]) -> int:
    """Best-effort corpus count placeholder when only traces are available."""

    return len({candidate.doc_id for trace in traces for candidate in trace.candidates})


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stage-2 retrieval comparisons on official LogicPoison corpora."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_retrieval_stage2.yaml"),
        help="Path to the stage-2 retrieval YAML config.",
    )
    args = parser.parse_args()
    config = LogicPoisonRetrievalConfig.from_yaml(args.config)
    metrics = run_from_config(config)
    for item in metrics:
        print(
            f"{item.dataset}/{item.retriever}/{item.corpus_state}: "
            f"hit@{item.top_k}={item.hit_at_k:.4f}, "
            f"recall@{item.top_k}={item.gold_recall_at_k:.4f}, "
            f"changed_doc@{item.top_k}={item.changed_doc_retrieval_at_k:.4f}, "
            f"changed_gold@{item.top_k}={item.changed_gold_exposure_at_k:.4f}"
        )


if __name__ == "__main__":
    main()
