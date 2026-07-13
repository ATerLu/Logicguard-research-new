from pathlib import Path

import pandas as pd

from logicguard.ms_graphrag.query_time_defense import (
    GraphRagTextUnitEvidence,
    build_query_time_variants,
    load_text_unit_evidence,
)


def test_load_text_unit_evidence_maps_official_document_ids_to_logicguard_doc_ids(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pd.DataFrame(
        [
            {
                "id": "doc-hash-1",
                "human_readable_id": 0,
                "title": "4669.txt",
                "text": "Document ID: 4669\nTitle: Zabou Breitman\n\nZabou text.",
                "text_unit_ids": ["unit-1"],
                "creation_date": "2026-06-19",
                "raw_data": None,
            }
        ]
    ).to_parquet(output_dir / "documents.parquet")
    pd.DataFrame(
        [
            {
                "id": "unit-1",
                "human_readable_id": 0,
                "text": "Document ID: 4669\nTitle: Zabou Breitman\n\nZabou text.",
                "n_tokens": 20,
                "document_id": "doc-hash-1",
                "entity_ids": [],
                "relationship_ids": [],
                "covariate_ids": [],
            }
        ]
    ).to_parquet(output_dir / "text_units.parquet")

    evidence = load_text_unit_evidence(output_dir)

    assert len(evidence) == 1
    assert evidence[0].text_unit_id == "unit-1"
    assert evidence[0].official_document_id == "doc-hash-1"
    assert evidence[0].logicguard_doc_id == "4669"
    assert evidence[0].title == "Zabou Breitman"


def test_build_query_time_variants_filters_changed_and_recovers_clean_evidence() -> None:
    poisoned_units = [
        GraphRagTextUnitEvidence(
            text_unit_id="p1",
            human_readable_id=0,
            official_document_id="poison-doc-1",
            logicguard_doc_id="4669",
            title="Zabou Breitman",
            text="Zabou Breitman is the daughter of actors 8th Earl-Claude Deret and Celine Leger.",
            n_tokens=18,
        ),
        GraphRagTextUnitEvidence(
            text_unit_id="p2",
            human_readable_id=1,
            official_document_id="poison-doc-2",
            logicguard_doc_id="4670",
            title="Someone I Loved",
            text="Someone I Loved is a French drama film directed by Zabou Breitman.",
            n_tokens=14,
        ),
    ]
    clean_units = [
        GraphRagTextUnitEvidence(
            text_unit_id="c1",
            human_readable_id=0,
            official_document_id="clean-doc-1",
            logicguard_doc_id="4669",
            title="Zabou Breitman",
            text="Zabou Breitman is the daughter of actors Jean-Claude Deret and Celine Leger.",
            n_tokens=18,
        ),
        GraphRagTextUnitEvidence(
            text_unit_id="c2",
            human_readable_id=1,
            official_document_id="clean-doc-2",
            logicguard_doc_id="4670",
            title="Someone I Loved",
            text="Someone I Loved is a French drama film directed by Zabou Breitman.",
            n_tokens=14,
        ),
    ]

    variants = build_query_time_variants(
        query="Who is the father of the director of film Someone I Loved?",
        poisoned_units=poisoned_units,
        clean_reference_units=clean_units,
        changed_doc_ids={"4669"},
        top_k=2,
        max_units=2,
        max_chars_per_unit=400,
    )

    by_name = {variant.name: variant for variant in variants}

    assert [item.logicguard_doc_id for item in by_name["poisoned"].evidence] == ["4670", "4669"]
    assert by_name["poisoned"].changed_doc_count == 1
    assert [item.logicguard_doc_id for item in by_name["guarded"].evidence] == ["4670"]
    assert by_name["guarded"].changed_doc_count == 0
    assert [item.logicguard_doc_id for item in by_name["recovered"].evidence] == ["4670", "4669"]
    assert by_name["recovered"].changed_doc_count == 0
    assert by_name["recovered"].recovered_doc_count == 1
    assert "Jean-Claude Deret" in by_name["recovered"].context_text
    assert "8th Earl-Claude Deret" not in by_name["recovered"].context_text
