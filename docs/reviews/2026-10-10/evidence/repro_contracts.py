"""Offline review probes; no provider calls or repository writes."""

import json

from logicguard.benchmark.attack_runner import execute_attempt
from logicguard.benchmark.execution_protocols import parse_poisonedrag_response
from logicguard.benchmark.trust_manifest import (
    build_trust_manifest,
    materialize_protected_snapshot,
)
from logicguard.benchmark.trusted_controls import (
    RetrievalBudget,
    audit_equal_information_contract,
    build_t1_context,
)
from logicguard.llm.provider import ChatResponse


class FakeClient:
    def __init__(self):
        self.responses = iter(
            [
                dict(
                    root_nodes=None,
                    middle_role=None,
                    leaf_role=None,
                    relation_templates=None,
                ),
                dict(
                    original_relation_pattern=None,
                    modified_middle_node=None,
                    target_relation=None,
                ),
                dict(direct_adv_texts=[], indirect_adv_texts=[], enhanced_texts=[]),
            ]
        )

    def chat(self, **kwargs):
        return ChatResponse(json.dumps(next(self.responses)), "{}", 1, 1, 2)


def hit(text, rank, group="same"):
    return dict(
        document_id=f"chunk-{rank}",
        source_group_id=group,
        title="Fixture",
        text=text,
        n_tokens=3,
        rank=rank,
    )


a1 = parse_poisonedrag_response('{"target_answer":null,"malicious_texts":[null]}')
assert a1 == {"target_answer": "None", "malicious_texts": ["None"]}
print("A1 null accepted:", a1)

a3 = execute_attempt(
    dict(
        attack_id="A3_gragpoison",
        dataset="toy",
        query_id="q",
        question="Who?",
        attack_seed="s",
    ),
    client=FakeClient(),
    model="fake",
    timeout_seconds=1,
)
assert a3["generation_valid"] is True
print(
    "A3 empty accepted:",
    {
        key: a3[key]
        for key in (
            "generation_valid",
            "phases_completed",
            "provider_calls_made",
            "error",
        )
    },
)

t1 = build_t1_context(
    query=dict(dataset="toy", query_id="q", question="Who?", backend="fixture"),
    live_hits=[],
    trusted_hits=[hit("Best evidence", 1), hit("Irrelevant evidence", 2)],
    budget=RetrievalBudget(3, 3, 3, 20, 2),
    coverage=1.0,
    manifest_sha256="fixture-manifest",
)
selected = t1["selected_sources"][0]
assert selected["text"] == "Irrelevant evidence" and selected["best_rank"] == 1
print(
    "T1 same-group selection:",
    {key: selected[key] for key in ("text", "rank", "best_rank")},
)

candidate = dict(
    t1,
    method_id="D6_logicguard",
    selected_sources=[hit("Extra source", 1, group="outside-pool")],
    budget={**t1["budget"], "max_context_tokens": 999},
)
audit = audit_equal_information_contract(reference_t1=t1, candidate_d6=candidate)
assert audit["passed"] is True
print("Altered sources/budget audit:", audit)
assert audit_equal_information_contract(reference_t1={}, candidate_d6={})["passed"]
print("Two empty rows pass audit: True")

clean = [dict(_id="d1", title="Fixture", text="Original", source_group_id="g1")]
manifest = build_trust_manifest(
    clean_documents=clean,
    dataset="toy",
    dataset_revision="fixture",
    assignment_seed="seed",
    coverage_levels=[1.0, 0.0],
)
snapshot = materialize_protected_snapshot(
    clean_documents=[{**clean[0], "text": "Poisoned"}],
    manifest=manifest,
    coverage=1.0,
)
assert snapshot[0]["text"] == "Poisoned"
print("Changed trusted text accepted:", snapshot)
