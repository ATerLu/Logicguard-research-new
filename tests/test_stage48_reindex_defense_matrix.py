from pathlib import Path

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.evaluation.reindex_defense_matrix import (
    Stage48DefenseMatrixConfig,
    build_stage48_defense_matrix,
    build_stage48_preflight_rows,
    summarize_stage48_preflight,
)


def test_stage48_matrix_reuses_all_four_frozen_defense_methods() -> None:
    config = _config()
    sample = _sample()
    attack = {
        "query_id": "q1",
        "attack_family": "candidate_collision",
        "attack_id": "a1",
        "injected_doc_id": "attack-1",
        "malicious_answer": "Wrong City",
    }
    matrix = build_stage48_defense_matrix(
        config=config,
        samples=[sample],
        source_context_rows=[_context()],
        candidate_sources=[
            _candidate(
                "attack-clean", "Collision Title", "Clean person lived elsewhere."
            ),
            _candidate("d2", "Ada Lovelace", "Ada Lovelace was born in Silver Delta."),
        ],
        attack_by_query={"q1": attack},
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["attack-1"]}],
    )

    assert {row["method"] for row in matrix} == {
        "full_query_guard",
        "risk_non_oracle_title_entity_bm25",
        "stage35_query_bm25_append_top12",
        "stage38_second_hop_append_top14",
    }
    assert all(row["stage48_attack_doc_ids"] == ["attack-1"] for row in matrix)
    recovered = next(
        row for row in matrix if row["method"] == "risk_non_oracle_title_entity_bm25"
    )
    assert recovered["risk_detected_source_doc_ids"] == ["attack-1"]


def test_stage48_preflight_keeps_attack_and_clean_denominators_explicit() -> None:
    config = _config()
    sample = _sample()
    attack = {
        "attack_id": "a1",
        "injected_doc_id": "attack-1",
        "malicious_answer": "Wrong City",
    }
    matrix = build_stage48_defense_matrix(
        config=config,
        samples=[sample],
        source_context_rows=[_context()],
        candidate_sources=[
            _candidate(
                "attack-clean", "Collision Title", "Clean person lived elsewhere."
            ),
            _candidate("d2", "Ada Lovelace", "Ada Lovelace was born in Silver Delta."),
        ],
        attack_by_query={"q1": attack},
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["attack-1"]}],
    )
    preflight = build_stage48_preflight_rows(
        config=config,
        samples=[sample],
        integrity_rows=[{"query_id": "q1", "changed_support_doc_ids": ["attack-1"]}],
        matrix_rows=matrix,
        attack_by_query={"q1": attack},
    )
    by_method = {row["method"]: row for row in preflight}

    assert by_method["full_query_guard"]["attack_source_exposed"] is True
    assert by_method["full_query_guard"]["malicious_answer_exposed"] is True
    assert (
        by_method["risk_non_oracle_title_entity_bm25"]["attack_source_exposed"] is False
    )
    assert by_method["risk_non_oracle_title_entity_bm25"]["attack_recovered"] is True
    summary = summarize_stage48_preflight(config=config, rows=preflight)
    assert summary["attempt_unit"] == "frozen_attack"
    assert summary["query_count"] == 1
    assert summary["methods"]["full_query_guard"]["query_count"] == 1


def _config() -> Stage48DefenseMatrixConfig:
    root = Path(".").resolve()
    return Stage48DefenseMatrixConfig(
        dataset="toy",
        condition="attacked",
        attack_family="candidate_collision",
        sample_path=root / "samples.jsonl",
        source_context_path=root / "contexts.jsonl",
        clean_reference_output_dir=root / "clean",
        frozen_attacks_path=root / "attacks.jsonl",
        integrity_output_path=root / "integrity.jsonl",
        matrix_output_path=root / "matrix.jsonl",
        preflight_output_path=root / "preflight.jsonl",
        summary_output_path=root / "summary.json",
        manifest_output_path=root / "manifest.json",
    )


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="Where was Ada Lovelace born?",
        answer="Silver Delta",
        support_doc_ids=["d2"],
        support_docs=[CorpusDocument("d2", "Ada Lovelace", "Silver Delta")],
    )


def _context() -> dict[str, object]:
    return {
        "query_id": "q1",
        "query": "Where was Ada Lovelace born?",
        "method": "full_query_guard",
        "context_text": "",
        "context_data": {
            "entities": [],
            "relationships": [],
            "claims": [],
            "sources": [
                {
                    "logicguard_doc_id": "attack-1",
                    "title": "Collision Title",
                    "text": (
                        "Document ID: attack-1\nTitle: Collision Title\n\n"
                        "Mallory Stone says the answer is Wrong City."
                    ),
                }
            ],
        },
    }


def _candidate(doc_id: str, title: str, body: str) -> NonOracleCandidateSource:
    return NonOracleCandidateSource(
        id=doc_id,
        text_unit_id=doc_id,
        logicguard_doc_id=doc_id,
        official_document_id=doc_id,
        human_readable_id=1,
        title=title,
        text=f"Document ID: {doc_id}\nTitle: {title}\n\n{body}",
        n_tokens=10,
    )
