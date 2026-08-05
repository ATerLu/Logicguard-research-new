"""Dataset normalization and artifact writing for LogicGuard.

The first experimental milestone needs reproducible data artifacts, not a graph
yet. This module converts raw LogicPoison files into self-contained samples and
writes both machine-readable JSONL files and a human-readable validation report.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.schemas import CorpusDocument, NormalizedSample, RawDataset


@dataclass(frozen=True, slots=True)
class DataPreparationConfig:
    """Configuration needed to prepare one or more benchmark datasets."""

    raw_data_root: Path
    processed_data_root: Path
    report_root: Path
    datasets: list[str]
    debug_size: int = 50

    @classmethod
    def from_yaml(cls, path: Path) -> "DataPreparationConfig":
        """Load config from a small YAML file with paths relative to project root."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            raw_data_root=resolve_project_path(payload["raw_data_root"]),
            processed_data_root=resolve_project_path(payload["processed_data_root"]),
            report_root=resolve_project_path(payload["report_root"]),
            datasets=list(payload["datasets"]),
            debug_size=int(payload.get("debug_size", 50)),
        )


@dataclass(frozen=True, slots=True)
class DatasetValidationSummary:
    """Small summary used in console output and Markdown reports."""

    dataset: str
    queries: int
    answers: int
    corpus_docs: int
    qrel_queries: int
    missing_answers: int
    missing_qrels: int
    invalid_support_docs: int
    debug_subset: int
    support_docs_distribution: dict[int, int]

    @property
    def status(self) -> str:
        """Return PASS only when all required id relationships are valid."""

        if self.missing_answers or self.missing_qrels or self.invalid_support_docs:
            return "FAIL"
        return "PASS"


def build_samples(dataset: RawDataset) -> list[NormalizedSample]:
    """Join query, answer, qrels, and corpus into stable experiment samples."""

    samples: list[NormalizedSample] = []
    for query_id, query in dataset.queries.items():
        support_doc_ids = dataset.qrels[query_id]
        support_docs = [dataset.corpus[doc_id] for doc_id in support_doc_ids]
        samples.append(
            NormalizedSample(
                query_id=query_id,
                query=query.text,
                answer=dataset.answers[query_id].answer,
                support_doc_ids=support_doc_ids,
                support_docs=support_docs,
            )
        )
    return samples


def make_debug_subset(
    samples: list[NormalizedSample], size: int = 50
) -> list[NormalizedSample]:
    """Return the first `size` samples as a deterministic smoke-test subset.

    A deterministic subset is easier to compare across code changes than random
    sampling. Later experiments can add stratified subsets, but the first debug
    set should be boring and repeatable.
    """

    if size < 1:
        raise ValueError("debug subset size must be positive")
    return samples[: min(size, len(samples))]


def load_normalized_samples(path: Path) -> list[NormalizedSample]:
    """Read a generated `samples.jsonl` or `debug_*.jsonl` artifact.

    This keeps baseline runners independent from the raw benchmark layout. Once
    data is normalized, graph and attack modules should consume this stable
    project format instead of rejoining raw query/answer/qrels files.
    """

    samples: list[NormalizedSample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            support_docs = [
                CorpusDocument(
                    doc_id=str(doc["doc_id"]),
                    title=str(doc["title"]),
                    text=str(doc["text"]),
                )
                for doc in payload["support_docs"]
            ]
            samples.append(
                NormalizedSample(
                    query_id=str(payload["query_id"]),
                    query=str(payload["query"]),
                    answer=str(payload["answer"]),
                    support_doc_ids=[
                        str(doc_id) for doc_id in payload["support_doc_ids"]
                    ],
                    support_docs=support_docs,
                )
            )
            if not samples[-1].support_docs:
                raise ValueError(
                    f"Sample at line {line_number} has no support documents"
                )
    return samples


def prepare_dataset(
    dataset_name: str,
    raw_data_root: Path,
    processed_data_root: Path,
    report_root: Path,
    debug_size: int,
) -> DatasetValidationSummary:
    """Prepare one dataset and write JSONL artifacts plus a validation report."""

    raw_dataset = load_raw_dataset(DatasetPaths.from_root(raw_data_root, dataset_name))
    samples = build_samples(raw_dataset)
    debug_subset = make_debug_subset(samples, size=debug_size)

    dataset_output_root = processed_data_root / dataset_name
    dataset_output_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    _write_jsonl(dataset_output_root / "samples.jsonl", samples)
    _write_jsonl(dataset_output_root / f"debug_{len(debug_subset)}.jsonl", debug_subset)

    summary = build_validation_summary(raw_dataset, debug_subset_size=len(debug_subset))
    _write_report(report_root / f"data_validation_{dataset_name}.md", summary)
    return summary


def build_validation_summary(
    dataset: RawDataset,
    debug_subset_size: int,
) -> DatasetValidationSummary:
    """Calculate lightweight integrity statistics for one loaded dataset."""

    query_ids = set(dataset.queries)
    answer_ids = set(dataset.answers)
    qrel_query_ids = set(dataset.qrels)
    corpus_ids = set(dataset.corpus)
    support_counts = [len(dataset.qrels[query_id]) for query_id in dataset.queries]
    invalid_docs = {
        doc_id
        for doc_ids in dataset.qrels.values()
        for doc_id in doc_ids
        if doc_id not in corpus_ids
    }

    return DatasetValidationSummary(
        dataset=dataset.name,
        queries=len(dataset.queries),
        answers=len(dataset.answers),
        corpus_docs=len(dataset.corpus),
        qrel_queries=len(dataset.qrels),
        missing_answers=len(query_ids - answer_ids),
        missing_qrels=len(query_ids - qrel_query_ids),
        invalid_support_docs=len(invalid_docs),
        debug_subset=debug_subset_size,
        support_docs_distribution=dict(sorted(Counter(support_counts).items())),
    )


def _write_jsonl(path: Path, samples: list[NormalizedSample]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_json_dict(), ensure_ascii=False) + "\n")


def _write_report(path: Path, summary: DatasetValidationSummary) -> None:
    distribution = ", ".join(
        f"{support_count}: {query_count}"
        for support_count, query_count in summary.support_docs_distribution.items()
    )
    average_supports = _weighted_average(summary.support_docs_distribution)
    content = "\n".join(
        [
            f"# 数据集可用性验证报告：{summary.dataset}",
            "",
            "## 指标说明",
            "",
            "- `Query数`：当前实验 split 中的问题数量。",
            "- `答案数`：可用于自动评估的 gold answer 数量。",
            "- `语料文档数`：检索器可访问的 corpus 文档数量。",
            "- `qrels问题数`：拥有 gold support 标注的问题数量。",
            "- `缺失答案数`：有 query 但没有 answer 的异常样本数量。",
            "- `缺失qrels数`：有 query 但没有 support 标注的异常样本数量。",
            "- `无效support文档数`：qrels 引用但 corpus 中不存在的文档数量。",
            "- `debug子集`：用于快速冒烟测试的确定性样本数量。",
            "- `平均support文档数/Query`：每个问题平均依赖的 gold support 文档数量。",
            "",
            "## 验证结果",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| Query数 | {summary.queries} |",
            f"| 答案数 | {summary.answers} |",
            f"| 语料文档数 | {summary.corpus_docs} |",
            f"| qrels问题数 | {summary.qrel_queries} |",
            f"| 缺失答案数 | {summary.missing_answers} |",
            f"| 缺失qrels数 | {summary.missing_qrels} |",
            f"| 无效support文档数 | {summary.invalid_support_docs} |",
            f"| debug子集 | {summary.debug_subset} |",
            f"| 平均support文档数/Query | {average_supports:.2f} |",
            "",
            f"Support文档数量分布：`{distribution}`",
            "",
            f"验证状态：**{_localize_status(summary.status)}**",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _weighted_average(distribution: dict[int, int]) -> float:
    values = [
        support_count
        for support_count, query_count in distribution.items()
        for _ in range(query_count)
    ]
    return mean(values) if values else 0.0


def _localize_status(status: str) -> str:
    return "通过" if status == "PASS" else "失败"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare LogicGuard benchmark datasets."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/data.yaml"),
        help="Path to the data preparation YAML config.",
    )
    args = parser.parse_args()

    config = DataPreparationConfig.from_yaml(args.config)
    for dataset_name in config.datasets:
        summary = prepare_dataset(
            dataset_name=dataset_name,
            raw_data_root=config.raw_data_root,
            processed_data_root=config.processed_data_root,
            report_root=config.report_root,
            debug_size=config.debug_size,
        )
        print(
            f"{summary.dataset}: status={summary.status}, "
            f"queries={summary.queries}, debug_subset={summary.debug_subset}"
        )


if __name__ == "__main__":
    main()
