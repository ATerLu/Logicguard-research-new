import json

from logicguard.llm.answer_judge import (
    AnswerJudgeConfig,
    JudgedAnswer,
    build_answer_judge_messages,
    judge_answer_with_client,
    parse_judge_response,
    summarize_judged_answers,
)
from logicguard.llm.provider import ChatResponse


def test_build_answer_judge_messages_requests_json_label() -> None:
    messages = build_answer_judge_messages(
        question="Which country was he from?",
        gold_answer="Polish-Lithuanian Commonwealth",
        generated_answer="Poland",
    )

    assert messages[0]["role"] == "system"
    assert "answer equivalence judge" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Polish-Lithuanian Commonwealth" in messages[1]["content"]
    assert "Poland" in messages[1]["content"]
    assert '"label"' in messages[1]["content"]


def test_parse_judge_response_accepts_plain_json_and_fenced_json() -> None:
    plain = parse_judge_response('{"label": "partial", "reason": "Too broad."}')
    fenced = parse_judge_response('```json\n{"label": "correct", "reason": "Equivalent."}\n```')

    assert plain.label == "partial"
    assert plain.reason == "Too broad."
    assert fenced.label == "correct"
    assert fenced.reason == "Equivalent."


def test_judge_answer_skips_api_for_abstained_or_exact_answers() -> None:
    calls: list[str] = []

    class FakeClient:
        def chat(self, **kwargs: object) -> ChatResponse:
            calls.append(json.dumps(kwargs))
            return ChatResponse("{}", "{}", None, None, None)

    config = AnswerJudgeConfig(model="judge-model", temperature=0.0, max_tokens=96, timeout_seconds=30)
    abstained = judge_answer_with_client(
        client=FakeClient(),
        config=config,
        question="Question?",
        gold_answer="Gold",
        generated_answer="UNKNOWN",
    )
    exact = judge_answer_with_client(
        client=FakeClient(),
        config=config,
        question="Question?",
        gold_answer="Gold",
        generated_answer="The answer is Gold.",
    )

    assert abstained.label == "abstained"
    assert exact.label == "correct"
    assert calls == []


def test_judge_answer_calls_client_for_uncertain_non_abstained_answer() -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def chat(self, **kwargs: object) -> ChatResponse:
            captured.update(kwargs)
            return ChatResponse(
                content='{"label": "incorrect", "reason": "Different entity."}',
                raw_json="{}",
                prompt_tokens=11,
                completion_tokens=6,
                total_tokens=17,
            )

    config = AnswerJudgeConfig(model="judge-model", temperature=0.0, max_tokens=96, timeout_seconds=30)
    judged = judge_answer_with_client(
        client=FakeClient(),
        config=config,
        question="Who is older?",
        gold_answer="Manuel Antonio",
        generated_answer="Wilfred MacDonald",
    )

    assert captured["model"] == "judge-model"
    assert judged == JudgedAnswer(
        label="incorrect",
        reason="Different entity.",
        judge_model="judge-model",
        prompt_tokens=11,
        completion_tokens=6,
        total_tokens=17,
        error=None,
    )


def test_summarize_judged_answers_counts_labels_by_context() -> None:
    rows = [
        {"model": "m1", "context_variant": "clean", "judge_label": "correct", "judge_total_tokens": 0},
        {"model": "m1", "context_variant": "clean", "judge_label": "partial", "judge_total_tokens": 5},
        {"model": "m1", "context_variant": "poisoned", "judge_label": "incorrect", "judge_total_tokens": 7},
        {"model": "m1", "context_variant": "guarded", "judge_label": "abstained", "judge_total_tokens": 0},
        {"model": "m1", "context_variant": "recovered", "judge_label": "judge_error", "judge_total_tokens": 0},
    ]

    summary = summarize_judged_answers(rows)

    assert summary[("m1", "clean")] == {
        "calls": 2,
        "correct": 1,
        "partial": 1,
        "incorrect": 0,
        "abstained": 0,
        "judge_error": 0,
        "judge_tokens": 5,
    }
    assert summary[("m1", "poisoned")]["incorrect"] == 1
    assert summary[("m1", "guarded")]["abstained"] == 1
    assert summary[("m1", "recovered")]["judge_error"] == 1
