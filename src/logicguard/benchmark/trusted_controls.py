"""Equal-information T0/T1 context controls for comparison-v1.2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from logicguard.benchmark.trust_manifest import assert_no_evaluator_fields
from logicguard.core.run_state import fingerprint_json

_HIT_FIELDS = {"document_id", "source_group_id", "title", "text", "n_tokens", "rank"}
VerificationStatus = Literal[
    "verified_safe", "verified_risky", "unverifiable", "not_assessed"
]


@dataclass(frozen=True, slots=True)
class RetrievalBudget:
    """Shared upper bounds for T1 and the future D6 comparison."""

    live_top_k: int
    trusted_top_k: int
    final_source_limit: int
    max_context_tokens: int
    max_retrieval_calls: int
    max_model_calls: int = 1
    rrf_k: int = 60

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_retrieval_calls < 2:
            raise ValueError(
                "equal-information T1/D6 budget needs at least two retrieval calls"
            )

    @property
    def fingerprint(self) -> str:
        self.validate()
        return fingerprint_json(asdict(self))


def build_t0_context(
    *,
    query: dict[str, Any],
    trusted_hits: list[dict[str, Any]],
    budget: RetrievalBudget,
    coverage: float,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Build trusted-pool-only retrieval without any LogicGuard decisions."""

    _validate_query(query)
    budget.validate()
    trusted = _normalize_hits(trusted_hits, pool="trusted")[: budget.trusted_top_k]
    selected, used_tokens = _select_budgeted(trusted, budget)
    return _context_row(
        query=query,
        method_id="T0_trusted_pool_only_retrieval",
        coverage=coverage,
        manifest_sha256=manifest_sha256,
        budget=budget,
        selected=selected,
        used_tokens=used_tokens,
        retrieval_calls_used=1,
        verification_status="not_assessed" if selected else "unverifiable",
        candidate_pool_fingerprint=fingerprint_json({"trusted": trusted}),
    )


def build_t1_context(
    *,
    query: dict[str, Any],
    live_hits: list[dict[str, Any]],
    trusted_hits: list[dict[str, Any]],
    budget: RetrievalBudget,
    coverage: float,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Build ordinary live+trusted RRF augmentation without verification logic."""

    _validate_query(query)
    budget.validate()
    live = _normalize_hits(live_hits, pool="live")[: budget.live_top_k]
    trusted = _normalize_hits(trusted_hits, pool="trusted")[: budget.trusted_top_k]
    fused = _rrf_merge(live=live, trusted=trusted, rrf_k=budget.rrf_k)
    selected, used_tokens = _select_budgeted(fused, budget)
    return _context_row(
        query=query,
        method_id="T1_ordinary_trusted_augmentation",
        coverage=coverage,
        manifest_sha256=manifest_sha256,
        budget=budget,
        selected=selected,
        used_tokens=used_tokens,
        retrieval_calls_used=2,
        verification_status="not_assessed" if selected else "unverifiable",
        candidate_pool_fingerprint=fingerprint_json({"live": live, "trusted": trusted}),
    )


def _validate_query(query: dict[str, Any]) -> None:
    allowed = {"dataset", "query_id", "question", "backend"}
    assert_no_evaluator_fields(query, location="query")
    if set(query) != allowed or any(
        not isinstance(query[name], str) or not query[name].strip() for name in allowed
    ):
        raise ValueError(
            "query must contain only nonempty dataset/query_id/question/backend"
        )


def _normalize_hits(hits: list[dict[str, Any]], *, pool: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, hit in enumerate(hits):
        assert_no_evaluator_fields(hit, location=f"{pool}_hits[{index}]")
        if set(hit) != _HIT_FIELDS:
            raise ValueError(f"retrieval hit has invalid fields: {sorted(set(hit))}")
        if any(
            not isinstance(hit[name], str) or not hit[name].strip()
            for name in ("document_id", "source_group_id", "text")
        ):
            raise ValueError(
                "retrieval hit identifiers and text must be nonempty strings"
            )
        if not isinstance(hit["title"], str):
            raise ValueError("retrieval hit title must be a string")
        if type(hit["rank"]) is not int or hit["rank"] <= 0:
            raise ValueError("retrieval rank must be a positive integer")
        if type(hit["n_tokens"]) is not int or hit["n_tokens"] <= 0:
            raise ValueError("retrieval token count must be a positive integer")
        normalized.append({**hit, "pool": pool})
    normalized.sort(key=lambda row: (row["rank"], row["source_group_id"]))
    return normalized


def _rrf_merge(
    *, live: list[dict[str, Any]], trusted: list[dict[str, Any]], rrf_k: int
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for hit in live + trusted:
        group_id = hit["source_group_id"]
        entry = groups.setdefault(
            group_id,
            {"score": 0.0, "pools": [], "best_rank": hit["rank"], "hit": hit},
        )
        entry["score"] += 1.0 / (rrf_k + hit["rank"])
        entry["pools"].append(hit["pool"])
        entry["best_rank"] = min(entry["best_rank"], hit["rank"])
        if hit["pool"] == "trusted":
            entry["hit"] = hit
    output: list[dict[str, Any]] = []
    for group_id, entry in groups.items():
        hit = dict(entry["hit"])
        hit["rrf_score"] = round(entry["score"], 12)
        hit["contributing_pools"] = sorted(set(entry["pools"]))
        hit["best_rank"] = entry["best_rank"]
        output.append(hit)
    output.sort(
        key=lambda row: (-row["rrf_score"], row["best_rank"], row["source_group_id"])
    )
    return output


def _select_budgeted(
    hits: list[dict[str, Any]], budget: RetrievalBudget
) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    used_tokens = 0
    for hit in hits:
        if len(selected) >= budget.final_source_limit:
            break
        if hit["source_group_id"] in seen_groups:
            continue
        if used_tokens + hit["n_tokens"] > budget.max_context_tokens:
            continue
        selected.append(hit)
        seen_groups.add(hit["source_group_id"])
        used_tokens += hit["n_tokens"]
    return selected, used_tokens


def _context_row(
    *,
    query: dict[str, Any],
    method_id: str,
    coverage: float,
    manifest_sha256: str,
    budget: RetrievalBudget,
    selected: list[dict[str, Any]],
    used_tokens: int,
    retrieval_calls_used: int,
    verification_status: VerificationStatus,
    candidate_pool_fingerprint: str,
) -> dict[str, Any]:
    information_contract = {
        "dataset": query["dataset"],
        "query_id": query["query_id"],
        "backend": query["backend"],
        "trust_coverage": float(coverage),
        "budget_sha256": budget.fingerprint,
        "trust_manifest_sha256": manifest_sha256,
        "candidate_pool_sha256": candidate_pool_fingerprint,
    }
    return {
        **query,
        "method_id": method_id,
        "trust_coverage": float(coverage),
        "status": "CONTEXT_READY" if selected else "UNVERIFIABLE",
        "verification_status": verification_status,
        "selected_sources": selected,
        "selected_source_count": len(selected),
        "context_tokens_used": used_tokens,
        "retrieval_calls_used": retrieval_calls_used,
        "budget": asdict(budget),
        "budget_sha256": budget.fingerprint,
        "trust_manifest_sha256": manifest_sha256,
        "candidate_pool_sha256": candidate_pool_fingerprint,
        "equal_information_contract_sha256": fingerprint_json(information_contract),
        "model_calls_used": 0,
        "provider_calls_made": 0,
    }


def audit_equal_information_contract(
    *, reference_t1: dict[str, Any], candidate_d6: dict[str, Any]
) -> dict[str, Any]:
    """Check that a future D6 row did not gain pool or budget information."""

    identity_fields = ("dataset", "query_id", "backend", "trust_coverage")
    checks = {
        "same_case": all(
            reference_t1.get(name) == candidate_d6.get(name) for name in identity_fields
        ),
        "same_budget": reference_t1.get("budget_sha256")
        == candidate_d6.get("budget_sha256"),
        "same_trust_manifest": reference_t1.get("trust_manifest_sha256")
        == candidate_d6.get("trust_manifest_sha256"),
        "same_candidate_pool": reference_t1.get("candidate_pool_sha256")
        == candidate_d6.get("candidate_pool_sha256"),
        "same_information_contract": reference_t1.get(
            "equal_information_contract_sha256"
        )
        == candidate_d6.get("equal_information_contract_sha256"),
    }
    return {"checks": checks, "passed": all(checks.values())}
