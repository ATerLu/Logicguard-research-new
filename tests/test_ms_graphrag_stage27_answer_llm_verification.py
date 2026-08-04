import csv
import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.llm.provider import ChatResponse
from logicguard.evaluation.answer_generation import (
    Stage27AnswerLLMConfig,
    Stage27RenderingPolicy,
    build_stage27_answer_cases,
    run_stage27_answer_generation,
    summarize_stage27_results,
    write_stage27_outputs,
)


def test_build_stage27_answer_cases_renders_official_source_contexts() -> None:
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
        _context("q1", "full_query_guard", [_source("d2", "Mallory poisoned body.")]),
        _context("q1", "guarded_sources", []),
        _context(
            "q1",
            "recovered_sources_by_doc_id",
            [_source("d2", "Ada River clean recovered.", recovered=True)],
        ),
        _context(
            "q1",
            "non_oracle_title_entity_bm25",
            [_source("d1", "Trusted context with Ada River.")],
        ),
    ]

    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset="toy",
        methods=[
            "full_query_guard",
            "guarded_sources",
            "recovered_sources_by_doc_id",
            "non_oracle_title_entity_bm25",
        ],
        max_sources=2,
        max_chars_per_source=80,
    )

    assert [case.method for case in cases] == [
        "full_query_guard",
        "guarded_sources",
        "recovered_sources_by_doc_id",
        "non_oracle_title_entity_bm25",
    ]
    assert cases[0].context_doc_ids == ["d2"]
    assert cases[0].unrecovered_changed_doc_ids == ["d2"]
    assert (
        "[G1] doc_id=d2; source_state=official_poisoned_context"
        in cases[0].rendered_context
    )
    assert cases[1].rendered_context == ""
    assert cases[2].recovered_support_doc_ids == ["d2"]
    assert "source_state=clean_reference" in cases[2].rendered_context


def test_build_stage27_answer_cases_applies_title_overlap_rendering_policy() -> None:
    samples = [
        NormalizedSample(
            query_id="q1",
            query="Where was Ada Lovelace born?",
            answer="Silver Delta",
            support_doc_ids=["d2"],
            support_docs=[
                CorpusDocument("d2", "Ada Lovelace", "Ada was born in Silver Delta."),
            ],
        )
    ]
    context_rows = [
        _context(
            "q1",
            "risk_non_oracle_title_entity_bm25",
            [
                _source("d1", "Nothing useful here.", title="Unrelated document"),
                _source(
                    "d2",
                    "Ada was born in Silver Delta.",
                    title="Ada Lovelace",
                    recovered=True,
                ),
            ],
        )
    ]

    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=context_rows,
        dataset="toy",
        methods=["risk_non_oracle_title_entity_bm25"],
        max_sources=1,
        max_chars_per_source=80,
        rendering_policies={
            "risk_non_oracle_title_entity_bm25": Stage27RenderingPolicy(
                order_policy="title_query_overlap",
                max_sources=1,
                max_chars_per_source=120,
            )
        },
    )

    assert len(cases) == 1
    assert cases[0].context_doc_ids == ["d2"]
    assert cases[0].support_hit_doc_ids == ["d2"]
    assert cases[0].context_has_gold_answer is True
    assert cases[0].order_policy == "title_query_overlap"
    assert cases[0].max_sources == 1
    assert cases[0].max_chars_per_source == 120


def test_stage27_rendering_policy_carries_prompt_policy_to_model_call() -> None:
    samples = [
        NormalizedSample(
            "q1",
            "Which film has the older director, A or B?",
            "A",
            ["d1"],
            [CorpusDocument("d1", "A", "A has the older director.")],
        )
    ]
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": []}],
        context_rows=[
            _context(
                "q1",
                "stage35_query_bm25_append_top12",
                [_source("d1", "A has the older director.", recovered=True)],
            )
        ],
        dataset="toy",
        methods=["stage35_query_bm25_append_top12"],
        max_sources=1,
        max_chars_per_source=80,
        rendering_policies={
            "stage35_query_bm25_append_top12": Stage27RenderingPolicy(
                prompt_policy="evidence_compare"
            )
        },
    )
    config = _config(Path("."), models=["toy-model"])
    fake_client = FakeClient()

    results = run_stage27_answer_generation(
        config=config, cases=cases, client=fake_client
    )

    assert cases[0].prompt_policy == "evidence_compare"
    assert results[0].prompt_policy == "evidence_compare"
    sent_messages = fake_client.calls[0]["messages"]
    assert isinstance(sent_messages, list)
    assert "check all numbered evidence blocks" in sent_messages[0]["content"]


def test_run_stage27_answer_generation_with_fake_client_labels_outcomes() -> None:
    samples = [
        NormalizedSample(
            "q1",
            "Who wrote Target Film?",
            "Ada River",
            ["d2"],
            [CorpusDocument("d2", "D2", "Ada")],
        )
    ]
    integrity_rows = [{"query_id": "q1", "changed_support_doc_ids": ["d2"]}]
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=[
            _context(
                "q1", "full_query_guard", [_source("d2", "Mallory poisoned body.")]
            ),
            _context("q1", "guarded_sources", []),
            _context(
                "q1",
                "recovered_sources_by_doc_id",
                [_source("d2", "Ada River clean recovered.", recovered=True)],
            ),
        ],
        dataset="toy",
        methods=["full_query_guard", "guarded_sources", "recovered_sources_by_doc_id"],
        max_sources=2,
        max_chars_per_source=80,
    )
    config = _config(Path("."), models=["toy-model"])
    fake_client = FakeClient()

    results = run_stage27_answer_generation(
        config=config, cases=cases, client=fake_client
    )
    by_method = {result.method: result for result in results}

    assert len(fake_client.calls) == 3
    assert by_method["full_query_guard"].answer_label == "incorrect"
    assert by_method["full_query_guard"].attack_success is True
    assert by_method["guarded_sources"].answer_label == "abstained"
    assert by_method["recovered_sources_by_doc_id"].answer_label == "correct"
    assert by_method["recovered_sources_by_doc_id"].is_correct is True


def test_summarize_and_write_stage27_outputs(tmp_path: Path) -> None:
    samples = [
        NormalizedSample(
            "q1",
            "Who wrote Target Film?",
            "Ada River",
            ["d2"],
            [CorpusDocument("d2", "D2", "Ada")],
        )
    ]
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["d2"]}],
        context_rows=[
            _context(
                "q1", "full_query_guard", [_source("d2", "Mallory poisoned body.")]
            ),
            _context(
                "q1",
                "recovered_sources_by_doc_id",
                [_source("d2", "Ada River clean recovered.", recovered=True)],
            ),
        ],
        dataset="toy",
        methods=["full_query_guard", "recovered_sources_by_doc_id"],
        max_sources=2,
        max_chars_per_source=80,
    )
    config = _config(tmp_path, models=["toy-model"])
    results = run_stage27_answer_generation(
        config=config, cases=cases, client=FakeClient()
    )
    summary = summarize_stage27_results(results)

    assert {row.method: row.correct_rate for row in summary} == {
        "full_query_guard": 0.0,
        "recovered_sources_by_doc_id": 1.0,
    }

    write_stage27_outputs(config=config, cases=cases, results=results)

    saved_case = json.loads(
        config.cases_output_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert saved_case["method"] == "full_query_guard"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["model"] == "toy-model"
    assert config.report_path.read_text(encoding="utf-8").startswith(
        "# Stage27 official sources LLM 回答层验证"
    )


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
        if "NO_CONTEXT" in rendered_prompt:
            content = "UNKNOWN"
        elif "Mallory poisoned body" in rendered_prompt:
            content = "Mallory Stone"
        else:
            content = "Ada River"
        return ChatResponse(
            content=content,
            raw_json="{}",
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
        )


def _config(root: Path, *, models: list[str]) -> Stage27AnswerLLMConfig:
    return Stage27AnswerLLMConfig(
        dataset="toy",
        sample_path=root / "samples.jsonl",
        query_integrity_path=root / "integrity.jsonl",
        context_input_path=root / "contexts.jsonl",
        cases_output_path=root / "cases.jsonl",
        results_output_path=root / "results.jsonl",
        metrics_output_path=root / "metrics.csv",
        summary_output_path=root / "summary.csv",
        report_path=root / "report.md",
        methods=["full_query_guard", "guarded_sources", "recovered_sources_by_doc_id"],
        models=models,
        max_queries=1,
        max_sources=3,
        max_chars_per_source=120,
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        temperature=0.0,
        max_tokens=48,
        timeout_seconds=60,
        judge_model=None,
        judge_temperature=0.0,
        judge_max_tokens=96,
        judge_timeout_seconds=60,
        stage_label="Stage27",
    )


def _source(
    doc_id: str,
    text: str,
    *,
    title: str | None = None,
    recovered: bool = False,
) -> dict[str, object]:
    source_title = title or doc_id.upper()
    return {
        "id": doc_id,
        "logicguard_doc_id": doc_id,
        "title": source_title,
        "text": f"Document ID: {doc_id}\nTitle: {source_title}\n\n{text}",
        "source_state": "clean_reference" if recovered else "official_poisoned_context",
        "recovered_from_changed_doc": recovered,
    }


def _context(
    query_id: str, method: str, sources: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": "Who wrote Target Film?",
        "method": method,
        "context_text": "\n\n".join(str(source["text"]) for source in sources),
        "context_data": {"sources": sources, "entities": []},
    }
