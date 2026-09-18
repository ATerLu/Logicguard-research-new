"""Endpoint-separated summaries for comparison-v1.2; never hide unknown outcomes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def outcome_rate(outcomes: Sequence[bool | None]) -> dict[str, Any]:
    """Use the fixed planned denominator, with bounds when outcomes are unknown."""
    if any(value is not None and type(value) is not bool for value in outcomes):
        raise TypeError("outcomes must be bool or None")
    total = len(outcomes)
    successes = sum(value is True for value in outcomes)
    unknown = sum(value is None for value in outcomes)
    return {
        "planned": total,
        "successes": successes,
        "unknown": unknown,
        "rate": successes / total if total and not unknown else None,
        "bounds": [successes / total, (successes + unknown) / total] if total else None,
    }


def clean_correct_flip(
    clean_correct: Sequence[bool | None], attacked_correct: Sequence[bool | None]
) -> dict[str, Any]:
    if len(clean_correct) != len(attacked_correct):
        raise ValueError("clean/attacked records must be paired")
    outcome_rate(clean_correct)
    outcome_rate(attacked_correct)
    flips = [
        None if attacked is None else not attacked
        for clean, attacked in zip(clean_correct, attacked_correct, strict=True)
        if clean is True
    ]
    return {
        "fixed_attempted": len(clean_correct),
        "clean_unknown": sum(value is None for value in clean_correct),
        "clean_incorrect": sum(value is False for value in clean_correct),
        "clean_correct_subset": outcome_rate(flips),
        "population_complete": all(value is not None for value in clean_correct),
    }


def paired_attack_effect(
    baseline_success: Sequence[bool | None], defense_success: Sequence[bool | None]
) -> dict[str, Any]:
    if len(baseline_success) != len(defense_success):
        raise ValueError("baseline/defense records must be paired")
    outcome_rate(baseline_success)
    outcome_rate(defense_success)
    pairs = list(zip(baseline_success, defense_success, strict=True))
    mitigated = sum(left is True and right is False for left, right in pairs)
    induced = sum(left is False and right is True for left, right in pairs)
    unknown = sum(left is None or right is None for left, right in pairs)
    total = len(pairs)
    return {
        "planned_pairs": total,
        "mitigated": mitigated,
        "induced": induced,
        "unknown_pairs": unknown,
        "net_reduction": (mitigated - induced) / total
        if total and not unknown
        else None,
        "net_reduction_bounds": [
            (mitigated - induced - unknown) / total,
            (mitigated - induced + unknown) / total,
        ]
        if total
        else None,
    }
