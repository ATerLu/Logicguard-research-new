import csv
import json
from pathlib import Path

from logicguard.llm.provider import ChatResponse
from logicguard.evaluation.judge_audit import (
    Stage34AnswerJudgeAuditConfig,
    build_stage34_judge_rows,
    summarize_stage34_judge_rows,
    write_stage34_outputs,
)


def test_stage34_calls_judge_only_for_uncertain_incorrect_rows() -> None:
    client = FakeJudgeClient({"q3": '{"label": "partial", "reason": "Too broad."}'})

    rows = build_stage34_judge_rows(
        audited_rows=[
            _audited("q1", "correct", "original_correct", "Gold", "Gold"),
            _audited(
                "q2",
                "abstained",
                "abstain_without_gold_answer_surface",
                "Gold",
                "UNKNOWN",
            ),
            _audited(
                "q3",
                "incorrect",
                "incorrect_despite_gold_answer_surface",
                "Polish-Lithuanian Commonwealth",
                "Poland",
            ),
        ],
        client=client,
        judge_model="judge-model",
        judge_temperature=0.0,
        judge_max_tokens=96,
        judge_timeout_seconds=30,
    )
    by_query = {row.query_id: row for row in rows}

    assert client.called_queries == ["Which country q3?"]
    assert by_query["q1"].final_label == "correct"
    assert by_query["q1"].judge_called is False
    assert by_query["q2"].final_label == "abstained"
    assert by_query["q2"].judge_called is False
    assert by_query["q3"].judge_called is True
    assert by_query["q3"].judge_label == "partial"
    assert by_query["q3"].final_label == "partial"
    assert by_query["q3"].final_attack_success is False


def test_stage34_summary_counts_judge_aware_utility() -> None:
    rows = build_stage34_judge_rows(
        audited_rows=[
            _audited("q1", "correct", "original_correct", "Gold", "Gold"),
            _audited(
                "q2",
                "abstained",
                "abstain_without_gold_answer_surface",
                "Gold",
                "UNKNOWN",
            ),
            _audited(
                "q3",
                "incorrect",
                "incorrect_despite_gold_answer_surface",
                "Polish-Lithuanian Commonwealth",
                "Poland",
            ),
        ],
        client=FakeJudgeClient({"q3": '{"label": "partial", "reason": "Too broad."}'}),
        judge_model="judge-model",
        judge_temperature=0.0,
        judge_max_tokens=96,
        judge_timeout_seconds=30,
    )

    summary = summarize_stage34_judge_rows(rows)

    assert len(summary) == 1
    assert summary[0].query_count == 3
    assert summary[0].final_correct_rate == 1 / 3
    assert summary[0].final_partial_rate == 1 / 3
    assert summary[0].final_utility_rate == 2 / 3
    assert summary[0].judge_call_rate == 1 / 3


def test_stage34_outputs_are_written_with_chinese_report(tmp_path: Path) -> None:
    rows = build_stage34_judge_rows(
        audited_rows=[
            _audited("q1", "correct", "original_correct", "Gold", "Gold"),
            _audited(
                "q3",
                "incorrect",
                "incorrect_despite_gold_answer_surface",
                "Polish-Lithuanian Commonwealth",
                "Poland",
            ),
        ],
        client=FakeJudgeClient({"q3": '{"label": "partial", "reason": "Too broad."}'}),
        judge_model="judge-model",
        judge_temperature=0.0,
        judge_max_tokens=96,
        judge_timeout_seconds=30,
    )
    config = Stage34AnswerJudgeAuditConfig(
        dataset="toy",
        audited_results_path=tmp_path / "stage33_audited.jsonl",
        judged_results_output_path=tmp_path / "judged.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        breakdown_output_path=tmp_path / "breakdown.csv",
        examples_output_path=tmp_path / "examples.jsonl",
        report_path=tmp_path / "report.md",
        methods=["risk_non_oracle_title_entity_bm25"],
        judge_model="judge-model",
        judge_api_key_env="DASHSCOPE_API_KEY",
        judge_base_url_env="DASHSCOPE_BASE_URL",
        judge_temperature=0.0,
        judge_max_tokens=96,
        judge_timeout_seconds=30,
        max_examples=4,
        stage_label="Stage34",
    )

    write_stage34_outputs(config=config, rows=rows)

    saved = json.loads(
        config.judged_results_output_path.read_text(encoding="utf-8").splitlines()[1]
    )
    assert saved["final_label"] == "partial"
    with config.summary_output_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        summary = list(csv.DictReader(handle))
    assert summary[0]["final_utility_rate"] == "1.0000"
    report_text = config.report_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Stage34 回答裁判增强审计")
    assert "LLM judge" in report_text


class FakeJudgeClient:
    def __init__(self, responses_by_query_id: dict[str, str]) -> None:
        self.responses_by_query_id = responses_by_query_id
        self.called_queries: list[str] = []

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse:
        user_message = messages[-1]["content"]
        query_line = next(
            line for line in user_message.splitlines() if line.startswith("Question: ")
        )
        query = query_line.removeprefix("Question: ")
        self.called_queries.append(query)
        query_id = query.rsplit(" ", maxsplit=1)[-1].rstrip("?")
        return ChatResponse(
            content=self.responses_by_query_id[query_id],
            raw_json="{}",
            prompt_tokens=10,
            completion_tokens=4,
            total_tokens=14,
        )


def _audited(
    query_id: str,
    stage29_label: str,
    audit_reason: str,
    gold_answer: str,
    generated_answer: str,
) -> dict[str, object]:
    return {
        "dataset": "toy",
        "model": "toy-model",
        "query_id": query_id,
        "query": f"Which country {query_id}?",
        "method": "risk_non_oracle_title_entity_bm25",
        "gold_answer": gold_answer,
        "generated_answer": generated_answer,
        "original_answer_label": "incorrect",
        "stage29_label": stage29_label,
        "audit_reason": audit_reason,
        "normalized_gold_answer": gold_answer.lower(),
        "normalized_generated_answer": generated_answer.lower(),
        "support_doc_ids": ["d1"],
        "changed_support_doc_ids": [],
        "context_doc_ids": ["d1"],
        "support_hit_doc_ids": ["d1"],
        "unrecovered_changed_doc_ids": [],
        "recovered_support_doc_ids": ["d1"],
        "source_count": 8,
        "recovered_source_count": 8,
        "context_has_gold_answer": True,
        "original_attack_success": False,
        "stage29_attack_success": False,
        "error": None,
        "source_summaries": [
            {
                "rank": 1,
                "doc_id": "d1",
                "title": "Evidence",
                "source_state": "clean_reference",
                "snippet": "Evidence snippet.",
            }
        ],
    }
