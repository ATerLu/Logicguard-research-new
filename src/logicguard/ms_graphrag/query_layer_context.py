"""Export Stage20 contexts through GraphRAG's official local context builder."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.ms_graphrag.official_local_context import (
    apply_local_search_overrides,
    serialize_context_data,
)


@dataclass(frozen=True, slots=True)
class ResolvedMethodEntities:
    """Validated entity controls passed to LocalSearchMixedContext."""

    include_entity_names: list[str]
    exclude_entity_names: list[str]
    unknown_entity_names: list[str]


@dataclass(frozen=True, slots=True)
class QueryLayerContextConfig:
    """Configuration shared by seed planning and official context export."""

    dataset: str
    sample_path: Path
    workspace_root: Path
    seed_plan_path: Path
    output_path: Path
    report_path: Path
    methods: list[str]
    max_queries: int
    community_level: int
    response_type: str
    local_search_overrides: dict[str, float | int]
    emit_markdown_report: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> "QueryLayerContextConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: str) -> Path:
            candidate = Path(raw)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(str(payload["sample_path"])),
            workspace_root=resolve(str(payload["workspace_root"])),
            seed_plan_path=resolve(str(payload["seed_plan_output_path"])),
            output_path=resolve(str(payload["context_output_path"])),
            report_path=resolve(str(payload["context_report_path"])),
            methods=[str(method) for method in payload["methods"]],
            max_queries=int(payload.get("max_queries", 5)),
            community_level=int(payload.get("community_level", 2)),
            response_type=str(payload.get("response_type", "Single Sentence")),
            local_search_overrides={
                str(key): value
                for key, value in payload.get("local_search_overrides", {}).items()
            },
            emit_markdown_report=bool(payload.get("emit_markdown_report", True)),
        )


class ContextBuilder(Protocol):
    """Small structural interface used by tests and GraphRAG's real builder."""

    def build_context(self, *, query: str, **kwargs: Any) -> Any: ...


def resolve_method_entities(
    *,
    plan: dict[str, Any],
    method: str,
    available_entity_names: set[str],
) -> ResolvedMethodEntities:
    """Filter plan controls to exact GraphRAG entity titles."""

    method_plan = plan.get("methods", {}).get(method, {})
    raw_include = [str(name) for name in method_plan.get("include_entity_names", [])]
    raw_exclude = [str(name) for name in method_plan.get("exclude_entity_names", [])]
    include = _deduplicate(
        name for name in raw_include if name in available_entity_names
    )
    include_set = set(include)
    exclude = _deduplicate(
        name
        for name in raw_exclude
        if name in available_entity_names and name not in include_set
    )
    unknown = _deduplicate(
        name for name in raw_include + raw_exclude if name not in available_entity_names
    )
    return ResolvedMethodEntities(include, exclude, unknown)


def resolve_entity_adapter_community_level(
    *,
    configured_community_level: int,
    community_prop: float,
) -> int | None:
    """Keep unclustered entities when community reports are not part of context.

    GraphRAG's indexer adapter filters out entities without a community when a
    level is supplied. In a local-only protocol those memberships are not
    required, and dropping them can remove entire disconnected components from
    the query candidate space.
    """

    if community_prop == 0.0:
        return None
    return configured_community_level


def build_query_guard_context_rows(
    *,
    query_rows: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    methods: list[str],
    available_entity_names: set[str],
    context_builder: ContextBuilder,
    context_builder_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build one official context row per query and Stage20 method."""

    plan_by_query = {str(plan["query_id"]): plan for plan in plans}
    rows: list[dict[str, Any]] = []
    for query_row in query_rows:
        query_id = str(query_row["query_id"])
        query = str(query_row["query"])
        plan = plan_by_query.get(query_id)
        if plan is None:
            raise ValueError(f"Missing Stage20 seed plan for query_id={query_id}")
        for method in methods:
            resolved = resolve_method_entities(
                plan=plan,
                method=method,
                available_entity_names=available_entity_names,
            )
            result = context_builder.build_context(
                query=query,
                include_entity_names=resolved.include_entity_names,
                exclude_entity_names=resolved.exclude_entity_names,
                **context_builder_params,
            )
            rows.append(
                {
                    "query_id": query_id,
                    "query": query,
                    "method": method,
                    "include_entity_names": resolved.include_entity_names,
                    "exclude_entity_names": resolved.exclude_entity_names,
                    "unknown_entity_names": resolved.unknown_entity_names,
                    "fallback_to_baseline": not (
                        resolved.include_entity_names or resolved.exclude_entity_names
                    ),
                    "context_text": str(result.context_chunks),
                    "context_data": serialize_context_data(result.context_records),
                }
            )
    return rows


def run_from_config(config: QueryLayerContextConfig) -> list[dict[str, Any]]:
    """Load official GraphRAG artifacts and export all Stage20 contexts."""

    builder, builder_params, entity_names = _load_official_context_builder(config)
    rows = build_query_guard_context_rows(
        query_rows=_load_query_rows(config.sample_path, config.max_queries),
        plans=_load_jsonl(config.seed_plan_path),
        methods=config.methods,
        available_entity_names=entity_names,
        context_builder=builder,
        context_builder_params=builder_params,
    )
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    full_context_path = config.output_path.with_name(
        f"{config.output_path.stem}_full_query_guard{config.output_path.suffix}"
    )
    write_method_context_rows(
        path=full_context_path,
        rows=rows,
        method="full_query_guard",
    )
    if config.emit_markdown_report:
        _write_context_report(config, rows)
    return rows


def write_method_context_rows(
    *,
    path: Path,
    rows: list[dict[str, Any]],
    method: str,
) -> int:
    """Write a single-method context file for downstream answer experiments."""

    selected = [row for row in rows if str(row.get("method")) == method]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(selected)


def _load_official_context_builder(
    config: QueryLayerContextConfig,
) -> tuple[ContextBuilder, dict[str, Any], set[str]]:
    """Construct GraphRAG 3.1.0's LocalSearchMixedContext without calling the answer LLM."""

    try:
        from graphrag.cli.query import _resolve_output_files
        from graphrag.config.embeddings import entity_description_embedding
        from graphrag.config.load_config import load_config
        from graphrag.query.factory import get_local_search_engine
        from graphrag.query.indexer_adapters import (
            read_indexer_covariates,
            read_indexer_entities,
            read_indexer_relationships,
            read_indexer_reports,
            read_indexer_text_units,
        )
        from graphrag.utils.api import get_embedding_store
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Run Stage20 context export with tools/ms_graphrag/.venv and PYTHONPATH=src."
        ) from exc

    workspace_root = config.workspace_root.resolve()
    output_dir = (workspace_root / "output").resolve()
    graph_config = load_config(
        root_dir=workspace_root,
        cli_overrides={"output_storage": {"base_dir": str(output_dir)}},
    )
    apply_local_search_overrides(graph_config, config.local_search_overrides)
    frames = _resolve_output_files(
        config=graph_config,
        output_list=[
            "communities",
            "community_reports",
            "text_units",
            "relationships",
            "entities",
        ],
        optional_list=["covariates"],
    )
    entity_community_level = resolve_entity_adapter_community_level(
        configured_community_level=config.community_level,
        community_prop=float(graph_config.local_search.community_prop),
    )
    entities = read_indexer_entities(
        frames["entities"],
        frames["communities"],
        entity_community_level,
    )
    reports = read_indexer_reports(
        frames["community_reports"],
        frames["communities"],
        config.community_level,
    )
    covariates = (
        read_indexer_covariates(frames["covariates"])
        if frames["covariates"] is not None
        else []
    )
    embedding_store = get_embedding_store(
        config=graph_config.vector_store,
        embedding_name=entity_description_embedding,
    )
    engine = get_local_search_engine(
        config=graph_config,
        reports=reports,
        text_units=read_indexer_text_units(frames["text_units"]),
        entities=entities,
        relationships=read_indexer_relationships(frames["relationships"]),
        covariates={"claims": covariates},
        description_embedding_store=embedding_store,
        response_type=config.response_type,
    )
    return (
        engine.context_builder,
        dict(engine.context_builder_params),
        {entity.title for entity in entities},
    )


def _write_context_report(
    config: QueryLayerContextConfig, rows: list[dict[str, Any]]
) -> None:
    table = [
        "| method | rows | avg include | avg exclude | fallback |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for method in config.methods:
        method_rows = [row for row in rows if row["method"] == method]
        count = len(method_rows)
        avg_include = (
            sum(len(row["include_entity_names"]) for row in method_rows) / count
            if count
            else 0.0
        )
        avg_exclude = (
            sum(len(row["exclude_entity_names"]) for row in method_rows) / count
            if count
            else 0.0
        )
        fallback = sum(bool(row["fallback_to_baseline"]) for row in method_rows)
        table.append(
            f"| {method} | {count} | {avg_include:.2f} | {avg_exclude:.2f} | {fallback} |"
        )
    content = "\n".join(
        [
            "# Microsoft GraphRAG Stage20 Query-layer Context导出报告",
            "",
            "## 实验目的",
            "",
            "通过GraphRAG 3.1.0官方LocalSearchMixedContext接口注入或排除实体，不修改官方源码，也不调用回答模型。",
            "",
            "## 指标说明",
            "",
            "- avg include：每个query显式前置的实体数。",
            "- avg exclude：每个query从embedding候选中排除的异常实体数。",
            "- fallback：没有有效include/exclude并退化为baseline的query数。",
            "",
            "## 导出汇总",
            "",
            *table,
            "",
            f"- 输出：{config.output_path.as_posix()}",
            f"- 总行数：{len(rows)}",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _load_query_rows(path: Path, max_queries: int) -> list[dict[str, str]]:
    return [
        {"query_id": str(row["query_id"]), "query": str(row["query"])}
        for row in _load_jsonl(path)[:max_queries]
    ]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected JSON object in {path}")
                rows.append(payload)
    return rows


def _deduplicate(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Stage20 official query-layer contexts."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_query_layer_stage20.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(QueryLayerContextConfig.from_yaml(args.config))
    print(f"stage20_context_rows={len(rows)}")


if __name__ == "__main__":
    main()
