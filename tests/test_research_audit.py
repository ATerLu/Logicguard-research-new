import json
from pathlib import Path

import yaml

from logicguard.benchmark.research_audit import (
    evidence_class,
    match_query,
    records,
    run,
    select_development,
)


def test_history_never_treats_a_document_id_as_a_query() -> None:
    keys = {"q1": {("hotpotqa", "q1")}}
    assert match_query({"doc_id": "q1", "id": "q1"}, "file.json", keys, {})[0] == set()
    assert match_query({"query_id": "q1"}, "file.json", keys, {})[0] == keys["q1"]
    assert (
        match_query({"query_id": "q1", "dataset": "musique"}, "file.json", keys, {})[0]
        == set()
    )


def test_history_requires_dataset_disambiguation() -> None:
    keys = {"q1": {("hotpotqa", "q1"), ("musique", "q1")}}
    assert (
        match_query({"query_id": "q1"}, "file.json", keys, {})[1] == "ambiguous_dataset"
    )
    assert match_query({"query_id": "q1"}, "musique/results.json", keys, {})[0] == {
        ("musique", "q1")
    }
    assert match_query(
        {"question": "  SAME question "},
        "x",
        {},
        {"same question": {("musique", "q2")}},
    )[0] == {("musique", "q2")}


def test_parser_finds_nested_query_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested.jsonl"
    path.write_text(
        '{"rows":[{"query_id":"q1","answer":"private-label"}]}\n', encoding="utf-8"
    )
    found = list(records(path))
    assert any(
        pointer == "line:1.rows[0]" and row.get("query_id") == "q1"
        for pointer, row in found
    )
    assert evidence_class("x/request_plan.jsonl") == "prepared_or_listed"
    assert evidence_class("x/attack_records.jsonl") == "attack_attempt_artifact"


def test_pilot_never_selects_locked_queries_or_uses_outcomes() -> None:
    rows = [
        {
            "query_id": "a",
            "stratum": "2",
            "order_key": "2",
            "split": "development",
            "success": True,
        },
        {
            "query_id": "b",
            "stratum": "2",
            "order_key": "1",
            "split": "development",
            "success": False,
        },
        {
            "query_id": "c",
            "stratum": "4",
            "order_key": "3",
            "split": "development",
            "success": False,
        },
        {
            "query_id": "test",
            "stratum": "4",
            "order_key": "0",
            "split": "locked_test",
            "success": True,
        },
    ]
    assert [row["query_id"] for row in select_development(rows, 2)] == ["b", "c"]
    assert select_development(rows, 3) == select_development(list(reversed(rows)), 3)


def test_audit_end_to_end_is_repeatable_protects_inputs_and_omits_labels(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    splits = tmp_path / "splits"
    (splits / "evaluator_only").mkdir(parents=True)
    rows = [
        {
            "dataset": "hotpotqa",
            "query_id": f"q{index}",
            "question": f"Question {index}?",
            "split": split,
            "stratum": "2",
            "order_key": str(index),
        }
        for index, split in enumerate(("development", "validation", "locked_test"))
    ]
    (splits / "hotpotqa_attacker_safe.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )
    # Deliberately not valid JSON: evaluator contents must only be hashed.
    (splits / "evaluator_only" / "hotpotqa.jsonl").write_text(
        "private-evaluator-label", encoding="utf-8"
    )
    history = tmp_path / "history"
    history.mkdir()
    (history / "clean_traces.jsonl").write_text(
        '{"query_id":"q2","answer":"private-answer"}\n', encoding="utf-8"
    )
    (history / "broken.jsonl").write_text("invalid JSON", encoding="utf-8")
    config = tmp_path / "audit.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "benchmark_version": "comparison-v1.2",
                "audit_date": "2026-09-06",
                "split_root": "splits",
                "datasets": ["hotpotqa"],
                "history_roots": ["history"],
                "history_files": [],
                "excluded_directory_names": [],
                "excluded_filename_fragments": [],
                "max_json_bytes": 1024,
                "development_queries_per_dataset": 1,
                "output_root": "audit_output",
                "protected_artifacts": [],
                "reviewed_sources": [],
            }
        ),
        encoding="utf-8",
    )
    result = run(config)
    assert result["protected_artifacts_unchanged"] is True
    assert result["file_status_counts"] == {"parse_error": 1, "scanned": 1}
    assert result["datasets_and_splits"][2]["execution_or_analysis_overlap"] == 1
    output = tmp_path / "audit_output"
    frozen = {path.name: path.read_bytes() for path in output.iterdir()}
    assert run(config) == result
    assert frozen == {path.name: path.read_bytes() for path in output.iterdir()}
    for payload in frozen.values():
        assert b"private-answer" not in payload
        assert b"private-evaluator-label" not in payload
    pilot = json.loads((output / "wp2_development_queries.jsonl").read_text())
    assert pilot["query_id"] == "q0"
    assert pilot["split"] == "development"
