from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from logicguard.benchmark.dev60_launch import freeze
from logicguard.benchmark.request_cost_guard import (
    RequestCostGuard,
    RequestCostGuardError,
)
from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file, write_jsonl


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/benchmark/comparison_v1_2_dev60_launch.yaml"
OUTPUT = ROOT / "artifacts/benchmark/research_revision_v1_2/wp2/dev60_launch_v1"


def _guard_fixture(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    plan_path = tmp_path / "request_plan.jsonl"
    rows = [
        {
            "request_slot_id": "slot-1",
            "input_token_cap": 1000,
            "output_token_cap": 1000,
            "reserved_cost_cny": 0.01,
            "prompt_fingerprint": "prompt-1",
            "actual_prompt_binding": "fully_frozen",
            "depends_on_request_slot_id": None,
        },
        {
            "request_slot_id": "slot-2",
            "input_token_cap": 1000,
            "output_token_cap": 1000,
            "reserved_cost_cny": 0.01,
            "prompt_fingerprint": "prompt-2",
            "actual_prompt_binding": "fully_frozen",
            "depends_on_request_slot_id": "slot-1",
        },
    ]
    write_jsonl(plan_path, rows)
    manifest_path = tmp_path / "launch.json"
    atomic_write_json(
        manifest_path,
        {
            "launch_fingerprint": "frozen-launch",
            "limits": {"max_provider_calls": 2, "hard_cost_cap_cny": 0.02},
            "pricing": {
                "input_per_million_tokens_cny": 2.0,
                "output_per_million_tokens_cny": 8.0,
            },
            "artifacts": {
                "request_plan": {
                    "path": "request_plan.jsonl",
                    "sha256": sha256_file(plan_path),
                }
            },
        },
    )
    return manifest_path, tmp_path / "guard_state.json"


def test_dev60_launch_is_frozen_and_idempotent() -> None:
    before = {path.name: sha256_file(path) for path in OUTPUT.iterdir()}
    first = freeze(CONFIG)
    second = freeze(CONFIG)
    after = {path.name: sha256_file(path) for path in OUTPUT.iterdir()}

    assert first == second
    assert before == after
    assert first["unique_queries"] == 60
    assert first["attack_attempts"] == 180
    assert first["request_slots"] == 300
    assert first["calls_by_attack"] == {
        "A1_poisonedrag": 60,
        "A2_logicpoison": 60,
        "A3_gragpoison": 180,
    }
    assert first["worst_case_reserved_cost_cny"] == pytest.approx(8.68176)
    assert first["provider_calls_made"] == 0
    assert first["credentials_read"] is False
    assert first["paid_dispatch_allowed"] is False


def test_dev60_attempts_keep_fixed_denominators_and_shared_backend_seed() -> None:
    rows = load_jsonl(OUTPUT / "dev60_attack_attempts.jsonl")
    counts = Counter((row["dataset"], row["attack_id"]) for row in rows)
    assert set(counts.values()) == {20}
    assert all(row["fixed_attempted"] for row in rows)
    assert all(row["replacement_after_outcome"] is False for row in rows)
    assert all(len(row["backend_targets"]) == 2 for row in rows)
    forbidden = {"gold_answer", "support_doc_ids", "changed_support_doc_ids"}
    assert all(not (set(row) & forbidden) for row in rows)


def test_dev60_request_slots_and_manifest_are_self_consistent() -> None:
    plan = load_jsonl(OUTPUT / "dev60_request_plan.jsonl")
    manifest = json.loads(
        (OUTPUT / "dev60_launch_manifest.json").read_text(encoding="utf-8")
    )
    assert len({row["request_slot_id"] for row in plan}) == 300
    assert sum(row["input_token_cap"] for row in plan) == 1_530_000
    assert sum(row["output_token_cap"] for row in plan) == 702_720
    assert sum(row["reserved_cost_cny"] for row in plan) == pytest.approx(
        manifest["limits"]["hard_cost_cap_cny"]
    )
    assert manifest["request_cost_guard"]["runner_binding_complete"] is False
    assert manifest["paid_dispatch_allowed"] is False
    for artifact in manifest["artifacts"].values():
        path = ROOT / artifact["path"]
        assert sha256_file(path) == artifact["sha256"]


def test_guard_reserves_before_call_and_reconciles_actual_cost(tmp_path: Path) -> None:
    manifest, state = _guard_fixture(tmp_path)
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    reserved = guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    assert reserved["status"] == "in_flight"
    assert json.loads(state.read_text())["requests"]["slot-1"]["status"] == "in_flight"

    completed = guard.complete(
        "slot-1", prompt_tokens=10, completion_tokens=5, reasoning_tokens=0
    )
    assert completed["status"] == "complete"
    guard.reserve("slot-2", actual_prompt_fingerprint="prompt-2")
    summary = guard.summary()
    assert summary["known_catalog_cost_cny"] == pytest.approx(0.00006)
    assert summary["reserved_or_charged_cny"] == pytest.approx(0.01006)


def test_in_flight_or_unknown_usage_blocks_every_later_dispatch(
    tmp_path: Path,
) -> None:
    manifest, state = _guard_fixture(tmp_path)
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    resumed = RequestCostGuard(launch_manifest=manifest, state_path=state)
    with pytest.raises(RequestCostGuardError, match="unresolved request"):
        resumed.reserve("slot-2", actual_prompt_fingerprint="prompt-2")

    state.unlink()
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    with pytest.raises(RequestCostGuardError, match="nonnegative integer"):
        guard.complete("slot-1", prompt_tokens=None, completion_tokens=5)
    assert guard.summary()["status"] == "STOPPED_UNCERTAIN_REQUEST"
    with pytest.raises(RequestCostGuardError, match="unresolved request"):
        guard.reserve("slot-2", actual_prompt_fingerprint="prompt-2")


def test_provider_error_and_limit_violation_fail_closed_without_secrets(
    tmp_path: Path,
) -> None:
    manifest, state = _guard_fixture(tmp_path)
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    guard.provider_error("slot-1", error_type="TimeoutError")
    payload = state.read_text(encoding="utf-8")
    assert "TimeoutError" in payload
    assert "provider-secret-message" not in payload
    assert guard.summary()["status"] == "STOPPED_UNCERTAIN_REQUEST"

    state.unlink()
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    with pytest.raises(RequestCostGuardError, match="exceeded"):
        guard.complete(
            "slot-1", prompt_tokens=10, completion_tokens=5, reasoning_tokens=1
        )
    assert guard.summary()["status"] == "STOPPED_COST_VIOLATION"


def test_guard_skips_only_declared_downstream_failures(tmp_path: Path) -> None:
    manifest, state = _guard_fixture(tmp_path)
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    guard.complete("slot-1", prompt_tokens=10, completion_tokens=5)
    guard.invalidate_schema("slot-1", error_type="ValueError")
    guard.skip("slot-2", reason="attempt_generation_invalid")
    assert guard.summary()["status"] == "COMPLETE"
    assert guard.summary()["reserved_or_charged_cny"] == pytest.approx(0.00006)

    with pytest.raises(ValueError, match="unsupported skip reason"):
        guard.skip("slot-1", reason="observed_low_attack_success")


def test_guard_enforces_prompt_identity_and_phase_dependency(tmp_path: Path) -> None:
    manifest, state = _guard_fixture(tmp_path)
    guard = RequestCostGuard(launch_manifest=manifest, state_path=state)
    with pytest.raises(RequestCostGuardError, match="actual prompt"):
        guard.reserve("slot-1", actual_prompt_fingerprint="changed-prompt")
    with pytest.raises(RequestCostGuardError, match="dependency"):
        guard.reserve("slot-2", actual_prompt_fingerprint="prompt-2")
    assert guard.summary()["recorded_request_slots"] == 0
