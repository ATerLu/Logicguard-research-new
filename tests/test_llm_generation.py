import json
from pathlib import Path

from logicguard.data.schemas import CorpusDocument
from logicguard.llm.context import build_context_blocks, build_qa_messages
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import OpenAICompatibleChatClient
from logicguard.llm.run_generation_pilot import (
    GenerationCase,
    GenerationPilotConfig,
    _context_variants_for_case,
    is_answer_stage_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "llm_generation_pilot_debug.yaml"
RECOVERY_CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "llm_generation_expanded_natural_bridge_v2_recovery_full_500.yaml"
)


def test_generation_pilot_config_resolves_debug_paths() -> None:
    config = GenerationPilotConfig.from_yaml(CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.models == ["qwen3.7-plus", "deepseek-v4-flash"]
    assert config.api_key_env == "DASHSCOPE_API_KEY"
    assert config.base_url_env == "DASHSCOPE_BASE_URL"
    assert config.run_name == "debug_50"
    assert (
        config.output_dir()
        == PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "pilot"
        / "2wikimultihopqa"
        / "debug_50"
    )
    assert (
        config.clean_trace_path
        == PROJECT_ROOT
        / "outputs"
        / "baseline"
        / "2wikimultihopqa"
        / "debug_50_traces.jsonl"
    )
    assert (
        config.entity_guarded_trace_path
        == PROJECT_ROOT
        / "outputs"
        / "defense"
        / "logicguard_mvp"
        / "2wikimultihopqa"
        / "entity_swap_guarded_traces.jsonl"
    )
    assert config.include_recovered_context is False
    assert config.entity_recovered_trace_path is None


def test_generation_config_can_enable_recovered_context() -> None:
    config = GenerationPilotConfig.from_yaml(RECOVERY_CONFIG_PATH)

    assert config.run_name == "full_500_expanded_20_recovery"
    assert config.max_cases_per_attack == 20
    assert config.include_recovered_context is True
    assert (
        config.entity_recovered_trace_path
        == PROJECT_ROOT
        / "outputs"
        / "defense"
        / "logicguard_bridge_v2_natural_full_500"
        / "2wikimultihopqa"
        / "entity_swap_recovered_traces.jsonl"
    )
    assert config.output_dir() == (
        PROJECT_ROOT
        / "outputs"
        / "llm_generation"
        / "expanded_natural_bridge_v2_recovery"
        / "2wikimultihopqa"
        / "full_500_expanded_20_recovery"
    )


def test_context_variants_adds_recovered_only_when_enabled() -> None:
    case = GenerationCase(
        attack_type="entity_swap",
        query_id="q1",
        question="Question?",
        gold_answer="Gold",
        poisoned_answer="Poison",
        poisoned_doc_ids=["p1"],
        clean_doc_ids=["c1"],
        poisoned_doc_ids_in_context=["p1"],
        guarded_doc_ids=[],
        recovered_doc_ids=["c1", "c2"],
    )

    without_recovery = _context_variants_for_case(case, include_recovered_context=False)
    with_recovery = _context_variants_for_case(case, include_recovered_context=True)

    assert [variant[0] for variant in without_recovery] == [
        "clean",
        "poisoned",
        "guarded",
    ]
    assert [variant[0] for variant in with_recovery] == [
        "clean",
        "poisoned",
        "guarded",
        "recovered",
    ]
    assert with_recovery[-1] == ("recovered", ["c1", "c2"], "clean")


def test_build_context_blocks_truncates_and_labels_documents() -> None:
    documents = {
        "d1": CorpusDocument(doc_id="d1", title="Known Film", text="A" * 80),
        "d2": CorpusDocument(doc_id="d2", title="Known Person", text="B" * 80),
    }

    context = build_context_blocks(
        ["d1", "missing", "d2"], documents, max_docs=2, max_chars_per_doc=24
    )

    assert "[D1] doc_id=d1" in context
    assert "Title: Known Film" in context
    assert "A" * 24 in context
    assert "missing" not in context
    assert "[D2] doc_id=d2" in context


def test_build_qa_messages_instructs_model_to_use_only_context() -> None:
    messages = build_qa_messages(
        question="Who directed Known Film?",
        context="Document context",
    )

    assert messages[0]["role"] == "system"
    assert "only the provided context" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "Who directed Known Film?" in messages[1]["content"]
    assert "Document context" in messages[1]["content"]


def test_build_qa_messages_supports_evidence_compare_prompt_policy() -> None:
    messages = build_qa_messages(
        question="Which film has the older director, A or B?",
        context="Document context",
        prompt_policy="evidence_compare",
    )

    assert "check all numbered evidence blocks" in messages[0]["content"]
    assert "comparison questions" in messages[0]["content"]
    assert "return the item requested" in messages[0]["content"]
    assert "Which film has the older director, A or B?" in messages[1]["content"]


def test_classify_answer_detects_correct_poisoned_and_abstained_outputs() -> None:
    correct = classify_answer(
        "The answer is Gisela Elsner.",
        gold_answer="Gisela Elsner",
        poisoned_answer="Wrong Name",
    )
    poisoned = classify_answer(
        "Wrong Name", gold_answer="Gisela Elsner", poisoned_answer="Wrong Name"
    )
    abstained = classify_answer(
        "UNKNOWN", gold_answer="Gisela Elsner", poisoned_answer="Wrong Name"
    )
    chinese_abstained = classify_answer(
        "无法确定", gold_answer="Gisela Elsner", poisoned_answer="Wrong Name"
    )

    assert correct.is_correct is True
    assert correct.is_poisoned is False
    assert poisoned.is_correct is False
    assert poisoned.is_poisoned is True
    assert abstained.is_abstained is True
    assert chinese_abstained.is_abstained is True


def test_classify_answer_uses_word_boundaries_for_short_answers() -> None:
    classification = classify_answer(
        "UNKNOWN", gold_answer="no", poisoned_answer="London"
    )

    assert classification.is_correct is False
    assert classification.is_abstained is True


def test_openai_compatible_client_builds_chat_completion_request() -> None:
    captured: dict[str, object] = {}

    def fake_transport(
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return {
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": "Gisela Elsner"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        }

    client = OpenAICompatibleChatClient(
        base_url="https://example.test/compatible-mode/v1",
        api_key="secret-key",
        transport=fake_transport,
    )

    response = client.chat(
        model="qwen3.7-plus",
        messages=[{"role": "user", "content": "Question"}],
        temperature=0.0,
        max_tokens=64,
        timeout_seconds=30,
    )

    assert captured["url"] == "https://example.test/compatible-mode/v1/chat/completions"
    assert captured["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
    }
    assert captured["payload"] == {
        "model": "qwen3.7-plus",
        "messages": [{"role": "user", "content": "Question"}],
        "temperature": 0.0,
        "max_tokens": 64,
    }
    assert captured["timeout_seconds"] == 30
    assert response.content == "Gisela Elsner"
    assert json.loads(response.raw_json)["usage"]["total_tokens"] == 13


def test_answer_stage_candidate_filter_skips_boolean_answers_and_requires_poison_text() -> (
    None
):
    assert (
        is_answer_stage_candidate(
            gold_answer="no",
            poisoned_answer="London",
            poisoned_document_texts=["This text mentions London."],
        )
        is False
    )
    assert (
        is_answer_stage_candidate(
            gold_answer="London",
            poisoned_answer="Roman",
            poisoned_document_texts=["The corrupted document now says Roman."],
        )
        is True
    )
    assert (
        is_answer_stage_candidate(
            gold_answer="London",
            poisoned_answer="Roman",
            poisoned_document_texts=["The corrupted document omits the target answer."],
        )
        is False
    )
