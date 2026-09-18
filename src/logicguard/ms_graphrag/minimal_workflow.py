"""Prepare reproducible Microsoft GraphRAG minimal-workflow workspaces."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.ms_graphrag.prepare_workspace import (
    DocScope,
    MissingSupportPolicy,
    MsGraphRagWorkspaceConfig,
    prepare_ms_graphrag_workspace,
)

MINIMAL_WORKFLOWS = [
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

QUERY_READY_WORKFLOWS = [
    "load_input_documents",
    "create_base_text_units",
    "create_final_documents",
    "extract_graph",
    "finalize_graph",
    "create_communities",
    "create_final_text_units",
    "create_community_reports",
    "generate_text_embeddings",
]


@dataclass(frozen=True, slots=True)
class MsGraphRagMinimalConfig:
    """Configuration for one Microsoft GraphRAG minimal workspace."""

    dataset: str
    sample_path: Path
    corpus_path: Path
    workspace_root: Path
    template_root: Path
    doc_scope: DocScope = "sample_support"
    max_docs: int | None = None
    missing_support_policy: MissingSupportPolicy = "use_embedded"
    completion_model: str = "qwen3.7-plus"
    embedding_model: str = "text-embedding-v4"
    vector_size: int = 1024
    embedding_batch_size: int = 10


def prepare_ms_graphrag_minimal_workspace(
    config: MsGraphRagMinimalConfig,
) -> dict[str, object]:
    """Prepare input files, prompts, settings, and manifest for minimal indexing."""

    manifest = prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset=config.dataset,
            sample_path=config.sample_path,
            corpus_path=config.corpus_path,
            workspace_root=config.workspace_root,
            doc_scope=config.doc_scope,
            max_docs=config.max_docs,
            missing_support_policy=config.missing_support_policy,
        )
    )
    _clear_runtime_dirs(config.workspace_root)
    _copy_prompts(config.template_root / "prompts", config.workspace_root / "prompts")
    settings = build_minimal_settings(config)
    (config.workspace_root / "settings.yaml").write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = {
        **manifest,
        "ms_graphrag_workflow": "minimal",
        "workflows": MINIMAL_WORKFLOWS,
        "completion_model": config.completion_model,
        "embedding_model": config.embedding_model,
        "vector_size": config.vector_size,
        "embedding_batch_size": config.embedding_batch_size,
        "notes": [
            "Use tools/ms_graphrag/.venv/Scripts/graphrag.exe index --root <workspace> to run indexing.",
            "Settings use DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL environment variables; no secret is written to disk.",
            "This minimal workflow intentionally skips create_community_reports_text to avoid the previously observed compatibility stall.",
        ],
    }
    (config.workspace_root / "logicguard_manifest.json").write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def prepare_ms_graphrag_query_ready_workspace(
    config: MsGraphRagMinimalConfig,
) -> dict[str, object]:
    """Prepare a Microsoft GraphRAG workspace that can run official local/global query.

    The previous minimal workflow intentionally skipped community report generation.
    Local/global search needs `community_reports.parquet`, so this variant adds the
    graph-based `create_community_reports` step while still avoiding the text-based
    `create_community_reports_text` workflow that previously stalled.
    """

    manifest = prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset=config.dataset,
            sample_path=config.sample_path,
            corpus_path=config.corpus_path,
            workspace_root=config.workspace_root,
            doc_scope=config.doc_scope,
            max_docs=config.max_docs,
            missing_support_policy=config.missing_support_policy,
        )
    )
    _clear_runtime_dirs(config.workspace_root)
    _copy_prompts(config.template_root / "prompts", config.workspace_root / "prompts")
    settings = build_query_ready_settings(config)
    (config.workspace_root / "settings.yaml").write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest = {
        **manifest,
        "ms_graphrag_workflow": "query_ready",
        "workflows": QUERY_READY_WORKFLOWS,
        "completion_model": config.completion_model,
        "embedding_model": config.embedding_model,
        "vector_size": config.vector_size,
        "embedding_batch_size": config.embedding_batch_size,
        "notes": [
            "Use tools/ms_graphrag/.venv/Scripts/graphrag.exe index --root <workspace> to run indexing.",
            "This workflow adds graph-based create_community_reports so official local/global query can run.",
            "It intentionally avoids create_community_reports_text, which previously stalled in this environment.",
            "Settings use DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL environment variables; no secret is written to disk.",
        ],
    }
    (config.workspace_root / "logicguard_manifest.json").write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def build_minimal_settings(config: MsGraphRagMinimalConfig) -> dict[str, object]:
    """Return a GraphRAG settings payload for the low-cost minimal workflow."""

    return {
        "completion_models": {
            "default_completion_model": {
                "model_provider": "openai",
                "model": config.completion_model,
                "auth_method": "api_key",
                "api_key": "${DASHSCOPE_API_KEY}",
                "api_base": "${DASHSCOPE_BASE_URL}",
                "call_args": {
                    "temperature": 0.0,
                    "enable_thinking": False,
                    "max_completion_tokens": 1600,
                },
                "retry": None,
            }
        },
        "embedding_models": {
            "default_embedding_model": {
                "model_provider": "openai",
                "model": config.embedding_model,
                "auth_method": "api_key",
                "api_key": "${DASHSCOPE_API_KEY}",
                "api_base": "${DASHSCOPE_BASE_URL}",
                "retry": None,
            }
        },
        "input": {"type": "text"},
        "chunking": {
            "type": "tokens",
            "size": 1200,
            "overlap": 100,
            "encoding_model": "o200k_base",
        },
        "input_storage": {"type": "file", "base_dir": "input"},
        "output_storage": {"type": "file", "base_dir": "output"},
        "reporting": {"type": "file", "base_dir": "logs"},
        "cache": {"type": "json", "storage": {"type": "file", "base_dir": "cache"}},
        "vector_store": {
            "type": "lancedb",
            "db_uri": "output\\lancedb",
            "vector_size": config.vector_size,
        },
        "workflows": MINIMAL_WORKFLOWS,
        "embed_text": {
            "embedding_model_id": "default_embedding_model",
            "batch_size": config.embedding_batch_size,
        },
        "extract_graph": {
            "completion_model_id": "default_completion_model",
            "prompt": "prompts/extract_graph.txt",
            "entity_types": ["organization", "person", "geo", "event"],
            "max_gleanings": 0,
        },
        "summarize_descriptions": {
            "completion_model_id": "default_completion_model",
            "prompt": "prompts/summarize_descriptions.txt",
            "max_length": 500,
        },
        "extract_graph_nlp": {
            "text_analyzer": {"extractor_type": "regex_english"},
        },
        "cluster_graph": {"max_cluster_size": 10},
        "snapshots": {"graphml": False, "embeddings": False},
        "local_search": {
            "completion_model_id": "default_completion_model",
            "embedding_model_id": "default_embedding_model",
            "prompt": "prompts/local_search_system_prompt.txt",
        },
        "basic_search": {
            "completion_model_id": "default_completion_model",
            "embedding_model_id": "default_embedding_model",
            "prompt": "prompts/basic_search_system_prompt.txt",
        },
    }


def build_query_ready_settings(config: MsGraphRagMinimalConfig) -> dict[str, object]:
    """Return settings for a low-cost workspace that supports official query methods."""

    settings = build_minimal_settings(config)
    settings["workflows"] = QUERY_READY_WORKFLOWS
    settings["concurrent_requests"] = 1
    settings["async_mode"] = "threaded"
    settings["community_reports"] = {
        "completion_model_id": "default_completion_model",
        "graph_prompt": "prompts/community_report_graph.txt",
        "max_length": 500,
        "max_input_length": 6000,
    }
    settings["global_search"] = {
        "completion_model_id": "default_completion_model",
        "map_prompt": "prompts/global_search_map_system_prompt.txt",
        "reduce_prompt": "prompts/global_search_reduce_system_prompt.txt",
        "knowledge_prompt": "prompts/global_search_knowledge_system_prompt.txt",
    }
    return settings


def _copy_prompts(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Missing GraphRAG prompt template directory: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _clear_runtime_dirs(workspace_root: Path) -> None:
    """Remove stale GraphRAG runtime outputs from a regenerated workspace."""

    resolved_root = workspace_root.resolve()
    for dirname in ("output", "cache", "logs"):
        target = (workspace_root / dirname).resolve()
        if target == resolved_root or resolved_root not in target.parents:
            raise ValueError(f"Refusing to remove path outside workspace: {target}")
        if target.exists():
            shutil.rmtree(target)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare a Microsoft GraphRAG minimal workspace."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--sample-path", type=Path, required=True)
    parser.add_argument("--corpus-path", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--template-root", type=Path, default=Path("outputs/ms_graphrag/template")
    )
    parser.add_argument(
        "--doc-scope", choices=["all", "sample_support"], default="sample_support"
    )
    parser.add_argument("--max-docs", type=int, default=None)
    parser.add_argument(
        "--missing-support-policy",
        choices=["use_embedded", "skip"],
        default="use_embedded",
        help="Whether missing sample support docs may fall back to embedded clean support text.",
    )
    parser.add_argument("--completion-model", default="qwen3.7-plus")
    parser.add_argument("--embedding-model", default="text-embedding-v4")
    parser.add_argument("--vector-size", type=int, default=1024)
    parser.add_argument("--embedding-batch-size", type=int, default=10)
    parser.add_argument("--query-ready", action="store_true")
    args = parser.parse_args()
    config = MsGraphRagMinimalConfig(
        dataset=args.dataset,
        sample_path=args.sample_path,
        corpus_path=args.corpus_path,
        workspace_root=args.workspace_root,
        template_root=args.template_root,
        doc_scope=args.doc_scope,
        max_docs=args.max_docs,
        missing_support_policy=args.missing_support_policy,
        completion_model=args.completion_model,
        embedding_model=args.embedding_model,
        vector_size=args.vector_size,
        embedding_batch_size=args.embedding_batch_size,
    )
    if args.query_ready:
        manifest = prepare_ms_graphrag_query_ready_workspace(config)
    else:
        manifest = prepare_ms_graphrag_minimal_workspace(config)
    print(
        f"{manifest['dataset']}: workflow={manifest['ms_graphrag_workflow']}, queries={manifest['query_count']}, "
        f"input_docs={manifest['input_doc_count']}, workspace={manifest['workspace_root']}"
    )


if __name__ == "__main__":
    main()
