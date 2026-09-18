"""Strict adapters from backend-native retrieval evidence to comparison hits."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


TOKEN_COUNTER_ID = "unicode_lexical_v1"
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)
_MS_HEADER = re.compile(
    r"^Document ID:\s*(?P<id>[^\r\n]+)\r?\nTitle:\s*(?P<title>[^\r\n]*)\r?\n\r?\n(?P<body>.*)$",
    flags=re.DOTALL,
)


def comparison_token_count(text: str) -> int:
    """Return the deterministic comparison-layer lexical token count."""

    return len(_TOKEN_PATTERN.findall(text))


def normalize_ms_graphrag_context(
    row: Mapping[str, Any],
    *,
    dataset: str,
    clean_documents: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize one saved Microsoft GraphRAG local-context row."""

    query_id = _required_string(row.get("query_id"), "query_id")
    question = _required_string(row.get("query"), "query")
    context_data = row.get("context_data")
    if not isinstance(context_data, Mapping) or not isinstance(
        context_data.get("sources"), list
    ):
        raise ValueError("Microsoft GraphRAG trace requires context_data.sources")
    hits: list[dict[str, Any]] = []
    clean_exact_matches = 0
    for rank, source in enumerate(context_data["sources"], start=1):
        if not isinstance(source, Mapping):
            raise ValueError("Microsoft GraphRAG sources must be objects")
        text = _required_string(source.get("text"), "source.text")
        match = _MS_HEADER.match(text)
        parsed_id = match.group("id").strip() if match else ""
        document_id = str(source.get("logicguard_doc_id", "")).strip() or parsed_id
        if not document_id:
            raise ValueError("Microsoft GraphRAG source has no recoverable document ID")
        title = str(source.get("title", "")).strip()
        if not title and match:
            title = match.group("title").strip()
        hits.append(_hit(document_id, document_id, title, text, rank))
        if clean_documents is not None:
            clean = clean_documents.get(document_id)
            body = match.group("body").strip() if match else text.strip()
            if clean is not None and body == str(clean.get("text", "")).strip():
                clean_exact_matches += 1
    return {
        "dataset": _required_string(dataset, "dataset"),
        "query_id": query_id,
        "question": question,
        "backend": "S1_microsoft_graphrag",
        "live_hits": hits,
        "trace_metadata": {
            "adapter": "microsoft_graphrag_saved_local_context_v1",
            "token_counter_id": TOKEN_COUNTER_ID,
            "retrieved_sources": len(hits),
            "clean_exact_matches": clean_exact_matches
            if clean_documents is not None
            else None,
            "clean_exact_match_audited": clean_documents is not None,
        },
    }


def normalize_lightrag_query_data(
    *,
    query_id: str,
    question: str,
    dataset: str,
    payload: Mapping[str, Any],
    chunk_to_group: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize the documented LightRAG ``query_data`` response schema."""

    if payload.get("status") != "success" or not isinstance(
        payload.get("data"), Mapping
    ):
        raise ValueError(
            "LightRAG query_data payload must have success status and data"
        )
    chunks = payload["data"].get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("LightRAG query_data payload requires data.chunks")
    hits: list[dict[str, Any]] = []
    for rank, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, Mapping):
            raise ValueError("LightRAG chunks must be objects")
        chunk_id = _required_string(
            chunk.get("chunk_id") or chunk.get("reference_id"), "chunk_id"
        )
        text = _required_string(chunk.get("content"), "chunk.content")
        explicit_group = str(chunk.get("full_doc_id", "")).strip()
        mapped_group = str((chunk_to_group or {}).get(chunk_id, "")).strip()
        file_group = Path(str(chunk.get("file_path", ""))).stem.strip()
        group_id = explicit_group or mapped_group or file_group
        if not group_id:
            raise ValueError("LightRAG chunk has no source-group mapping")
        hits.append(_hit(chunk_id, group_id, "", text, rank))
    return {
        "dataset": _required_string(dataset, "dataset"),
        "query_id": _required_string(query_id, "query_id"),
        "question": _required_string(question, "question"),
        "backend": "S2_lightrag",
        "live_hits": hits,
        "trace_metadata": {
            "adapter": "lightrag_query_data_v1",
            "token_counter_id": TOKEN_COUNTER_ID,
            "retrieved_chunks": len(hits),
        },
    }


def _hit(
    document_id: str, source_group_id: str, title: str, text: str, rank: int
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "source_group_id": source_group_id,
        "title": title,
        "text": text,
        "n_tokens": comparison_token_count(text),
        "rank": rank,
    }


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()
