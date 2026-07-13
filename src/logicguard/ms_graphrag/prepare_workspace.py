"""Prepare Microsoft GraphRAG workspaces from LogicGuard datasets.

Microsoft GraphRAG owns indexing and querying inside its own CLI/runtime. This
module prepares the filesystem boundary between our experiments and that CLI:
it exports selected corpus documents into `input/*.txt` and writes a manifest
that records exactly which LogicGuard data split produced the workspace.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import CorpusDocument, NormalizedSample

DocScope = Literal["all", "sample_support"]
MissingSupportPolicy = Literal["use_embedded", "skip"]
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class MsGraphRagWorkspaceConfig:
    """Configuration for exporting one Microsoft GraphRAG workspace."""

    dataset: str
    sample_path: Path
    corpus_path: Path
    workspace_root: Path
    doc_scope: DocScope = "sample_support"
    max_docs: int | None = None
    missing_support_policy: MissingSupportPolicy = "use_embedded"


def prepare_ms_graphrag_workspace(config: MsGraphRagWorkspaceConfig) -> dict[str, object]:
    """Export selected documents to a Microsoft GraphRAG workspace.

    `sample_support` is the safe default for smoke tests because it writes only
    gold support documents referenced by the chosen sample file. `all` writes
    the full corpus and is appropriate only when we are ready to pay the
    indexing cost.

    By default, a missing support document falls back to the embedded clean
    support text stored in the sample artifact. Defense experiments can set
    `missing_support_policy="skip"` so a guarded corpus that deliberately omits
    suspicious documents does not silently reintroduce those documents.
    """

    if config.max_docs is not None and config.max_docs < 1:
        raise ValueError("max_docs must be positive when provided")
    if config.doc_scope not in {"all", "sample_support"}:
        raise ValueError(f"Unsupported doc_scope: {config.doc_scope}")
    if config.missing_support_policy not in {"use_embedded", "skip"}:
        raise ValueError(f"Unsupported missing_support_policy: {config.missing_support_policy}")

    samples = load_normalized_samples(config.sample_path)
    corpus_lookup = _load_corpus_lookup(config.corpus_path)
    selected_documents = _select_documents(
        samples=samples,
        corpus_lookup=corpus_lookup,
        doc_scope=config.doc_scope,
        max_docs=config.max_docs,
        missing_support_policy=config.missing_support_policy,
    )

    input_dir = config.workspace_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    _clear_previous_text_inputs(input_dir)
    for document in selected_documents:
        (input_dir / f"{_safe_filename(document.doc_id)}.txt").write_text(
            _format_document_for_graphrag(document),
            encoding="utf-8",
        )

    manifest = {
        "dataset": config.dataset,
        "sample_path": str(config.sample_path.resolve()),
        "corpus_path": str(config.corpus_path.resolve()),
        "workspace_root": str(config.workspace_root.resolve()),
        "doc_scope": config.doc_scope,
        "missing_support_policy": config.missing_support_policy,
        "query_count": len(samples),
        "input_doc_count": len(selected_documents),
        "max_docs": config.max_docs,
        "input_format": "text",
        "notes": [
            "Run `graphrag init --root <workspace>` before indexing if settings/prompts are missing.",
            "Run `graphrag index --root <workspace> --method fast` for a lower-cost initial index.",
        ],
    }
    config.workspace_root.mkdir(parents=True, exist_ok=True)
    (config.workspace_root / "logicguard_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _select_documents(
    samples: list[NormalizedSample],
    corpus_lookup: dict[str, CorpusDocument],
    doc_scope: DocScope,
    max_docs: int | None,
    missing_support_policy: MissingSupportPolicy,
) -> list[CorpusDocument]:
    """Select corpus documents while preserving deterministic corpus order."""

    if doc_scope == "all":
        selected = list(corpus_lookup.values())
    else:
        support_ids = {doc_id for sample in samples for doc_id in sample.support_doc_ids}
        embedded_supports = {
            document.doc_id: document
            for sample in samples
            for document in sample.support_docs
        }
        selected = []
        for doc_id in sorted(support_ids, key=_stable_doc_sort_key):
            if doc_id in corpus_lookup:
                selected.append(corpus_lookup[doc_id])
            elif missing_support_policy == "use_embedded" and doc_id in embedded_supports:
                selected.append(embedded_supports[doc_id])

    if max_docs is not None:
        selected = selected[:max_docs]
    if not selected:
        raise ValueError("No documents selected for Microsoft GraphRAG workspace")
    return selected


def _load_corpus_lookup(path: Path) -> dict[str, CorpusDocument]:
    """Load raw or poisoned corpus JSONL into a doc-id lookup."""

    documents: dict[str, CorpusDocument] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_id = payload.get("_id", payload.get("doc_id"))
            if doc_id is None:
                raise ValueError(f"Missing document id in {path} at line {line_number}")
            doc = CorpusDocument(
                doc_id=str(doc_id),
                title=str(payload.get("title", "")),
                text=str(payload["text"]),
            )
            documents[doc.doc_id] = doc
    if not documents:
        raise ValueError(f"Corpus file is empty: {path}")
    return documents


def _format_document_for_graphrag(document: CorpusDocument) -> str:
    """Format one document as plain text while retaining source metadata."""

    return "\n".join(
        [
            f"Document ID: {document.doc_id}",
            f"Title: {document.title}",
            "",
            document.text,
            "",
        ]
    )


def _clear_previous_text_inputs(input_dir: Path) -> None:
    """Remove stale text inputs from a previously prepared workspace."""

    for path in input_dir.glob("*.txt"):
        path.unlink()


def _safe_filename(doc_id: str) -> str:
    safe = _SAFE_NAME_PATTERN.sub("_", doc_id).strip("._")
    return safe or "document"


def _stable_doc_sort_key(doc_id: str) -> tuple[int, str]:
    return (int(doc_id), doc_id) if doc_id.isdigit() else (10**12, doc_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Microsoft GraphRAG input files.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--sample-path", type=Path, required=True)
    parser.add_argument("--corpus-path", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--doc-scope", choices=["all", "sample_support"], default="sample_support")
    parser.add_argument("--max-docs", type=int, default=None)
    parser.add_argument(
        "--missing-support-policy",
        choices=["use_embedded", "skip"],
        default="use_embedded",
        help="Whether sample_support may fall back to embedded sample support docs.",
    )
    args = parser.parse_args()

    summary = prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset=args.dataset,
            sample_path=args.sample_path,
            corpus_path=args.corpus_path,
            workspace_root=args.workspace_root,
            doc_scope=args.doc_scope,
            max_docs=args.max_docs,
            missing_support_policy=args.missing_support_policy,
        )
    )
    print(
        f"{summary['dataset']}: queries={summary['query_count']}, "
        f"input_docs={summary['input_doc_count']}, scope={summary['doc_scope']}"
    )


if __name__ == "__main__":
    main()
