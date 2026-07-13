import json
from pathlib import Path

import pandas as pd

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.source_recovery import (
    Stage23SourceRecoveryConfig,
    build_stage23_context_rows,
    build_stage23_metric_rows,
    load_clean_reference_sources,
    summarize_stage23_metrics,
    write_stage23_outputs,
)


def test_load_clean_reference_sources_maps_clean_text_units_to_source_records(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd.DataFrame(
        [
            {
                "id": "official-d1",
                "human_readable_id": 7,
                "title": "d1.txt",
                "text": "Document ID: d1\nTitle: Target Film\n\nTarget clean body.",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet")
    pd.DataFrame(
        [
            {
                "id": "tu1",
                "human_readable_id": 3,
                "document_id": "official-d1",
                "text": "Document ID: d1\nTitle: Target Film\n\nTarget clean body.",
                "n_tokens": 12,
            }
        ]
    ).to_parquet(output_dir / "text_units.parquet")

    clean_sources = load_clean_reference_sources(output_dir)

    assert clean_sources["d1"]["logicguard_doc_id"] == "d1"
    assert clean_sources["d1"]["title"] == "Target Film"
    assert clean_sources["d1"]["source_state"] == "clean_reference"


def test_build_stage23_context_rows_filters_and_recovers_official_sources() -> None:
    context_rows = [
        {
            "query_id": "q1",
            "query": "Question?",
            "method": "full_query_guard",
            "context_data": {
                "sources": [
                    {
                        "id": "0",
                        "logicguard_doc_id": "d1",
                        "title": "Trusted",
                        "text": "Document ID: d1\nTitle: Trusted\n\nTrusted text.",
                    },
                    {
                        "id": "1",
                        "logicguard_doc_id": "d2",
                        "title": "Changed",
                        "text": "Document ID: d2\nTitle: Changed\n\nPoisoned text.",
                    },
                ],
                "entities": [{"entity": "CHANGED"}],
            },
        }
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    clean_sources = {
        "d2": {
            "id": "clean-tu-d2",
            "logicguard_doc_id": "d2",
            "title": "Changed",
            "text": "Document ID: d2\nTitle: Changed\n\nClean recovered text.",
            "source_state": "clean_reference",
        }
    }

    rows = build_stage23_context_rows(
        source_context_rows=context_rows,
        integrity_rows=integrity_rows,
        clean_reference_sources=clean_sources,
        input_method_name="full_query_guard",
    )

    by_method = {row["method"]: row for row in rows}
    assert [source["logicguard_doc_id"] for source in by_method["full_query_guard"]["context_data"]["sources"]] == [
        "d1",
        "d2",
    ]
    assert by_method["full_query_guard"]["context_data"]["sources"][1]["risk_reasons"] == [
        "changed_logicpoison_support"
    ]
    assert [source["logicguard_doc_id"] for source in by_method["guarded_sources"]["context_data"]["sources"]] == [
        "d1"
    ]
    recovered_sources = by_method["recovered_sources_by_doc_id"]["context_data"]["sources"]
    assert [source["logicguard_doc_id"] for source in recovered_sources] == ["d1", "d2"]
    assert recovered_sources[1]["recovered_from_changed_doc"] is True
    assert "Clean recovered text" in by_method["recovered_sources_by_doc_id"]["context_text"]
    assert "Poisoned text" not in by_method["recovered_sources_by_doc_id"]["context_text"]


def test_stage23_metrics_do_not_count_clean_recovered_sources_as_changed_exposure() -> None:
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
        _context("q1", "full_query_guard", [_source("d1"), _source("d2")]),
        _context("q1", "guarded_sources", [_source("d1")]),
        _context(
            "q1",
            "recovered_sources_by_doc_id",
            [_source("d1"), _source("d2", source_state="clean_reference", recovered=True)],
        ),
    ]

    rows = build_stage23_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset="toy",
    )
    by_method = {row.method: row for row in rows}

    assert by_method["full_query_guard"].gold_support_recall == 1.0
    assert by_method["full_query_guard"].changed_support_exposure == 1.0
    assert by_method["guarded_sources"].gold_support_recall == 0.5
    assert by_method["guarded_sources"].changed_support_exposure == 0.0
    assert by_method["recovered_sources_by_doc_id"].gold_support_recall == 1.0
    assert by_method["recovered_sources_by_doc_id"].changed_support_exposure == 0.0
    assert by_method["recovered_sources_by_doc_id"].recovered_source_count == 1

    summaries = summarize_stage23_metrics(rows)
    recovered = next(row for row in summaries if row.method == "recovered_sources_by_doc_id")
    assert recovered.avg_gold_support_recall == 1.0
    assert recovered.avg_changed_support_exposure == 0.0


def test_write_stage23_outputs_creates_jsonl_csv_and_chinese_report(tmp_path: Path) -> None:
    context_rows = [_context("q1", "recovered_sources_by_doc_id", [_source("d1")])]
    metric_rows = build_stage23_metric_rows(
        samples=[NormalizedSample("q1", "Q?", "A", ["d1"], [CorpusDocument("d1", "D1", "text")])],
        integrity_rows=[],
        context_rows=context_rows,
        dataset="toy",
    )
    config = Stage23SourceRecoveryConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        source_context_path=tmp_path / "source_context.jsonl",
        baseline_context_path=None,
        clean_reference_output_dir=tmp_path / "clean",
        context_output_path=tmp_path / "contexts.jsonl",
        metrics_output_path=tmp_path / "metrics.csv",
        summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        input_method_name="full_query_guard",
        max_queries=1,
    )

    write_stage23_outputs(config=config, context_rows=context_rows, metric_rows=metric_rows)

    saved_context = json.loads(config.context_output_path.read_text(encoding="utf-8").strip())
    assert saved_context["method"] == "recovered_sources_by_doc_id"
    assert "gold_support_recall" in config.metrics_output_path.read_text(encoding="utf-8-sig")
    report = config.report_path.read_text(encoding="utf-8")
    assert "Stage23" in report
    assert "sources级Recovery" in report
    assert "指标说明" in report


def test_write_stage_outputs_uses_configured_stage_label(tmp_path: Path) -> None:
    context_rows = [_context("q1", "recovered_sources_by_doc_id", [_source("d1")])]
    metric_rows = build_stage23_metric_rows(
        samples=[NormalizedSample("q1", "Q?", "A", ["d1"], [CorpusDocument("d1", "D1", "text")])],
        integrity_rows=[],
        context_rows=context_rows,
        dataset="toy",
    )
    config = Stage23SourceRecoveryConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        source_context_path=tmp_path / "source_context.jsonl",
        baseline_context_path=None,
        clean_reference_output_dir=tmp_path / "clean",
        context_output_path=tmp_path / "contexts.jsonl",
        metrics_output_path=tmp_path / "metrics.csv",
        summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        input_method_name="full_query_guard",
        max_queries=1,
        stage_label="Stage24",
    )

    write_stage23_outputs(config=config, context_rows=context_rows, metric_rows=metric_rows)

    report = config.report_path.read_text(encoding="utf-8")
    assert "Stage24 sources级Recovery实验报告" in report
    assert "Stage23" not in report


def _source(doc_id: str, *, source_state: str = "official_poisoned_context", recovered: bool = False):
    return {
        "id": doc_id,
        "logicguard_doc_id": doc_id,
        "title": doc_id.upper(),
        "text": f"Document ID: {doc_id}\nTitle: {doc_id.upper()}\n\ntext",
        "source_state": source_state,
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
