import json
from pathlib import Path

import pytest

from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.llm.provider import ChatResponse
from logicguard.defense.non_oracle_recovery import NonOracleCandidateSource
from logicguard.attack.adaptive import (
    Stage47AdaptiveAttackConfig,
    build_stage47_defense_matrix,
    build_stage47_preflight_rows,
    generate_query_attacks,
    summarize_stage47_preflight,
    run_from_config,
)


class _FakeClient:
    def __init__(self) -> None:
        self.call_count = 0

    def chat(self, **_: object) -> ChatResponse:
        self.call_count += 1
        payload = {
            "low_drift": {
                "target_doc_id": "d1",
                "target_title": "Film Alpha",
                "malicious_answer": "2001",
                "attacked_text": "Film Alpha premiered in 2001 in London.",
            },
            "candidate_collision": {
                "candidate_doc_id": "d2",
                "malicious_answer": "Paris",
                "attacked_text": (
                    "Film Alpha was catalogued in Paris by Maria Stone, Peter Hall, "
                    "Delta House, and Orion Press."
                ),
            },
            "natural_bridge": {
                "title": "Film Alpha production reference",
                "malicious_answer": "Rome",
                "attacked_text": "A production register places Film Alpha's premiere in Rome.",
            },
        }
        return ChatResponse(
            content=json.dumps(payload),
            raw_json="{}",
            prompt_tokens=100,
            completion_tokens=80,
            total_tokens=180,
        )


class _InterruptingClient(_FakeClient):
    def __init__(self, *, interrupt_at: int) -> None:
        super().__init__()
        self.interrupt_at = interrupt_at

    def chat(self, **kwargs: object) -> ChatResponse:
        if self.call_count + 1 == self.interrupt_at:
            raise KeyboardInterrupt("simulated attack-generation interruption")
        return super().chat(**kwargs)


class _NullTargetClient(_FakeClient):
    def chat(self, **kwargs: object) -> ChatResponse:
        response = super().chat(**kwargs)
        payload = json.loads(response.content)
        payload["candidate_collision"]["malicious_answer"] = None
        return ChatResponse(
            content=json.dumps(payload),
            raw_json=response.raw_json,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
        )


def test_stage47_generates_three_label_blind_attacks_and_defense_matrix(
    tmp_path: Path,
) -> None:
    sample = _sample()
    config = _config(tmp_path)
    candidates = _candidates()
    records, attacked_rows = generate_query_attacks(
        config=config,
        sample=sample,
        base_row=_context_row(),
        candidate_sources=candidates,
        client=_FakeClient(),
    )

    assert [record.attack_family for record in records] == [
        "low_drift",
        "candidate_collision",
        "natural_bridge",
    ]
    assert all(record.valid for record in records)
    assert all(not record.attacker_used_gold_answer for record in records)
    assert records[0].entity_drift == 0.0

    integrity = [
        {
            "query_id": "q1",
            "changed_support_doc_ids": [record.target_doc_id for record in records],
        }
    ]
    matrix = build_stage47_defense_matrix(
        config=config,
        samples=[sample],
        attacked_rows=attacked_rows,
        integrity_rows=integrity,
        candidate_sources=candidates,
    )
    assert len(matrix) == 12
    collision_recovery = next(
        row
        for row in matrix
        if row["method"] == "stage47_candidate_collision__stage43_recovery"
    )
    assert "d2" in collision_recovery["recovered_source_doc_ids"]

    preflight = build_stage47_preflight_rows(
        config=config,
        samples=[sample],
        attack_records=records,
        integrity_rows=integrity,
        context_rows=matrix,
    )
    summaries = summarize_stage47_preflight(preflight)
    collision_summary = next(
        row
        for row in summaries
        if row.attack_family == "candidate_collision"
        and row.defense_stage == "stage43_recovery"
    )
    assert collision_summary.candidate_collision_recovery_rate == 1.0
    low_drift = next(
        row
        for row in summaries
        if row.attack_family == "low_drift" and row.defense_stage == "unprotected"
    )
    assert low_drift.malicious_answer_surface_rate == 1.0


def test_stage47_attack_generation_resumes_by_query_without_duplicate_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    config = Stage47AdaptiveAttackConfig(
        **{
            key: (2 if key == "max_queries" else value)
            for key, value in {
                field: getattr(config, field)
                for field in Stage47AdaptiveAttackConfig.__dataclass_fields__
            }.items()
        }
    )
    samples = [
        _sample(),
        NormalizedSample(
            query_id="q2",
            query="When did Film Alpha premiere?",
            answer="1999",
            support_doc_ids=["d1"],
            support_docs=[CorpusDocument("d1", "Film Alpha", "clean")],
        ),
    ]
    config.sample_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "query_id": sample.query_id,
                    "query": sample.query,
                    "answer": sample.answer,
                    "support_doc_ids": sample.support_doc_ids,
                    "support_docs": [
                        {
                            "doc_id": doc.doc_id,
                            "title": doc.title,
                            "text": doc.text,
                        }
                        for doc in sample.support_docs
                    ],
                }
            )
            for sample in samples
        )
        + "\n",
        encoding="utf-8",
    )
    clean_rows = []
    for sample in samples:
        row = _context_row()
        row["query_id"] = sample.query_id
        clean_rows.append(row)
    config.clean_context_path.write_text(
        "\n".join(json.dumps(row) for row in clean_rows) + "\n",
        encoding="utf-8",
    )
    config.clean_reference_output_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "logicguard.attack.adaptive.load_candidate_sources", lambda _: _candidates()
    )
    interrupted = _InterruptingClient(interrupt_at=2)

    with pytest.raises(KeyboardInterrupt):
        run_from_config(config, client=interrupted)

    checkpoint = tmp_path / "attacks_checkpoint.jsonl"
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 1
    resumed = _FakeClient()
    records, _ = run_from_config(config, client=resumed)

    assert len(records) == 6
    assert resumed.call_count == 1
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 2


def test_stage47_attack_generation_respects_query_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    config = Stage47AdaptiveAttackConfig(
        **{
            key: (1 if key in {"query_offset", "max_queries"} else value)
            for key, value in {
                field: getattr(config, field)
                for field in Stage47AdaptiveAttackConfig.__dataclass_fields__
            }.items()
        }
    )
    samples = [
        _sample(),
        NormalizedSample(
            query_id="q2",
            query="Where did Film Alpha premiere?",
            answer="London",
            support_doc_ids=["d1"],
            support_docs=[CorpusDocument("d1", "Film Alpha", "clean")],
        ),
    ]
    config.sample_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "query_id": sample.query_id,
                    "query": sample.query,
                    "answer": sample.answer,
                    "support_doc_ids": sample.support_doc_ids,
                    "support_docs": [
                        {
                            "doc_id": doc.doc_id,
                            "title": doc.title,
                            "text": doc.text,
                        }
                        for doc in sample.support_docs
                    ],
                }
            )
            for sample in samples
        )
        + "\n",
        encoding="utf-8",
    )
    row = _context_row()
    row["query_id"] = "q2"
    config.clean_context_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    config.clean_reference_output_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "logicguard.attack.adaptive.load_candidate_sources", lambda _: _candidates()
    )
    client = _FakeClient()

    records, _ = run_from_config(config, client=client)

    assert client.call_count == 1
    assert {record.query_id for record in records} == {"q2"}


def test_stage47_rejects_non_scalar_malicious_target(tmp_path: Path) -> None:
    records, _ = generate_query_attacks(
        config=_config(tmp_path),
        sample=_sample(),
        base_row=_context_row(),
        candidate_sources=_candidates(),
        client=_NullTargetClient(),
    )

    collision = next(
        record for record in records if record.attack_family == "candidate_collision"
    )
    assert collision.valid is False
    assert collision.invalid_reason == "missing_malicious_answer"
    assert collision.malicious_answer == ""


def _sample() -> NormalizedSample:
    return NormalizedSample(
        query_id="q1",
        query="When did Film Alpha premiere?",
        answer="1999",
        support_doc_ids=["d1"],
        support_docs=[
            CorpusDocument(
                doc_id="d1",
                title="Film Alpha",
                text="Film Alpha premiered in 1999 in London.",
            )
        ],
    )


def _context_row() -> dict[str, object]:
    return {
        "query_id": "q1",
        "query": "When did Film Alpha premiere?",
        "method": "full_query_guard",
        "include_entity_names": ["FILM ALPHA"],
        "context_data": {
            "entities": [],
            "sources": [
                {
                    "id": "s1",
                    "logicguard_doc_id": "d1",
                    "title": "Film Alpha",
                    "text": (
                        "Document ID: d1\nTitle: Film Alpha\n\n"
                        "Film Alpha premiered in 1999 in London."
                    ),
                    "source_state": "clean_reference",
                }
            ],
        },
    }


def _candidates() -> list[NonOracleCandidateSource]:
    return [
        _candidate("d1", "Film Alpha", "Film Alpha premiered in 1999 in London.", 1),
        _candidate("d2", "Beta Archive", "Beta Archive is maintained in Paris.", 2),
        _candidate("d3", "Gamma Notes", "Gamma Notes opened in Rome.", 3),
    ]


def _candidate(
    doc_id: str,
    title: str,
    body: str,
    human_id: int,
) -> NonOracleCandidateSource:
    return NonOracleCandidateSource(
        id=f"s-{doc_id}",
        text_unit_id=f"tu-{doc_id}",
        logicguard_doc_id=doc_id,
        official_document_id=f"od-{doc_id}",
        human_readable_id=human_id,
        title=title,
        text=f"Document ID: {doc_id}\nTitle: {title}\n\n{body}",
        n_tokens=20,
    )


def _config(tmp_path: Path) -> Stage47AdaptiveAttackConfig:
    return Stage47AdaptiveAttackConfig(
        dataset="toy",
        sample_path=tmp_path / "sample.jsonl",
        clean_context_path=tmp_path / "clean.jsonl",
        clean_reference_output_dir=tmp_path / "output",
        attack_records_output_path=tmp_path / "attacks.jsonl",
        attack_integrity_output_path=tmp_path / "integrity.jsonl",
        attacked_context_output_path=tmp_path / "attacked.jsonl",
        context_matrix_output_path=tmp_path / "matrix.jsonl",
        valid_context_matrix_output_path=tmp_path / "valid-matrix.jsonl",
        preflight_rows_output_path=tmp_path / "preflight.jsonl",
        preflight_summary_output_path=tmp_path / "summary.csv",
        report_path=tmp_path / "report.md",
        max_queries=1,
    )
