import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.evaluation.answerability_ablation import (
    Stage31AnswerabilityConfig,
    build_stage31_ablation_rows,
    summarize_stage31_rows,
    write_stage31_outputs,
)


def test_stage31_ordering_topk_and_prompt_budget_change_answer_surface() -> None:
    rows = build_stage31_ablation_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        order_policies=["official_order", "oracle_answer_surface_first"],
        top_ks=[1],
        prompt_char_budgets={"compact": 80, "expanded": 900},
    )
    by_key = {
        (row.order_policy, row.prompt_policy): row for row in rows if row.top_k == 1
    }

    assert by_key[("official_order", "expanded")].context_doc_ids == ["d1"]
    assert by_key[("official_order", "expanded")].context_has_gold_answer is False
    assert by_key[("oracle_answer_surface_first", "compact")].context_doc_ids == ["d2"]
    assert (
        by_key[("oracle_answer_surface_first", "compact")].context_has_gold_answer
        is False
    )
    assert by_key[("oracle_answer_surface_first", "expanded")].context_doc_ids == ["d2"]
    assert (
        by_key[("oracle_answer_surface_first", "expanded")].context_has_gold_answer
        is True
    )
    assert (
        by_key[("oracle_answer_surface_first", "expanded")].answerability_label
        == "answerable_clean"
    )
    assert (
        by_key[("oracle_answer_surface_first", "expanded")].first_gold_answer_rank == 1
    )


def test_stage31_title_query_overlap_is_non_oracle_and_can_surface_support() -> None:
    rows = build_stage31_ablation_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        order_policies=["official_order", "title_query_overlap"],
        top_ks=[1],
        prompt_char_budgets={"expanded": 900},
    )
    by_policy = {row.order_policy: row for row in rows}

    assert by_policy["official_order"].context_doc_ids == ["d1"]
    assert by_policy["title_query_overlap"].context_doc_ids == ["d2"]
    assert by_policy["title_query_overlap"].support_hit_doc_ids == ["d2"]
    assert by_policy["title_query_overlap"].context_has_gold_answer is True
    assert by_policy["title_query_overlap"].ordering_uses_oracle is False


def test_stage31_summaries_and_outputs_are_written(tmp_path: Path) -> None:
    rows = build_stage31_ablation_rows(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        order_policies=["official_order", "title_query_overlap"],
        top_ks=[1],
        prompt_char_budgets={"expanded": 900},
    )
    summaries = summarize_stage31_rows(rows)
    by_policy = {row.order_policy: row for row in summaries}

    assert by_policy["official_order"].answer_surface_rate == 0.0
    assert by_policy["title_query_overlap"].answer_surface_rate == 1.0
    assert by_policy["title_query_overlap"].clean_answerable_rate == 1.0

    config = Stage31AnswerabilityConfig(
        dataset="toy",
        sample_path=tmp_path / "samples.jsonl",
        query_integrity_path=tmp_path / "integrity.jsonl",
        context_input_path=tmp_path / "contexts.jsonl",
        ablation_rows_output_path=tmp_path / "rows.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        methods=["risk_non_oracle_title_entity_bm25"],
        order_policies=["official_order", "title_query_overlap"],
        top_ks=[1],
        prompt_char_budgets={"expanded": 900},
        stage_label="Stage31",
    )

    write_stage31_outputs(config=config, rows=rows, summaries=summaries)

    first_row = config.ablation_rows_output_path.read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert json.loads(first_row)["query_id"] == "q1"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["query_count"] == "1"
    report_text = config.report_path.read_text(encoding="utf-8")
    assert "# Stage31 回答可用性消融" in report_text
    assert "source ordering / top-k / prompt budget" in report_text


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


def _context_row() -> dict[str, object]:
    filler = " ".join(["context"] * 60)
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
                {
                    "logicguard_doc_id": "d2",
                    "title": "Ada Lovelace",
                    "source_state": "clean_reference",
                    "recovered_from_risk_non_oracle_source": True,
                    "text": f"Document ID: d2\nTitle: Ada Lovelace\n\n{filler} Silver Delta.",
                },
            ]
        },
    }
