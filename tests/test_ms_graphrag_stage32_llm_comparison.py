import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.llm.provider import ChatResponse
from logicguard.evaluation.llm_comparison import (
    Stage32LLMComparisonConfig,
    Stage32VariantConfig,
    build_stage32_cases,
    run_stage32_generation,
    summarize_stage32_results,
    write_stage32_outputs,
)


def test_stage32_builds_default_and_title_overlap_cases() -> None:
    cases = build_stage32_cases(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        source_method="risk_non_oracle_title_entity_bm25",
        variants=[
            Stage32VariantConfig(
                name="stage28_default",
                order_policy="official_order",
                top_k=1,
                max_chars_per_source=900,
            ),
            Stage32VariantConfig(
                name="stage31_title_query_overlap",
                order_policy="title_query_overlap",
                top_k=1,
                max_chars_per_source=900,
            ),
        ],
    )

    assert [case.variant for case in cases] == [
        "stage28_default",
        "stage31_title_query_overlap",
    ]
    assert cases[0].context_doc_ids == ["d1"]
    assert cases[0].context_has_gold_answer is False
    assert cases[1].context_doc_ids == ["d2"]
    assert cases[1].support_hit_doc_ids == ["d2"]
    assert cases[1].context_has_gold_answer is True
    assert cases[1].ordering_uses_oracle is False


def test_stage32_generation_and_summary_compare_variants() -> None:
    cases = build_stage32_cases(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        source_method="risk_non_oracle_title_entity_bm25",
        variants=[
            Stage32VariantConfig("stage28_default", "official_order", 1, 900),
            Stage32VariantConfig(
                "stage31_title_query_overlap", "title_query_overlap", 1, 900
            ),
        ],
    )
    config = _config(
        Path("."),
        variants=[
            Stage32VariantConfig("stage28_default", "official_order", 1, 900),
            Stage32VariantConfig(
                "stage31_title_query_overlap", "title_query_overlap", 1, 900
            ),
        ],
    )

    results = run_stage32_generation(config=config, cases=cases, client=FakeClient())
    summary = summarize_stage32_results(results)
    by_variant = {row.variant: row for row in summary}

    assert by_variant["stage28_default"].utility_rate == 0.0
    assert by_variant["stage28_default"].abstain_rate == 1.0
    assert by_variant["stage31_title_query_overlap"].utility_rate == 1.0
    assert by_variant["stage31_title_query_overlap"].correct_rate == 1.0


def test_stage32_outputs_are_written_with_chinese_report(tmp_path: Path) -> None:
    variants = [
        Stage32VariantConfig("stage28_default", "official_order", 1, 900),
        Stage32VariantConfig(
            "stage31_title_query_overlap", "title_query_overlap", 1, 900
        ),
    ]
    cases = build_stage32_cases(
        samples=[_sample()],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[_context_row()],
        dataset="toy",
        source_method="risk_non_oracle_title_entity_bm25",
        variants=variants,
    )
    config = _config(tmp_path, variants=variants)
    results = run_stage32_generation(config=config, cases=cases, client=FakeClient())

    write_stage32_outputs(config=config, cases=cases, results=results)

    saved_case = json.loads(
        config.cases_output_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert saved_case["variant"] == "stage28_default"
    saved_result = json.loads(
        config.results_output_path.read_text(encoding="utf-8").splitlines()[1]
    )
    assert saved_result["variant"] == "stage31_title_query_overlap"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["query_count"] == "1"
    report_text = config.report_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Stage32 真实回答对照验证")
    assert "问题：" in report_text
    assert "引用 sources：" in report_text


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
            }
        )
        rendered_prompt = "\n".join(message["content"] for message in messages)
        content = "Silver Delta" if "Silver Delta" in rendered_prompt else "UNKNOWN"
        return ChatResponse(
            content=content,
            raw_json="{}",
            prompt_tokens=20,
            completion_tokens=2,
            total_tokens=22,
        )


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
                    "text": "Document ID: d2\nTitle: Ada Lovelace\n\nAda was born in Silver Delta.",
                },
            ]
        },
    }


def _config(
    root: Path,
    *,
    variants: list[Stage32VariantConfig],
) -> Stage32LLMComparisonConfig:
    return Stage32LLMComparisonConfig(
        dataset="toy",
        sample_path=root / "samples.jsonl",
        query_integrity_path=root / "integrity.jsonl",
        context_input_path=root / "contexts.jsonl",
        cases_output_path=root / "cases.jsonl",
        results_output_path=root / "results.jsonl",
        summary_output_path=root / "summary.csv",
        pairwise_output_path=root / "pairwise.csv",
        examples_output_path=root / "examples.jsonl",
        report_path=root / "report.md",
        source_method="risk_non_oracle_title_entity_bm25",
        variants=variants,
        models=["toy-model"],
        max_queries=1,
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        temperature=0.0,
        max_tokens=48,
        timeout_seconds=60,
        stage_label="Stage32",
        max_examples=4,
    )
