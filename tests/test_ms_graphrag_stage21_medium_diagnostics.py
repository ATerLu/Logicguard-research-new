import json
from pathlib import Path

import pandas as pd

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.ms_graphrag.stage21_medium_diagnostics import (
    Stage21RunConfig,
    build_stage21_metric_rows,
    build_stage21_method_contexts,
    load_stage21_text_units,
    rank_text_units_bm25,
    summarize_stage21_metrics,
    write_stage21_outputs,
)


def test_load_stage21_text_units_restores_logicguard_doc_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd.DataFrame(
        [
            {
                "id": "official-d1",
                "human_readable_id": 7,
                "title": "d1.txt",
                "text": "Document ID: d1\nTitle: Target Film\n\nTarget body.",
            }
        ]
    ).to_parquet(output_dir / "documents.parquet")
    pd.DataFrame(
        [
            {
                "id": "tu1",
                "human_readable_id": 3,
                "document_id": "official-d1",
                "text": "Document ID: d1\nTitle: Target Film\n\nTarget body.",
                "n_tokens": 12,
            }
        ]
    ).to_parquet(output_dir / "text_units.parquet")

    units = load_stage21_text_units(output_dir)

    assert len(units) == 1
    assert units[0].logicguard_doc_id == "d1"
    assert units[0].title == "Target Film"
    assert units[0].text_unit_id == "tu1"


def test_rank_text_units_bm25_can_use_title_boost() -> None:
    units = [
        _unit("tu1", "d1", "Target Film", "A short unrelated body."),
        _unit("tu2", "d2", "Other Work", "Target words appear repeatedly in this body Target."),
    ]

    plain = rank_text_units_bm25("Target Film", units, top_k=2, title_boost=0.0)
    boosted = rank_text_units_bm25("Target Film", units, top_k=2, title_boost=4.0)

    assert plain[0].logicguard_doc_id == "d2"
    assert boosted[0].logicguard_doc_id == "d1"
    assert boosted[0].rank == 1


def test_build_stage21_method_contexts_filters_and_recovers_changed_docs() -> None:
    poisoned_units = [
        _unit("p1", "d1", "Clean Support", "clean support text"),
        _unit("p2", "d2", "Changed Support", "poisoned support text"),
    ]
    clean_units = [_unit("c2", "d2", "Changed Support", "clean recovered text")]

    contexts = build_stage21_method_contexts(
        query="Changed Support",
        poisoned_units=poisoned_units,
        clean_reference_units=clean_units,
        changed_doc_ids={"d2"},
        top_k=2,
        title_boost=4.0,
    )

    guarded_ids = [item.logicguard_doc_id for item in contexts["guarded_filter"]]
    recovered = contexts["recovered_by_doc_id"]

    assert guarded_ids == ["d1"]
    assert [item.logicguard_doc_id for item in recovered] == ["d2", "d1"]
    assert recovered[0].source_state == "clean_reference"
    assert recovered[0].recovered_from_changed_doc is True
    assert any("known_changed_doc" in item.risk_reasons for item in contexts["poisoned_bm25"])


def test_build_and_summarize_stage21_metrics_cover_precision_mrr_and_distractors() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Question?",
            answer="Answer",
            support_doc_ids=["d1", "d2"],
            support_docs=[
                CorpusDocument("d1", "Trusted", "trusted text"),
                CorpusDocument("d2", "Changed", "changed text"),
            ],
        )
    ]
    method_contexts = {
        "q1": {
            "poisoned_bm25": [
                _ranked("d2", rank=1, source_state="poisoned"),
                _ranked("x1", rank=2, source_state="poisoned"),
            ],
            "guarded_filter": [],
        }
    }

    rows = build_stage21_metric_rows(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["d2"]}],
        contexts_by_query=method_contexts,
        top_k=2,
    )
    summaries = summarize_stage21_metrics(rows)

    by_method = {row.method: row for row in rows}
    poisoned = by_method["poisoned_bm25"]
    assert poisoned.hit_at_k == 1.0
    assert poisoned.gold_recall_at_k == 0.5
    assert poisoned.precision_at_k == 0.5
    assert poisoned.distractor_ratio_at_k == 0.5
    assert poisoned.mrr_at_k == 1.0
    assert poisoned.changed_doc_exposure_at_k == 1.0
    assert poisoned.changed_gold_exposure_at_k == 1.0
    assert poisoned.trusted_gold_recall_at_k == 0.0
    assert by_method["guarded_filter"].empty_context == 1
    assert {summary.method for summary in summaries} == {"poisoned_bm25", "guarded_filter"}


def test_write_stage21_outputs_creates_csv_jsonl_and_chinese_report(tmp_path: Path) -> None:
    rows = [
        build_stage21_metric_rows(
            samples=[
                NormalizedSample("q1", "Q?", "A", ["d1"], [CorpusDocument("d1", "D1", "text")])
            ],
            integrity_rows=[],
            contexts_by_query={"q1": {"poisoned_bm25": [_ranked("d1", rank=1)]}},
            top_k=1,
        )[0]
    ]
    config = Stage21RunConfig(
        dataset="2wikimultihopqa",
        sample_path=tmp_path / "samples.jsonl",
        poisoned_output_dir=tmp_path / "poisoned",
        clean_output_dir=tmp_path / "clean",
        query_integrity_path=tmp_path / "integrity.jsonl",
        evidence_output_path=tmp_path / "evidence.jsonl",
        metrics_output_path=tmp_path / "metrics.csv",
        summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        max_queries=1,
        top_k_values=[1],
        title_boost=2.0,
    )
    write_stage21_outputs(
        config=config,
        evidence_rows=[{"query_id": "q1", "method": "poisoned_bm25"}],
        metric_rows=rows,
    )

    assert config.evidence_output_path.exists()
    assert json.loads(config.evidence_output_path.read_text(encoding="utf-8").strip())["query_id"] == "q1"
    assert "gold_recall" in config.metrics_output_path.read_text(encoding="utf-8-sig")
    report = config.report_path.read_text(encoding="utf-8")
    assert "Stage21" in report
    assert "指标说明" in report
    assert "干扰文档比例" in report


def _unit(text_unit_id: str, doc_id: str, title: str, text: str):
    from logicguard.ms_graphrag.stage21_medium_diagnostics import Stage21TextUnit

    return Stage21TextUnit(
        text_unit_id=text_unit_id,
        human_readable_id=0,
        official_document_id=f"official-{doc_id}",
        logicguard_doc_id=doc_id,
        title=title,
        text=text,
        n_tokens=len(text.split()),
    )


def _ranked(doc_id: str, *, rank: int = 1, source_state: str = "poisoned"):
    unit = _unit(f"tu-{doc_id}", doc_id, doc_id.upper(), "text")
    return unit.to_ranked(score=10.0 / rank, rank=rank, source_state=source_state)
