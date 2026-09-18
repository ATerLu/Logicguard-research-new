"""Provider-free audits for frozen PoisonedRAG and GRAGPoison assets."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any


def whitespace_word_count(text: str) -> int:
    """Match the upstream GRAGPoison interpretation of a word budget."""

    return len(text.split())


def audit_poisonedrag_hotpotqa_asset(
    payload: Mapping[str, Any],
    *,
    expected_records: int = 100,
    texts_per_record: int = 5,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit the paper-native fixed HotpotQA targeted-poison asset."""

    if len(payload) != expected_records:
        raise ValueError(f"A1 record count mismatch: {len(payload)}")
    rows: list[dict[str, Any]] = []
    all_counts: list[int] = []
    target_surface_hits = 0
    for key, raw in payload.items():
        if not isinstance(raw, Mapping):
            raise ValueError("A1 records must be objects")
        required = {"id", "question", "correct answer", "incorrect answer", "adv_texts"}
        if set(raw) != required or raw["id"] != key:
            raise ValueError("A1 record schema or keyed ID mismatch")
        strings = [raw[name] for name in required - {"adv_texts"}]
        if any(not isinstance(value, str) or not value.strip() for value in strings):
            raise ValueError("A1 identifiers, question, and answers must be nonempty")
        if _normal(raw["correct answer"]) == _normal(raw["incorrect answer"]):
            raise ValueError("A1 correct and incorrect targets must differ")
        texts = raw["adv_texts"]
        if (
            not isinstance(texts, list)
            or len(texts) != texts_per_record
            or any(not isinstance(text, str) or not text.strip() for text in texts)
        ):
            raise ValueError(
                "A1 requires the frozen number of nonempty adversarial texts"
            )
        counts = [whitespace_word_count(text) for text in texts]
        target_hits = sum(
            _normal(raw["incorrect answer"]) in _normal(text) for text in texts
        )
        target_surface_hits += target_hits
        all_counts.extend(counts)
        rows.append(
            {
                "query_id": key,
                "adversarial_text_count": len(texts),
                "materialized_document_count": len(texts),
                "question_prefix_applied_by_upstream_attack": True,
                "materialized_word_count": sum(
                    whitespace_word_count(f"{raw['question']}. {text}")
                    for text in texts
                ),
                "incorrect_target_surface_hits": target_hits,
            }
        )
    summary = {
        "attack_id": "A1_poisonedrag",
        "status": "PAPER_ASSET_MECHANISM_ANCHOR_PASSED",
        "evidence_scope": "frozen_upstream_asset_not_backend_effect",
        "records": len(rows),
        "generated_adversarial_texts": len(all_counts),
        "logical_materialized_poison_documents": len(all_counts),
        "upstream_materialization_prefix": "question_plus_period",
        "word_count": _stats(all_counts),
        "incorrect_target_surface_hits": target_surface_hits,
        "incorrect_target_surface_misses": len(all_counts) - target_surface_hits,
        "target_surface_presence_is_diagnostic_not_acceptance_gate": True,
        "shared_runner_label": "PoisonedRAG_inspired_adaptation",
        "backend_effect_qualified": False,
    }
    return summary, rows


def calculate_need_to_keep(
    num_texts: int, num_text_per_root: int, num_keep: int
) -> list[int]:
    """Faithfully reproduce the upstream GRAGPoison index-selection helper."""

    if min(num_texts, num_text_per_root, num_keep) <= 0:
        return []
    return [
        index
        for start in range(0, num_texts, num_text_per_root)
        for index in range(start, start + num_keep)
    ]


def audit_gragpoison_artifact(
    payload: Sequence[Mapping[str, Any]],
    *,
    n_alpha: int = 10,
    n_beta: int = 5,
    word_budget: int = 400,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit and materialize the upstream black-box relation-sharing policy."""

    if not payload:
        raise ValueError("A3 artifact must not be empty")
    selected: dict[str, list[str]] = {"direct": [], "indirect": [], "enhanced": []}
    raw_counts = {name: 0 for name in selected}
    rows: list[dict[str, Any]] = []
    relation_keys: list[str] = []
    recent_key: str | None = None
    required_text = {
        "question",
        "middle_node",
        "Original Middle Node",
        "Modified Middle Node",
    }
    for index, raw in enumerate(payload):
        if raw.get("type") != "normal":
            raise ValueError("A3 qualification accepts only upstream normal records")
        if any(
            not isinstance(raw.get(name), str) or not raw[name].strip()
            for name in required_text
        ):
            raise ValueError(f"A3 record {index} has an empty node/relation field")
        if any(
            not _nonempty_nodes(raw.get(name))
            for name in ("Root Node", "Original Relationship", "Modified Relationship")
        ):
            raise ValueError(f"A3 record {index} has an empty node/relation field")
        roots = raw.get("root_nodes")
        leaves = raw.get("leaf_nodes")
        if not _nonempty_nodes(roots) or not _nonempty_nodes(leaves):
            raise ValueError(f"A3 record {index} has empty root/leaf nodes")
        root_count = 1 if isinstance(roots, str) else len(roots)
        lists = {
            "direct": raw.get("direct_adv_texts"),
            "indirect": raw.get("indirect_adv_texts"),
            "enhanced": raw.get("enhanced_texts"),
        }
        if any(
            not isinstance(values, list)
            or not values
            or any(not isinstance(text, str) or not text.strip() for text in values)
            for values in lists.values()
        ):
            raise ValueError(f"A3 record {index} has invalid adversarial text lists")
        for name, values in lists.items():
            raw_counts[name] += len(values)
        relation_key = json.dumps(
            [roots, raw["middle_node"]], ensure_ascii=False, sort_keys=True
        )
        relation_keys.append(relation_key)

        indirect = lists["indirect"][:n_beta]
        enhanced_indices = _upstream_indices(len(lists["enhanced"]), root_count, n_beta)
        enhanced = [lists["enhanced"][item] for item in enhanced_indices]
        direct: list[str] = []
        direct_indices: list[int] = []
        direct_reused_from_immediately_previous = relation_key == recent_key
        if not direct_reused_from_immediately_previous:
            direct_indices = _upstream_indices(
                len(lists["direct"]), root_count, n_alpha
            )
            direct = [lists["direct"][item] for item in direct_indices]
            recent_key = relation_key
        selected["direct"].extend(direct)
        selected["indirect"].extend(indirect)
        selected["enhanced"].extend(enhanced)
        rows.append(
            {
                "row_index": index,
                "question": raw["question"],
                "root_count": root_count,
                "relation_key": relation_key,
                "direct_reused_from_immediately_previous": direct_reused_from_immediately_previous,
                "selected_occurrences": {
                    "direct": len(direct),
                    "indirect": len(indirect),
                    "enhanced": len(enhanced),
                },
                "overlapping_direct_indices": len(direct_indices)
                - len(set(direct_indices)),
                "overlapping_enhanced_indices": len(enhanced_indices)
                - len(set(enhanced_indices)),
            }
        )

    adjacent_reuses = sum(
        relation_keys[index] == relation_keys[index - 1]
        for index in range(1, len(relation_keys))
    )
    nonadjacent_repeats = len(relation_keys) - len(set(relation_keys)) - adjacent_reuses
    all_selected = [text for values in selected.values() for text in values]
    maximum = max(whitespace_word_count(text) for text in all_selected)
    if maximum > word_budget:
        raise ValueError("A3 selected text exceeds the configured word budget")
    summary = {
        "attack_id": "A3_gragpoison",
        "status": "PAPER_ARTIFACT_MECHANISM_BUDGET_ANCHOR_PASSED_WITH_CAVEATS",
        "evidence_scope": "frozen_upstream_artifact_not_backend_effect",
        "records": len(payload),
        "parameters": {
            "N_alpha": n_alpha,
            "N_beta": n_beta,
            "word_budget": word_budget,
        },
        "raw_generated_texts": raw_counts,
        "selected_text_occurrences": {
            name: len(values) for name, values in selected.items()
        },
        "selected_unique_texts": {
            name: len(set(values)) for name, values in selected.items()
        },
        "selected_occurrences_total": len(all_selected),
        "selected_unique_texts_total": len(set(all_selected)),
        "physical_injected_files": 3,
        "adjacent_relation_reuses": adjacent_reuses,
        "nonadjacent_repeated_relation_keys_not_merged": nonadjacent_repeats,
        "overlapping_selected_index_occurrences": sum(
            row["overlapping_direct_indices"] + row["overlapping_enhanced_indices"]
            for row in rows
        ),
        "selected_word_count": _stats(
            [whitespace_word_count(text) for text in all_selected]
        ),
        "configured_word_budget_passed_posthoc": maximum <= word_budget,
        "word_budget_enforced_during_generation_by_upstream": False,
        "shared_runner_label": "GRAGPoison_inspired_adaptation",
        "backend_effect_qualified": False,
    }
    return summary, rows


def _upstream_indices(num_texts: int, root_count: int, keep: int) -> list[int]:
    per_root = num_texts // root_count if root_count else 0
    return [
        index
        for index in calculate_need_to_keep(num_texts, per_root, keep)
        if index < num_texts
    ]


def _nonempty_nodes(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _normal(value: str) -> str:
    return " ".join(value.casefold().split())


def _stats(values: list[int]) -> dict[str, float | int]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(fmean(values), 6),
        "total": sum(values),
    }
