import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.defense.source_enrichment import (
    Stage35SourceEnrichmentConfig,
    build_stage35_enrichment_rows,
    build_stage35_enriched_context_rows,
    summarize_stage35_rows,
    write_stage35_outputs,
)


def test_stage35_query_bm25_enrichment_adds_clean_answer_candidate() -> None:
    rows = build_stage35_enrichment_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Ada Lovelace", "Ada was born in Silver Delta."),
            _candidate("d3", "Unrelated", "No answer here."),
        ],
        audited_rows=[
            _audited("q1", "abstained", "abstain_without_gold_answer_surface")
        ],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["stage33_title_overlap", "query_bm25_append"],
        max_sources_values=[1, 2],
        max_chars_per_source=220,
        candidate_pool_top_k=3,
    )
    by_key = {(row.enrichment_policy, row.max_sources): row for row in rows}

    assert by_key[("stage33_title_overlap", 1)].context_doc_ids == ["d1"]
    assert by_key[("stage33_title_overlap", 1)].context_has_gold_answer is False
    assert by_key[("query_bm25_append", 2)].context_doc_ids == ["d1", "d2"]
    assert by_key[("query_bm25_append", 2)].added_doc_ids == ["d2"]
    assert by_key[("query_bm25_append", 2)].context_has_gold_answer is True
    assert by_key[("query_bm25_append", 2)].support_context_has_gold_answer is True
    assert by_key[("query_bm25_append", 2)].answerability_label == "answerable_clean"
    assert by_key[("query_bm25_append", 2)].ordering_uses_oracle is False


def test_stage35_oracle_support_append_reports_upper_bound() -> None:
    rows = build_stage35_enrichment_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Ada Lovelace", "Ada was born in Silver Delta.")
        ],
        audited_rows=[],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["oracle_support_append"],
        max_sources_values=[2],
        max_chars_per_source=220,
        candidate_pool_top_k=3,
    )

    assert len(rows) == 1
    assert rows[0].ordering_uses_oracle is True
    assert rows[0].added_support_doc_ids == ["d2"]
    assert rows[0].context_has_gold_answer is True


def test_stage35_query_bm25_append_inserts_candidates_after_stage33_baseline() -> None:
    context_row = _context_row()
    context_row["context_data"]["sources"].append(
        {
            "logicguard_doc_id": "d4",
            "title": "Current distractor",
            "source_state": "clean_reference",
            "text": "Document ID: d4\nTitle: Current distractor\n\nThis current source should stay behind the enriched answer candidate.",
        }
    )

    rows = build_stage35_enrichment_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[context_row],
        candidate_sources=[
            _candidate("d2", "Ada Lovelace", "Ada was born in Silver Delta.")
        ],
        audited_rows=[],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["query_bm25_append"],
        max_sources_values=[2],
        max_chars_per_source=220,
        candidate_pool_top_k=3,
        baseline_max_sources=1,
    )

    assert rows[0].context_doc_ids == ["d1", "d2"]
    assert rows[0].added_doc_ids == ["d2"]


def test_stage35_summary_contexts_and_outputs_are_written(tmp_path: Path) -> None:
    rows = build_stage35_enrichment_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Ada Lovelace", "Ada was born in Silver Delta.")
        ],
        audited_rows=[
            _audited("q1", "abstained", "abstain_without_gold_answer_surface")
        ],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["stage33_title_overlap", "query_bm25_append"],
        max_sources_values=[1, 2],
        max_chars_per_source=220,
        candidate_pool_top_k=3,
    )
    summaries = summarize_stage35_rows(rows)
    by_policy = {row.enrichment_policy: row for row in summaries}

    assert by_policy["stage33_title_overlap"].answer_surface_rate == 0.0
    assert by_policy["query_bm25_append"].answer_surface_rate == 1.0
    assert by_policy["query_bm25_append"].support_answer_surface_rate == 1.0
    assert by_policy["query_bm25_append"].gained_answer_surface_rate == 1.0

    enriched_context_rows = build_stage35_enriched_context_rows(
        context_rows=[_context_row()],
        enrichment_rows=rows,
        selected_policy="query_bm25_append",
        selected_max_sources=2,
    )
    assert enriched_context_rows[0]["method"] == "stage35_query_bm25_append_top2"
    assert enriched_context_rows[0]["stage35_added_doc_ids"] == ["d2"]
    assert "Silver Delta" in enriched_context_rows[0]["context_text"]

    config = Stage35SourceEnrichmentConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        context_input_path=tmp_path / "contexts.jsonl",
        clean_reference_output_dir=tmp_path / "clean",
        audited_results_path=tmp_path / "audited.jsonl",
        enriched_context_output_path=tmp_path / "enriched_contexts.jsonl",
        enrichment_rows_output_path=tmp_path / "rows.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        methods=["risk_non_oracle_title_entity_bm25"],
        enrichment_policies=["stage33_title_overlap", "query_bm25_append"],
        max_sources_values=[1, 2],
        max_queries=1,
        max_chars_per_source=220,
        candidate_pool_top_k=3,
        selected_policy="query_bm25_append",
        selected_max_sources=2,
        stage_label="Stage35",
    )

    write_stage35_outputs(
        config=config,
        rows=rows,
        summaries=summaries,
        enriched_context_rows=enriched_context_rows,
    )

    assert (
        json.loads(
            config.enrichment_rows_output_path.read_text(encoding="utf-8").splitlines()[
                0
            ]
        )["query_id"]
        == "q1"
    )
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["query_count"] == "1"
    assert config.report_path.read_text(encoding="utf-8").startswith(
        "# Stage35 候选源扩展诊断"
    )


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="Where was Ada Lovelace born?",
        answer="Silver Delta",
        support_doc_ids=["d2"],
        support_docs=[
            CorpusDocument(
                doc_id="d2", title="Ada Lovelace", text="Ada was born in Silver Delta."
            ),
        ],
    )


def _candidate(doc_id: str, title: str, text: str) -> NonOracleCandidateSource:
    return NonOracleCandidateSource(
        id=f"tu-{doc_id}",
        text_unit_id=f"tu-{doc_id}",
        logicguard_doc_id=doc_id,
        official_document_id=doc_id,
        human_readable_id=int(doc_id[1:]) if doc_id[1:].isdigit() else 1,
        title=title,
        text=f"Document ID: {doc_id}\nTitle: {title}\n\n{text}",
        n_tokens=32,
    )


def _context_row() -> dict[str, object]:
    return {
        "query_id": "q1",
        "query": "Where was Ada Lovelace born?",
        "method": "risk_non_oracle_title_entity_bm25",
        "context_data": {
            "sources": [
                {
                    "logicguard_doc_id": "d1",
                    "title": "Unrelated document",
                    "source_state": "clean_reference",
                    "text": "Document ID: d1\nTitle: Unrelated document\n\nNothing useful here.",
                },
            ]
        },
    }


def _audited(query_id: str, label: str, reason: str) -> dict[str, object]:
    return {
        "query_id": query_id,
        "final_label": label,
        "final_reason": reason,
        "stage29_label": label,
        "audit_reason": reason,
    }
