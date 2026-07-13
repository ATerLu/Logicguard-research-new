import csv
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.official_entity_diagnostics import (
    build_entity_diagnostic_rows,
    summarize_entity_diagnostics,
    write_entity_diagnostic_artifacts,
)


def test_build_entity_diagnostic_rows_tracks_support_title_hits() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Who directed Film A?",
            answer="Alice",
            support_doc_ids=["d1", "d2"],
            support_docs=[
                CorpusDocument(doc_id="d1", title="Film A", text="Film A text"),
                CorpusDocument(doc_id="d2", title="Alice Director", text="Alice text"),
            ],
        )
    ]
    context_rows = [
        {
            "query_id": "q1",
            "context_data": {
                "entities": [
                    {"id": "1", "entity": "FILM A", "number of relationships": "3", "in_context": True},
                    {"id": "2", "entity": "UNRELATED", "number of relationships": "9", "in_context": True},
                ],
                "sources": [{"logicguard_doc_id": "d1"}],
            },
        }
    ]

    rows = build_entity_diagnostic_rows(samples=samples, context_rows=context_rows, recall_rows=[])

    assert len(rows) == 1
    row = rows[0]
    assert row.selected_entity_names == ["FILM A", "UNRELATED"]
    assert row.selected_entity_ranks == ["3", "9"]
    assert row.support_titles == ["Film A", "Alice Director"]
    assert row.support_title_entity_hits == ["Film A"]
    assert row.support_title_entity_hit_rate == 0.5
    assert row.context_doc_ids == ["d1"]


def test_summarize_entity_diagnostics_counts_repeated_top_entities() -> None:
    samples = [
        NormalizedSample("q1", "Q1", "A1", ["d1"], [CorpusDocument("d1", "Doc One", "text")]),
        NormalizedSample("q2", "Q2", "A2", ["d2"], [CorpusDocument("d2", "Doc Two", "text")]),
    ]
    context_rows = [
        {"query_id": "q1", "context_data": {"entities": [{"entity": "SHARED"}, {"entity": "A"}], "sources": []}},
        {"query_id": "q2", "context_data": {"entities": [{"entity": "SHARED"}, {"entity": "B"}], "sources": []}},
    ]

    rows = build_entity_diagnostic_rows(samples=samples, context_rows=context_rows, recall_rows=[])
    summary = summarize_entity_diagnostics(rows)

    assert summary.query_count == 2
    assert summary.avg_support_title_entity_hit_rate == 0.0
    assert summary.most_common_top_entities[0] == ("SHARED", 2)
    assert summary.repeated_top_entity_query_count == 2


def test_write_entity_diagnostic_artifacts_outputs_csv_and_report(tmp_path: Path) -> None:
    samples = [
        NormalizedSample("q1", "Q1", "A1", ["d1"], [CorpusDocument("d1", "Doc One", "text")]),
    ]
    context_rows = [
        {"query_id": "q1", "context_data": {"entities": [{"entity": "DOC ONE"}], "sources": []}},
    ]
    rows = build_entity_diagnostic_rows(samples=samples, context_rows=context_rows, recall_rows=[])
    csv_path = tmp_path / "entities.csv"
    report_path = tmp_path / "entities.md"

    write_entity_diagnostic_artifacts(
        csv_path=csv_path,
        report_path=report_path,
        rows=rows,
        source_context_path=Path("outputs/context.jsonl"),
        source_recall_path=Path("outputs/recall.csv"),
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    report = report_path.read_text(encoding="utf-8")

    assert saved[0]["query_id"] == "q1"
    assert saved[0]["selected_entity_names"] == "DOC ONE"
    assert saved[0]["support_title_entity_hit_rate"] == "1.0000"
    assert "实体诊断指标说明" in report
    assert "most_common_top_entities" in report
