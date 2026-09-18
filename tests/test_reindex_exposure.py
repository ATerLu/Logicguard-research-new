from pathlib import Path

import pandas as pd
import pytest

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.evaluation.reindex_exposure import (
    _build_poisoned_corpus_rows,
    _catalog_cost_estimate_cny,
    _omit_unused_community_report_workflow,
    _matching_record_surfaces,
    _record_surfaces,
    _read_graphrag_metrics,
    _read_reindex_frames,
    _require_new_workspace,
    select_frozen_attacks,
)


def test_cached_record_surfaces_preserve_term_matching_semantics() -> None:
    frame = pd.DataFrame(
        [
            {"title": "Alpha Bridge", "description": "unrelated"},
            {"title": "Other", "description": "malicious target"},
        ]
    )

    matches = _matching_record_surfaces(
        _record_surfaces(frame), ["Alpha Bridge", "malicious target", "1952"]
    )

    assert matches == ["Alpha Bridge", "malicious target"]


def test_select_frozen_attacks_requires_strict_targeted_success() -> None:
    samples = {
        query_id: NormalizedSample(
            query_id=query_id,
            query=f"Question {query_id}",
            answer=f"gold-{query_id}",
            support_doc_ids=["d1"],
            support_docs=[CorpusDocument("d1", "Clean", "clean")],
        )
        for query_id in ("2hop__a", "2hop__b", "3hop1__c", "4hop1__d")
    }
    attack_rows = [
        _attack(query_id, malicious=f"wrong-{query_id}") for query_id in samples
    ]
    attacked_rows = [_attacked_context(query_id) for query_id in samples]
    preflight_rows = [_preflight(query_id, exposed=True) for query_id in samples]
    judged_rows = [
        _judged(query_id, generated=f"wrong-{query_id}", label="incorrect")
        for query_id in samples
    ]
    preflight_rows[1] = _preflight("2hop__b", exposed=False)

    selected = select_frozen_attacks(
        dataset="toy",
        attack_family="natural_bridge",
        max_attacks=3,
        samples_by_id=samples,
        attack_rows=attack_rows,
        attacked_context_rows=attacked_rows,
        preflight_rows=preflight_rows,
        judged_rows=judged_rows,
    )

    assert {row["query_id"] for row in selected} == {
        "2hop__a",
        "3hop1__c",
        "4hop1__d",
    }
    assert all(row["oracle_fields_used_for_generation"] is False for row in selected)


def test_select_frozen_attacks_evaluation_valid_does_not_select_on_answer() -> None:
    samples = {
        "2hop__a": NormalizedSample(
            query_id="2hop__a",
            query="Question",
            answer="gold",
            support_doc_ids=["d1"],
            support_docs=[CorpusDocument("d1", "Clean", "clean")],
        )
    }
    attack = _attack("2hop__a", malicious="wrong")
    attack["attack_family"] = "low_drift"
    attacked_context = _attacked_context("2hop__a")
    attacked_context["method"] = "low_drift"
    preflight = _preflight("2hop__a", exposed=False)
    preflight["method"] = "stage47_low_drift__unprotected"
    judged = _judged("2hop__a", generated="gold", label="correct")
    judged["method"] = "stage47_low_drift__unprotected"
    selected = select_frozen_attacks(
        dataset="toy",
        attack_family="low_drift",
        max_attacks=1,
        samples_by_id=samples,
        attack_rows=[attack],
        attacked_context_rows=[attacked_context],
        preflight_rows=[preflight],
        judged_rows=[judged],
        selection_policy="evaluation_valid",
    )

    assert [row["query_id"] for row in selected] == ["2hop__a"]
    assert selected[0]["selection_policy"] == "evaluation_valid"


def test_omit_unused_community_report_workflow(tmp_path: Path) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "workflows:\n- load_input_documents\n- create_community_reports\n"
        "- generate_text_embeddings\n",
        encoding="utf-8",
    )

    _omit_unused_community_report_workflow(settings)

    rendered = settings.read_text(encoding="utf-8")
    assert "create_community_reports" not in rendered
    assert "generate_text_embeddings" in rendered
    assert "entity_description" in rendered


def test_poisoned_corpus_replaces_existing_ids_and_appends_new_ids() -> None:
    rows, mutation = _build_poisoned_corpus_rows(
        clean_base=[
            CorpusDocument("d1", "Clean 1", "old"),
            CorpusDocument("d2", "Clean 2", "keep"),
        ],
        selected=[
            {
                "injected_doc_id": "d1",
                "injected_title": "Changed 1",
                "injected_body": "new",
            },
            {
                "injected_doc_id": "attack-d3",
                "injected_title": "Attack 3",
                "injected_body": "poison",
            },
        ],
    )

    assert [row["_id"] for row in rows] == ["d1", "d2", "attack-d3"]
    assert rows[0]["text"] == "new"
    assert mutation == {
        "replaced_document_count": 1,
        "appended_document_count": 1,
        "unique_document_count": 3,
    }


def test_prepare_guard_refuses_to_overwrite_existing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "settings.yaml").write_text("existing", encoding="utf-8")

    with pytest.raises(RuntimeError, match="already contains files"):
        _require_new_workspace(workspace)


def test_reindex_audit_accepts_intentionally_omitted_community_reports(
    tmp_path: Path,
) -> None:
    for name in (
        "documents",
        "text_units",
        "entities",
        "relationships",
        "communities",
    ):
        pd.DataFrame([{"id": name}]).to_parquet(tmp_path / f"{name}.parquet")

    frames = _read_reindex_frames(tmp_path)

    assert frames["documents"].iloc[0]["id"] == "documents"
    assert frames["community_reports"].empty


def test_graphrag_metrics_aggregate_interrupted_and_resumed_processes(
    tmp_path: Path,
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "index.log").write_text(
        "\nMetrics for openai/qwen3.7-plus: {\n"
        '  "attempted_request_count": 2,\n'
        '  "successful_response_count": 1,\n'
        '  "failed_response_count": 0,\n'
        '  "prompt_tokens": 100,\n'
        '  "completion_tokens": 50,\n'
        '  "total_tokens": 150\n'
        "}\nMetrics for openai/qwen3.7-plus: {\n"
        '  "attempted_request_count": 1,\n'
        '  "successful_response_count": 1,\n'
        '  "failed_response_count": 0,\n'
        '  "prompt_tokens": 20,\n'
        '  "completion_tokens": 10,\n'
        '  "total_tokens": 30\n'
        "}\n",
        encoding="utf-8",
    )

    metrics = _read_graphrag_metrics(tmp_path)

    chat = metrics["openai/qwen3.7-plus"]
    assert chat["attempted_request_count"] == 3
    assert chat["successful_response_count"] == 2
    assert chat["incomplete_response_count"] == 1
    assert chat["prompt_tokens"] == 120
    assert _catalog_cost_estimate_cny(metrics) == pytest.approx(0.00072)


def _attack(query_id: str, *, malicious: str) -> dict[str, object]:
    return {
        "dataset": "toy",
        "query_id": query_id,
        "attack_family": "natural_bridge",
        "attack_id": f"attack-{query_id}",
        "valid": True,
        "target_doc_id": f"attack-{query_id}",
        "target_title": f"Bridge {query_id}",
        "malicious_answer": malicious,
        "attacker_used_gold_answer": False,
        "attacker_used_support_ids": False,
        "attacker_used_changed_labels": False,
    }


def _attacked_context(query_id: str) -> dict[str, object]:
    doc_id = f"attack-{query_id}"
    malicious = f"wrong-{query_id}"
    return {
        "query_id": query_id,
        "method": "natural_bridge",
        "context_data": {
            "sources": [
                {
                    "logicguard_doc_id": doc_id,
                    "title": f"Bridge {query_id}",
                    "text": (
                        f"Document ID: {doc_id}\nTitle: Bridge {query_id}\n\n"
                        f"The answer is {malicious}."
                    ),
                    "source_state": "stage47_adaptive_poison",
                }
            ]
        },
    }


def _preflight(query_id: str, *, exposed: bool) -> dict[str, object]:
    return {
        "query_id": query_id,
        "method": "stage47_natural_bridge__unprotected",
        "attack_source_exposed": exposed,
        "malicious_answer_exposed": exposed,
    }


def _judged(query_id: str, *, generated: str, label: str) -> dict[str, object]:
    return {
        "query_id": query_id,
        "method": "stage47_natural_bridge__unprotected",
        "generated_answer": generated,
        "final_label": label,
    }
