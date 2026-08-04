"""Stage-8 non-oracle recovery for official LogicPoison experiments.

Earlier LogicPoison answer-level runs used `full_logicguard_recovery`, which
backfilled filtered contexts from the clean retrieval trace. That is useful as
an upper bound, but it is still oracle-like because the clean trace is already
known. Stage 8 replaces that assumption with a deployable approximation:

1. keep the safe candidates that survived `full_logicguard`;
2. build a BM25 index over the trusted clean reference corpus;
3. re-query that trusted corpus with the original question;
4. backfill remaining context slots from the trusted retrieval results.

The output filenames intentionally match the existing answer-evaluation
contract, so `run_logicpoison_answer_eval` can consume this stage by pointing
`defense_root` at the stage-8 output directory.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.loader import _load_corpus
from logicguard.data.logicpoison_official import (
    LogicPoisonOfficialConfig,
    build_corpus_diff_records,
    build_query_integrity_records,
    load_logicpoison_pair,
)
from logicguard.data.schemas import CorpusDocument
from logicguard.defense.run_logicpoison_defense import (
    LogicPoisonDefenseMetrics,
    calculate_logicpoison_defense_metrics,
    write_metrics_jsonl,
)
from logicguard.defense.schemas import RerankedCandidate, RerankedTrace
from logicguard.experiments.run_logicpoison_retrieval import load_retrieval_traces
from logicguard.naive_rag.baseline import NaiveRagIndex

RecoveryMode = Literal["trusted_bm25"]


@dataclass(frozen=True, slots=True)
class NonOracleRecoveryConfig:
    """Configuration for stage-8 trusted-corpus recovery."""

    clean_data_root: Path
    poisoned_data_root: Path
    retrieval_root: Path
    stage3_defense_root: Path
    output_root: Path
    report_path: Path
    datasets: list[str]
    retrievers: list[str]
    top_k: int
    recovery_mode: RecoveryMode

    @classmethod
    def from_yaml(cls, path: Path) -> "NonOracleRecoveryConfig":
        """Load YAML configuration with paths relative to the project root."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        recovery_mode = str(payload.get("recovery_mode", "trusted_bm25"))
        if recovery_mode != "trusted_bm25":
            raise ValueError(f"Unsupported non-oracle recovery mode: {recovery_mode}")

        return cls(
            clean_data_root=resolve_project_path(payload["clean_data_root"]),
            poisoned_data_root=resolve_project_path(payload["poisoned_data_root"]),
            retrieval_root=resolve_project_path(payload["retrieval_root"]),
            stage3_defense_root=resolve_project_path(payload["stage3_defense_root"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            datasets=[str(dataset) for dataset in payload["datasets"]],
            retrievers=[str(retriever) for retriever in payload["retrievers"]],
            top_k=int(payload.get("top_k", 10)),
            recovery_mode="trusted_bm25",
        )

    def to_logicpoison_official_config(self) -> LogicPoisonOfficialConfig:
        """Reuse the official clean/poisoned corpus pair loader."""

        return LogicPoisonOfficialConfig(
            clean_data_root=self.clean_data_root,
            poisoned_data_root=self.poisoned_data_root,
            output_root=self.output_root,
            report_path=self.report_path,
            datasets=self.datasets,
        )


def run_from_config(config: NonOracleRecoveryConfig) -> list[LogicPoisonDefenseMetrics]:
    """Run trusted BM25 recovery for every configured dataset/retriever."""

    official_config = config.to_logicpoison_official_config()
    all_metrics: list[LogicPoisonDefenseMetrics] = []

    for dataset in config.datasets:
        pair = load_logicpoison_pair(official_config, dataset)
        diff_records = build_corpus_diff_records(pair)
        changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
        integrity_records = build_query_integrity_records(pair, changed_doc_ids)
        changed_gold_by_query = {
            record.query_id: set(record.changed_support_doc_ids)
            for record in integrity_records
        }
        clean_documents = list(
            _load_corpus(config.clean_data_root / dataset / "corpus.jsonl").values()
        )
        trusted_index = NaiveRagIndex.build(clean_documents, mode="bm25")
        dataset_metrics: list[LogicPoisonDefenseMetrics] = []

        for retriever in config.retrievers:
            poisoned_traces = load_retrieval_traces(
                config.retrieval_root / dataset / f"{retriever}_poisoned_traces.jsonl"
            )
            none_traces = _load_reranked_traces(
                config.stage3_defense_root / dataset / f"{retriever}_none_traces.jsonl"
            )
            guarded_traces = _load_reranked_traces(
                config.stage3_defense_root
                / dataset
                / f"{retriever}_full_logicguard_traces.jsonl"
            )
            recovered_traces = [
                build_non_oracle_recovered_trace_from_index(
                    guarded_trace=trace,
                    trusted_index=trusted_index,
                    top_k=config.top_k,
                )
                for trace in guarded_traces
            ]

            dataset_output_root = config.output_root / dataset
            _write_reranked_traces(
                dataset_output_root / f"{retriever}_none_traces.jsonl",
                none_traces,
            )
            _write_reranked_traces(
                dataset_output_root / f"{retriever}_full_logicguard_traces.jsonl",
                guarded_traces,
            )
            _write_reranked_traces(
                dataset_output_root
                / f"{retriever}_full_logicguard_recovery_traces.jsonl",
                recovered_traces,
            )

            metric = calculate_logicpoison_defense_metrics(
                dataset=dataset,
                retriever=retriever,
                mode="full_logicguard_non_oracle_bm25_recovery",
                before_traces=poisoned_traces,
                after_traces=recovered_traces,
                changed_doc_ids=changed_doc_ids,
                changed_gold_doc_ids_by_query=changed_gold_by_query,
                top_k=config.top_k,
            )
            dataset_metrics.append(metric)
            all_metrics.append(metric)

        write_metrics_jsonl(
            config.output_root / dataset / "stage8_recovery_metrics.jsonl",
            dataset_metrics,
        )

    write_metrics_jsonl(
        config.output_root / "stage8_recovery_metrics.jsonl", all_metrics
    )
    write_stage8_report(config.report_path, all_metrics)
    return all_metrics


def build_non_oracle_recovered_trace(
    *,
    guarded_trace: RerankedTrace,
    clean_documents: list[CorpusDocument],
    top_k: int,
) -> RerankedTrace:
    """Backfill a guarded trace by re-querying the trusted clean corpus.

    This function deliberately does not accept or read a clean retrieval trace.
    The only recovery signal is the original question plus the trusted clean
    corpus, which makes it a non-oracle approximation of deployment-time
    evidence recovery.
    """

    if top_k < 1:
        raise ValueError("top_k must be positive")
    index = NaiveRagIndex.build(clean_documents, mode="bm25")
    return build_non_oracle_recovered_trace_from_index(
        guarded_trace=guarded_trace,
        trusted_index=index,
        top_k=top_k,
    )


def build_non_oracle_recovered_trace_from_index(
    *,
    guarded_trace: RerankedTrace,
    trusted_index: NaiveRagIndex,
    top_k: int,
) -> RerankedTrace:
    """Backfill a guarded trace using a reusable trusted BM25 index."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    scores, _ = trusted_index.score(guarded_trace.query, mode="bm25")
    ranked_indices = sorted(
        range(len(scores)), key=lambda item: (-float(scores[item]), item)
    )

    recovered_candidates: list[RerankedCandidate] = []
    seen_doc_ids: set[str] = set()

    for candidate in guarded_trace.candidates:
        if len(recovered_candidates) >= top_k:
            break
        if candidate.doc_id in seen_doc_ids:
            continue
        recovered_candidates.append(candidate)
        seen_doc_ids.add(candidate.doc_id)

    for original_rank, document_index in enumerate(ranked_indices, start=1):
        if len(recovered_candidates) >= top_k:
            break
        document = trusted_index.documents[document_index]
        if document.doc_id in seen_doc_ids:
            continue
        recovered_candidates.append(
            RerankedCandidate(
                doc_id=document.doc_id,
                title=document.title,
                original_rank=original_rank,
                new_rank=0,
                base_score=float(scores[document_index]),
                risk_score=0.0,
                adjusted_score=float(scores[document_index]),
                path_length=1,
                direct_query_match=True,
                source_support_count=1,
                global_support_count=None,
                known_source_document=True,
                reference_content_changed=False,
                matched_query_entities=[],
                bridge_entities=["trusted_bm25"],
                risk_reasons=["trusted_reference_recovery", "non_oracle_bm25_recovery"],
            )
        )
        seen_doc_ids.add(document.doc_id)

    return RerankedTrace(
        query_id=guarded_trace.query_id,
        query=guarded_trace.query,
        answer=guarded_trace.answer,
        gold_doc_ids=guarded_trace.gold_doc_ids,
        candidates=[
            _with_new_rank(candidate, new_rank=index)
            for index, candidate in enumerate(recovered_candidates, start=1)
        ],
    )


def write_stage8_report(path: Path, rows: list[LogicPoisonDefenseMetrics]) -> None:
    """Write the stage-8 Chinese Markdown report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| 数据集 | 检索器 | Query数 | 改写文档暴露@k | 改写gold暴露@k | gold_recall@k | trusted_recall@k | 空上下文率 | recovery候选数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.dataset,
                    row.retriever,
                    str(row.query_count),
                    f"{row.before_changed_doc_exposure_at_k:.4f} -> {row.after_changed_doc_exposure_at_k:.4f}",
                    f"{row.before_changed_gold_exposure_at_k:.4f} -> {row.after_changed_gold_exposure_at_k:.4f}",
                    f"{row.before_gold_recall_at_k:.4f} -> {row.after_gold_recall_at_k:.4f}",
                    f"{row.before_trusted_gold_recall_at_k:.4f} -> {row.after_trusted_gold_recall_at_k:.4f}",
                    f"{row.empty_context_rate:.4f}",
                    str(row.recovered_candidate_count),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicPoison 阶段8非Oracle Recovery实验报告",
            "",
            "## 实验目的",
            "",
            "阶段8用于替代此前偏理想化的 clean-trace recovery。实验在 `full_logicguard` 过滤后，使用原始问题重新检索可信 clean corpus，并将检索到的可信证据回填到上下文中。",
            "",
            "## 方法说明",
            "",
            "- `guarded`：沿用阶段3的 `full_logicguard` 输出，污染文档被 content-integrity 过滤。",
            "- `non_oracle_bm25_recovery`：不读取 clean retrieval trace，只在 clean corpus 上为原始问题重新建立 BM25 检索并回填。",
            "- 阶段8输出目录中的 `full_logicguard_recovery` 文件名保持不变，是为了复用现有回答层 LLM 评估脚本；其内部候选会带有 `non_oracle_bm25_recovery` 标记。",
            "",
            "## 指标说明",
            "",
            "- `改写文档暴露@k`：top-k 中是否仍有 poisoned 版本的改写文档。来自 clean corpus 的 recovery 候选不计为 poisoned 暴露。",
            "- `改写gold暴露@k`：top-k 中是否仍有 poisoned 版本的改写 gold support。",
            "- `gold_recall@k`：防御前后 top-k 覆盖全部 gold support 的比例。",
            "- `trusted_recall@k`：排除已改写 gold support 后，对仍可信 gold support 的召回比例。",
            "- `空上下文率`：回填后上下文为空的 query 比例。",
            "- `recovery候选数`：从可信 clean corpus 二次检索回填的候选数量。",
            "",
            "## 实验结果",
            "",
            *table_lines,
            "",
            "## 当前解读",
            "",
            "- 如果改写文档暴露降为 0，说明 LogicGuard 仍能阻断 poisoned 版本证据进入上下文。",
            "- 如果 gold_recall 明显恢复，说明非 oracle 的可信语料二次检索可以替代 clean-trace 上界的一部分能力。",
            "- 如果 gold_recall 明显低于阶段6/7的 oracle recovery，说明后续需要更强的二次检索，例如混合检索、实体约束检索或 GraphRAG local search。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _load_reranked_traces(path: Path) -> list[RerankedTrace]:
    traces: list[RerankedTrace] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            traces.append(_reranked_trace_from_json(payload))
    return traces


def _reranked_trace_from_json(payload: dict[str, object]) -> RerankedTrace:
    candidates_payload = payload.get("candidates", [])
    if not isinstance(candidates_payload, list):
        raise ValueError("Reranked trace candidates must be a list")
    return RerankedTrace(
        query_id=str(payload["query_id"]),
        query=str(payload["query"]),
        answer=str(payload["answer"]),
        gold_doc_ids=[str(doc_id) for doc_id in payload.get("gold_doc_ids", [])],
        candidates=[
            RerankedCandidate(
                doc_id=str(candidate["doc_id"]),
                title=str(candidate.get("title", "")),
                original_rank=int(candidate.get("original_rank", index)),
                new_rank=int(candidate.get("new_rank", index)),
                base_score=float(candidate.get("base_score", 0.0)),
                risk_score=float(candidate.get("risk_score", 0.0)),
                adjusted_score=float(
                    candidate.get("adjusted_score", candidate.get("base_score", 0.0))
                ),
                path_length=int(candidate.get("path_length", 0)),
                direct_query_match=bool(candidate.get("direct_query_match", False)),
                source_support_count=int(candidate.get("source_support_count", 0)),
                global_support_count=(
                    int(candidate["global_support_count"])
                    if candidate.get("global_support_count") is not None
                    else None
                ),
                known_source_document=(
                    bool(candidate["known_source_document"])
                    if candidate.get("known_source_document") is not None
                    else None
                ),
                reference_content_changed=(
                    bool(candidate["reference_content_changed"])
                    if candidate.get("reference_content_changed") is not None
                    else None
                ),
                matched_query_entities=[
                    str(entity)
                    for entity in candidate.get("matched_query_entities", [])
                ],
                bridge_entities=[
                    str(entity) for entity in candidate.get("bridge_entities", [])
                ],
                risk_reasons=[
                    str(reason) for reason in candidate.get("risk_reasons", [])
                ],
            )
            for index, candidate in enumerate(candidates_payload, start=1)
            if isinstance(candidate, dict)
        ],
    )


def _write_reranked_traces(path: Path, traces: list[RerankedTrace]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace.to_json_dict(), ensure_ascii=False) + "\n")


def _with_new_rank(candidate: RerankedCandidate, new_rank: int) -> RerankedCandidate:
    return RerankedCandidate(
        doc_id=candidate.doc_id,
        title=candidate.title,
        original_rank=candidate.original_rank,
        new_rank=new_rank,
        base_score=candidate.base_score,
        risk_score=candidate.risk_score,
        adjusted_score=candidate.adjusted_score,
        path_length=candidate.path_length,
        direct_query_match=candidate.direct_query_match,
        source_support_count=candidate.source_support_count,
        global_support_count=candidate.global_support_count,
        known_source_document=candidate.known_source_document,
        reference_content_changed=candidate.reference_content_changed,
        matched_query_entities=candidate.matched_query_entities,
        bridge_entities=candidate.bridge_entities,
        risk_reasons=candidate.risk_reasons,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stage-8 non-oracle LogicPoison recovery."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_recovery_stage8.yaml"),
        help="Path to the stage-8 recovery YAML config.",
    )
    args = parser.parse_args()
    rows = run_from_config(NonOracleRecoveryConfig.from_yaml(args.config))
    for row in rows:
        print(
            f"{row.dataset}/{row.retriever}: "
            f"changed_doc@{row.top_k}={row.before_changed_doc_exposure_at_k:.4f}"
            f"->{row.after_changed_doc_exposure_at_k:.4f}, "
            f"gold_recall@{row.top_k}={row.before_gold_recall_at_k:.4f}"
            f"->{row.after_gold_recall_at_k:.4f}, "
            f"recovered={row.recovered_candidate_count}"
        )


if __name__ == "__main__":
    main()
