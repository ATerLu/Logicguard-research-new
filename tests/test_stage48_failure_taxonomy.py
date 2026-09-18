from __future__ import annotations

from logicguard.evaluation.stage48_failure_taxonomy import (
    build_failure_rows,
    classify_attack_validity,
    classify_prompt_propagation,
)


def _inventory_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset": "toy",
        "query_id": "q1",
        "attack_family": "candidate_collision",
        "generation_valid": True,
        "non_oracle_generation": True,
        "target_is_wrong": True,
        "wrong_collision_candidate": True,
        "evaluation_valid": True,
        "invalid_reason": "",
        "selected_for_reindex": True,
    }
    row.update(overrides)
    return row


def _exposure_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset": "toy",
        "query_id": "q1",
        "attack_family": "candidate_collision",
        "index_document_included": True,
        "index_text_unit_included": True,
        "retrieved": True,
        "source_rank": 2,
        "prompt_source_exposed": True,
        "prompt_target_exposed": True,
    }
    row.update(overrides)
    return row


def test_attack_validity_separates_missing_target_and_gold_candidate() -> None:
    missing_target = classify_attack_validity(
        _inventory_row(
            generation_valid=False,
            evaluation_valid=False,
            invalid_reason="missing_malicious_answer",
        )
    )
    gold_candidate = classify_attack_validity(
        _inventory_row(
            wrong_collision_candidate=False,
            evaluation_valid=False,
        )
    )

    assert (missing_target.stage, missing_target.category) == (
        "generation",
        "missing_malicious_answer",
    )
    assert (gold_candidate.stage, gold_candidate.category) == (
        "evaluation",
        "collision_candidate_is_gold_support",
    )


def test_attack_validity_rejects_gold_target_and_oracle_access() -> None:
    gold_target = classify_attack_validity(
        _inventory_row(target_is_wrong=False, evaluation_valid=False)
    )
    oracle = classify_attack_validity(
        _inventory_row(non_oracle_generation=False, evaluation_valid=False)
    )

    assert gold_target.category == "malicious_target_matches_gold"
    assert oracle.category == "oracle_label_access"


def test_prompt_taxonomy_separates_top_k_and_character_truncation() -> None:
    top_k = classify_prompt_propagation(
        _exposure_row(
            source_rank=14,
            prompt_source_exposed=False,
            prompt_target_exposed=False,
        ),
        prompt_source_limit=12,
    )
    character_truncation = classify_prompt_propagation(
        _exposure_row(prompt_target_exposed=False),
        prompt_source_limit=12,
    )

    assert top_k.category == "retrieved_beyond_prompt_source_limit"
    assert character_truncation.category == "prompt_source_exposed_target_truncated"


def test_prompt_target_without_attack_source_is_not_counted_as_exposure() -> None:
    label = classify_prompt_propagation(
        _exposure_row(
            prompt_source_exposed=False,
            prompt_target_exposed=True,
        ),
        prompt_source_limit=12,
    )

    assert label.category == "target_surface_without_attack_source"


def test_failure_rows_preserve_fixed_quota_and_underpowered_cells() -> None:
    inventory = [
        _inventory_row(query_id="q1", selected_for_reindex=True),
        _inventory_row(query_id="q2", selected_for_reindex=False),
        _inventory_row(
            query_id="q3",
            attack_family="natural_bridge",
            selected_for_reindex=False,
        ),
    ]
    exposure = [_exposure_row(query_id="q1")]

    rows = build_failure_rows(
        inventory_rows=inventory,
        exposure_rows=exposure,
        required_evaluation_valid_per_cell=2,
        prompt_source_limit=12,
    )
    categories = {str(row["query_id"]): row["failure_category"] for row in rows}

    assert categories == {
        "q1": "prompt_source_and_target_exposed",
        "q2": "fixed_quota_not_selected",
        "q3": "cell_below_reindex_minimum",
    }
