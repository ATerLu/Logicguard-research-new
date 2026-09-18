from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from logicguard.benchmark.logicpoison_corpus import (
    corpus_statistics,
    replacement_plan,
    rewrite_corpus,
)
from logicguard.benchmark.logicpoison_pipeline import FixtureClient, FixtureNER, run
from logicguard.core.io import load_jsonl, sha256_file
from logicguard.llm.provider import ChatResponse


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/logicpoison_v1_2"


@pytest.fixture
def setup_run(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    for path in FIXTURES.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    config = yaml.safe_load(
        (
            ROOT / "configs/benchmark/comparison_v1_2_logicpoison_fixture.yaml"
        ).read_text()
    )
    for field in ("corpus", "queries", "ner_fixture", "query_fixture"):
        config[field] = Path(config[field]).name
    path = tmp_path / "config.yaml"

    def save():
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return path

    save()
    return config, path, save, tmp_path / config["output_root"]


def test_full_fixture_pipeline_preserves_ids_titles_and_records_provenance(setup_run):
    config, path, _, output = setup_run
    clean_path = path.parent / config["corpus"]
    before = sha256_file(clean_path)
    result = run(path)
    assert result["status"] == "CORPUS_MATERIALIZED"
    assert result["completed_stages"] == [
        "global",
        "query",
        "logic",
        "corpus_materialization",
    ]
    assert result["provider_calls_made"] == 0
    assert result["fixture_calls_made"] == 2
    assert result["known_catalog_cost_cny"] == 0
    assert result["attack_effect_measured"] is False
    assert result["poison_metrics"]["changed_documents"] == 3
    assert sha256_file(clean_path) == before
    clean, poison = load_jsonl(clean_path), load_jsonl(output / "corpus.jsonl")
    assert [(r["_id"], r["title"]) for r in clean] == [
        (r["_id"], r["title"]) for r in poison
    ]
    assert poison[0]["text"] == "Bea met Ada in Paris. Bea wrote with Ada."
    assert poison[2] == clean[2]
    assert poison[3]["text"].startswith("Adaline is not Bea's")
    assert len(load_jsonl(output / "changed_documents.jsonl")) == 3
    frozen = {p.name: p.read_bytes() for p in output.iterdir()}
    assert run(path) == result
    assert frozen == {p.name: p.read_bytes() for p in output.iterdir()}


def test_logic_mapping_and_corpus_match_pinned_upstream_on_unambiguous_fixture(
    setup_run, tmp_path
):
    _, path, _, output = setup_run
    run(path)
    spec = importlib.util.spec_from_file_location(
        "pinned_logic_stage", ROOT / "vendor/upstream/LogicPoison/src/logic_poison.py"
    )
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    stats = upstream.load_corpus_stats(str(output / "global_stats.json"))
    pools, all_sets = upstream.build_corpus_pools(stats, top_ratio=0.05)
    attack = upstream.load_query_entities(
        str(output / "query_entities.jsonl"), all_sets
    )
    mapping, _ = upstream.build_replace_map(
        attack, pools, {label: dict(rows) for label, rows in stats.items()}
    )
    own = json.loads((output / "replacement_plan.json").read_text())
    assert own["mapping"] == mapping
    upstream.poison_corpus_file(
        str(path.parent / "corpus.jsonl"), str(tmp_path / "upstream.jsonl"), mapping
    )
    assert load_jsonl(tmp_path / "upstream.jsonl") == load_jsonl(
        output / "corpus.jsonl"
    )


def test_cross_type_ambiguity_is_rejected_instead_of_silently_overwritten():
    stats = {
        "PERSON": [["Jordan", 5], ["Ada", 2]],
        "GPE": [["Jordan", 3], ["Paris", 1]],
    }
    queries = [{"query_id": "q", "entities": [{"type": "PERSON", "entity": "Ada"}]}]
    with pytest.raises(ValueError, match="ambiguous"):
        replacement_plan(stats, queries, top_ratio=0.05)


def test_single_pass_longest_first_boundaries_and_no_cascades():
    mapping = {"New York": "York", "York": "Rome", "Rome": "New York"}
    plan = {
        "mapping": mapping,
        "typed_mapping": [
            {"source": s, "target": t, "type": "GPE"} for s, t in mapping.items()
        ],
    }
    budget = {
        "max_changed_documents": 1,
        "max_changed_document_fraction": 1,
        "max_replacement_occurrences": 5,
        "max_poisoned_text_utf8_bytes": 100,
    }
    poison, provenance, _ = rewrite_corpus(
        [{"_id": "d", "text": "New York York Rome Yorkshire"}], plan, budget=budget
    )
    assert poison[0]["text"] == "York Rome New York Yorkshire"
    assert len(provenance[0]["replacements"]) == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_changed_documents", 1),
        ("max_changed_document_fraction", 0.1),
        ("max_replacement_occurrences", 1),
        ("max_poisoned_text_utf8_bytes", 1),
    ],
)
def test_poison_budget_never_publishes_a_truncated_attack(setup_run, field, value):
    config, path, save, output = setup_run
    config["poison_budget"][field] = value
    save()
    result = run(path)
    assert result["status"] == "LOGIC_STAGE_REJECTED"
    assert not (output / "corpus.jsonl").exists()


def test_request_budget_stops_before_any_call(setup_run):
    config, path, save, _ = setup_run
    config["pricing"]["hard_cost_cap_cny"] = 0
    save()
    result = run(path)
    assert result["status"] == "STOPPED_REQUEST_BUDGET"
    assert result["fixture_calls_made"] == 0


class InterruptAfterOne:
    def __init__(self):
        self.calls = 0
        self.fixture = FixtureClient(load_jsonl(FIXTURES / "query_responses.jsonl"))

    def chat(self, **kwargs):
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt
        return self.fixture.chat(**kwargs)


def test_interrupted_request_is_reserved_and_never_replayed(setup_run):
    _, path, _, output = setup_run
    client = InterruptAfterOne()
    with pytest.raises(KeyboardInterrupt):
        run(path, client=client)
    state = json.loads((output / "checkpoint.json").read_text())
    assert state["requests"]["fixture-q1"]["status"] == "complete"
    assert state["requests"]["fixture-q2"]["status"] == "in_flight"
    assert state["requests"]["fixture-q2"]["reserved_cny"] > 0
    result = run(path, client=client)
    assert result["status"] == "STOPPED_UNCERTAIN_REQUEST"
    assert client.calls == 2


@pytest.mark.parametrize(
    "failure",
    ["missing_usage", "exception", "overspend", "invalid_schema", "nonstring_entity"],
)
def test_provider_failures_stop_or_freeze_without_retries(setup_run, failure):
    _, path, _, output = setup_run

    class Client:
        calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if failure == "exception":
                raise RuntimeError("do-not-log-provider-secret")
            if failure == "missing_usage":
                return ChatResponse("[]", "{}", None, 5, None)
            if failure == "overspend":
                return ChatResponse("[]", "{}", 10000, 1000, 11000)
            content = (
                "not-json"
                if failure == "invalid_schema"
                else '[{"hop":1,"entity":123,"type":"PERSON"}]'
            )
            return ChatResponse(content, "{}", 10, 5, 15)

    client = Client()
    result = run(path, client=client)
    assert result["generation_valid"] is False
    calls = client.calls
    assert calls == (2 if failure in {"invalid_schema", "nonstring_entity"} else 1)
    run(path, client=client)
    assert client.calls == calls
    assert not (output / "corpus.jsonl").exists()
    assert all(
        "do-not-log-provider-secret" not in p.read_text() for p in output.iterdir()
    )


@pytest.mark.parametrize("target", ["corpus", "queries"])
def test_evaluator_fields_rejected_before_execution(setup_run, target):
    config, path, _, output = setup_run
    source = path.parent / config[target]
    rows = load_jsonl(source)
    rows[0]["gold_answer"] = "private-label"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="fields"):
        run(path)
    assert not output.exists()


def test_config_or_artifact_changes_block_resume(setup_run):
    config, path, save, output = setup_run
    run(path)
    config["top_ratio"] = 0.5
    save()
    with pytest.raises(ValueError, match="identity mismatch"):
        run(path)
    config["top_ratio"] = 0.05
    save()
    (output / "corpus.jsonl").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        run(path)


def test_forbidden_namespace_and_concurrent_runner_are_rejected(setup_run):
    config, path, save, output = setup_run
    config["output_root"] = "artifacts/benchmark/e1_preparation"
    save()
    with pytest.raises(ValueError, match="dedicated child"):
        run(path)
    config["output_root"] = str(output.relative_to(path.parent))
    save()
    output.mkdir(parents=True)
    (output / "run.lock").write_text("12345")
    with pytest.raises(FileExistsError):
        run(path)
    assert (output / "run.lock").exists()


def test_global_counts_and_stable_ties_match_expected():
    stats = corpus_statistics(
        load_jsonl(FIXTURES / "corpus.jsonl"),
        FixtureNER(load_jsonl(FIXTURES / "ner.jsonl")),
    )
    assert stats["PERSON"] == [["Ada", 4], ["Bea", 3], ["Cora", 1], ["Adaline", 1]]
    assert stats["GPE"] == [["London", 2], ["Paris", 1]]


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("pricing", "max_calls", 1.5),
        ("pricing", "max_input_tokens", True),
        ("poison_budget", "max_changed_documents", 2.5),
        ("poison_budget", "max_changed_document_fraction", 1.1),
        (None, "expected_queries", 2.0),
        (None, "timeout_seconds", 0),
    ],
)
def test_invalid_resource_limits_fail_before_outputs(setup_run, section, key, value):
    config, path, save, output = setup_run
    (config[section] if section else config)[key] = value
    save()
    with pytest.raises(ValueError):
        run(path)
    assert not output.exists()


def test_fixture_corpus_is_not_reported_as_real_attack_generation(setup_run):
    _, path, _, _ = setup_run
    result = run(path)
    assert result["corpus_materialization_valid"] is True
    assert result["generation_valid"] is False


def test_reconciled_budget_admits_next_call_without_charging_full_reservation(
    setup_run,
):
    config, path, save, _ = setup_run
    config["pricing"]["hard_cost_cap_cny"] = 0.013
    save()
    result = run(path)
    assert result["status"] == "CORPUS_MATERIALIZED"
    assert result["fixture_calls_made"] == 2
    assert result["fixture_simulated_catalog_cost_cny"] == pytest.approx(0.0012)


def test_resume_between_query_calls_does_not_reissue_completed_request(
    setup_run, monkeypatch
):
    import logicguard.benchmark.logicpoison_pipeline as pipeline

    _, path, _, _ = setup_run
    original = pipeline.build_logicpoison_query_request
    client = FixtureClient(load_jsonl(FIXTURES / "query_responses.jsonl"))

    def interrupt(**kwargs):
        if kwargs["query_id"] == "fixture-q2":
            raise KeyboardInterrupt
        return original(**kwargs)

    monkeypatch.setattr(pipeline, "build_logicpoison_query_request", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(path, client=client)
    monkeypatch.setattr(pipeline, "build_logicpoison_query_request", original)

    class SecondQueryOnly:
        calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            assert "Where did Bea work?" in kwargs["messages"][1]["content"]
            return client.chat(**kwargs)

    resumed = SecondQueryOnly()
    assert run(path, client=resumed)["status"] == "CORPUS_MATERIALIZED"
    assert resumed.calls == 1


@pytest.mark.parametrize("backend", ["en_core_web_lg", "en_core_web_sm"])
def test_alternate_ner_models_cannot_be_silently_substituted(setup_run, backend):
    config, path, save, output = setup_run
    config["ner_backend"] = backend
    save()
    with pytest.raises(ValueError, match="pinned"):
        run(path)
    assert not output.exists()


def test_execute_mode_rejects_synthetic_ner(setup_run):
    config, path, save, output = setup_run
    config.update(run_mode="execute", ner_backend="fixture")
    save()
    with pytest.raises(ValueError, match="synthetic"):
        run(path)
    assert not output.exists()
