import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.answer_level_llm_verification import Stage27RenderingPolicy
from logicguard.ms_graphrag.stage46_answer_preflight import (
    Stage46AnswerPreflightConfig,
    Stage46ContextVariant,
    build_stage46_context_matrix,
    build_stage46_preflight_rows,
    summarize_stage46_preflight_rows,
    write_stage46_preflight_outputs,
)
from logicguard.ms_graphrag.answer_level_llm_verification import (
    build_stage27_answer_cases,
)


def test_stage46_freezes_one_row_per_query_and_measures_rendered_exposure(
    tmp_path: Path,
) -> None:
    sample = _sample()
    unsafe_path = tmp_path / "unsafe.jsonl"
    recovered_path = tmp_path / "recovered.jsonl"
    _write_jsonl(unsafe_path, [_context_row("full_query_guard", "official_poisoned_context")])
    _write_jsonl(
        recovered_path,
        [
            _context_row(
                "risk_non_oracle_title_entity_bm25",
                "recovered_reference",
                recovered=True,
            )
        ],
    )
    variants = [
        Stage46ContextVariant(
            method="full_query_guard",
            context_input_path=unsafe_path,
            source_method="full_query_guard",
            description="baseline",
        ),
        Stage46ContextVariant(
            method="risk_non_oracle_title_entity_bm25",
            context_input_path=recovered_path,
            source_method="risk_non_oracle_title_entity_bm25",
            description="recovered",
        ),
    ]
    matrix = build_stage46_context_matrix(
        samples=[sample], variants=variants, stage_label="Stage46-toy"
    )
    assert len(matrix) == 2
    assert matrix[0]["stage46_provenance"]["source_method"] == "full_query_guard"

    cases = build_stage27_answer_cases(
        samples=[sample],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["d1"]}],
        context_rows=matrix,
        dataset="toy",
        methods=[variant.method for variant in variants],
        max_sources=1,
        max_chars_per_source=220,
        rendering_policies={
            variant.method: Stage27RenderingPolicy(
                prompt_policy="evidence_compare", max_sources=1, max_chars_per_source=220
            )
            for variant in variants
        },
    )
    rows = build_stage46_preflight_rows(cases)
    summaries = summarize_stage46_preflight_rows(rows)

    baseline = next(row for row in rows if row.method == "full_query_guard")
    recovered = next(
        row for row in rows if row.method == "risk_non_oracle_title_entity_bm25"
    )
    assert baseline.unrecovered_changed_source_exposed is True
    assert recovered.unrecovered_changed_source_exposed is False
    assert next(
        row for row in summaries if row.method == "full_query_guard"
    ).attack_pressure_status == "充分"

    config = _config(tmp_path, variants)
    write_stage46_preflight_outputs(
        config=config,
        matrix_rows=matrix,
        cases=cases,
        preflight_rows=rows,
        summaries=summaries,
    )
    with config.preflight_summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved = list(csv.DictReader(handle))
    assert saved[0]["dataset"] == "toy"
    assert "实际未恢复污染源暴露率" in config.report_path.read_text(encoding="utf-8")


def test_stage46_rejects_missing_query_variant_context(tmp_path: Path) -> None:
    source_path = tmp_path / "contexts.jsonl"
    _write_jsonl(source_path, [])
    variant = Stage46ContextVariant(
        method="full_query_guard",
        context_input_path=source_path,
        source_method="full_query_guard",
        description="baseline",
    )
    try:
        build_stage46_context_matrix(samples=[_sample()], variants=[variant])
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("missing query context should fail")


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="Who directed Film Alpha?",
        answer="Raj Kanwar",
        support_doc_ids=["d1"],
        support_docs=[
            CorpusDocument(
                doc_id="d1",
                title="Film Alpha",
                text="Film Alpha was directed by Raj Kanwar.",
            )
        ],
    )


def _context_row(method: str, state: str, *, recovered: bool = False) -> dict[str, object]:
    return {
        "query_id": "q1",
        "query": "Who directed Film Alpha?",
        "method": method,
        "context_data": {
            "sources": [
                {
                    "logicguard_doc_id": "d1",
                    "title": "Film Alpha",
                    "source_state": state,
                    "recovered_from_risk_non_oracle_source": recovered,
                    "text": "Document ID: d1\nTitle: Film Alpha\n\nFilm Alpha was directed by Raj Kanwar.",
                }
            ]
        },
    }


def _config(tmp_path: Path, variants: list[Stage46ContextVariant]) -> Stage46AnswerPreflightConfig:
    return Stage46AnswerPreflightConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        variants=variants,
        context_matrix_output_path=tmp_path / "matrix.jsonl",
        preflight_cases_output_path=tmp_path / "cases.jsonl",
        preflight_rows_output_path=tmp_path / "rows.jsonl",
        preflight_summary_output_path=tmp_path / "summary.csv",
        preflight_examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        rendering_policies={},
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
