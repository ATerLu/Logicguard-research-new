import json
from pathlib import Path

from logicguard.ms_graphrag.local_defense_data import (
    LocalDefenseDataConfig,
    prepare_local_defense_data,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_prepare_local_defense_data_writes_four_condition_corpora(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    clean_corpus_path = tmp_path / "clean.jsonl"
    poisoned_corpus_path = tmp_path / "poisoned.jsonl"
    integrity_path = tmp_path / "query_integrity.jsonl"
    output_sample_path = tmp_path / "stage10" / "samples.jsonl"
    variant_corpus_root = tmp_path / "stage10" / "corpora"
    manifest_path = tmp_path / "stage10" / "manifest.json"

    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Who directed the film?",
                "answer": "Alice",
                "support_doc_ids": ["1", "2"],
                "support_docs": [
                    {"doc_id": "1", "title": "Changed", "text": "Alice directed the film."},
                    {"doc_id": "2", "title": "Trusted", "text": "The film exists."},
                ],
            },
            {
                "query_id": "q2",
                "query": "Who wrote the book?",
                "answer": "Carol",
                "support_doc_ids": ["3"],
                "support_docs": [{"doc_id": "3", "title": "Book", "text": "Carol wrote the book."}],
            },
        ],
    )
    _write_jsonl(
        clean_corpus_path,
        [
            {"_id": "1", "title": "Changed", "text": "Alice directed the film."},
            {"_id": "2", "title": "Trusted", "text": "The film exists."},
            {"_id": "3", "title": "Book", "text": "Carol wrote the book."},
        ],
    )
    _write_jsonl(
        poisoned_corpus_path,
        [
            {"_id": "1", "title": "Changed", "text": "Mallory directed the film."},
            {"_id": "2", "title": "Trusted", "text": "The film exists."},
            {"_id": "3", "title": "Book", "text": "Carol wrote the book."},
        ],
    )
    _write_jsonl(
        integrity_path,
        [
            {
                "query_id": "q1",
                "support_doc_ids": ["1", "2"],
                "changed_support_doc_ids": ["1"],
                "answer_surface_loss": True,
            },
            {
                "query_id": "q2",
                "support_doc_ids": ["3"],
                "changed_support_doc_ids": ["3"],
                "answer_surface_loss": True,
            },
        ],
    )

    manifest = prepare_local_defense_data(
        LocalDefenseDataConfig(
            dataset="toy",
            sample_path=sample_path,
            clean_corpus_path=clean_corpus_path,
            poisoned_corpus_path=poisoned_corpus_path,
            query_integrity_path=integrity_path,
            output_sample_path=output_sample_path,
            variant_corpus_root=variant_corpus_root,
            manifest_path=manifest_path,
            max_queries=1,
        )
    )

    assert manifest["selected_query_ids"] == ["q1"]
    assert manifest["changed_support_doc_ids"] == ["1"]
    assert manifest["trusted_support_doc_ids"] == ["2"]
    assert len(_read_jsonl(output_sample_path)) == 1
    assert {row["_id"] for row in _read_jsonl(variant_corpus_root / "clean" / "corpus.jsonl")} == {"1", "2"}
    assert {row["_id"] for row in _read_jsonl(variant_corpus_root / "poisoned" / "corpus.jsonl")} == {"1", "2"}
    assert {row["_id"] for row in _read_jsonl(variant_corpus_root / "guarded" / "corpus.jsonl")} == {"2"}
    assert {row["_id"] for row in _read_jsonl(variant_corpus_root / "recovered" / "corpus.jsonl")} == {"1", "2"}
