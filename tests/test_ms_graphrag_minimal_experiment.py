import json
from pathlib import Path

import pandas as pd

from logicguard.ms_graphrag.minimal_experiment import (
    MsGraphRagMinimalExperimentConfig,
    load_ms_graphrag_indexed_documents,
    parse_logicguard_doc_id,
    run_from_config,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_parse_logicguard_doc_id_from_graphrag_text() -> None:
    text = "Document ID: doc-17\nTitle: Demo\n\nBody text"

    assert parse_logicguard_doc_id(text) == "doc-17"


def test_load_ms_graphrag_indexed_documents_restores_original_doc_ids(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "workspace" / "output"
    output_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "id": "hashed-id",
                "title": "doc-17.txt",
                "text": "Document ID: doc-17\nTitle: Demo\n\nBody text",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet")

    documents = load_ms_graphrag_indexed_documents(output_dir)

    assert documents[0].doc_id == "doc-17"
    assert documents[0].title == "Demo"
    assert documents[0].text == "Body text"


def test_run_minimal_experiment_writes_trace_metrics_and_report(tmp_path: Path) -> None:
    clean_output = tmp_path / "clean" / "output"
    poisoned_output = tmp_path / "poisoned" / "output"
    clean_output.mkdir(parents=True)
    poisoned_output.mkdir(parents=True)
    for output_dir, body in [
        (clean_output, "Gold answer lives here."),
        (poisoned_output, "Wrong answer lives here."),
    ]:
        pd.DataFrame(
            [
                {
                    "id": "hash-g1",
                    "title": "g1.txt",
                    "text": f"Document ID: g1\nTitle: Gold Doc\n\n{body}",
                }
            ]
        ).to_parquet(output_dir / "documents.parquet")

    sample_path = tmp_path / "samples.jsonl"
    changed_docs_path = tmp_path / "changed_docs.jsonl"
    query_integrity_path = tmp_path / "query_integrity.jsonl"
    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Where does the gold answer live?",
                "answer": "Gold answer",
                "support_doc_ids": ["g1"],
                "support_docs": [
                    {
                        "doc_id": "g1",
                        "title": "Gold Doc",
                        "text": "Gold answer lives here.",
                    }
                ],
            }
        ],
    )
    _write_jsonl(changed_docs_path, [{"doc_id": "g1", "changed": True}])
    _write_jsonl(
        query_integrity_path,
        [{"query_id": "q1", "changed_support_doc_ids": ["g1"]}],
    )

    config = MsGraphRagMinimalExperimentConfig(
        dataset="toy",
        sample_path=sample_path,
        clean_output_dir=clean_output,
        poisoned_output_dir=poisoned_output,
        changed_docs_path=changed_docs_path,
        query_integrity_path=query_integrity_path,
        output_root=tmp_path / "retrieval",
        report_path=tmp_path / "report.md",
        top_k=1,
    )

    rows = run_from_config(config)

    assert len(rows) == 2
    assert rows[1].corpus_state == "poisoned"
    assert rows[1].changed_doc_retrieval_at_k == 1.0
    assert (
        config.output_root / "toy" / "ms_graphrag_minimal_poisoned_traces.jsonl"
    ).exists()
    assert "Microsoft GraphRAG minimal" in config.report_path.read_text(
        encoding="utf-8"
    )
