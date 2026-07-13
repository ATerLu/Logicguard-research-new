from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.query_layer_evaluation import (
    build_query_layer_metric_rows,
    summarize_query_layer_metrics,
    write_query_layer_evaluation,
)


def test_build_query_layer_metric_rows_measures_recall_exposure_and_entity_hit() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Question?",
            answer="Answer",
            support_doc_ids=["d1", "d2"],
            support_docs=[
                CorpusDocument("d1", "Target One", "text"),
                CorpusDocument("d2", "Target Two", "text"),
            ],
        )
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    context_rows = [
        {
            "query_id": "q1",
            "method": "full_query_guard",
            "include_entity_names": ["TARGET TWO"],
            "exclude_entity_names": ["HUB"],
            "context_data": {
                "sources": [
                    {"logicguard_doc_id": "d2", "text": "Document ID: d2\nTitle: Target Two"},
                    {"logicguard_doc_id": "x", "text": "Document ID: x\nTitle: Other"},
                ],
                "entities": [{"entity": "TARGET TWO"}],
            },
        }
    ]

    rows = build_query_layer_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
    )

    row = rows[0]
    assert row.gold_support_recall == 0.5
    assert row.changed_support_exposure == 1.0
    assert row.trusted_support_recall == 0.0
    assert row.support_title_entity_hit_rate == 0.5
    assert row.context_recall_failure is False
    assert row.include_entity_count == 1
    assert row.exclude_entity_count == 1


def test_summarize_and_write_query_layer_evaluation_outputs_chinese_report(tmp_path: Path) -> None:
    samples = [
        NormalizedSample("q1", "Q1", "A1", ["d1"], [CorpusDocument("d1", "D1", "text")]),
        NormalizedSample("q2", "Q2", "A2", ["d2"], [CorpusDocument("d2", "D2", "text")]),
    ]
    contexts = [
        _context("q1", "mixed_baseline", ["d1"], ["D1"]),
        _context("q2", "mixed_baseline", [], []),
        _context("q1", "full_query_guard", ["d1"], ["D1"]),
        _context("q2", "full_query_guard", ["d2"], ["D2"]),
    ]
    rows = build_query_layer_metric_rows(
        samples=samples,
        integrity_rows=[],
        context_rows=contexts,
    )

    summaries = summarize_query_layer_metrics(rows)
    metrics_path = tmp_path / "metrics.csv"
    summary_path = tmp_path / "summary.csv"
    report_path = tmp_path / "report.md"
    write_query_layer_evaluation(
        rows=rows,
        metrics_path=metrics_path,
        summary_path=summary_path,
        report_path=report_path,
    )

    by_method = {summary.method: summary for summary in summaries}
    assert by_method["mixed_baseline"].avg_gold_support_recall == 0.5
    assert by_method["full_query_guard"].avg_gold_support_recall == 1.0
    assert by_method["full_query_guard"].context_recall_failure_count == 0
    report = report_path.read_text(encoding="utf-8")
    assert "Stage20 Query-layer检索实验报告" in report
    assert "指标说明" in report
    assert "证据与限制" in report


def _context(
    query_id: str,
    method: str,
    doc_ids: list[str],
    entities: list[str],
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "method": method,
        "context_data": {
            "sources": [
                {"logicguard_doc_id": doc_id, "text": f"Document ID: {doc_id}"}
                for doc_id in doc_ids
            ],
            "entities": [{"entity": entity} for entity in entities],
        },
    }
