"""Readers for LogicPoison benchmark files.

The raw datasets use the common BEIR-style layout:

- `queries.jsonl`: question id and question text
- `answers.jsonl`: question id and gold answer
- `corpus.jsonl`: document id, title, and text
- `qrels/test.tsv`: query-to-support-document links

This module intentionally does not build graph objects. Its only job is to
turn files into typed records and fail early when ids do not line up.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from logicguard.data.schemas import (
    AnswerRecord,
    CorpusDocument,
    QueryRecord,
    RawDataset,
)


@dataclass(frozen=True, slots=True)
class DatasetPaths:
    """Filesystem locations for one dataset split."""

    name: str
    queries_path: Path
    answers_path: Path
    corpus_path: Path
    qrels_path: Path

    @classmethod
    def from_root(cls, raw_root: Path, name: str) -> "DatasetPaths":
        """Create paths for a dataset stored under the LogicPoison data root."""

        dataset_root = raw_root / name
        return cls(
            name=name,
            queries_path=dataset_root / "queries.jsonl",
            answers_path=dataset_root / "answers.jsonl",
            corpus_path=dataset_root / "corpus.jsonl",
            qrels_path=dataset_root / "qrels" / "test.tsv",
        )

    def required_files(self) -> Iterable[Path]:
        """Yield files that must exist before the dataset can be loaded."""

        yield self.queries_path
        yield self.answers_path
        yield self.corpus_path
        yield self.qrels_path


def load_raw_dataset(paths: DatasetPaths) -> RawDataset:
    """Load one benchmark dataset and validate its cross-file ids.

    The validation is deliberately strict for this first project phase. If a
    later dataset has partial labels, we can add an explicit relaxed mode rather
    than allowing silent data loss in the main experiments.
    """

    _ensure_required_files(paths)
    queries = _load_queries(paths.queries_path)
    answers = _load_answers(paths.answers_path)
    corpus = _load_corpus(paths.corpus_path)
    qrels = _load_qrels(paths.qrels_path)
    dataset = RawDataset(
        name=paths.name,
        queries=queries,
        answers=answers,
        corpus=corpus,
        qrels=qrels,
    )
    _validate_dataset(dataset)
    return dataset


def _ensure_required_files(paths: DatasetPaths) -> None:
    missing = [str(path) for path in paths.required_files() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(missing))


def _read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}"
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object in {path} at line {line_number}")
            yield payload


def _load_queries(path: Path) -> dict[str, QueryRecord]:
    records: dict[str, QueryRecord] = {}
    for item in _read_jsonl(path):
        query_id = str(item["_id"])
        records[query_id] = QueryRecord(query_id=query_id, text=str(item["text"]))
    return records


def _load_answers(path: Path) -> dict[str, AnswerRecord]:
    records: dict[str, AnswerRecord] = {}
    for item in _read_jsonl(path):
        query_id = str(item["id"])
        records[query_id] = AnswerRecord(query_id=query_id, answer=str(item["answer"]))
    return records


def _load_corpus(path: Path) -> dict[str, CorpusDocument]:
    records: dict[str, CorpusDocument] = {}
    for item in _read_jsonl(path):
        doc_id = str(item["_id"])
        records[doc_id] = CorpusDocument(
            doc_id=doc_id,
            title=str(item.get("title", "")),
            text=str(item["text"]),
        )
    return records


def _load_qrels(path: Path) -> dict[str, list[str]]:
    qrels: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        expected_fields = {"query-id", "corpus-id", "score"}
        if set(reader.fieldnames or []) != expected_fields:
            raise ValueError(f"Unexpected qrels header in {path}: {reader.fieldnames}")
        for row in reader:
            query_id = row["query-id"]
            doc_id = row["corpus-id"]
            qrels.setdefault(query_id, []).append(doc_id)
    return qrels


def _validate_dataset(dataset: RawDataset) -> None:
    query_ids = set(dataset.queries)
    answer_ids = set(dataset.answers)
    qrel_query_ids = set(dataset.qrels)
    corpus_ids = set(dataset.corpus)

    missing_answers = query_ids - answer_ids
    if missing_answers:
        raise ValueError(f"Missing answers for {len(missing_answers)} queries")

    missing_qrels = query_ids - qrel_query_ids
    if missing_qrels:
        raise ValueError(f"Missing qrels for {len(missing_qrels)} queries")

    unknown_docs = {
        doc_id
        for doc_ids in dataset.qrels.values()
        for doc_id in doc_ids
        if doc_id not in corpus_ids
    }
    if unknown_docs:
        raise ValueError(
            f"Qrels reference {len(unknown_docs)} unknown corpus documents"
        )
