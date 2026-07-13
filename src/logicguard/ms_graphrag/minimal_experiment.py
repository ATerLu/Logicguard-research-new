"""Auditable experiments over Microsoft GraphRAG minimal index artifacts."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import CorpusDocument
from logicguard.experiments.run_logicpoison_retrieval import (
    LogicPoisonRetrievalMetrics,
    calculate_logicpoison_retrieval_metrics,
    load_retrieval_traces,
)
from logicguard.naive_rag.baseline import NaiveRagOutputPaths, run_naive_rag_baseline

_DOC_ID_PATTERN = re.compile(r"^Document ID:\s*(?P<doc_id>.+?)\s*$", re.MULTILINE)
_TITLE_PATTERN = re.compile(r"^Title:\s*(?P<title>.*?)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class MsGraphRagMinimalExperimentConfig:
    """Configuration for a clean/poisoned minimal-index comparison."""

    dataset: str
    sample_path: Path
    clean_output_dir: Path
    poisoned_output_dir: Path
    changed_docs_path: Path
    query_integrity_path: Path
    output_root: Path
    report_path: Path
    top_k: int = 10

    @classmethod
    def from_yaml(cls, path: Path) -> "MsGraphRagMinimalExperimentConfig":
        """Load YAML configuration with project-relative paths."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(payload["sample_path"]),
            clean_output_dir=resolve_project_path(payload["clean_output_dir"]),
            poisoned_output_dir=resolve_project_path(payload["poisoned_output_dir"]),
            changed_docs_path=resolve_project_path(payload["changed_docs_path"]),
            query_integrity_path=resolve_project_path(payload["query_integrity_path"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            top_k=int(payload.get("top_k", 10)),
        )


def run_from_config(config: MsGraphRagMinimalExperimentConfig) -> list[LogicPoisonRetrievalMetrics]:
    """Run BM25 traces over documents emitted by GraphRAG minimal indexing."""

    samples = load_normalized_samples(config.sample_path)
    clean_documents = load_ms_graphrag_indexed_documents(config.clean_output_dir)
    poisoned_documents = load_ms_graphrag_indexed_documents(config.poisoned_output_dir)
    changed_doc_ids = _load_changed_doc_ids(config.changed_docs_path)
    changed_gold_by_query = _load_changed_gold_doc_ids_by_query(config.query_integrity_path)

    rows: list[LogicPoisonRetrievalMetrics] = []
    for corpus_state, documents in (("clean", clean_documents), ("poisoned", poisoned_documents)):
        trace_path = config.output_root / config.dataset / f"ms_graphrag_minimal_{corpus_state}_traces.jsonl"
        report_path = config.output_root / config.dataset / "reports" / f"ms_graphrag_minimal_{corpus_state}.md"
        run_naive_rag_baseline(
            dataset_name=config.dataset,
            samples=samples,
            corpus_documents=documents,
            outputs=NaiveRagOutputPaths(trace_path=trace_path, report_path=report_path),
            mode="bm25",
            top_k=config.top_k,
        )
        traces = load_retrieval_traces(trace_path)
        metric = calculate_logicpoison_retrieval_metrics(
            dataset=config.dataset,
            retriever="ms_graphrag_minimal_indexed_bm25",
            corpus_state=corpus_state,
            traces=traces,
            changed_doc_ids=changed_doc_ids,
            changed_gold_doc_ids_by_query=changed_gold_by_query,
            top_k=config.top_k,
        )
        rows.append(_with_corpus_doc_count(metric, len(documents)))

    _write_metrics_jsonl(config.output_root / config.dataset / "ms_graphrag_minimal_metrics.jsonl", rows)
    _write_metrics_jsonl(config.output_root / "ms_graphrag_minimal_metrics.jsonl", rows)
    write_minimal_experiment_report(config.report_path, rows, clean_documents, poisoned_documents)
    return rows


def load_ms_graphrag_indexed_documents(output_dir: Path) -> list[CorpusDocument]:
    """Load `documents.parquet` and restore LogicGuard source document ids."""

    documents_path = output_dir / "documents.parquet"
    if not documents_path.exists():
        raise FileNotFoundError(f"Missing Microsoft GraphRAG documents parquet: {documents_path}")
    frame = pd.read_parquet(documents_path)
    documents: list[CorpusDocument] = []
    for row in frame.to_dict(orient="records"):
        text = str(row["text"])
        doc_id = parse_logicguard_doc_id(text)
        title = _parse_title(text) or str(row.get("title", "")).removesuffix(".txt")
        body = _parse_body(text)
        documents.append(CorpusDocument(doc_id=doc_id, title=title, text=body))
    return documents


def parse_logicguard_doc_id(text: str) -> str:
    """Parse the original LogicGuard doc_id from GraphRAG plain-text input."""

    match = _DOC_ID_PATTERN.search(text)
    if not match:
        raise ValueError("GraphRAG document text does not contain `Document ID:`")
    return match.group("doc_id").strip()


def write_minimal_experiment_report(
    path: Path,
    rows: list[LogicPoisonRetrievalMetrics],
    clean_documents: list[CorpusDocument],
    poisoned_documents: list[CorpusDocument],
) -> None:
    """Write a Chinese report for the Microsoft GraphRAG minimal experiment."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| 语料状态 | Query数 | 已索引文档数 | hit@k | gold_recall@k | changed_doc@k | changed_gold@k | trusted_recall@k |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.corpus_state,
                    str(row.query_count),
                    str(row.corpus_doc_count),
                    f"{row.hit_at_k:.4f}",
                    f"{row.gold_recall_at_k:.4f}",
                    f"{row.changed_doc_retrieval_at_k:.4f}",
                    f"{row.changed_gold_exposure_at_k:.4f}",
                    f"{row.trusted_gold_recall_at_k:.4f}",
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Microsoft GraphRAG minimal 小规模对照实验报告",
            "",
            "## 实验目的",
            "",
            "本实验使用 Microsoft GraphRAG 官方 minimal indexing workflow 生成 clean 与 poisoned 两个索引工作区，然后读取其 `documents.parquet` 产物并恢复 LogicGuard 原始 doc_id，在已索引文档集合上生成可审计检索 trace。",
            "",
            "## 重要边界",
            "",
            "- 该实验证明官方 GraphRAG minimal indexing 管线可以处理 LogicGuard 数据，并能产出 documents、text_units、entities、relationships、communities 与 LanceDB embedding。",
            "- 下表中的检索 trace 是在 GraphRAG 已索引文档集合上运行的 BM25 可审计检索，不等同于 Microsoft GraphRAG 的 official local/global query。",
            "- official query 可用于回答 smoke test，但当前 CLI 不直接导出 LogicGuard 所需的 top-k 证据 trace。",
            "",
            "## 指标说明",
            "",
            "- `hit@k`：top-k 是否命中至少一个 gold support。",
            "- `gold_recall@k`：top-k 覆盖 gold support 的比例。",
            "- `changed_doc@k`：top-k 中是否出现被 LogicPoison 改写过的 doc_id。",
            "- `changed_gold@k`：top-k 中是否出现被改写过的 gold support。",
            "- `trusted_recall@k`：排除改写 gold support 后，对仍可信 gold support 的召回比例。",
            "",
            "## 索引规模",
            "",
            f"- clean 已索引文档数：`{len(clean_documents)}`",
            f"- poisoned 已索引文档数：`{len(poisoned_documents)}`",
            "",
            "## 检索对照结果",
            "",
            *table_lines,
            "",
            "## 当前解读",
            "",
            "- 如果 poisoned 的 `changed_doc@k` 或 `changed_gold@k` 很高，说明即使经过 GraphRAG minimal indexing，官方污染文档仍会出现在可检索证据集合中。",
            "- 由于本实验的输入范围是 debug_50 的 support 文档集合，指标不能外推到 full_500 或完整语料索引。",
            "- 后续若要声称 official Microsoft GraphRAG query 级防御，需要进一步接入 local/basic query 的证据来源或实现 query context tracing。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _parse_title(text: str) -> str:
    match = _TITLE_PATTERN.search(text)
    return match.group("title").strip() if match else ""


def _parse_body(text: str) -> str:
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else text.strip()


def _load_changed_doc_ids(path: Path) -> set[str]:
    return {
        str(row["doc_id"])
        for row in _load_jsonl(path)
        if bool(row.get("changed", True))
    }


def _load_changed_gold_doc_ids_by_query(path: Path) -> dict[str, set[str]]:
    return {
        str(row["query_id"]): {str(doc_id) for doc_id in row.get("changed_support_doc_ids", [])}
        for row in _load_jsonl(path)
    }


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _write_metrics_jsonl(path: Path, rows: list[LogicPoisonRetrievalMetrics]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")


def _with_corpus_doc_count(
    metric: LogicPoisonRetrievalMetrics,
    corpus_doc_count: int,
) -> LogicPoisonRetrievalMetrics:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Microsoft GraphRAG minimal indexed-corpus experiment.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_minimal_stage9.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(MsGraphRagMinimalExperimentConfig.from_yaml(args.config))
    for row in rows:
        print(
            f"{row.dataset}/{row.corpus_state}: "
            f"hit@{row.top_k}={row.hit_at_k:.4f}, "
            f"recall@{row.top_k}={row.gold_recall_at_k:.4f}, "
            f"changed_doc@{row.top_k}={row.changed_doc_retrieval_at_k:.4f}"
        )


if __name__ == "__main__":
    main()
