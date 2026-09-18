from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.core.run_state import fingerprint_json
from logicguard.evaluation.gate_a_expansion import build_inventory_rows


def test_gate_a_inventory_enforces_collision_and_fixed_selection() -> None:
    samples = {
        f"2hop__q{i}": NormalizedSample(
            query_id=f"2hop__q{i}",
            query=f"query {i}",
            answer="gold",
            support_doc_ids=["support"],
            support_docs=[CorpusDocument("support", "Support", "text")],
        )
        for i in range(3)
    }
    records = []
    batch_by_key = {}
    for query_id in samples:
        for family in ("natural_bridge", "low_drift", "candidate_collision"):
            candidate = "support" if query_id == "2hop__q0" else "other"
            records.append(
                {
                    "query_id": query_id,
                    "attack_family": family,
                    "attack_id": f"{family}-{query_id}",
                    "valid": True,
                    "malicious_answer": "wrong",
                    "collision_candidate_doc_id": candidate,
                    "attacker_used_gold_answer": False,
                    "attacker_used_support_ids": False,
                    "attacker_used_changed_labels": False,
                }
            )
            batch_by_key[(query_id, family)] = "batch"

    rows = build_inventory_rows(
        dataset="toy",
        samples_by_id=samples,
        attack_records=records,
        batch_by_key=batch_by_key,
        target_per_family=2,
    )

    collisions = [row for row in rows if row["attack_family"] == "candidate_collision"]
    natural = [row for row in rows if row["attack_family"] == "natural_bridge"]
    assert sum(row["evaluation_valid"] for row in collisions) == 2
    assert sum(row["selected_for_reindex"] for row in collisions) == 2
    assert sum(row["evaluation_valid"] for row in natural) == 3
    assert sum(row["selected_for_reindex"] for row in natural) == 2


def test_gate_a_selection_uses_the_same_fingerprint_as_reindexing() -> None:
    samples = {
        f"2hop__q{i}": NormalizedSample(
            query_id=f"2hop__q{i}",
            query=f"query {i}",
            answer="gold",
            support_doc_ids=["support"],
            support_docs=[CorpusDocument("support", "Support", "text")],
        )
        for i in range(8)
    }
    records = [
        {
            "query_id": query_id,
            "attack_family": "natural_bridge",
            "attack_id": f"natural_bridge-{query_id}",
            "valid": True,
            "malicious_answer": "wrong",
            "attacker_used_gold_answer": False,
            "attacker_used_support_ids": False,
            "attacker_used_changed_labels": False,
        }
        for query_id in samples
    ]

    rows = build_inventory_rows(
        dataset="toy",
        samples_by_id=samples,
        attack_records=records,
        batch_by_key={(query_id, "natural_bridge"): "batch" for query_id in samples},
        target_per_family=3,
    )

    selected = {str(row["query_id"]) for row in rows if row["selected_for_reindex"]}
    expected = set(sorted(samples, key=fingerprint_json)[:3])
    assert selected == expected
