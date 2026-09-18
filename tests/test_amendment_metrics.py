import pytest

from logicguard.benchmark.amendment_metrics import (
    clean_correct_flip,
    outcome_rate,
    paired_attack_effect,
)


def test_infrastructure_unknown_does_not_become_attack_failure() -> None:
    result = outcome_rate([True, False, None, False])
    assert result["rate"] is None
    assert result["bounds"] == [0.25, 0.5]
    assert outcome_rate([])["rate"] is None
    with pytest.raises(TypeError):
        outcome_rate([1])


def test_flip_denominator_excludes_clean_wrong_but_reports_clean_unknown() -> None:
    result = clean_correct_flip([True, False, True, None], [False, False, None, False])
    assert result["fixed_attempted"] == 4
    assert result["clean_correct_subset"]["planned"] == 2
    assert result["clean_correct_subset"]["bounds"] == [0.5, 1.0]
    assert result["population_complete"] is False


def test_paired_effect_counts_attacks_induced_by_defense() -> None:
    result = paired_attack_effect(
        [True, False, True, False], [False, True, False, False]
    )
    assert result["mitigated"] == 2
    assert result["induced"] == 1
    assert result["net_reduction"] == 0.25
    with pytest.raises(ValueError):
        paired_attack_effect([True], [])
