"""Read-only LogicGuard probes. Fake clients only; writes stay under /tmp."""

import json
import tempfile
from pathlib import Path

import yaml

from logicguard.benchmark.adapters import normalize_context_trace, normalize_defense_trace
from logicguard.benchmark.attack_runner import execute_attempt, run
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
from logicguard.benchmark.request_cost_guard import RequestCostGuard
from logicguard.core.io import append_jsonl, atomic_write_json, load_jsonl, sha256_file
from logicguard.core.run_state import load_checkpoint_rows


class FakeClient:
    def __init__(self, crash_second=False, unknown=False, excessive=False, responses=None):
        self.calls = 0
        self.crash_second = crash_second
        self.unknown = unknown
        self.excessive = excessive
        self.responses = iter(responses) if responses is not None else None

    def chat(self, **kwargs):
        self.calls += 1
        if self.crash_second and self.calls == 2:
            raise KeyboardInterrupt("synthetic process interruption")
        usage = None if self.unknown else (1_000_000 if self.excessive else 1)
        content = (
            json.dumps(next(self.responses))
            if self.responses is not None
            else '{"target_answer":"X","malicious_texts":["Evidence X"]}'
        )
        return ChatResponse(content, "{}", usage, usage, usage)


def fixture_config(root):
    (root / "pyproject.toml").write_text("")
    rows = [
        dict(dataset="toy", attack_id="A1_poisonedrag", query_id=f"q{i}",
             question="Who?", attack_seed="s", split="development")
        for i in range(2)
    ]
    (root / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    cfg = dict(
        attacks=["A1_poisonedrag"], datasets=["toy"], split="development",
        input_manifest="inputs.jsonl",
        outputs=dict(results="results.jsonl", summary="summary.json", request_plan="plan.jsonl"),
        matched_documents_per_target=1, run_mode="execute", benchmark_version="fixture",
        model="fake", timeout_seconds=1,
        pricing=dict(input_per_million_tokens_cny=2, output_per_million_tokens_cny=8,
                     hard_cost_cap_cny=.1,
                     per_attack_token_caps={"A1_poisonedrag": dict(input_per_call=100, output_per_call=1600)}),
    )
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def hit(text, rank, group="same"):
    return dict(document_id=f"chunk-{rank}", source_group_id=group,
                title="Fixture", text=text, n_tokens=3, rank=rank)


results = []

a1 = parse_poisonedrag_response('{"target_answer":null,"malicious_texts":[null]}')
assert a1 == {"target_answer": "None", "malicious_texts": ["None"]}
results.append(dict(id="a1_null_schema", reproduced=True, actual=a1,
                    source="src/logicguard/benchmark/execution_protocols.py:80-90"))

a3 = execute_attempt(
    dict(attack_id="A3_gragpoison", dataset="toy", query_id="q", question="Who?", attack_seed="s"),
    client=FakeClient(responses=[
        dict(root_nodes=None, middle_role=None, leaf_role=None, relation_templates=None),
        dict(original_relation_pattern=None, modified_middle_node=None, target_relation=None),
        dict(direct_adv_texts=[], indirect_adv_texts=[], enhanced_texts=[]),
    ]), model="fake", timeout_seconds=1,
)
assert a3["generation_valid"] is True
results.append(dict(id="a3_empty_schema", reproduced=True,
                    actual={k: a3[k] for k in ("generation_valid", "phases_completed", "provider_calls_made", "error")},
                    source="src/logicguard/benchmark/execution_protocols.py:209-229"))

t1 = build_t1_context(
    query=dict(dataset="toy", query_id="q", question="Who?", backend="fixture"), live_hits=[],
    trusted_hits=[hit("Best evidence", 1), hit("Irrelevant evidence", 2)],
    budget=RetrievalBudget(3, 3, 3, 20, 2), coverage=1.0, manifest_sha256="fixture-manifest",
)
selected = t1["selected_sources"][0]
assert selected["text"] == "Irrelevant evidence" and selected["best_rank"] == 1
results.append(dict(id="t1_lower_rank_overwrite", reproduced=True,
                    actual={k: selected[k] for k in ("text", "rank", "best_rank")},
                    source="src/logicguard/benchmark/trusted_controls.py:142-152"))

candidate = dict(t1, method_id="D6_logicguard",
                 selected_sources=[hit("Extra source", 1, group="outside-pool")],
                 budget={**t1["budget"], "max_context_tokens": 999})
altered = audit_equal_information_contract(reference_t1=t1, candidate_d6=candidate)
empty = audit_equal_information_contract(reference_t1={}, candidate_d6={})
assert altered["passed"] and empty["passed"]
results.append(dict(id="equal_information_unbound_content", reproduced=True,
                    actual=dict(altered_row=altered, two_empty_rows=empty),
                    source="src/logicguard/benchmark/trusted_controls.py:227-248"))

clean = [dict(_id="d1", title="Fixture", text="Original", source_group_id="g1")]
manifest = build_trust_manifest(clean_documents=clean, dataset="toy", dataset_revision="fixture",
                                assignment_seed="seed", coverage_levels=[1.0, 0.0])
snapshot = materialize_protected_snapshot(clean_documents=[{**clean[0], "text": "Poisoned"}],
                                          manifest=manifest, coverage=1.0)
assert snapshot[0]["text"] == "Poisoned"
results.append(dict(id="protected_snapshot_hash_unchecked", reproduced=True, actual=snapshot,
                    source="src/logicguard/benchmark/trust_manifest.py:175-181"))

trace = normalize_context_trace(
    backend_id="S1_microsoft_graphrag", instance_id="i", defense_id="D0_no_defense",
    corpus_modified=True, index_included=True, graph_surfaced=True,
    retrieved_document_ids=["a", "b"], prompt_document_ids=["a", "b"],
    rendered_prompt="A B",
)
post_trace = normalize_defense_trace(
    trace, defense_id="D5_logicguard_stage43_45", kept_prompt_document_ids=["a"],
)
assert post_trace.prompt_document_ids == ("a",)
assert post_trace.prompt_sha256 == trace.prompt_sha256
results.append(dict(
    id="defense_trace_hash_reused_after_prompt_filter", reproduced=True,
    actual={"before_prompt_ids": trace.prompt_document_ids,
            "after_prompt_ids": post_trace.prompt_document_ids,
            "before_hash": trace.prompt_sha256, "after_hash": post_trace.prompt_sha256},
    source="src/logicguard/benchmark/adapters.py:271-307",
    applicability="Trace normalization/readiness fixture and any callers of normalize_defense_trace; not evidence of real defense effect.",
    call_sites=["src/logicguard/benchmark/readiness.py:637; current E0 fixture preserves prompt_document_ids, so this counterexample is latent when a future caller filters them"],
))


def guard_fixture(root):
    (root / "pyproject.toml").write_text("")
    plan = root / "request_plan.jsonl"
    row = dict(request_slot_id="slot-1", input_token_cap=500, output_token_cap=1000,
               reserved_cost_cny=0.0001, prompt_fingerprint="prompt-1",
               actual_prompt_binding="fully_frozen", depends_on_request_slot_id=None)
    plan.write_text(json.dumps(row) + "\n")
    manifest = root / "launch.json"
    atomic_write_json(manifest, dict(
        launch_fingerprint="frozen-launch", limits={"max_provider_calls": 1, "hard_cost_cap_cny": 1.0},
        pricing={"input_per_million_tokens_cny": 0.2, "output_per_million_tokens_cny": 0.0},
        artifacts={"request_plan": {"path": "request_plan.jsonl", "sha256": sha256_file(plan)}}))
    return manifest, root / "guard_state.json"


with tempfile.TemporaryDirectory(prefix="logicguard-review-known-overbudget-") as tmp:
    manifest_path, state_path = guard_fixture(Path(tmp))
    guard = RequestCostGuard(launch_manifest=manifest_path, state_path=state_path)
    guard.reserve("slot-1", actual_prompt_fingerprint="prompt-1")
    try:
        guard.complete("slot-1", prompt_tokens=1000, completion_tokens=0)
    except Exception:
        pass
    summary = guard.summary()
    recorded_actual = json.loads(state_path.read_text())["requests"]["slot-1"]["actual_cost_cny"]
    assert recorded_actual == 0.0002
    assert summary["known_catalog_cost_cny"] == 0.0
    assert summary["reserved_or_charged_cny"] == 0.0001
    results.append(dict(
        id="guard_known_overbudget_cost_underreported", reproduced=True,
        actual={**{k: summary[k] for k in ("status", "known_catalog_cost_cny", "reserved_or_charged_cny")},
                "state_recorded_actual_cost_cny": recorded_actual},
        source="src/logicguard/benchmark/request_cost_guard.py:157-180,257-270,314-323",
        applicability="RequestCostGuard summary/audit accounting; stop state itself still fails closed.",
        call_sites=["RequestCostGuard is currently imported by tests/test_dev60_launch_guard.py only; dev60_launch.py:374 records future runner binding, not an executed integration"],
    ))

with tempfile.TemporaryDirectory(prefix="logicguard-review-partial-append-") as tmp:
    path = Path(tmp) / "checkpoint.jsonl"
    path.write_text('{"run_fingerprint":"fp","case":"partial"', encoding="utf-8")
    before = load_checkpoint_rows(path, fingerprint="fp")
    assert before == []
    append_jsonl(path, {"run_fingerprint": "fp", "case": "resumed"})
    try:
        load_checkpoint_rows(path, fingerprint="fp")
    except json.JSONDecodeError as exc:
        failure = f"{type(exc).__name__}: {exc}"
    else:
        raise AssertionError("expected malformed JSONL after append")
    results.append(dict(
        id="partial_jsonl_append_breaks_resume", reproduced=True,
        actual={"rows_before_append": before, "raw_after_append": path.read_text(encoding="utf-8"), "reload_error": failure},
        source="src/logicguard/core/io.py:16-45,64-71; src/logicguard/core/run_state.py:174-186",
        applicability="Any checkpoint caller using tolerate_trailing_partial then append_jsonl; answer_generation call site answer_generation.py:457-505.",
        call_sites=["src/logicguard/evaluation/answer_generation.py:458,493",
                    "src/logicguard/evaluation/reindex_answer_gate.py:202,215",
                    "src/logicguard/attack/adaptive.py:1284,411"],
    ))

with tempfile.TemporaryDirectory(prefix="logicguard-review-runner-") as tmp:
    root = Path(tmp)
    cfg = fixture_config(root)
    first = FakeClient(crash_second=True)
    try:
        run(cfg, client=first)
    except KeyboardInterrupt:
        pass
    before = dict(provider_calls=first.calls,
                  persisted_results=(root / "results.jsonl").exists(),
                  persisted_summary=(root / "summary.json").exists(),
                  files=sorted(p.name for p in root.iterdir()))
    second = FakeClient()
    resumed = run(cfg, client=second)
    assert first.calls == second.calls == 2 and not before["persisted_results"]
    results.append(dict(id="runner_interruption_replays_requests", reproduced=True,
                        actual=dict(interrupted=before, rerun_calls=second.calls, rerun_status=resumed["status"]),
                        source="src/logicguard/benchmark/attack_runner.py:268-278,319-329"))

with tempfile.TemporaryDirectory(prefix="logicguard-review-usage-") as tmp:
    cfg = fixture_config(Path(tmp))
    result = run(cfg, client=FakeClient(unknown=True))
    assert result["status"] == "EXECUTION_COMPLETE" and result["actual_catalog_cost_cny"] == 0.0
    results.append(dict(id="runner_unknown_usage_is_zero_cost", reproduced=True,
                        actual={k: result[k] for k in ("status", "generation_valid", "provider_calls_made", "actual_catalog_cost_cny")},
                        source="src/logicguard/benchmark/attack_runner.py:165-173,330-368"))

with tempfile.TemporaryDirectory(prefix="logicguard-review-cost-") as tmp:
    cfg = fixture_config(Path(tmp))
    fake = FakeClient(excessive=True)
    result = run(cfg, client=fake)
    assert fake.calls == 2 and result["status"] == "EXECUTION_COST_CAP_VIOLATION"
    results.append(dict(id="runner_cost_violation_checked_after_all_calls", reproduced=True,
                        actual={k: result[k] for k in ("status", "provider_calls_made", "hard_cost_cap_cny", "actual_catalog_cost_cny")},
                        source="src/logicguard/benchmark/attack_runner.py:319-368"))

report = dict(date="2026-10-16", provider_calls_made=0, repository_files_written=0,
              cases=results,
              limitations="Synthetic offline probes; no defense effectiveness or paid provider behavior measured.")
output = Path("/tmp/logicguard_review_20261016/benchmark_probe.json")
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
