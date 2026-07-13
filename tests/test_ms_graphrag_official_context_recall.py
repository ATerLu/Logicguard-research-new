import csv
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.official_context_recall import (
    build_context_recall_rows,
    summarize_context_recall,
    write_context_recall_artifacts,
)


def test_build_context_recall_rows_measures_support_hits_and_diagnosis() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Who?",
            answer="Alice",
            support_doc_ids=["a", "b", "c"],
            support_docs=[
                CorpusDocument(doc_id="a", title="A", text="A text"),
                CorpusDocument(doc_id="b", title="B", text="B text"),
                CorpusDocument(doc_id="c", title="C", text="C text"),
            ],
        )
    ]
    integrity_rows = [
        {
            "query_id": "q1",
            "changed_support_doc_ids": ["b"],
        }
    ]
    context_rows = [
        {
            "query_id": "q1",
            "response": "polluted answer",
            "context_data": {
                "sources": [
                    {"logicguard_doc_id": "b", "text": "Document ID: b\nTitle: B"},
                    {"logicguard_doc_id": "x", "text": "Document ID: x\nTitle: X"},
                ]
            },
        }
    ]
    result_rows = [
        _result("q1", "poisoned", correct=False, abstained=False, incorrect=True),
        _result("q1", "guarded", correct=False, abstained=True, incorrect=False),
        _result("q1", "recovered", correct=True, abstained=False, incorrect=False),
    ]

    rows = build_context_recall_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        result_rows=result_rows,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.context_doc_ids == ["b", "x"]
    assert row.gold_support_hit_ids == ["b"]
    assert row.changed_support_hit_ids == ["b"]
    assert row.trusted_support_hit_ids == []
    assert row.gold_support_recall == 1 / 3
    assert row.changed_support_exposure == 1.0
    assert row.trusted_support_recall == 0.0
    assert row.poisoned_outcome == "incorrect"
    assert row.guarded_outcome == "abstained"
    assert row.recovered_outcome == "correct"
    assert row.diagnosis == "attack_recovered"


def test_summarize_context_recall_counts_failure_types() -> None:
    rows = build_context_recall_rows(
        samples=[
            NormalizedSample("q1", "Q1", "A1", ["d1"], [CorpusDocument("d1", "D1", "text")]),
            NormalizedSample("q2", "Q2", "A2", ["d2"], [CorpusDocument("d2", "D2", "text")]),
        ],
        integrity_rows=[
            {"query_id": "q1", "changed_support_doc_ids": ["d1"]},
            {"query_id": "q2", "changed_support_doc_ids": ["d2"]},
        ],
        context_rows=[
            {"query_id": "q1", "context_data": {"sources": [{"logicguard_doc_id": "d1"}]}},
            {"query_id": "q2", "context_data": {"sources": [{"logicguard_doc_id": "x"}]}},
        ],
        result_rows=[
            _result("q1", "poisoned", correct=False, abstained=False, incorrect=True),
            _result("q1", "guarded", correct=False, abstained=True, incorrect=False),
            _result("q1", "recovered", correct=True, abstained=False, incorrect=False),
            _result("q2", "poisoned", correct=False, abstained=True, incorrect=False),
            _result("q2", "guarded", correct=False, abstained=True, incorrect=False),
            _result("q2", "recovered", correct=False, abstained=True, incorrect=False),
        ],
    )

    summary = summarize_context_recall(rows)

    assert summary.query_count == 2
    assert summary.avg_gold_support_recall == 0.5
    assert summary.context_recall_failure_count == 1
    assert summary.attack_recovered_count == 1


def test_write_context_recall_artifacts_outputs_csv_and_chinese_report(tmp_path: Path) -> None:
    rows = build_context_recall_rows(
        samples=[NormalizedSample("q1", "Q1", "A1", ["d1"], [CorpusDocument("d1", "D1", "text")])],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["d1"]}],
        context_rows=[{"query_id": "q1", "context_data": {"sources": [{"logicguard_doc_id": "d1"}]}}],
        result_rows=[
            _result("q1", "poisoned", correct=False, abstained=False, incorrect=True),
            _result("q1", "guarded", correct=False, abstained=True, incorrect=False),
            _result("q1", "recovered", correct=True, abstained=False, incorrect=False),
        ],
    )
    csv_path = tmp_path / "recall.csv"
    report_path = tmp_path / "recall.md"

    write_context_recall_artifacts(
        csv_path=csv_path,
        report_path=report_path,
        rows=rows,
        source_context_path=Path("outputs/context.jsonl"),
        source_results_path=Path("outputs/results.jsonl"),
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    report = report_path.read_text(encoding="utf-8")

    assert saved[0]["query_id"] == "q1"
    assert saved[0]["context_doc_ids"] == "d1"
    assert saved[0]["gold_support_recall"] == "1.0000"
    assert "召回指标说明" in report
    assert "gold_support_recall" in report


def _result(
    query_id: str,
    variant: str,
    *,
    correct: bool,
    abstained: bool,
    incorrect: bool,
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "variant": variant,
        "is_correct": correct,
        "is_abstained": abstained,
        "is_incorrect": incorrect,
        "error": None,
    }
