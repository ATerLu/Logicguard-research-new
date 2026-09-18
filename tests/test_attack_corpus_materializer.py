import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from logicguard.benchmark.attack_corpus_materializer import (
    materialize_a1_documents,
    materialize_a3_documents,
    run_from_config,
)

ROOT = Path(__file__).parents[1]


def _result(attack_id: str, query_id: str, output: dict) -> dict:
    return {
        "dataset": "toy",
        "attack_id": attack_id,
        "query_id": query_id,
        "generation_valid": True,
        "output": output,
    }


def test_a1_uses_exact_upstream_question_period_prefix() -> None:
    result = _result(
        "A1_poisonedrag",
        "q1",
        {"target_answer": "Wrong", "malicious_texts": ["Evidence."]},
    )

    rows, audit = materialize_a1_documents(
        result, question="Question?", max_documents=5, word_budget=20
    )

    assert rows[0]["text"] == "Question?.Evidence."
    assert audit["materialization_prefix"] == (
        "question_plus_period_without_inserted_space"
    )
    assert not audit["paper_native_document_count"]


def test_a3_reuses_direct_text_for_adjacent_matching_relation_key() -> None:
    attack_record = {
        "root_nodes": ["Root"],
        "modified_middle_node": "Middle",
        "target_relation": "relation",
        "direct_adv_texts": ["Direct one", "Direct two"],
        "indirect_adv_texts": ["Indirect one"],
        "enhanced_texts": ["Enhanced one"],
    }
    results = [
        _result("A3_gragpoison", "q1", {"attack_record": attack_record}),
        _result("A3_gragpoison", "q2", {"attack_record": attack_record}),
    ]

    rows, audits = materialize_a3_documents(
        results,
        questions={"q1": "First?", "q2": "Second?"},
        n_alpha=10,
        n_beta=5,
        max_documents_per_query=30,
        word_budget=20,
    )

    assert [row["attack_family"] for row in rows].count("direct") == 2
    assert audits[0]["direct_reused_from_immediately_previous"] is False
    assert audits[1]["direct_reused_from_immediately_previous"] is True
    assert len(rows) == 6


def test_a1_rejects_word_budget_overflow() -> None:
    result = _result(
        "A1_poisonedrag",
        "q1",
        {"target_answer": "Wrong", "malicious_texts": ["too many words here"]},
    )
    with pytest.raises(ValueError, match="word budget"):
        materialize_a1_documents(
            result, question="Question", max_documents=5, word_budget=2
        )


def test_real_anchor_materializes_and_replays_without_provider() -> None:
    source = yaml.safe_load(
        (
            ROOT / "configs/benchmark/"
            "comparison_v1_2_a1_a3_common_dev_materialization_anchor.yaml"
        ).read_text(encoding="utf-8")
    )
    output = (
        ROOT
        / "artifacts/benchmark/research_revision_v1_2/wp2/test_materializer"
        / uuid4().hex
    )
    source["output_root"] = str(output.relative_to(ROOT))
    temporary = ROOT / "tmp/attack_corpus_materializer_tests" / uuid4().hex
    temporary.mkdir(parents=True)
    config_path = temporary / "config.yaml"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    try:
        first = run_from_config(config_path)
        second = run_from_config(config_path)

        assert first == second
        assert first["status"] == "COMMON_DEV_MATERIALIZATION_ANCHOR_PASSED"
        assert len(first["cells"]) == 2
        assert sum(cell["poison_document_occurrences"] for cell in first["cells"]) == 9
        assert all(not cell["paper_native_count_ready"] for cell in first["cells"])
        assert first["provider_calls_made"] == 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
