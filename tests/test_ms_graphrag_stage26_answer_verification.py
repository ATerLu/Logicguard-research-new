import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.evaluation.answer_proxy import (
    Stage26AnswerVerificationConfig,
    build_stage26_answer_rows,
    summarize_stage26_answer_rows,
    write_stage26_outputs,
)


def test_build_stage26_answer_rows_labels_correct_partial_incorrect_and_abstained() -> (
    None
):
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Who wrote Target Film?",
            answer="Ada River",
            support_doc_ids=["d1", "d2"],
            support_docs=[
                CorpusDocument("d1", "Trusted", "trusted"),
                CorpusDocument("d2", "Changed", "changed"),
            ],
        )
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    context_rows = [
        _context(
            "q1",
            "recovered_sources_by_doc_id",
            [_source("d1", "Ada River wrote Target Film.", recovered=True)],
        ),
        _context(
            "q1",
            "full_query_guard",
            [_source("d2", "Ada River appears, but this source is changed.")],
        ),
        _context(
            "q1",
            "non_oracle_title_entity_bm25",
            [_source("d2", "Changed poisoned body without answer.")],
        ),
        _context("q1", "guarded_sources", []),
    ]

    rows = build_stage26_answer_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset="toy",
    )
    by_method = {row.method: row for row in rows}

    assert by_method["recovered_sources_by_doc_id"].answer_label == "correct"
    assert by_method["recovered_sources_by_doc_id"].generated_answer == "Ada River"
    assert by_method["full_query_guard"].answer_label == "partial"
    assert by_method["full_query_guard"].is_partial is True
    assert by_method["non_oracle_title_entity_bm25"].answer_label == "incorrect"
    assert by_method["non_oracle_title_entity_bm25"].attack_success_proxy is True
    assert by_method["guarded_sources"].answer_label == "abstained"
    assert by_method["guarded_sources"].generated_answer == "UNKNOWN"


def test_summarize_stage26_answer_rows_reports_utility_and_attack_success() -> None:
    samples = [
        NormalizedSample(
            "q1", "Q1?", "Alice", ["d1"], [CorpusDocument("d1", "D1", "Alice text")]
        ),
        NormalizedSample(
            "q2", "Q2?", "Bob", ["d2"], [CorpusDocument("d2", "D2", "Bob text")]
        ),
    ]
    integrity_rows = [
        {"query_id": "q1", "changed_support_doc_ids": ["d1"]},
        {"query_id": "q2", "changed_support_doc_ids": ["d2"]},
    ]
    context_rows = [
        _context("q1", "method", [_source("d1", "Alice", recovered=True)]),
        _context("q2", "method", [_source("d2", "No answer")]),
    ]

    rows = build_stage26_answer_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset="toy",
    )
    summary = summarize_stage26_answer_rows(rows)

    assert len(summary) == 1
    assert summary[0].method == "method"
    assert summary[0].correct_rate == 0.5
    assert summary[0].utility_rate == 0.5
    assert summary[0].attack_success_proxy_rate == 0.5


def test_write_stage26_outputs_creates_jsonl_csv_summary_and_report(
    tmp_path: Path,
) -> None:
    samples = [
        NormalizedSample(
            "q1", "Q?", "Alice", ["d1"], [CorpusDocument("d1", "D1", "Alice")]
        ),
    ]
    rows = build_stage26_answer_rows(
        samples=samples,
        integrity_rows=[],
        context_rows=[_context("q1", "method", [_source("d1", "Alice")])],
        dataset="toy",
    )
    config = Stage26AnswerVerificationConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        context_input_path=tmp_path / "contexts.jsonl",
        results_output_path=tmp_path / "results.jsonl",
        metrics_output_path=tmp_path / "metrics.csv",
        summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        methods=["method"],
        max_queries=1,
        stage_label="Stage26",
    )

    write_stage26_outputs(config=config, answer_rows=rows)

    saved_result = json.loads(
        config.results_output_path.read_text(encoding="utf-8").strip()
    )
    assert saved_result["answer_label"] == "correct"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["utility_rate"] == "1.0000"
    report = config.report_path.read_text(encoding="utf-8")
    assert "Stage26 official sources answer-level proxy verification" in report
    assert "method" in report


def _source(doc_id: str, text: str, *, recovered: bool = False) -> dict[str, object]:
    return {
        "id": doc_id,
        "logicguard_doc_id": doc_id,
        "title": doc_id.upper(),
        "text": f"Document ID: {doc_id}\nTitle: {doc_id.upper()}\n\n{text}",
        "source_state": "clean_reference" if recovered else "official_poisoned_context",
        "recovered_from_changed_doc": recovered,
    }


def _context(
    query_id: str, method: str, sources: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": "Q?",
        "method": method,
        "context_text": "\n\n".join(str(source["text"]) for source in sources),
        "context_data": {"sources": sources, "entities": []},
    }
