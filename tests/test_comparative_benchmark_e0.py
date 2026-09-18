from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from logicguard.benchmark.contracts import (
    ATTACK_CONTRACTS,
    BACKEND_CONTRACTS,
    DEFENSE_CONTRACTS,
    validate_attack_instance,
    validate_contract_registry,
)
from logicguard.benchmark.readiness import FORBIDDEN_ATTACKER_FIELDS, run
from logicguard.benchmark.schemas import AttackInstance, BenchmarkQuery, FunnelCounts
from logicguard.core.io import load_jsonl, sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "configs" / "benchmark" / "comparison_v1_1_e0.yaml"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts" / "benchmark" / "e0"


def test_contract_registries_are_complete_and_oracle_is_isolated() -> None:
    for registry in (ATTACK_CONTRACTS, BACKEND_CONTRACTS, DEFENSE_CONTRACTS):
        validate_contract_registry(registry)

    assert {contract.adapter_id for contract in ATTACK_CONTRACTS} == {
        "A1_poisonedrag",
        "A2_logicpoison",
        "A3_gragpoison",
        "A4_badrag",
    }
    assert {contract.adapter_id for contract in BACKEND_CONTRACTS} == {
        "S1_microsoft_graphrag",
        "S2_lightrag",
    }
    assert {contract.adapter_id for contract in DEFENSE_CONTRACTS} == {
        "D0_no_defense",
        "D1_query_paraphrase",
        "D2_ppl_pti",
        "D3_ragdefender",
        "D4_hog_grag",
        "D5_logicguard_stage43_45",
        "D6_logicguard_full",
        "D7_oracle_clean_recovery",
    }
    gold_readers = [
        contract.adapter_id
        for contract in DEFENSE_CONTRACTS
        if contract.gold_access_allowed
    ]
    assert gold_readers == ["D7_oracle_clean_recovery"]


def test_attacker_query_schema_cannot_carry_evaluator_gold() -> None:
    query = BenchmarkQuery(
        dataset="musique",
        query_id="2hop__1_2",
        question="Which answer follows from two facts?",
        split="development",
        stratum="2hop",
    )
    assert not FORBIDDEN_ATTACKER_FIELDS.intersection(query.to_json_dict())
    with pytest.raises(TypeError):
        BenchmarkQuery(  # type: ignore[call-arg]
            dataset="musique",
            query_id="2hop__1_2",
            question="Question",
            split="development",
            stratum="2hop",
            gold_answer="leak",
        )


def test_attack_endpoint_semantics_do_not_collapse_to_one_asr() -> None:
    poisonedrag = AttackInstance(
        attack_id="A1_poisonedrag",
        instance_id="p-1",
        dataset="hotpotqa",
        query_id="q-1",
        threat_track="wrong_answer",
        endpoint_family="targeted_wrong_answer",
        fidelity="paper_native",
        malicious_document_ids=("adv-1",),
        target_answer="wrong target",
    )
    validate_attack_instance(poisonedrag)

    logicpoison = AttackInstance(
        attack_id="A2_logicpoison",
        instance_id="lp-1",
        dataset="musique",
        query_id="q-2",
        threat_track="logical",
        endpoint_family="clean_correct_attack_flip",
        fidelity="paper_native",
        malicious_document_ids=("changed-1",),
    )
    validate_attack_instance(logicpoison)

    bad_logicpoison = AttackInstance(
        attack_id="A2_logicpoison",
        instance_id="lp-2",
        dataset="musique",
        query_id="q-3",
        threat_track="logical",
        endpoint_family="clean_correct_attack_flip",
        fidelity="dataset_port",
        malicious_document_ids=("changed-2",),
        target_answer="must not be used",
    )
    with pytest.raises(ValueError, match="clean-correct"):
        validate_attack_instance(bad_logicpoison)

    badrag = AttackInstance(
        attack_id="A4_badrag",
        instance_id="br-1",
        dataset="hotpotqa",
        query_id="q-4",
        threat_track="backdoor",
        endpoint_family="trigger_payload_success",
        fidelity="reimplementation",
        malicious_document_ids=("trigger-doc",),
        trigger="semantic trigger",
    )
    validate_attack_instance(badrag)


def test_funnel_enforces_attempted_denominator_and_monotonicity() -> None:
    funnel = FunnelCounts(100, 90, 80, 80, 70, 60, 50, 40, 40, 10)
    assert funnel.rate("threat_native_success") == pytest.approx(0.10)
    assert funnel.rate("threat_native_success", "prompt_exposed") == pytest.approx(0.25)

    with pytest.raises(ValueError, match="non-monotonic"):
        FunnelCounts(100, 90, 80, 80, 70, 60, 50, 40, 41, 10)


def test_e0_build_is_deterministic_and_passes_e0_a() -> None:
    first = run(CONFIG)
    watched = [
        OUTPUT_ROOT / "comparison_v1_1_asset_manifest.json",
        OUTPUT_ROOT / "comparison_v1_1_split_audit.json",
        OUTPUT_ROOT / "comparison_v1_1_overlap_audit.json",
        OUTPUT_ROOT / "comparison_v1_1_adapter_contracts.json",
        OUTPUT_ROOT / "comparison_v1_1_fidelity_smoke.json",
    ]
    first_hashes = {path.name: sha256_file(path) for path in watched}
    second = run(CONFIG)
    second_hashes = {path.name: sha256_file(path) for path in watched}

    assert first == second
    assert first_hashes == second_hashes
    assert first["e0_a_passed"] is True
    assert first["e0_b_passed"] is True
    assert first["overall_status"] == "E0_PASSED__E1_IMPLEMENTATION_GATED"
    assert first["paid_api_calls"] == 0
    assert first["gates"]["backend_runtime_imports"] is True
    assert first["gates"]["external_defense_source_smoke"] is True
    assert first["gates"]["adapter_fixture_fidelity"] is True
    assert (
        first["backend_runtime_smoke"]["checks"]["lightrag"]["details"]["mode"]
        == "hybrid"
    )


@pytest.mark.parametrize("dataset", ["hotpotqa", "musique", "2wikimultihopqa"])
def test_frozen_split_is_exact_disjoint_and_attacker_safe(dataset: str) -> None:
    run(CONFIG)
    public = load_jsonl(OUTPUT_ROOT / "splits" / f"{dataset}_attacker_safe.jsonl")
    evaluator = load_jsonl(
        OUTPUT_ROOT / "splits" / "evaluator_only" / f"{dataset}.jsonl"
    )
    counts = {
        split: sum(row["split"] == split for row in public)
        for split in ("development", "validation", "locked_test")
    }
    assert counts == {"development": 100, "validation": 100, "locked_test": 300}
    assert len({row["query_id"] for row in public}) == 500
    assert all(not FORBIDDEN_ATTACKER_FIELDS.intersection(row) for row in public)
    assert all("gold_answer" in row and "support_doc_ids" in row for row in evaluator)
    assert [row["query_id"] for row in public] == [row["query_id"] for row in evaluator]


def test_official_overlap_fixtures_are_contract_sized_not_result_samples() -> None:
    run(CONFIG)
    audit = json.loads(
        (OUTPUT_ROOT / "comparison_v1_1_overlap_audit.json").read_text(encoding="utf-8")
    )
    poisonedrag = load_jsonl(
        OUTPUT_ROOT / "fixtures" / "poisonedrag_hotpotqa_overlap.jsonl"
    )
    gragpoison = load_jsonl(
        OUTPUT_ROOT / "fixtures" / "gragpoison_musique_overlap.jsonl"
    )

    assert audit["poisonedrag_hotpotqa"]["official_instance_count"] == 100
    assert len(poisonedrag) == 6
    assert {row["malicious_document_count"] for row in poisonedrag} == {5}
    assert audit["gragpoison_musique"]["official_question_count"] == 67
    assert len(gragpoison) == 14


def test_legacy_logicpoison_is_audited_but_not_promoted_to_official_poison() -> None:
    readiness = run(CONFIG)
    audit = json.loads(
        (OUTPUT_ROOT / "comparison_v1_1_legacy_logicpoison_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert readiness["gates"]["legacy_logicpoison_audit"] is True
    assert audit["paper_faithful_anchor_available"] is False
    assert all(row["classification"] == "legacy_adapted" for row in audit["datasets"])
    assert all(row["changed_document_count"] > 0 for row in audit["datasets"])
    assert all(
        all(row["immutable_evaluator_files_equal"].values())
        for row in audit["datasets"]
    )


def test_cell_matrix_keeps_e2_locked_and_badrag_separate() -> None:
    run(CONFIG)
    rows = list(
        csv.DictReader(
            (PROJECT_ROOT / "docs" / "对比实验预注册表_v1.1.csv").open(
                encoding="utf-8-sig", newline=""
            )
        )
    )
    assert len(rows) == 216
    assert all(row["status"] != "ready_for_e2" for row in rows if row["stage"] == "E2")
    assert all(
        row["track"] == "backdoor" for row in rows if row["attack"] == "A4_badrag"
    )
