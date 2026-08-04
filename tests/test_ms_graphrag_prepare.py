import json
from pathlib import Path

from logicguard.ms_graphrag.prepare_workspace import (
    MsGraphRagWorkspaceConfig,
    prepare_ms_graphrag_workspace,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_prepare_ms_graphrag_workspace_writes_support_docs_and_manifest(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "samples.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    workspace_root = tmp_path / "ms_graphrag" / "toy"

    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Who directed Atomised?",
                "answer": "Oskar Roehler",
                "support_doc_ids": ["d1"],
                "support_docs": [
                    {
                        "doc_id": "d1",
                        "title": "Atomised Film",
                        "text": "Atomised was directed by Oskar Roehler.",
                    }
                ],
            }
        ],
    )
    _write_jsonl(
        corpus_path,
        [
            {
                "_id": "d1",
                "title": "Atomised Film",
                "text": "Atomised was directed by Oskar Roehler.",
            },
            {
                "_id": "d2",
                "title": "Unused",
                "text": "This document is outside the support set.",
            },
        ],
    )

    summary = prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset="toy",
            sample_path=sample_path,
            corpus_path=corpus_path,
            workspace_root=workspace_root,
            doc_scope="sample_support",
            max_docs=None,
        )
    )

    assert summary["input_doc_count"] == 1
    assert (workspace_root / "input" / "d1.txt").exists()
    assert not (workspace_root / "input" / "d2.txt").exists()
    manifest = json.loads(
        (workspace_root / "logicguard_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["dataset"] == "toy"
    assert manifest["doc_scope"] == "sample_support"


def test_prepare_ms_graphrag_workspace_can_skip_missing_support_docs(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "samples.jsonl"
    corpus_path = tmp_path / "guarded_corpus.jsonl"
    workspace_root = tmp_path / "ms_graphrag" / "guarded"

    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Who directed Atomised?",
                "answer": "Oskar Roehler",
                "support_doc_ids": ["trusted", "suspicious"],
                "support_docs": [
                    {
                        "doc_id": "trusted",
                        "title": "Trusted Hop",
                        "text": "Atomised is a German film.",
                    },
                    {
                        "doc_id": "suspicious",
                        "title": "Suspicious Hop",
                        "text": "Atomised was directed by Oskar Roehler.",
                    },
                ],
            }
        ],
    )
    _write_jsonl(
        corpus_path,
        [
            {
                "_id": "trusted",
                "title": "Trusted Hop",
                "text": "Atomised is a German film.",
            },
        ],
    )

    summary = prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset="toy",
            sample_path=sample_path,
            corpus_path=corpus_path,
            workspace_root=workspace_root,
            doc_scope="sample_support",
            missing_support_policy="skip",
        )
    )

    assert summary["input_doc_count"] == 1
    assert summary["missing_support_policy"] == "skip"
    assert (workspace_root / "input" / "trusted.txt").exists()
    assert not (workspace_root / "input" / "suspicious.txt").exists()
