"""Shared deterministic metrics used by experiment analyses."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from typing import Any, TypeVar

T = TypeVar("T", bound=Hashable)


def ratio(numerator: int | float, denominator: int | float) -> float:
    """Return a safe floating-point ratio."""

    return float(numerator / denominator) if denominator else 0.0


def mean(values: Iterable[int | float]) -> float:
    """Return the arithmetic mean, or zero for an empty iterable."""

    materialized = list(values)
    return float(sum(materialized) / len(materialized)) if materialized else 0.0


def mean_defined(values: Iterable[int | float | None]) -> float:
    """Return the mean of non-null values, or zero when none are defined."""

    return mean(float(value) for value in values if value is not None)


def dedupe(values: Iterable[T]) -> list[T]:
    """Remove duplicates while preserving first-seen order."""

    return list(dict.fromkeys(values))


def dedupe_strings(values: Iterable[Any]) -> list[str]:
    """Normalize non-empty values to strings and deduplicate in input order."""

    return list(dict.fromkeys(str(value) for value in values if value))
