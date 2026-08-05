"""Adapters and integrity metadata for official LogicPoison corpora.

The official LogicPoison pipeline mutates corpus text in place: document ids,
queries, answers, and qrels are copied from the clean benchmark, while entity
mentions inside `corpus.jsonl` are replaced. This module keeps that threat model
explicit by always loading clean and poisoned datasets as a pair and by writing
document-level and query-level integrity metadata before any retrieval run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.schemas import CorpusDocument, RawDataset


@dataclass(frozen=True, slots=True)
class LogicPoisonOfficialConfig:
    """Configuration for the official LogicPoison corpus validation stage."""

    clean_data_root: Path
    poisoned_data_root: Path
    output_root: Path
    report_path: Path
    datasets: list[str]

    @classmethod
    def from_yaml(cls, path: Path) -> "LogicPoisonOfficialConfig":
        """Load a YAML config and resolve relative paths from the project root."""

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
            clean_data_root=resolve_project_path(payload["clean_data_root"]),
            poisoned_data_root=resolve_project_path(payload["poisoned_data_root"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            datasets=list(payload["datasets"]),
        )


@dataclass(frozen=True, slots=True)
class LogicPoisonDatasetPair:
    """Clean and poisoned versions of one benchmark dataset."""

    dataset: str
    clean: RawDataset
    poisoned: RawDataset


@dataclass(frozen=True, slots=True)
class CorpusDiffRecord:
    """Document-level integrity comparison between clean and poisoned corpora."""

    doc_id: str
    clean_title: str
    poisoned_title: str
    clean_hash: str
    poisoned_hash: str
    changed: bool
    title_changed: bool
    text_changed: bool
    clean_text_length: int
    poisoned_text_length: int

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON representation for downstream experiment code."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class QueryIntegrityRecord:
    """Query-level view of whether gold support evidence was changed."""

    query_id: str
    query: str
    answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    changed_support_rate: float
    answer_in_clean_support: bool
    answer_in_poisoned_support: bool
    answer_surface_loss: bool

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON representation for downstream experiment code."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class LogicPoisonValidationSummary:
    """Compact metrics for the stage-0 LogicPoison corpus validation report."""

    dataset: str
    queries: int
    answers: int
    clean_docs: int
    poisoned_docs: int
    qrel_queries: int
    changed_doc_count: int
    changed_doc_rate: float
    changed_gold_doc_occurrences: int
    unique_changed_gold_doc_count: int
    queries_with_changed_gold_support: int
    changed_gold_query_rate: float
    average_changed_support_rate: float
    answer_surface_loss_count: int
    answer_surface_loss_rate: float


def load_logicpoison_pair(
    config: LogicPoisonOfficialConfig,
    dataset_name: str,
) -> LogicPoisonDatasetPair:
    """Load and validate clean/poisoned datasets for one benchmark.

    The pair validation is intentionally strict. LogicPoison should not change
    ids, labels, or qrels; if any of those drift, later defense metrics would be
    ambiguous and should fail early instead of silently continuing.
    """

    clean = load_raw_dataset(
        DatasetPaths.from_root(config.clean_data_root, dataset_name)
    )
    poisoned = load_raw_dataset(
        DatasetPaths.from_root(config.poisoned_data_root, dataset_name)
    )
    _validate_pair_alignment(dataset_name, clean, poisoned)
    return LogicPoisonDatasetPair(dataset=dataset_name, clean=clean, poisoned=poisoned)


def build_corpus_diff_records(pair: LogicPoisonDatasetPair) -> list[CorpusDiffRecord]:
    """Return document-level clean-vs-poisoned fingerprint records."""

    records: list[CorpusDiffRecord] = []
    for doc_id, clean_doc in pair.clean.corpus.items():
        poisoned_doc = pair.poisoned.corpus[doc_id]
        clean_hash = document_fingerprint(clean_doc)
        poisoned_hash = document_fingerprint(poisoned_doc)
        title_changed = _normalize_text(clean_doc.title) != _normalize_text(
            poisoned_doc.title
        )
        text_changed = _normalize_text(clean_doc.text) != _normalize_text(
            poisoned_doc.text
        )
        records.append(
            CorpusDiffRecord(
                doc_id=doc_id,
                clean_title=clean_doc.title,
                poisoned_title=poisoned_doc.title,
                clean_hash=clean_hash,
                poisoned_hash=poisoned_hash,
                changed=clean_hash != poisoned_hash,
                title_changed=title_changed,
                text_changed=text_changed,
                clean_text_length=len(clean_doc.text),
                poisoned_text_length=len(poisoned_doc.text),
            )
        )
    return records


def build_query_integrity_records(
    pair: LogicPoisonDatasetPair,
    changed_doc_ids: set[str],
) -> list[QueryIntegrityRecord]:
    """Return query-level metadata about changed gold support documents."""

    records: list[QueryIntegrityRecord] = []
    for query_id, query in pair.clean.queries.items():
        support_doc_ids = list(pair.clean.qrels[query_id])
        changed_support_doc_ids = [
            doc_id for doc_id in support_doc_ids if doc_id in changed_doc_ids
        ]
        clean_support_docs = [pair.clean.corpus[doc_id] for doc_id in support_doc_ids]
        poisoned_support_docs = [
            pair.poisoned.corpus[doc_id] for doc_id in support_doc_ids
        ]
        answer = pair.clean.answers[query_id].answer
        answer_in_clean_support = answer_appears_in_docs(answer, clean_support_docs)
        answer_in_poisoned_support = answer_appears_in_docs(
            answer, poisoned_support_docs
        )
        records.append(
            QueryIntegrityRecord(
                query_id=query_id,
                query=query.text,
                answer=answer,
                support_doc_ids=support_doc_ids,
                changed_support_doc_ids=changed_support_doc_ids,
                changed_support_rate=(
                    len(changed_support_doc_ids) / len(support_doc_ids)
                    if support_doc_ids
                    else 0.0
                ),
                answer_in_clean_support=answer_in_clean_support,
                answer_in_poisoned_support=answer_in_poisoned_support,
                answer_surface_loss=answer_in_clean_support
                and not answer_in_poisoned_support,
            )
        )
    return records


def summarize_logicpoison_pair(
    pair: LogicPoisonDatasetPair,
    diff_records: list[CorpusDiffRecord],
    integrity_records: list[QueryIntegrityRecord],
) -> LogicPoisonValidationSummary:
    """Summarize corpus and gold-support changes for one dataset."""

    changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
    changed_gold_occurrences = sum(
        len(record.changed_support_doc_ids) for record in integrity_records
    )
    unique_changed_gold_doc_ids = {
        doc_id
        for record in integrity_records
        for doc_id in record.changed_support_doc_ids
    }
    queries_with_changed_gold = sum(
        1 for record in integrity_records if record.changed_support_doc_ids
    )
    answer_surface_loss_count = sum(
        1 for record in integrity_records if record.answer_surface_loss
    )
    return LogicPoisonValidationSummary(
        dataset=pair.dataset,
        queries=len(pair.clean.queries),
        answers=len(pair.clean.answers),
        clean_docs=len(pair.clean.corpus),
        poisoned_docs=len(pair.poisoned.corpus),
        qrel_queries=len(pair.clean.qrels),
        changed_doc_count=len(changed_doc_ids),
        changed_doc_rate=len(changed_doc_ids) / len(pair.clean.corpus)
        if pair.clean.corpus
        else 0.0,
        changed_gold_doc_occurrences=changed_gold_occurrences,
        unique_changed_gold_doc_count=len(unique_changed_gold_doc_ids),
        queries_with_changed_gold_support=queries_with_changed_gold,
        changed_gold_query_rate=queries_with_changed_gold / len(integrity_records)
        if integrity_records
        else 0.0,
        average_changed_support_rate=mean(
            record.changed_support_rate for record in integrity_records
        )
        if integrity_records
        else 0.0,
        answer_surface_loss_count=answer_surface_loss_count,
        answer_surface_loss_rate=answer_surface_loss_count / len(integrity_records)
        if integrity_records
        else 0.0,
    )


def run_from_config(
    config: LogicPoisonOfficialConfig,
) -> list[LogicPoisonValidationSummary]:
    """Generate stage-0 LogicPoison validation artifacts for all configured datasets."""

    summaries: list[LogicPoisonValidationSummary] = []
    for dataset_name in config.datasets:
        pair = load_logicpoison_pair(config, dataset_name)
        diff_records = build_corpus_diff_records(pair)
        changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
        integrity_records = build_query_integrity_records(pair, changed_doc_ids)
        summaries.append(
            summarize_logicpoison_pair(pair, diff_records, integrity_records)
        )

        dataset_output = config.output_root / dataset_name
        _write_jsonl(
            dataset_output / "changed_docs.jsonl",
            [record.to_json_dict() for record in diff_records],
        )
        _write_jsonl(
            dataset_output / "query_integrity.jsonl",
            [record.to_json_dict() for record in integrity_records],
        )

    write_validation_report(config.report_path, summaries)
    return summaries


def write_validation_report(
    path: Path,
    summaries: list[LogicPoisonValidationSummary],
) -> None:
    """Write a Chinese Markdown report for the official corpus validation stage."""

    path.parent.mkdir(parents=True, exist_ok=True)
    metric_rows = [
        "| 数据集 | Query数 | Clean文档数 | Poisoned文档数 | 改写文档数 | 改写文档比例 | 含改写gold support的Query数 | Gold support改写出现次数 | 答案表面消失Query数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        metric_rows.append(
            "| "
            + " | ".join(
                [
                    summary.dataset,
                    str(summary.queries),
                    str(summary.clean_docs),
                    str(summary.poisoned_docs),
                    str(summary.changed_doc_count),
                    f"{summary.changed_doc_rate:.4f}",
                    str(summary.queries_with_changed_gold_support),
                    str(summary.changed_gold_doc_occurrences),
                    str(summary.answer_surface_loss_count),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicPoison 官方污染语料可用性验证报告",
            "",
            "## 实验目的",
            "",
            "本报告验证 LogicPoison 官方 pipeline 生成的 poisoned corpus 是否可以作为 LogicGuard 后续检索与防御实验输入。"
            "本阶段只读取 clean/poisoned 数据并生成完整性元数据，不修改 LogicPoison 原项目目录。",
            "",
            "## 指标说明",
            "",
            "- `改写文档数`：clean 与 poisoned corpus 中内容 fingerprint 不一致的文档数量。",
            "- `改写文档比例`：改写文档数除以 clean corpus 文档总数。",
            "- `含改写gold support的Query数`：至少一个 gold support 文档被 LogicPoison 改写的 query 数量。",
            "- `Gold support改写出现次数`：按 query-support 关系计数的改写 gold support 出现次数，允许同一文档在多个 query 中重复计数。",
            "- `答案表面消失Query数`：答案字符串在 clean gold support 中出现，但在 poisoned gold support 中不再出现的 query 数量。",
            "",
            "## 验证结果",
            "",
            *metric_rows,
            "",
            "## 当前结论",
            "",
            "- clean 与 poisoned 数据的 query、answer、qrels 和 corpus id 应保持对齐；若后续运行失败，说明数据结构不再满足 LogicPoison 原位替换假设。",
            "- 对 LogicPoison 这种原位实体替换攻击，后续防御实验应重点使用 `changed_docs.jsonl` 和 `query_integrity.jsonl` 判断内容完整性与 gold support 完整性。",
            "- 如果 gold support 本身被改写，单纯过滤污染证据可能导致 `UNKNOWN` 增多，因此后续必须继续评估 answer recovery。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def document_fingerprint(document: CorpusDocument) -> str:
    """Hash a document after whitespace normalization.

    The same normalization is used for clean and poisoned corpora so harmless
    formatting differences do not become false-positive content mismatches.
    """

    normalized = "\n".join(
        [_normalize_text(document.title), _normalize_text(document.text)]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def answer_appears_in_docs(answer: str, docs: list[CorpusDocument]) -> bool:
    """Return whether an answer string appears in the joined support text."""

    normalized_answer = _normalize_text(answer).casefold()
    if not normalized_answer:
        return False
    joined_text = " ".join(_normalize_text(doc.text).casefold() for doc in docs)
    return normalized_answer in joined_text


def _validate_pair_alignment(
    dataset_name: str,
    clean: RawDataset,
    poisoned: RawDataset,
) -> None:
    if set(clean.queries) != set(poisoned.queries):
        raise ValueError(f"{dataset_name}: clean/poisoned query ids differ")
    if set(clean.answers) != set(poisoned.answers):
        raise ValueError(f"{dataset_name}: clean/poisoned answer ids differ")
    if set(clean.qrels) != set(poisoned.qrels):
        raise ValueError(f"{dataset_name}: clean/poisoned qrel query ids differ")
    if set(clean.corpus) != set(poisoned.corpus):
        raise ValueError(f"{dataset_name}: clean/poisoned corpus ids differ")
    for query_id, clean_doc_ids in clean.qrels.items():
        if clean_doc_ids != poisoned.qrels[query_id]:
            raise ValueError(f"{dataset_name}: qrels differ for query {query_id}")
    for query_id, clean_answer in clean.answers.items():
        if clean_answer.answer != poisoned.answers[query_id].answer:
            raise ValueError(f"{dataset_name}: answers differ for query {query_id}")
    for query_id, clean_query in clean.queries.items():
        if clean_query.text != poisoned.queries[query_id].text:
            raise ValueError(f"{dataset_name}: queries differ for query {query_id}")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate official LogicPoison clean/poisoned corpus pairs."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_official.yaml"),
        help="Path to the LogicPoison official validation config.",
    )
    args = parser.parse_args()
    config = LogicPoisonOfficialConfig.from_yaml(args.config)
    summaries = run_from_config(config)
    for summary in summaries:
        print(
            f"{summary.dataset}: changed_docs={summary.changed_doc_count}, "
            f"changed_gold_queries={summary.queries_with_changed_gold_support}, "
            f"answer_surface_loss={summary.answer_surface_loss_count}"
        )


if __name__ == "__main__":
    main()
