import json
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from logicguard.ms_graphrag.official_local_context import (
    OfficialLocalContextConfig,
    apply_local_search_overrides,
    extract_source_evidence,
    serialize_context_data,
    write_official_context_rows,
)
from logicguard.ms_graphrag.query_time_defense import (
    GraphRagTextUnitEvidence,
    build_query_time_variants_from_ranked_evidence,
)


def test_serialize_context_data_converts_dataframes_to_records() -> None:
    context_data = {
        "sources": pd.DataFrame(
            [
                {
                    "id": "0",
                    "text": "Document ID: 4669\nTitle: Zabou Breitman\n\nZabou text.",
                }
            ]
        ),
        "entities": pd.DataFrame([{"id": "1", "entity": "ZABOU BREITMAN"}]),
    }

    serialized = serialize_context_data(context_data)

    assert serialized["sources"][0]["id"] == "0"
    assert serialized["sources"][0]["logicguard_doc_id"] == "4669"
    assert serialized["sources"][0]["title"] == "Zabou Breitman"
    assert serialized["entities"][0]["entity"] == "ZABOU BREITMAN"


def test_extract_source_evidence_maps_official_sources_to_ranked_evidence() -> None:
    row = {
        "context_data": {
            "sources": [
                {
                    "id": "1",
                    "text": "Document ID: 4670\nTitle: Someone I Loved\n\nSomeone I Loved was directed by Zabou Breitman.",
                },
                {
                    "id": "0",
                    "text": "Document ID: 4669\nTitle: Zabou Breitman\n\nZabou is the daughter of 8th Earl-Claude Deret.",
                },
            ]
        }
    }

    evidence = extract_source_evidence(row)

    assert [item.logicguard_doc_id for item in evidence] == ["4670", "4669"]
    assert evidence[0].text_unit_id == "official-source-1"
    assert evidence[1].title == "Zabou Breitman"


def test_query_time_variants_can_use_official_ranked_sources() -> None:
    official_sources = [
        GraphRagTextUnitEvidence(
            text_unit_id="official-source-1",
            human_readable_id=1,
            official_document_id="official-source-1",
            logicguard_doc_id="4670",
            title="Someone I Loved",
            text="Someone I Loved was directed by Zabou Breitman.",
            n_tokens=8,
        ),
        GraphRagTextUnitEvidence(
            text_unit_id="official-source-0",
            human_readable_id=0,
            official_document_id="official-source-0",
            logicguard_doc_id="4669",
            title="Zabou Breitman",
            text="Zabou is the daughter of 8th Earl-Claude Deret.",
            n_tokens=9,
        ),
    ]
    clean_units = [
        GraphRagTextUnitEvidence(
            text_unit_id="clean-unit-4669",
            human_readable_id=0,
            official_document_id="clean-doc-4669",
            logicguard_doc_id="4669",
            title="Zabou Breitman",
            text="Zabou is the daughter of Jean-Claude Deret.",
            n_tokens=8,
        )
    ]

    variants = build_query_time_variants_from_ranked_evidence(
        ranked_poisoned_units=official_sources,
        clean_reference_units=clean_units,
        changed_doc_ids={"4669"},
        top_k=2,
        max_units=2,
        max_chars_per_unit=300,
    )

    by_name = {variant.name: variant for variant in variants}

    assert [item.logicguard_doc_id for item in by_name["poisoned"].evidence] == [
        "4670",
        "4669",
    ]
    assert [item.logicguard_doc_id for item in by_name["guarded"].evidence] == ["4670"]
    assert [item.logicguard_doc_id for item in by_name["recovered"].evidence] == [
        "4670",
        "4669",
    ]
    assert "Jean-Claude Deret" in by_name["recovered"].context_text


def test_write_official_context_rows_writes_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "contexts.jsonl"
    rows = [
        {
            "dataset": "toy",
            "query_id": "q1",
            "response": "answer",
            "context_data": {"sources": [{"id": "0", "logicguard_doc_id": "d1"}]},
        }
    ]

    write_official_context_rows(output_path, rows)

    saved = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert saved == rows


def test_official_context_config_parses_local_search_overrides(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "context.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "dataset": "toy",
                "sample_path": "data/sample.jsonl",
                "workspace_root": "outputs/workspace",
                "output_path": "outputs/context.jsonl",
                "report_path": "outputs/report.md",
                "local_search_overrides": {
                    "text_unit_prop": 0.8,
                    "community_prop": 0.0,
                    "top_k_entities": 30,
                    "top_k_relationships": 30,
                    "max_context_tokens": 20000,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = OfficialLocalContextConfig.from_yaml(config_path)

    assert config.local_search_overrides == {
        "text_unit_prop": 0.8,
        "community_prop": 0.0,
        "top_k_entities": 30,
        "top_k_relationships": 30,
        "max_context_tokens": 20000,
    }


def test_apply_local_search_overrides_updates_known_fields_only() -> None:
    graph_config = SimpleNamespace(
        local_search=SimpleNamespace(
            text_unit_prop=0.5,
            community_prop=0.15,
            top_k_entities=10,
            top_k_relationships=10,
            max_context_tokens=12000,
        )
    )

    apply_local_search_overrides(
        graph_config, {"text_unit_prop": 0.8, "top_k_entities": 40}
    )

    assert graph_config.local_search.text_unit_prop == 0.8
    assert graph_config.local_search.community_prop == 0.15
    assert graph_config.local_search.top_k_entities == 40


def test_apply_local_search_overrides_rejects_unknown_fields() -> None:
    graph_config = SimpleNamespace(local_search=SimpleNamespace(text_unit_prop=0.5))

    with pytest.raises(ValueError, match="Unsupported local_search override"):
        apply_local_search_overrides(graph_config, {"unknown": 1})
