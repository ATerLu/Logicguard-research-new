from __future__ import annotations

from pathlib import Path

import pytest

from logicguard.benchmark.attack_runner import (
    _planned_cost_cap,
    build_dry_run_plan,
    execute_attempt,
    run,
)
from logicguard.llm.provider import ChatResponse


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "benchmark" / "comparison_v1_1_attack_runner_dryrun.yaml"


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def chat(self, **_: object) -> ChatResponse:
        self.calls += 1
        content = self.responses.pop(0)
        return ChatResponse(content, "{}", 10, 5, 15)


def _row(attack_id: str) -> dict[str, str]:
    return {
        "dataset": "hotpotqa",
        "attack_id": attack_id,
        "query_id": "q1",
        "question": "Who directed the film?",
        "attack_seed": "seed",
    }


def test_full_validation_dry_run_plans_exact_calls_without_credentials(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    summary = run(CONFIG)
    assert summary["unique_attack_attempts"] == 600
    assert summary["planned_provider_calls"] == 1200
    assert summary["calls_by_attack"] == {
        "A1_poisonedrag": 300,
        "A3_gragpoison": 900,
    }
    assert summary["provider_calls_made"] == 0
    assert summary["credentials_read"] is False


def test_a1_execute_attempt_is_one_call_and_schema_checked() -> None:
    client = FakeClient(['{"target_answer":"Person X","malicious_texts":["Evidence"]}'])
    result = execute_attempt(
        _row("A1_poisonedrag"),
        client=client,
        model="test-model",
        timeout_seconds=1,
    )
    assert result["generation_valid"] is True
    assert result["provider_calls_made"] == 1
    assert result["phases_completed"] == 1
    assert result["token_usage"]["total_tokens"] == 15
    assert client.calls == 1


def test_a3_execute_attempt_is_three_bounded_calls_with_no_retry() -> None:
    client = FakeClient(
        [
            '{"root_nodes":["x"],"middle_role":"m","leaf_role":"l",'
            '"relation_templates":["r"]}',
            '{"original_relation_pattern":"r","modified_middle_node":"y",'
            '"target_relation":"t"}',
            '{"direct_adv_texts":["a"],"indirect_adv_texts":["b"],'
            '"enhanced_texts":["c"]}',
        ]
    )
    result = execute_attempt(
        _row("A3_gragpoison"),
        client=client,
        model="test-model",
        timeout_seconds=1,
    )
    assert result["generation_valid"] is True
    assert result["provider_calls_made"] == 3
    assert result["phases_completed"] == 3
    assert result["token_usage"]["total_tokens"] == 45
    assert client.calls == 3

    bad = FakeClient(["not-json"])
    failed = execute_attempt(
        _row("A3_gragpoison"),
        client=bad,
        model="test-model",
        timeout_seconds=1,
    )
    assert failed["generation_valid"] is False
    assert failed["provider_calls_made"] == 1
    assert bad.calls == 1


def test_a2_execute_attempt_is_one_call_and_strictly_parsed() -> None:
    client = FakeClient(['[{"hop":1,"entity":"the film director","type":"BRIDGE"}]'])
    result = execute_attempt(
        _row("A2_logicpoison"),
        client=client,
        model="test-model",
        timeout_seconds=1,
    )
    assert result["generation_valid"] is True
    assert result["provider_calls_made"] == 1
    assert result["output"]["entities"][0]["type"] == "BRIDGE"
    assert client.calls == 1


def test_paid_pilot_declared_cap_covers_every_planned_call() -> None:
    rows = [_row("A1_poisonedrag"), _row("A3_gragpoison")]
    plan = build_dry_run_plan(rows, document_count=1)
    config = {
        "pricing": {
            "input_per_million_tokens_cny": 2.0,
            "output_per_million_tokens_cny": 8.0,
            "per_attack_token_caps": {
                "A1_poisonedrag": {
                    "input_per_call": 6000,
                    "output_per_call": 1600,
                },
                "A3_gragpoison": {
                    "input_per_call": 6000,
                    "output_per_call": 3200,
                },
            },
        }
    }
    assert len(plan) == 4
    assert _planned_cost_cap(plan, config) == pytest.approx(0.1376)
