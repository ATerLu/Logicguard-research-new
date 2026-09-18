import json
from pathlib import Path

import pytest

from logicguard.benchmark.attack_qualification import (
    audit_gragpoison_artifact,
    audit_poisonedrag_hotpotqa_asset,
    calculate_need_to_keep,
)

ROOT = Path(__file__).parents[1]


def test_official_a1_asset_has_frozen_100_by_5_mechanism_anchor() -> None:
    payload = json.loads(
        (
            ROOT
            / "vendor/upstream/PoisonedRAG/results/adv_targeted_results/hotpotqa.json"
        ).read_text(encoding="utf-8")
    )

    summary, rows = audit_poisonedrag_hotpotqa_asset(payload)

    assert summary["status"] == "PAPER_ASSET_MECHANISM_ANCHOR_PASSED"
    assert summary["generated_adversarial_texts"] == 500
    assert summary["word_count"]["max"] == 34
    assert summary["incorrect_target_surface_misses"] == 40
    assert len(rows) == 100
    assert not summary["backend_effect_qualified"]


def test_a1_rejects_same_correct_and_incorrect_answer() -> None:
    payload = {
        "q": {
            "id": "q",
            "question": "Question?",
            "correct answer": "same",
            "incorrect answer": " same ",
            "adv_texts": ["text"] * 5,
        }
    }
    with pytest.raises(ValueError, match="must differ"):
        audit_poisonedrag_hotpotqa_asset(payload, expected_records=1)


def test_upstream_index_selection_preserves_overlap_caveat() -> None:
    assert calculate_need_to_keep(15, 7, 10) == [
        *range(0, 10),
        *range(7, 17),
        *range(14, 24),
    ]


def test_official_a3_artifact_reproduces_upstream_selection_counts() -> None:
    payload = json.loads(
        (
            ROOT / "vendor/upstream/GraphRAG_Under_Fire/datasets/"
            "misuque_3_black_shuffle_0601/test0_corpus.json"
        ).read_text(encoding="utf-8")
    )

    summary, rows = audit_gragpoison_artifact(payload)

    assert summary["raw_generated_texts"] == {
        "direct": 750,
        "indirect": 370,
        "enhanced": 435,
    }
    assert summary["selected_text_occurrences"] == {
        "direct": 654,
        "indirect": 370,
        "enhanced": 437,
    }
    assert summary["selected_occurrences_total"] == 1461
    assert summary["selected_unique_texts_total"] == 1341
    assert summary["adjacent_relation_reuses"] == 16
    assert summary["nonadjacent_repeated_relation_keys_not_merged"] == 1
    assert summary["overlapping_selected_index_occurrences"] == 90
    assert summary["selected_word_count"]["max"] == 72
    assert summary["configured_word_budget_passed_posthoc"]
    assert not summary["word_budget_enforced_during_generation_by_upstream"]
    assert len(rows) == 74
