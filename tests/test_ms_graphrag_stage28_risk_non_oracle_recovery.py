import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.defense.risk_aware_recovery import (
    Stage28RiskNonOracleRecoveryConfig,
    build_stage28_context_rows,
    build_stage28_metric_rows,
    detect_non_oracle_source_risk,
    summarize_stage28_metrics,
    write_stage28_outputs,
)


def test_detect_non_oracle_source_risk_uses_clean_candidate_drift_without_labels() -> (
    None
):
    candidate = _candidate(
        doc_id="638",
        title="Oskar Roehler",
        text="Oskar Roehler was born as the son of writer Gisela Elsner and writer Klaus Roehler.",
    )
    poisoned_source = _source(
        "638",
        "Oskar Roehler",
        "Oskar Roehler was born as the son of writer Mallory Stone and writer Klaus Roehler.",
    )
    clean_source = _source(
        "638",
        "Oskar Roehler",
        "Oskar Roehler was born as the son of writer Gisela Elsner and writer Klaus Roehler.",
    )

    poisoned_result = detect_non_oracle_source_risk(
        query="Who is the mother of the director of Atomised?",
        source=poisoned_source,
        candidate_sources=[candidate],
        entities=["OSKAR ROEHLER"],
        entity_drift_threshold=0.2,
    )
    clean_result = detect_non_oracle_source_risk(
        query="Who is the mother of the director of Atomised?",
        source=clean_source,
        candidate_sources=[candidate],
        entities=["OSKAR ROEHLER"],
        entity_drift_threshold=0.2,
    )

    assert poisoned_result.is_risky is True
    assert poisoned_result.candidate_doc_id == "638"
    assert "clean_candidate_entity_drift" in poisoned_result.risk_reasons
    assert clean_result.is_risky is False
    assert clean_result.risk_reasons == []


def test_detect_non_oracle_source_risk_ignores_shared_header_when_body_subject_drifts() -> (
    None
):
    candidate = _candidate(
        doc_id="4782",
        title="Marius Mapou",
        text="Marius Mapou is an international footballer for New Caledonia.",
    )
    poisoned_source = _source(
        "4782",
        "Marius Mapou",
        "Tu Du is an international footballer for New Caledonia.",
    )

    result = detect_non_oracle_source_risk(
        query="Which team did Marius Mapou play for?",
        source=poisoned_source,
        candidate_sources=[candidate],
        entities=["MARIUS MAPOU"],
        entity_drift_threshold=0.1,
    )

    assert result.is_risky is True
    assert result.entity_drift >= 0.1


def test_build_stage28_context_rows_filters_and_recovers_without_integrity_rows() -> (
    None
):
    candidate = _candidate(
        doc_id="638",
        title="Oskar Roehler",
        text="Oskar Roehler was born as the son of writer Gisela Elsner and writer Klaus Roehler.",
    )
    source_rows = [
        _context(
            query_id="q1",
            sources=[
                _source(
                    "638",
                    "Oskar Roehler",
                    "Oskar Roehler was born as the son of writer Mallory Stone and writer Klaus Roehler.",
                ),
                _source(
                    "639", "Atomised (film)", "Atomised was directed by Oskar Roehler."
                ),
            ],
        )
    ]

    rows = build_stage28_context_rows(
        source_context_rows=source_rows,
        candidate_sources=[candidate],
        input_method_name="full_query_guard",
        entity_drift_threshold=0.2,
    )
    by_method = {row["method"]: row for row in rows}

    assert set(by_method) == {
        "full_query_guard",
        "risk_non_oracle_guarded_sources",
        "risk_non_oracle_title_entity_bm25",
    }
    assert by_method["risk_non_oracle_guarded_sources"]["filtered_source_doc_ids"] == [
        "638"
    ]
    recovered_sources = by_method["risk_non_oracle_title_entity_bm25"]["context_data"][
        "sources"
    ]
    assert recovered_sources[0]["logicguard_doc_id"] == "638"
    assert recovered_sources[0]["source_state"] == "clean_reference"
    assert recovered_sources[0]["recovered_from_risk_non_oracle_source"] is True
    assert "Gisela Elsner" in recovered_sources[0]["text"]


def test_stage28_metrics_report_risk_detection_and_support_exposure() -> None:
    samples = [
        NormalizedSample(
            "q1",
            "Who is the mother of the director of Atomised?",
            "Gisela Elsner",
            ["638", "639"],
            [
                CorpusDocument("638", "Oskar Roehler", "Gisela Elsner"),
                CorpusDocument("639", "Atomised", "Oskar"),
            ],
        )
    ]
    context_rows = [
        _context(
            "q1",
            [_source("638", "Oskar Roehler", "poisoned")],
            method="full_query_guard",
        ),
        _context(
            "q1",
            [
                _source(
                    "639", "Atomised (film)", "Atomised was directed by Oskar Roehler."
                )
            ],
            method="risk_non_oracle_guarded_sources",
            filtered=["638"],
            risk=["638"],
        ),
        _context(
            "q1",
            [
                _recovered_source("638", "Oskar Roehler", "Gisela Elsner"),
                _source(
                    "639", "Atomised (film)", "Atomised was directed by Oskar Roehler."
                ),
            ],
            method="risk_non_oracle_title_entity_bm25",
            risk=["638"],
            recovered=["638"],
        ),
    ]
    metrics = build_stage28_metric_rows(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["638"]}],
        context_rows=context_rows,
        dataset="toy",
    )
    by_method = {row.method: row for row in metrics}

    assert by_method["risk_non_oracle_guarded_sources"].risk_recall == 1.0
    assert by_method["risk_non_oracle_guarded_sources"].risk_precision == 1.0
    assert by_method["risk_non_oracle_guarded_sources"].changed_support_exposure == 0.0
    assert by_method["risk_non_oracle_title_entity_bm25"].gold_support_recall == 1.0
    assert (
        by_method["risk_non_oracle_title_entity_bm25"].changed_support_exposure == 0.0
    )

    summary = summarize_stage28_metrics(metrics)
    assert {row.method: row.avg_risk_recall for row in summary}[
        "risk_non_oracle_title_entity_bm25"
    ] == 1.0


def test_write_stage28_outputs_creates_artifacts(tmp_path: Path) -> None:
    samples = [
        NormalizedSample(
            "q1", "Q?", "Alice", ["d1"], [CorpusDocument("d1", "D1", "Alice")]
        ),
    ]
    context_rows = [
        _context(
            "q1",
            [_recovered_source("d1", "D1", "Alice")],
            method="risk_non_oracle_title_entity_bm25",
            risk=["d1"],
            recovered=["d1"],
        )
    ]
    metrics = build_stage28_metric_rows(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["d1"]}],
        context_rows=context_rows,
        dataset="toy",
    )
    config = Stage28RiskNonOracleRecoveryConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        source_context_path=tmp_path / "contexts.jsonl",
        clean_reference_output_dir=tmp_path / "clean",
        context_output_path=tmp_path / "contexts_out.jsonl",
        metrics_output_path=tmp_path / "metrics.csv",
        summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        input_method_name="full_query_guard",
        max_queries=1,
        stage_label="Stage28",
    )

    write_stage28_outputs(config=config, context_rows=context_rows, metric_rows=metrics)

    assert (
        json.loads(config.context_output_path.read_text(encoding="utf-8").strip())[
            "method"
        ]
        == "risk_non_oracle_title_entity_bm25"
    )
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["avg_risk_recall"] == "1.0000"
    assert "Stage28 非 Oracle 风险识别与官方来源恢复" in config.report_path.read_text(
        encoding="utf-8"
    )


def _candidate(doc_id: str, title: str, text: str) -> NonOracleCandidateSource:
    return NonOracleCandidateSource(
        id=f"tu-{doc_id}",
        text_unit_id=f"tu-{doc_id}",
        logicguard_doc_id=doc_id,
        official_document_id=doc_id,
        human_readable_id=int(doc_id) if doc_id.isdigit() else 1,
        title=title,
        text=f"Document ID: {doc_id}\nTitle: {title}\n\n{text}",
        n_tokens=32,
    )


def _source(doc_id: str, title: str, text: str) -> dict[str, object]:
    return {
        "id": doc_id,
        "logicguard_doc_id": doc_id,
        "title": title,
        "text": f"Document ID: {doc_id}\nTitle: {title}\n\n{text}",
        "source_state": "official_poisoned_context",
    }


def _recovered_source(doc_id: str, title: str, text: str) -> dict[str, object]:
    source = _source(doc_id, title, text)
    source["source_state"] = "clean_reference"
    source["recovered_from_risk_non_oracle_source"] = True
    source["recovered_from_changed_doc"] = False
    return source


def _context(
    query_id: str,
    sources: list[dict[str, object]],
    *,
    method: str = "full_query_guard",
    filtered: list[str] | None = None,
    risk: list[str] | None = None,
    recovered: list[str] | None = None,
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": "Who is the mother of the director of Atomised?",
        "method": method,
        "include_entity_names": ["OSKAR ROEHLER"],
        "unknown_entity_names": [],
        "context_data": {"sources": sources, "entities": []},
        "filtered_source_doc_ids": filtered or [],
        "risk_detected_source_doc_ids": risk or [],
        "recovered_source_doc_ids": recovered or [],
    }
