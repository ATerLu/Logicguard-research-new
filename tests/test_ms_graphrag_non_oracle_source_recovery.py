from pathlib import Path

import pandas as pd

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.non_oracle_source_recovery import (
    NonOracleCandidateSource,
    build_stage25_context_rows,
    build_stage25_metric_rows,
    load_candidate_sources,
    rank_non_oracle_candidates,
    summarize_stage25_metrics,
)


def test_load_candidate_sources_reads_clean_text_units_without_doc_id_lookup_table(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd.DataFrame(
        [
            {
                "id": "official-d1",
                "human_readable_id": 1,
                "title": "d1.txt",
                "text": "Document ID: d1\nTitle: Target Film\n\nClean body.",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet")
    pd.DataFrame(
        [
            {
                "id": "tu1",
                "human_readable_id": 4,
                "document_id": "official-d1",
                "text": "Document ID: d1\nTitle: Target Film\n\nClean body.",
                "n_tokens": 9,
            }
        ]
    ).to_parquet(output_dir / "text_units.parquet")

    candidates = load_candidate_sources(output_dir)

    assert len(candidates) == 1
    assert candidates[0].logicguard_doc_id == "d1"
    assert candidates[0].title == "Target Film"
    assert candidates[0].source_state == "clean_reference"


def test_rank_non_oracle_candidates_prefers_lexical_match_over_same_doc_id_distractor() -> None:
    risky_source = {
        "id": "poisoned-source",
        "logicguard_doc_id": "d2",
        "title": "Target Film",
        "text": "Document ID: d2\nTitle: Target Film\n\nPoisoned unrelated body.",
    }
    candidates = [
        NonOracleCandidateSource(
            id="same-doc-distractor",
            text_unit_id="same-doc-distractor",
            logicguard_doc_id="d2",
            official_document_id="official-d2",
            human_readable_id=2,
            title="Unrelated Page",
            text="Document ID: d2\nTitle: Unrelated Page\n\nNo useful lexical evidence.",
            n_tokens=11,
        ),
        NonOracleCandidateSource(
            id="lexical-hit",
            text_unit_id="lexical-hit",
            logicguard_doc_id="d9",
            official_document_id="official-d9",
            human_readable_id=9,
            title="Target Film",
            text="Document ID: d9\nTitle: Target Film\n\nLena directed Target Film in Vienna.",
            n_tokens=13,
        ),
    ]

    hits = rank_non_oracle_candidates(
        query="Who directed Target Film with Lena in Vienna?",
        source=risky_source,
        candidate_sources=candidates,
        entities=["Lena", "Vienna"],
        method="non_oracle_hybrid_policy",
        top_k=2,
    )

    assert hits[0].candidate.logicguard_doc_id == "d9"
    assert hits[0].score > hits[1].score
    assert hits[0].score_breakdown["doc_id_lookup"] == 0.0


def test_build_stage25_context_rows_replaces_changed_sources_with_ranked_candidates() -> None:
    context_rows = [
        {
            "query_id": "q1",
            "query": "Who directed Target Film with Lena?",
            "method": "full_query_guard",
            "context_data": {
                "sources": [
                    _source("d1", "Trusted Page", "Trusted text."),
                    _source("d2", "Target Film", "Poisoned Target Film text."),
                ],
                "entities": [{"entity": "LENA"}],
            },
        }
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    candidates = [
        NonOracleCandidateSource(
            id="clean-d2",
            text_unit_id="clean-d2",
            logicguard_doc_id="d2",
            official_document_id="official-d2",
            human_readable_id=2,
            title="Target Film",
            text="Document ID: d2\nTitle: Target Film\n\nClean Target Film Lena evidence.",
            n_tokens=12,
        )
    ]

    rows = build_stage25_context_rows(
        source_context_rows=context_rows,
        integrity_rows=integrity_rows,
        candidate_sources=candidates,
        input_method_name="full_query_guard",
    )

    by_method = {row["method"]: row for row in rows}
    assert "full_query_guard" in by_method
    assert "guarded_sources" in by_method
    assert "non_oracle_query_bm25" in by_method
    assert "non_oracle_title_entity_bm25" in by_method
    assert "non_oracle_hybrid_policy" in by_method

    recovered_sources = by_method["non_oracle_hybrid_policy"]["context_data"]["sources"]
    assert [source["logicguard_doc_id"] for source in recovered_sources] == ["d1", "d2"]
    recovered = recovered_sources[1]
    assert recovered["source_state"] == "clean_reference"
    assert recovered["recovered_from_changed_doc"] is True
    assert recovered["recovery_method"] == "non_oracle_hybrid_policy"
    assert recovered["candidate_score"] > 0.0
    assert "Clean Target Film Lena evidence" in by_method["non_oracle_hybrid_policy"]["context_text"]
    assert "Poisoned Target Film text" not in by_method["non_oracle_hybrid_policy"]["context_text"]


def test_stage25_metrics_add_oracle_gap_and_replacement_quality() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Question?",
            answer="Answer",
            support_doc_ids=["d1", "d2"],
            support_docs=[
                CorpusDocument("d1", "Trusted", "trusted"),
                CorpusDocument("d2", "Changed", "changed"),
            ],
        )
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    context_rows = [
        _context("q1", "recovered_sources_by_doc_id", [_source("d1"), _source("d2", recovered=True)]),
        _context("q1", "non_oracle_hybrid_policy", [_source("d1"), _source("d2", recovered=True)]),
        _context("q1", "non_oracle_query_bm25", [_source("d1"), _source("d9", recovered=True)]),
    ]

    metric_rows = build_stage25_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset="toy",
    )
    summaries = summarize_stage25_metrics(metric_rows)
    by_method = {row.method: row for row in summaries}

    assert by_method["non_oracle_hybrid_policy"].avg_oracle_gap == 0.0
    assert by_method["non_oracle_hybrid_policy"].avg_replacement_hit_rate == 1.0
    assert by_method["non_oracle_hybrid_policy"].avg_bad_replacement_rate == 0.0
    assert by_method["non_oracle_query_bm25"].avg_oracle_gap == 0.5
    assert by_method["non_oracle_query_bm25"].avg_replacement_hit_rate == 0.0
    assert by_method["non_oracle_query_bm25"].avg_bad_replacement_rate == 1.0


def _source(
    doc_id: str,
    title: str | None = None,
    body: str = "text",
    *,
    recovered: bool = False,
):
    return {
        "id": doc_id,
        "logicguard_doc_id": doc_id,
        "title": title or doc_id.upper(),
        "text": f"Document ID: {doc_id}\nTitle: {title or doc_id.upper()}\n\n{body}",
        "source_state": "clean_reference" if recovered else "official_poisoned_context",
        "recovered_from_changed_doc": recovered,
    }


def _context(query_id: str, method: str, sources: list[dict[str, object]]):
    return {
        "query_id": query_id,
        "query": "Q?",
        "method": method,
        "context_text": "",
        "context_data": {"sources": sources, "entities": []},
    }
