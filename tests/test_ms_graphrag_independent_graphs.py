import csv
import json
from pathlib import Path

from logicguard.ms_graphrag.independent_graphs import (
    Stage18IndependentGraphConfig,
    build_independent_graph_comparison_rows,
    prepare_independent_query_ready_workspaces,
    write_stage18_comparison_artifacts,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_required_prompts(template_root: Path) -> None:
    prompt_dir = template_root / "prompts"
    prompt_dir.mkdir(parents=True)
    for prompt_name in [
        "extract_graph.txt",
        "summarize_descriptions.txt",
        "local_search_system_prompt.txt",
        "basic_search_system_prompt.txt",
        "community_report_graph.txt",
        "global_search_map_system_prompt.txt",
        "global_search_reduce_system_prompt.txt",
        "global_search_knowledge_system_prompt.txt",
    ]:
        (prompt_dir / prompt_name).write_text(prompt_name, encoding="utf-8")


def test_prepare_independent_query_ready_workspaces_writes_per_query_samples_and_manifests(
    tmp_path: Path,
) -> None:
    sample_path = tmp_path / "samples.jsonl"
    corpus_path = tmp_path / "poisoned" / "corpus.jsonl"
    template_root = tmp_path / "template"
    sample_output_root = tmp_path / "stage18_samples"
    workspace_root = tmp_path / "stage18_workspaces"
    manifest_path = tmp_path / "stage18_manifest.json"
    _write_required_prompts(template_root)
    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "query/one",
                "query": "Who directed Alpha?",
                "answer": "Alice",
                "support_doc_ids": ["d1"],
                "support_docs": [
                    {"doc_id": "d1", "title": "Alpha", "text": "Alpha text."}
                ],
            },
            {
                "query_id": "query two",
                "query": "Who directed Beta?",
                "answer": "Bob",
                "support_doc_ids": ["d2"],
                "support_docs": [
                    {"doc_id": "d2", "title": "Beta", "text": "Beta text."}
                ],
            },
        ],
    )
    _write_jsonl(
        corpus_path,
        [
            {"_id": "d1", "title": "Alpha", "text": "Alpha poisoned text."},
            {"_id": "d2", "title": "Beta", "text": "Beta poisoned text."},
            {"_id": "unused", "title": "Unused", "text": "Unused text."},
        ],
    )

    manifest = prepare_independent_query_ready_workspaces(
        Stage18IndependentGraphConfig(
            dataset="toy",
            sample_path=sample_path,
            poisoned_corpus_path=corpus_path,
            sample_output_root=sample_output_root,
            workspace_root=workspace_root,
            template_root=template_root,
            manifest_path=manifest_path,
            max_queries=2,
            completion_model="qwen3.7-plus",
            embedding_model="text-embedding-v4",
        )
    )

    assert manifest["selected_query_count"] == 2
    assert len(manifest["workspaces"]) == 2
    first_workspace = Path(manifest["workspaces"][0]["workspace_root"])
    second_workspace = Path(manifest["workspaces"][1]["workspace_root"])
    first_sample = Path(manifest["workspaces"][0]["sample_path"])
    second_sample = Path(manifest["workspaces"][1]["sample_path"])

    assert first_sample.read_text(encoding="utf-8").count("\n") == 1
    assert second_sample.read_text(encoding="utf-8").count("\n") == 1
    assert (first_workspace / "input" / "d1.txt").exists()
    assert not (first_workspace / "input" / "d2.txt").exists()
    assert (second_workspace / "input" / "d2.txt").exists()
    assert manifest_path.exists()
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved_manifest["workspaces"][0]["input_doc_count"] == 1
    assert saved_manifest["workspaces"][0]["support_doc_ids"] == ["d1"]


def test_build_independent_graph_comparison_rows_measures_recall_and_entity_gain() -> (
    None
):
    rows = build_independent_graph_comparison_rows(
        mixed_recall_rows=[
            {
                "query_id": "q1",
                "gold_support_recall": "0.0000",
                "diagnosis": "context_recall_failure",
                "context_doc_ids": "x;y",
            },
            {
                "query_id": "q2",
                "gold_support_recall": "1.0000",
                "diagnosis": "attack_recovered",
                "context_doc_ids": "a;b",
            },
        ],
        independent_recall_rows=[
            {
                "query_id": "q1",
                "gold_support_recall": "1.0000",
                "diagnosis": "attack_recovered",
                "context_doc_ids": "d1;d2",
            },
            {
                "query_id": "q2",
                "gold_support_recall": "1.0000",
                "diagnosis": "attack_recovered",
                "context_doc_ids": "a;b",
            },
        ],
        mixed_entity_rows=[
            {
                "query_id": "q1",
                "support_title_entity_hit_rate": "0.0000",
                "top_entity_names": "Wrong Entity",
            },
            {
                "query_id": "q2",
                "support_title_entity_hit_rate": "1.0000",
                "top_entity_names": "Right Entity",
            },
        ],
        independent_entity_rows=[
            {
                "query_id": "q1",
                "support_title_entity_hit_rate": "1.0000",
                "top_entity_names": "Gold Entity",
            },
            {
                "query_id": "q2",
                "support_title_entity_hit_rate": "1.0000",
                "top_entity_names": "Right Entity",
            },
        ],
    )

    assert len(rows) == 2
    assert rows[0].query_id == "q1"
    assert rows[0].recall_status == "improved"
    assert rows[0].gold_support_recall_delta == 1.0
    assert rows[0].support_title_entity_hit_rate_delta == 1.0
    assert rows[1].recall_status == "unchanged"


def test_write_stage18_comparison_artifacts_outputs_csv_and_chinese_report(
    tmp_path: Path,
) -> None:
    rows = build_independent_graph_comparison_rows(
        mixed_recall_rows=[
            {
                "query_id": "q1",
                "gold_support_recall": "0.0000",
                "diagnosis": "context_recall_failure",
            }
        ],
        independent_recall_rows=[
            {
                "query_id": "q1",
                "gold_support_recall": "1.0000",
                "diagnosis": "attack_recovered",
            }
        ],
        mixed_entity_rows=[
            {"query_id": "q1", "support_title_entity_hit_rate": "0.0000"}
        ],
        independent_entity_rows=[
            {"query_id": "q1", "support_title_entity_hit_rate": "1.0000"}
        ],
    )
    csv_path = tmp_path / "comparison.csv"
    report_path = tmp_path / "report.md"

    write_stage18_comparison_artifacts(
        csv_path=csv_path,
        report_path=report_path,
        rows=rows,
        mixed_context_label="5-query mixed graph",
        independent_context_label="per-query independent graph",
    )

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    report = report_path.read_text(encoding="utf-8")

    assert saved[0]["query_id"] == "q1"
    assert saved[0]["recall_status"] == "improved"
    assert "Stage18" in report
    assert "独立图" in report
    assert "gold_support_recall" in report
