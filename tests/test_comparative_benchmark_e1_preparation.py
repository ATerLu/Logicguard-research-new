from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from logicguard.benchmark.e1_preparation import run
from logicguard.benchmark.execution_protocols import (
    BoundedAttackRequest,
    build_gragpoison_blackbox_request,
    build_logicpoison_query_request,
    build_poisonedrag_request,
    parse_logicpoison_query_response,
    parse_poisonedrag_response,
    validate_gragpoison_phase,
)
from logicguard.core.io import load_jsonl, sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "benchmark" / "comparison_v1_1_e1_preparation.yaml"
OUTPUT = ROOT / "artifacts" / "benchmark" / "e1_preparation"


def test_attack_requests_are_gold_free_bounded_and_strictly_parsed() -> None:
    request = build_poisonedrag_request(
        query_id="q1", question="Who directed the film?", document_count=1
    )
    assert request.max_calls == 1
    assert "correct answer:" not in request.user_prompt.lower()
    parsed = parse_poisonedrag_response(
        '{"target_answer":"Person X","malicious_texts":["Synthetic evidence"]}'
    )
    assert parsed["target_answer"] == "Person X"
    with pytest.raises(ValueError, match="wrong malicious_texts count"):
        parse_poisonedrag_response('{"target_answer":"X","malicious_texts":["a","b"]}')
    with pytest.raises(ValueError, match="forbidden"):
        BoundedAttackRequest("A1", "q", "", "gold_answer: leak", 10, 0.0)


def test_gragpoison_has_three_one_call_question_only_phases() -> None:
    for phase in ("decompose", "select_relation", "generate_evidence"):
        request = build_gragpoison_blackbox_request(
            query_id="q1", question="Question text", phase=phase
        )
        assert request.max_calls == 1
        assert "gold_answer" not in request.user_prompt
    result = validate_gragpoison_phase(
        '{"direct_adv_texts":["a"],"indirect_adv_texts":["b"],"enhanced_texts":["c"]}',
        phase="generate_evidence",
    )
    assert result["enhanced_texts"] == ["c"]


def test_logicpoison_query_stage_is_gold_free_single_call_and_strict() -> None:
    request = build_logicpoison_query_request(
        query_id="q1", question="Where was the director born?"
    )
    assert request.max_calls == 1
    assert "gold_answer" not in request.user_prompt
    rows = parse_logicpoison_query_response(
        '[{"hop":1,"entity":"the director","type":"BRIDGE"}]'
    )
    assert rows == [{"hop": 1, "entity": "the director", "type": "BRIDGE"}]
    with pytest.raises(ValueError, match="exactly"):
        parse_logicpoison_query_response(
            '[{"hop":1,"entity":"x","type":"BRIDGE","answer":"y"}]'
        )


def test_e1_preparation_is_deterministic_paired_and_makes_no_paid_calls() -> None:
    first = run(CONFIG)
    watched = [
        OUTPUT / "comparison_v1_1_attack_inputs.jsonl",
        OUTPUT / "development_pilot" / "comparison_v1_1_attack_audit.json",
        OUTPUT / "logicpoison_development_pilot" / "comparison_v1_1_audit.json",
        OUTPUT / "logicpoison_cost_control_pilot" / "comparison_v1_1_audit.json",
        OUTPUT / "comparison_v1_1_indexing_pilot_audit.json",
        OUTPUT / "comparison_v1_1_execution_plan.json",
        OUTPUT / "comparison_v1_1_logicpoison_runtime_smoke.json",
        OUTPUT / "comparison_v1_1_badrag_development_smoke.json",
        OUTPUT / "comparison_v1_1_cost_forecast.json",
        OUTPUT / "comparison_v1_1_readiness.json",
    ]
    hashes = {path.name: sha256_file(path) for path in watched}
    second = run(CONFIG)
    assert first == second
    assert hashes == {path.name: sha256_file(path) for path in watched}
    assert first["attack_input_rows"] == 1800
    assert first["development_attack_input_rows"] == 2
    assert first["logicpoison_development_attack_input_rows"] == 1
    assert first["logicpoison_cost_control_attack_input_rows"] == 1
    assert len(first["cells"]) == 18
    assert first["paid_api_calls"] == 102
    assert first["attack_generations"] == 4
    assert first["development_indices"] == 4
    assert first["actual_catalog_cost_cny"] == pytest.approx(0.403953)
    assert first["gates"]["development_A1_A3_generation_pilot"] is True
    assert first["gates"]["A2_gold_free_staging_runner_dryrun"] is True
    assert first["gates"]["A2_default_thinking_cost_cap_passed"] is False
    assert first["gates"]["A2_nonthinking_generation_and_cost_control"] is True
    assert first["gates"]["bounded_one_and_ten_document_indexing_pilots"] is True
    assert first["gates"]["full_scale_indexing_hard_cap_frozen"] is False
    assert first["paid_e1_launch_allowed"] is False

    rows = load_jsonl(OUTPUT / "comparison_v1_1_attack_inputs.jsonl")
    forbidden = {
        "answer",
        "gold_answer",
        "support_doc_ids",
        "changed_support_doc_ids",
    }
    assert all(not forbidden.intersection(row) for row in rows)
    grouped: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    seeds: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        key = (row["dataset"], row["attack_id"], row["query_id"])
        grouped[key].add(row["backend"])
        seeds[key].add(row["attack_seed"])
    assert all(
        value == {"S1_microsoft_graphrag", "S2_lightrag"} for value in grouped.values()
    )
    assert all(len(value) == 1 for value in seeds.values())

    development_rows = load_jsonl(
        OUTPUT / "comparison_v1_1_development_attack_inputs.jsonl"
    )
    assert {(row["attack_id"], row["dataset"]) for row in development_rows} == {
        ("A1_poisonedrag", "hotpotqa"),
        ("A3_gragpoison", "musique"),
    }
    assert all(row["split"] == "development" for row in development_rows)
    logicpoison_development_rows = load_jsonl(
        OUTPUT / "comparison_v1_1_logicpoison_development_attack_inputs.jsonl"
    )
    assert len(logicpoison_development_rows) == 1
    assert logicpoison_development_rows[0]["attack_id"] == "A2_logicpoison"
    assert logicpoison_development_rows[0]["dataset"] == "2wikimultihopqa"
    logicpoison_control_rows = load_jsonl(
        OUTPUT / "comparison_v1_1_logicpoison_cost_control_attack_inputs.jsonl"
    )
    assert len(logicpoison_control_rows) == 1
    assert (
        logicpoison_control_rows[0]["query_id"]
        != logicpoison_development_rows[0]["query_id"]
    )


def test_source_and_cost_gates_refuse_overclaiming() -> None:
    run(CONFIG)
    plan = json.loads(
        (OUTPUT / "comparison_v1_1_execution_plan.json").read_text(encoding="utf-8")
    )
    assert all(item["revision_match"] for item in plan["source_checks"].values())
    assert all(
        not item["uses_forbidden_external_repo"]
        for item in plan["source_checks"].values()
    )
    assert isinstance(plan["environment_checks"]["en_core_web_trf_installed"], bool)
    assert plan["environment_checks"]["isolated_logicpoison_runtime"]["passed"] is True
    assert plan["logicpoison_staging_runner_dryrun"]["planned_provider_calls"] == 300

    smoke = json.loads(
        (OUTPUT / "comparison_v1_1_badrag_development_smoke.json").read_text(
            encoding="utf-8"
        )
    )
    assert smoke["gates"]["trigger_retrieval"] is False
    assert smoke["gates"]["false_activation"] is True
    assert smoke["gates"]["payload_success"] is False
    assert smoke["validation_eligible"] is False

    cost = json.loads(
        (OUTPUT / "comparison_v1_1_cost_forecast.json").read_text(encoding="utf-8")
    )
    assert cost["known_components_conservative_subtotal_cny"] > 0
    assert cost["overall_hard_cap_cny"] is None
    assert cost["paid_e1_launch_allowed"] is False
    assert len(cost["unbounded_components"]) == 1
    assert len(cost["calibration_only_components"]) == 2

    indexing = json.loads(
        (OUTPUT / "comparison_v1_1_indexing_pilot_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert indexing["status"] == "PASSED"
    assert indexing["development_indices_completed"] == 4
    assert indexing["provider_calls"] == 96
    assert indexing["catalog_cost_estimate_cny"] == pytest.approx(0.324525)
    assert indexing["corpus_document_counts"] == {
        "hotpotqa": 9811,
        "musique": 11656,
        "2wikimultihopqa": 6119,
    }
    assert indexing["documents_per_backend"] == 110344
    assert indexing["separate_indices_per_backend"] == 12
    assert indexing["full_scale_projection"]["is_hard_cap"] is False
    assert (
        indexing["full_scale_projection"]["eligible_to_freeze_overall_hard_cap"]
        is False
    )

    audit = json.loads(
        (OUTPUT / "development_pilot" / "comparison_v1_1_attack_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["status"] == "PASSED"
    assert audit["provider_calls_made"] == 4
    assert audit["a1_target_gold_collision_count"] == 0
    assert audit["provider_calls_this_audit"] == 0

    logicpoison_audit = json.loads(
        (
            OUTPUT / "logicpoison_development_pilot" / "comparison_v1_1_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert logicpoison_audit["status"] == "GENERATION_PASSED__COST_CAP_FAILED"
    assert logicpoison_audit["generation_gate_passed"] is True
    assert logicpoison_audit["cost_cap_gate_passed"] is False

    control_audit = json.loads(
        (
            OUTPUT / "logicpoison_cost_control_pilot" / "comparison_v1_1_audit.json"
        ).read_text(encoding="utf-8")
    )
    assert control_audit["status"] == "PASSED"
    assert control_audit["token_usage"]["reasoning_tokens"] == 0
    assert control_audit["actual_catalog_cost_cny"] < control_audit["hard_cost_cap_cny"]
