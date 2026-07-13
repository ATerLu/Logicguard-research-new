import json
from pathlib import Path

import yaml

from logicguard.ms_graphrag.minimal_workflow import (
    MsGraphRagMinimalConfig,
    prepare_ms_graphrag_query_ready_workspace,
    prepare_ms_graphrag_minimal_workspace,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_prepare_minimal_workspace_writes_prompts_settings_and_manifest(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    template_root = tmp_path / "template"
    workspace_root = tmp_path / "workspace"
    (template_root / "prompts").mkdir(parents=True)
    (template_root / "prompts" / "extract_graph.txt").write_text("extract", encoding="utf-8")
    (template_root / "prompts" / "summarize_descriptions.txt").write_text("summarize", encoding="utf-8")
    (template_root / "prompts" / "local_search_system_prompt.txt").write_text("local", encoding="utf-8")
    (template_root / "prompts" / "basic_search_system_prompt.txt").write_text("basic", encoding="utf-8")

    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Who directed Atomised?",
                "answer": "Oskar Roehler",
                "support_doc_ids": ["d1"],
                "support_docs": [{"doc_id": "d1", "title": "Atomised", "text": "Atomised was directed by Oskar."}],
            }
        ],
    )
    _write_jsonl(
        corpus_path,
        [
            {"_id": "d1", "title": "Atomised", "text": "Atomised was directed by Oskar."},
            {"_id": "d2", "title": "Other", "text": "Unused document."},
        ],
    )

    manifest = prepare_ms_graphrag_minimal_workspace(
        MsGraphRagMinimalConfig(
            dataset="toy",
            sample_path=sample_path,
            corpus_path=corpus_path,
            workspace_root=workspace_root,
            template_root=template_root,
            doc_scope="sample_support",
            max_docs=None,
            completion_model="qwen3.7-plus",
            embedding_model="text-embedding-v4",
            vector_size=1024,
            embedding_batch_size=10,
        )
    )

    settings = yaml.safe_load((workspace_root / "settings.yaml").read_text(encoding="utf-8"))

    assert manifest["input_doc_count"] == 1
    assert (workspace_root / "input" / "d1.txt").exists()
    assert (workspace_root / "prompts" / "extract_graph.txt").read_text(encoding="utf-8") == "extract"
    assert settings["completion_models"]["default_completion_model"]["api_key"] == "${DASHSCOPE_API_KEY}"
    assert settings["embedding_models"]["default_embedding_model"]["api_base"] == "${DASHSCOPE_BASE_URL}"
    assert settings["workflows"] == [
        "load_input_documents",
        "create_base_text_units",
        "create_final_documents",
        "extract_graph_nlp",
        "prune_graph",
        "finalize_graph",
        "create_communities",
        "create_final_text_units",
        "generate_text_embeddings",
    ]
    assert settings["vector_store"]["vector_size"] == 1024


def test_prepare_query_ready_workspace_enables_community_reports(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    template_root = tmp_path / "template"
    workspace_root = tmp_path / "workspace"
    (template_root / "prompts").mkdir(parents=True)
    (workspace_root / "output").mkdir(parents=True)
    (workspace_root / "output" / "stale.parquet").write_text("old", encoding="utf-8")
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
        (template_root / "prompts" / prompt_name).write_text(prompt_name, encoding="utf-8")

    _write_jsonl(
        sample_path,
        [
            {
                "query_id": "q1",
                "query": "Who directed Atomised?",
                "answer": "Oskar Roehler",
                "support_doc_ids": ["d1"],
                "support_docs": [{"doc_id": "d1", "title": "Atomised", "text": "Atomised was directed by Oskar."}],
            }
        ],
    )
    _write_jsonl(corpus_path, [{"_id": "d1", "title": "Atomised", "text": "Atomised was directed by Oskar."}])

    manifest = prepare_ms_graphrag_query_ready_workspace(
        MsGraphRagMinimalConfig(
            dataset="toy",
            sample_path=sample_path,
            corpus_path=corpus_path,
            workspace_root=workspace_root,
            template_root=template_root,
            doc_scope="sample_support",
            completion_model="qwen3.7-plus",
            embedding_model="text-embedding-v4",
        )
    )

    settings = yaml.safe_load((workspace_root / "settings.yaml").read_text(encoding="utf-8"))

    assert manifest["ms_graphrag_workflow"] == "query_ready"
    assert "extract_graph" in settings["workflows"]
    assert "extract_graph_nlp" not in settings["workflows"]
    assert "prune_graph" not in settings["workflows"]
    assert "create_community_reports" in settings["workflows"]
    assert "create_community_reports_text" not in settings["workflows"]
    assert settings["community_reports"]["graph_prompt"] == "prompts/community_report_graph.txt"
    assert settings["global_search"]["map_prompt"] == "prompts/global_search_map_system_prompt.txt"
    assert settings["concurrent_requests"] == 1
    assert not (workspace_root / "output" / "stale.parquet").exists()
