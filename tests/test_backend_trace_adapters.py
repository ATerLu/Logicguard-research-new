import pytest

from logicguard.benchmark.backend_trace_adapters import (
    TOKEN_COUNTER_ID,
    comparison_token_count,
    normalize_lightrag_query_data,
    normalize_ms_graphrag_context,
)


def test_ms_adapter_recovers_document_group_and_audits_clean_body() -> None:
    row = {
        "query_id": "q1",
        "query": "Who wrote Alpha?",
        "context_data": {
            "sources": [
                {
                    "id": "1",
                    "text": "Document ID: doc-1\nTitle: Alpha\n\nClean body.",
                    "logicguard_doc_id": "doc-1",
                    "title": "Alpha",
                }
            ]
        },
    }

    normalized = normalize_ms_graphrag_context(
        row, dataset="toy", clean_documents={"doc-1": {"text": "Clean body."}}
    )

    hit = normalized["live_hits"][0]
    assert hit["source_group_id"] == "doc-1"
    assert hit["n_tokens"] == comparison_token_count(hit["text"])
    assert normalized["trace_metadata"]["clean_exact_matches"] == 1
    assert normalized["trace_metadata"]["token_counter_id"] == TOKEN_COUNTER_ID


def test_lightrag_adapter_maps_chunks_to_full_document_groups() -> None:
    payload = {
        "status": "success",
        "data": {
            "chunks": [
                {
                    "content": "Evidence one.",
                    "file_path": "ignored.txt",
                    "chunk_id": "chunk-1",
                    "full_doc_id": "doc-1",
                },
                {
                    "content": "Evidence two.",
                    "file_path": "doc-2.txt",
                    "chunk_id": "chunk-2",
                },
            ]
        },
    }

    normalized = normalize_lightrag_query_data(
        query_id="q1", question="Q?", dataset="toy", payload=payload
    )

    assert [hit["source_group_id"] for hit in normalized["live_hits"]] == [
        "doc-1",
        "doc-2",
    ]
    assert [hit["rank"] for hit in normalized["live_hits"]] == [1, 2]


def test_lightrag_adapter_rejects_unmapped_source_group() -> None:
    payload = {
        "status": "success",
        "data": {"chunks": [{"content": "Evidence", "chunk_id": "chunk-1"}]},
    }
    with pytest.raises(ValueError, match="source-group mapping"):
        normalize_lightrag_query_data(
            query_id="q1", question="Q?", dataset="toy", payload=payload
        )
