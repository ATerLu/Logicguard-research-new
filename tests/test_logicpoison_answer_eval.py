from pathlib import Path

from logicguard.llm.run_logicpoison_answer_eval import (
    LogicPoisonAnswerCase,
    LogicPoisonAnswerEvalConfig,
    LogicPoisonAnswerResult,
    _context_variants_for_case,
    _select_answer_cases,
    _summarize_results,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_answer_stage4.yaml"


def test_logicpoison_answer_config_resolves_project_paths() -> None:
    config = LogicPoisonAnswerEvalConfig.from_yaml(CONFIG_PATH)

    assert config.dataset == "2wikimultihopqa"
    assert config.retriever == "naive_bm25"
    assert config.run_name == "stage4_pilot_3"
    assert config.models == ["qwen3.7-plus", "deepseek-v4-flash"]
    assert config.clean_data_root == PROJECT_ROOT / "data" / "logicpoison_official" / "clean"
    assert config.poisoned_data_root == PROJECT_ROOT / "data" / "logicpoison_official" / "poisoned"
    assert config.retrieval_root == PROJECT_ROOT / "outputs" / "retrieval" / "logicpoison_official"
    assert config.defense_root == PROJECT_ROOT / "outputs" / "defense" / "logicpoison_official"
    assert config.output_dir() == PROJECT_ROOT / "outputs" / "llm_generation" / "logicpoison_answer" / "2wikimultihopqa" / "stage4_pilot_3"
    assert config.context_variants == ["clean", "poisoned", "guarded", "recovered"]


def test_select_answer_cases_requires_answer_surface_loss_and_recovered_gold() -> None:
    query_integrity = {
        "q1": {
            "query_id": "q1",
            "query": "Question one?",
            "answer": "Gold One",
            "changed_support_doc_ids": ["g1"],
            "answer_surface_loss": True,
        },
        "q2": {
            "query_id": "q2",
            "query": "Question two?",
            "answer": "Gold Two",
            "changed_support_doc_ids": ["g2"],
            "answer_surface_loss": False,
        },
        "q3": {
            "query_id": "q3",
            "query": "Question three?",
            "answer": "Gold Three",
            "changed_support_doc_ids": ["g3"],
            "answer_surface_loss": True,
        },
    }
    clean_traces = {
        "q1": _trace("q1", "Question one?", "Gold One", ["g1", "c1"]),
        "q2": _trace("q2", "Question two?", "Gold Two", ["g2", "c2"]),
        "q3": _trace("q3", "Question three?", "Gold Three", ["c3"]),
    }
    poisoned_traces = {
        "q1": _trace("q1", "Question one?", "Gold One", ["g1", "p1"]),
        "q2": _trace("q2", "Question two?", "Gold Two", ["g2", "p2"]),
        "q3": _trace("q3", "Question three?", "Gold Three", ["p3"]),
    }
    guarded_traces = {
        "q1": _trace("q1", "Question one?", "Gold One", ["p1"]),
        "q2": _trace("q2", "Question two?", "Gold Two", ["p2"]),
        "q3": _trace("q3", "Question three?", "Gold Three", ["p3"]),
    }
    recovered_traces = {
        "q1": _trace("q1", "Question one?", "Gold One", ["g1", "c1"]),
        "q2": _trace("q2", "Question two?", "Gold Two", ["g2", "c2"]),
        "q3": _trace("q3", "Question three?", "Gold Three", ["c3"]),
    }

    cases = _select_answer_cases(
        query_integrity=query_integrity,
        clean_traces=clean_traces,
        poisoned_traces=poisoned_traces,
        guarded_traces=guarded_traces,
        recovered_traces=recovered_traces,
        top_k=10,
        max_cases=10,
        require_recovered_gold=True,
    )

    assert [case.query_id for case in cases] == ["q1"]
    assert cases[0].changed_gold_doc_ids == ["g1"]
    assert cases[0].poisoned_doc_ids == ["g1", "p1"]
    assert cases[0].recovered_doc_ids == ["g1", "c1"]


def test_context_variants_render_recovered_from_clean_corpus() -> None:
    case = LogicPoisonAnswerCase(
        query_id="q1",
        question="Question?",
        gold_answer="Gold",
        changed_gold_doc_ids=["g1"],
        clean_doc_ids=["g1", "c1"],
        poisoned_doc_ids=["g1", "p1"],
        guarded_doc_ids=["p1"],
        recovered_doc_ids=["g1", "c1"],
    )

    variants = _context_variants_for_case(case, requested_variants=["clean", "poisoned", "guarded", "recovered"])

    assert variants == [
        ("clean", ["g1", "c1"], "clean"),
        ("poisoned", ["g1", "p1"], "poisoned"),
        ("guarded", ["p1"], "poisoned"),
        ("recovered", ["g1", "c1"], "clean"),
    ]


def test_context_variants_can_select_recovered_only() -> None:
    case = LogicPoisonAnswerCase(
        query_id="q1",
        question="Question?",
        gold_answer="Gold",
        changed_gold_doc_ids=["g1"],
        clean_doc_ids=["g1", "c1"],
        poisoned_doc_ids=["g1", "p1"],
        guarded_doc_ids=["p1"],
        recovered_doc_ids=["g1", "c1"],
    )

    variants = _context_variants_for_case(case, requested_variants=["recovered"])

    assert variants == [("recovered", ["g1", "c1"], "clean")]


def test_summarize_answer_results_counts_answer_outcomes() -> None:
    results = [
        _result(model="m1", context_variant="clean", is_correct=True),
        _result(model="m1", context_variant="poisoned", is_correct=False),
        _result(model="m1", context_variant="guarded", is_abstained=True),
        _result(model="m1", context_variant="recovered", is_correct=True, total_tokens=7),
        _result(model="m1", context_variant="recovered", error="provider failed"),
    ]

    summary = _summarize_results(results)

    assert summary[("m1", "clean")] == {
        "calls": 1,
        "correct": 1,
        "incorrect": 0,
        "abstained": 0,
        "errors": 0,
        "total_tokens": 0,
    }
    assert summary[("m1", "poisoned")]["incorrect"] == 1
    assert summary[("m1", "guarded")]["abstained"] == 1
    assert summary[("m1", "recovered")]["calls"] == 2
    assert summary[("m1", "recovered")]["correct"] == 1
    assert summary[("m1", "recovered")]["errors"] == 1
    assert summary[("m1", "recovered")]["total_tokens"] == 7


def _trace(query_id: str, question: str, answer: str, doc_ids: list[str]) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": question,
        "answer": answer,
        "gold_doc_ids": [doc_id for doc_id in doc_ids if doc_id.startswith("g")],
        "candidates": [{"doc_id": doc_id, "title": doc_id, "new_rank": index + 1} for index, doc_id in enumerate(doc_ids)],
    }


def _result(
    *,
    model: str,
    context_variant: str,
    is_correct: bool = False,
    is_abstained: bool = False,
    total_tokens: int | None = None,
    error: str | None = None,
) -> LogicPoisonAnswerResult:
    return LogicPoisonAnswerResult(
        model=model,
        context_variant=context_variant,
        query_id="q1",
        question="Question?",
        gold_answer="Gold",
        generated_answer="" if error else "Gold",
        is_correct=is_correct,
        is_abstained=is_abstained,
        is_incorrect=not is_correct and not is_abstained and error is None,
        latency_seconds=0.1,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=total_tokens,
        error=error,
    )
