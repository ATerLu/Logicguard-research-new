import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.defense.chain_completion import (
    Stage38ChainCompletenessConfig,
    build_stage38_chain_rows,
    build_stage38_targeted_context_rows,
    summarize_stage38_rows,
    write_stage38_outputs,
)


def test_stage38_marks_answer_surface_without_full_chain_as_incomplete() -> None:
    rows = build_stage38_chain_rows(
        samples=[_sample()],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Raj Kanwar", "Raj Kanwar was born in Stone City.")
        ],
        judged_rows=[_judged("q1", "abstained", "abstain_despite_gold_answer_surface")],
        dataset="toy",
        methods=["stage35_query_bm25_append_top12"],
        max_sources=3,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.context_has_gold_answer is True
    assert row.full_support_hit is False
    assert row.missing_support_doc_ids == ["d2"]
    assert row.chain_diagnosis == "answer_surface_without_full_chain"
    assert row.targeted_added_doc_ids == ["d2"]
    assert row.targeted_full_support_hit is True
    assert row.targeted_chain_complete is True


def test_stage38_second_hop_append_uses_bridge_entities_from_current_context() -> None:
    rows = build_stage38_chain_rows(
        samples=[_sample()],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Raj Kanwar", "Raj Kanwar was born in Stone City."),
            _candidate("d3", "Unrelated Person", "This source is irrelevant."),
        ],
        judged_rows=[],
        dataset="toy",
        methods=["stage35_query_bm25_append_top12"],
        max_sources=2,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
    )

    assert rows[0].bridge_terms[:2] == ["Film Alpha", "Raj Kanwar"]
    assert rows[0].targeted_context_doc_ids == ["d1", "d2"]
    assert rows[0].targeted_added_support_doc_ids == ["d2"]


def test_stage38_summary_contexts_and_outputs_are_written(tmp_path: Path) -> None:
    rows = build_stage38_chain_rows(
        samples=[_sample()],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Raj Kanwar", "Raj Kanwar was born in Stone City.")
        ],
        judged_rows=[_judged("q1", "abstained", "abstain_despite_gold_answer_surface")],
        dataset="toy",
        methods=["stage35_query_bm25_append_top12"],
        max_sources=3,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
    )
    summaries = summarize_stage38_rows(rows)
    assert summaries[0].chain_complete_rate == 0.0
    assert summaries[0].targeted_chain_complete_rate == 1.0
    assert summaries[0].targeted_full_support_gain_rate == 1.0

    targeted_context_rows = build_stage38_targeted_context_rows(
        context_rows=[_context_row()],
        chain_rows=rows,
        selected_max_sources=3,
    )
    assert targeted_context_rows[0]["method"] == "stage38_second_hop_append_top3"
    assert targeted_context_rows[0]["stage38_targeted_added_doc_ids"] == ["d2"]
    assert "Stone City" in targeted_context_rows[0]["context_text"]

    config = Stage38ChainCompletenessConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        context_input_path=tmp_path / "contexts.jsonl",
        clean_reference_output_dir=tmp_path / "clean",
        judged_results_path=tmp_path / "judged.jsonl",
        chain_rows_output_path=tmp_path / "rows.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        targeted_context_output_path=tmp_path / "contexts_out.jsonl",
        examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        methods=["stage35_query_bm25_append_top12"],
        max_queries=1,
        max_sources=3,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
        stage_label="Stage38",
    )

    write_stage38_outputs(
        config=config,
        rows=rows,
        summaries=summaries,
        targeted_context_rows=targeted_context_rows,
    )

    saved = json.loads(
        config.chain_rows_output_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert saved["chain_diagnosis"] == "answer_surface_without_full_chain"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["targeted_chain_complete_rate"] == "1.0000"
    report_text = config.report_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Stage38 链路完整性与二跳补证诊断")


def test_stage38_report_omits_answer_metrics_without_judged_results(
    tmp_path: Path,
) -> None:
    rows = build_stage38_chain_rows(
        samples=[_sample()],
        context_rows=[_context_row()],
        candidate_sources=[
            _candidate("d2", "Raj Kanwar", "Raj Kanwar was born in Stone City.")
        ],
        judged_rows=[],
        dataset="toy",
        methods=["stage35_query_bm25_append_top12"],
        max_sources=3,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
    )
    summaries = summarize_stage38_rows(rows)
    assert summaries[0].answer_audit_available is False
    assert summaries[0].final_utility_rate is None
    assert summaries[0].final_attack_success_rate is None
    config = Stage38ChainCompletenessConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        context_input_path=tmp_path / "contexts.jsonl",
        clean_reference_output_dir=tmp_path / "clean",
        judged_results_path=None,
        chain_rows_output_path=tmp_path / "rows.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        targeted_context_output_path=tmp_path / "contexts_out.jsonl",
        examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        methods=["stage35_query_bm25_append_top12"],
        max_queries=1,
        max_sources=3,
        max_chars_per_source=220,
        candidate_pool_top_k=4,
        stage_label="Stage38",
    )

    write_stage38_outputs(
        config=config,
        rows=rows,
        summaries=summaries,
        targeted_context_rows=build_stage38_targeted_context_rows(
            context_rows=[_context_row()],
            chain_rows=rows,
            selected_max_sources=3,
        ),
    )

    report_text = config.report_path.read_text(encoding="utf-8")
    assert "回答审计输入：未提供" in report_text
    assert "| utility |" not in report_text
    assert "Stage37" not in report_text


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="Who directed Film Alpha and was born in Stone City?",
        answer="Raj Kanwar",
        support_doc_ids=["d1", "d2"],
        support_docs=[
            CorpusDocument(
                doc_id="d1",
                title="Film Alpha",
                text="Film Alpha was directed by Raj Kanwar.",
            ),
            CorpusDocument(
                doc_id="d2",
                title="Raj Kanwar",
                text="Raj Kanwar was born in Stone City.",
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
        "query": "Who directed Film Alpha and was born in Stone City?",
        "method": "stage35_query_bm25_append_top12",
        "context_data": {
            "sources": [
                {
                    "logicguard_doc_id": "d1",
                    "title": "Film Alpha",
                    "source_state": "clean_reference",
                    "text": "Document ID: d1\nTitle: Film Alpha\n\nFilm Alpha was directed by Raj Kanwar.",
                },
            ]
        },
    }


def _judged(query_id: str, label: str, reason: str) -> dict[str, object]:
    return {
        "dataset": "toy",
        "model": "toy-model",
        "query_id": query_id,
        "query": "Who directed Film Alpha and was born in Stone City?",
        "method": "stage35_query_bm25_append_top12",
        "gold_answer": "Raj Kanwar",
        "generated_answer": "UNKNOWN",
        "final_label": label,
        "final_reason": reason,
        "final_attack_success": False,
    }
