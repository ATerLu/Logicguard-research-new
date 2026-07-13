import json
from pathlib import Path

import pandas as pd

from logicguard.ms_graphrag.query_layer_seeding import (
    QueryLayerSeedSettings,
    build_query_seed_plans,
    load_query_records,
)


def test_load_query_records_projects_only_query_fields(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    sample_path.write_text(
        json.dumps(
            {
                "query_id": "q1",
                "query": "Which film Target Film?",
                "answer": "secret answer",
                "support_doc_ids": ["d1"],
                "support_docs": [{"doc_id": "d1", "title": "Target Film"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    records = load_query_records(sample_path, max_queries=5)

    assert len(records) == 1
    assert records[0].query_id == "q1"
    assert records[0].query == "Which film Target Film?"
    assert set(records[0].to_json_dict()) == {"query_id", "query"}


def test_build_seed_plans_maps_title_hits_to_entities_without_gold_fields() -> None:
    queries = [
        {"query_id": "q1", "query": "Which film was released earlier, Target Film or Other Work?"},
    ]
    entities = pd.DataFrame(
        [
            {"id": "e1", "title": "TARGET FILM", "description": "A film", "degree": 5},
            {"id": "e2", "title": "TARGET DIRECTOR", "description": "Directed Target Film", "degree": 8},
            {"id": "e3", "title": "UNRELATED HUB", "description": "Other topic", "degree": 20},
        ]
    )
    text_units = pd.DataFrame(
        [
            {
                "id": "t1",
                "text": "Document ID: d1\nTitle: Target Film\n\nText",
                "entity_ids": ["e1", "e2"],
            },
            {
                "id": "t2",
                "text": "Document ID: d2\nTitle: Unrelated Work\n\nText",
                "entity_ids": ["e3"],
            },
        ]
    )

    plans = build_query_seed_plans(
        query_rows=queries,
        entities_frame=entities,
        text_units_frame=text_units,
        baseline_context_rows=[],
        settings=QueryLayerSeedSettings(top_title_documents=2, entities_per_document=2, top_lexical_entities=2),
    )

    plan = plans[0]
    assert plan["methods"]["all_entities_baseline"] == {
        "include_entity_names": [],
        "exclude_entity_names": [],
    }
    assert plan["title_candidates"][0]["doc_id"] == "d1"
    assert plan["title_candidates"][0]["title"] == "Target Film"
    assert plan["title_seed_entities"][:2] == ["TARGET FILM", "TARGET DIRECTOR"]
    assert "TARGET FILM" in plan["methods"]["title_seeding"]["include_entity_names"]
    serialized = json.dumps(plan, ensure_ascii=False)
    assert "answer" not in serialized
    assert "support_doc" not in serialized


def test_build_seed_plans_suppresses_repeated_lexically_unrelated_cluster() -> None:
    queries = [
        {"query_id": "q1", "query": "Who directed Target Film?"},
        {"query_id": "q2", "query": "Where was Another Person born?"},
    ]
    entities = pd.DataFrame(
        [
            {"id": "e1", "title": "TARGET FILM", "description": "Target Film", "degree": 5},
            {"id": "e2", "title": "ANOTHER PERSON", "description": "Another Person", "degree": 5},
            {"id": "e3", "title": "UNRELATED HUB", "description": "Unrelated cinema cluster", "degree": 30},
        ]
    )
    text_units = pd.DataFrame(
        [
            {"id": "t1", "text": "Document ID: d1\nTitle: Target Film\n\nText", "entity_ids": ["e1"]},
            {"id": "t2", "text": "Document ID: d2\nTitle: Another Person\n\nText", "entity_ids": ["e2"]},
        ]
    )
    baseline_rows = [
        {"query_id": "q1", "context_data": {"entities": [{"entity": "UNRELATED HUB"}]}},
        {"query_id": "q2", "context_data": {"entities": [{"entity": "UNRELATED HUB"}]}},
    ]

    plans = build_query_seed_plans(
        query_rows=queries,
        entities_frame=entities,
        text_units_frame=text_units,
        baseline_context_rows=baseline_rows,
        settings=QueryLayerSeedSettings(repeated_entity_min_queries=2),
    )

    assert plans[0]["anomalous_entities"] == ["UNRELATED HUB"]
    assert plans[1]["anomalous_entities"] == ["UNRELATED HUB"]
    assert plans[0]["methods"]["cluster_suppression"]["exclude_entity_names"] == ["UNRELATED HUB"]
    assert "TARGET FILM" not in plans[0]["methods"]["full_query_guard"]["exclude_entity_names"]
