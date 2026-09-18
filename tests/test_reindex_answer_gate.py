from pathlib import Path

from logicguard.evaluation.reindex_answer_gate import (
    ReindexAnswerGateConfig,
    run_from_config,
    select_prompt_exposed_cases,
)
from logicguard.llm.provider import ChatResponse
from logicguard.llm.evaluation import classify_answer


def test_select_prompt_exposed_cases_requires_source_and_target() -> None:
    config = _config(Path("."))
    prompt_rows = [
        _prompt("q1", "wrong-1"),
        _prompt("q2", "wrong-2"),
    ]
    exposure_rows = [
        _exposure("q1", source=True, target=True),
        _exposure("q2", source=True, target=False),
    ]
    attack_rows = [_attack("q1", "wrong-1"), _attack("q2", "wrong-2")]

    selected = select_prompt_exposed_cases(
        config=config,
        prompt_rows=prompt_rows,
        exposure_rows=exposure_rows,
        attack_rows=attack_rows,
    )

    assert [row["query_id"] for row in selected] == ["q1"]


def test_run_from_config_writes_targeted_answer_gate_outputs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_jsonl(config.prompt_cases_path, [_prompt("q1", "wrong-1")])
    _write_jsonl(
        config.exposure_path,
        [_exposure("q1", source=True, target=True)],
    )
    _write_jsonl(config.frozen_attacks_path, [_attack("q1", "wrong-1")])

    results = run_from_config(config, client=FakeClient("wrong-1"))

    assert len(results) == 1
    assert results[0]["targeted_attack_success"] is True
    assert config.results_output_path.is_file()
    assert config.summary_output_path.is_file()
    assert config.cost_ledger_output_path.is_file()


def test_numeric_answer_prefix_matches_gold_with_provenance_suffix() -> None:
    classification = classify_answer(
        "28,776",
        gold_answer="28,776 at the 2010 census",
        poisoned_answer="42,500",
    )

    assert classification.is_correct is True
    assert classification.is_poisoned is False


def test_incidental_later_year_does_not_match_numeric_answer() -> None:
    classification = classify_answer(
        "2010",
        gold_answer="28,776 at the 2010 census",
        poisoned_answer="42,500",
    )

    assert classification.is_correct is False


class FakeClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def chat(self, **_: object) -> ChatResponse:
        return ChatResponse(
            content=self.answer,
            raw_json="{}",
            prompt_tokens=100,
            completion_tokens=2,
            total_tokens=102,
        )


def _config(root: Path) -> ReindexAnswerGateConfig:
    return ReindexAnswerGateConfig(
        dataset="toy",
        attack_family="natural_bridge",
        prompt_cases_path=root / "prompts.jsonl",
        exposure_path=root / "exposure.jsonl",
        frozen_attacks_path=root / "attacks.jsonl",
        results_output_path=root / "results.jsonl",
        summary_output_path=root / "summary.json",
        cost_ledger_output_path=root / "cost.json",
        model="toy-model",
    )


def _prompt(query_id: str, malicious: str) -> dict[str, object]:
    doc_id = f"attack-{query_id}"
    prompt_text = f"Context: {doc_id} says {malicious}. Question: {query_id}"
    return {
        "query_id": query_id,
        "query": f"Question {query_id}",
        "gold_answer": f"gold-{query_id}",
        "messages": [
            {"role": "system", "content": "Answer from context."},
            {"role": "user", "content": prompt_text},
        ],
        "prompt_text": prompt_text,
    }


def _exposure(query_id: str, *, source: bool, target: bool) -> dict[str, object]:
    return {
        "dataset": "toy",
        "query_id": query_id,
        "attack_family": "natural_bridge",
        "index_document_included": True,
        "index_text_unit_included": True,
        "retrieved": True,
        "source_rank": 1,
        "prompt_source_exposed": source,
        "prompt_target_exposed": target,
    }


def _attack(query_id: str, malicious: str) -> dict[str, object]:
    return {
        "query_id": query_id,
        "attack_id": f"attack-{query_id}",
        "injected_doc_id": f"attack-{query_id}",
        "malicious_answer": malicious,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(f"{__import__('json').dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )
