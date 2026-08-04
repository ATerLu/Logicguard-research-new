from types import SimpleNamespace

import pandas as pd

from logicguard.ms_graphrag.query_layer_context import (
    build_query_guard_context_rows,
    resolve_method_entities,
    resolve_entity_adapter_community_level,
    write_method_context_rows,
)


def test_resolve_method_entities_filters_unknown_names_and_include_exclude_overlap() -> (
    None
):
    plan = {
        "methods": {
            "full_query_guard": {
                "include_entity_names": ["TARGET", "UNKNOWN", "PROTECTED"],
                "exclude_entity_names": ["HUB", "PROTECTED", "MISSING"],
            }
        }
    }

    resolved = resolve_method_entities(
        plan=plan,
        method="full_query_guard",
        available_entity_names={"TARGET", "PROTECTED", "HUB"},
    )

    assert resolved.include_entity_names == ["TARGET", "PROTECTED"]
    assert resolved.exclude_entity_names == ["HUB"]
    assert resolved.unknown_entity_names == ["UNKNOWN", "MISSING"]


def test_build_query_guard_context_rows_passes_official_include_exclude_parameters() -> (
    None
):
    builder = RecordingContextBuilder()
    query_rows = [{"query_id": "q1", "query": "Who directed Target?"}]
    plans = [
        {
            "query_id": "q1",
            "methods": {
                "title_seeding": {
                    "include_entity_names": ["TARGET"],
                    "exclude_entity_names": [],
                },
                "cluster_suppression": {
                    "include_entity_names": [],
                    "exclude_entity_names": ["HUB"],
                },
            },
        }
    ]

    rows = build_query_guard_context_rows(
        query_rows=query_rows,
        plans=plans,
        methods=["title_seeding", "cluster_suppression"],
        available_entity_names={"TARGET", "HUB"},
        context_builder=builder,
        context_builder_params={"top_k_mapped_entities": 10},
    )

    assert len(rows) == 2
    assert builder.calls[0]["include_entity_names"] == ["TARGET"]
    assert builder.calls[0]["exclude_entity_names"] == []
    assert builder.calls[1]["include_entity_names"] == []
    assert builder.calls[1]["exclude_entity_names"] == ["HUB"]
    assert rows[0]["method"] == "title_seeding"
    assert rows[0]["context_data"]["sources"][0]["logicguard_doc_id"] == "d1"


def test_build_query_guard_context_rows_degrades_empty_seed_to_baseline_parameters() -> (
    None
):
    builder = RecordingContextBuilder()

    rows = build_query_guard_context_rows(
        query_rows=[{"query_id": "q1", "query": "Unknown query"}],
        plans=[{"query_id": "q1", "methods": {"title_seeding": {}}}],
        methods=["title_seeding"],
        available_entity_names={"TARGET"},
        context_builder=builder,
        context_builder_params={},
    )

    assert builder.calls[0]["include_entity_names"] == []
    assert builder.calls[0]["exclude_entity_names"] == []
    assert rows[0]["fallback_to_baseline"] is True


def test_local_only_context_keeps_entities_without_community_membership() -> None:
    assert (
        resolve_entity_adapter_community_level(
            configured_community_level=2,
            community_prop=0.0,
        )
        is None
    )
    assert (
        resolve_entity_adapter_community_level(
            configured_community_level=2,
            community_prop=0.1,
        )
        == 2
    )


def test_write_method_context_rows_keeps_only_requested_method(tmp_path) -> None:
    output_path = tmp_path / "full.jsonl"
    rows = [
        {"query_id": "q1", "method": "title_seeding"},
        {"query_id": "q1", "method": "full_query_guard"},
        {"query_id": "q2", "method": "full_query_guard"},
    ]

    written = write_method_context_rows(
        path=output_path,
        rows=rows,
        method="full_query_guard",
    )

    assert written == 2
    assert output_path.read_text(encoding="utf-8").count("\n") == 2
    assert "title_seeding" not in output_path.read_text(encoding="utf-8")


class RecordingContextBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_context(self, *, query: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"query": query, **kwargs})
        return SimpleNamespace(
            context_chunks="context",
            context_records={
                "sources": pd.DataFrame(
                    [{"id": 1, "text": "Document ID: d1\nTitle: Target\n\nText"}]
                ),
                "entities": pd.DataFrame([{"entity": "TARGET"}]),
            },
        )
