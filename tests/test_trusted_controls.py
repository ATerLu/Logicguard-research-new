import pytest

from logicguard.benchmark.trusted_controls import (
    RetrievalBudget,
    audit_equal_information_contract,
    build_t0_context,
    build_t1_context,
)


def _query() -> dict[str, str]:
    return {
        "dataset": "toy",
        "query_id": "q1",
        "question": "Who wrote Alpha?",
        "backend": "S1_microsoft_graphrag",
    }


def _hit(group: str, text: str, rank: int, tokens: int = 5) -> dict:
    return {
        "document_id": group,
        "source_group_id": group,
        "title": group.upper(),
        "text": text,
        "n_tokens": tokens,
        "rank": rank,
    }


def _budget() -> RetrievalBudget:
    return RetrievalBudget(3, 3, 3, 20, 2)


def test_t0_is_trusted_only_and_zero_coverage_is_unverifiable() -> None:
    ready = build_t0_context(
        query=_query(),
        trusted_hits=[_hit("clean", "clean evidence", 1)],
        budget=_budget(),
        coverage=0.2,
        manifest_sha256="manifest",
    )
    empty = build_t0_context(
        query=_query(),
        trusted_hits=[],
        budget=_budget(),
        coverage=0.0,
        manifest_sha256="manifest",
    )

    assert {row["pool"] for row in ready["selected_sources"]} == {"trusted"}
    assert ready["verification_status"] == "not_assessed"
    assert empty["status"] == "UNVERIFIABLE"
    assert empty["verification_status"] == "unverifiable"


def test_t1_uses_clean_trusted_copy_on_collision_and_obeys_equal_budget() -> None:
    row = build_t1_context(
        query=_query(),
        live_hits=[
            _hit("same", "poisoned live copy", 1),
            _hit("live", "other live evidence", 2),
        ],
        trusted_hits=[_hit("same", "protected clean copy", 1)],
        budget=_budget(),
        coverage=0.2,
        manifest_sha256="manifest",
    )

    same = next(
        hit for hit in row["selected_sources"] if hit["source_group_id"] == "same"
    )
    assert same["text"] == "protected clean copy"
    assert same["contributing_pools"] == ["live", "trusted"]
    assert row["budget_sha256"] == _budget().fingerprint
    assert row["retrieval_calls_used"] <= row["budget"]["max_retrieval_calls"]
    assert row["context_tokens_used"] <= row["budget"]["max_context_tokens"]


def test_t1_rejects_gold_or_outcome_leakage() -> None:
    leaked = _hit("x", "x", 1)
    leaked["attack_success"] = True
    with pytest.raises(ValueError, match="evaluator-only"):
        build_t1_context(
            query=_query(),
            live_hits=[leaked],
            trusted_hits=[],
            budget=_budget(),
            coverage=0.0,
            manifest_sha256="manifest",
        )


def test_future_d6_must_reuse_t1_information_contract() -> None:
    reference = build_t1_context(
        query=_query(),
        live_hits=[_hit("live", "live", 1)],
        trusted_hits=[_hit("clean", "clean", 1)],
        budget=_budget(),
        coverage=0.2,
        manifest_sha256="manifest",
    )
    matching = dict(reference, method_id="D6_logicguard")
    mismatch = dict(matching, candidate_pool_sha256="different")

    assert audit_equal_information_contract(
        reference_t1=reference, candidate_d6=matching
    )["passed"]
    assert not audit_equal_information_contract(
        reference_t1=reference, candidate_d6=mismatch
    )["passed"]
