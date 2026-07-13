import json
from pathlib import Path

from logicguard.ms_graphrag.query_experiment import (
    GraphRagCliResult,
    MsGraphRagQueryExperimentConfig,
    extract_response_preview,
    run_from_config,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _sample_row() -> dict[str, object]:
    return {
        "query_id": "q1",
        "query": "Who directed Atomised?",
        "answer": "Oskar Roehler",
        "support_doc_ids": ["d1"],
        "support_docs": [
            {
                "doc_id": "d1",
                "title": "Atomised",
                "text": "Atomised was directed by Oskar Roehler.",
            }
        ],
    }


def _fake_runner(
    *,
    workspace_root: Path,
    data_dir: Path,
    method: str,
    query: str,
    config: MsGraphRagQueryExperimentConfig,
) -> GraphRagCliResult:
    return GraphRagCliResult(
        command=["graphrag", "query", method, query],
        returncode=0,
        stdout=f"{workspace_root.name} {method} answered Oskar Roehler",
        stderr="",
        elapsed_seconds=0.1,
        timed_out=False,
    )


def test_extract_response_preview_uses_last_nonempty_lines() -> None:
    stdout = "\n".join(
        [
            "",
            "INFO: loading index",
            "",
            "The answer is unavailable from the supplied context.",
            "Please provide more evidence.",
        ]
    )

    assert extract_response_preview(stdout, max_lines=2) == (
        "The answer is unavailable from the supplied context.\nPlease provide more evidence."
    )


def test_run_from_config_writes_query_rows_and_report(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    clean_root = tmp_path / "clean"
    poisoned_root = tmp_path / "poisoned"
    output_path = tmp_path / "queries.jsonl"
    report_path = tmp_path / "report.md"
    (clean_root / "output").mkdir(parents=True)
    (poisoned_root / "output").mkdir(parents=True)
    _write_jsonl(sample_path, [_sample_row()])

    rows = run_from_config(
        MsGraphRagQueryExperimentConfig(
            dataset="toy",
            sample_path=sample_path,
            clean_workspace_root=clean_root,
            poisoned_workspace_root=poisoned_root,
            output_path=output_path,
            report_path=report_path,
            graphrag_cli=Path("graphrag.exe"),
            methods=("basic", "local"),
            max_queries=1,
            community_level=2,
            response_type="Single Sentence",
            timeout_seconds=30,
        ),
        runner=_fake_runner,
    )

    saved_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    report = report_path.read_text(encoding="utf-8")

    assert len(rows) == 4
    assert len(saved_rows) == 4
    assert {row["corpus_state"] for row in saved_rows} == {"clean", "poisoned"}
    assert {row["method"] for row in saved_rows} == {"basic", "local"}
    assert all(row["success"] for row in saved_rows)
    assert all(row["answer_emitted"] for row in saved_rows)
    assert all(row["expected_answer_present"] for row in saved_rows)
    assert "Microsoft GraphRAG 官方 query 级实验报告" in report
    assert "| clean | basic | 1 | 1 | 1 | 1 |" in report


def test_run_from_config_accepts_named_workspace_roots(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    clean_root = tmp_path / "clean"
    guarded_root = tmp_path / "guarded"
    output_path = tmp_path / "queries.jsonl"
    report_path = tmp_path / "report.md"
    (clean_root / "output").mkdir(parents=True)
    (guarded_root / "output").mkdir(parents=True)
    _write_jsonl(sample_path, [_sample_row()])

    rows = run_from_config(
        MsGraphRagQueryExperimentConfig(
            dataset="toy",
            sample_path=sample_path,
            output_path=output_path,
            report_path=report_path,
            graphrag_cli=Path("graphrag.exe"),
            workspace_roots={"clean": clean_root, "guarded": guarded_root},
            methods=("local",),
            max_queries=1,
        ),
        runner=_fake_runner,
    )

    saved_rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 2
    assert {row["corpus_state"] for row in saved_rows} == {"clean", "guarded"}
    assert all(row["method"] == "local" for row in saved_rows)
