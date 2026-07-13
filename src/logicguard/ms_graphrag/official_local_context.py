"""Export official Microsoft GraphRAG local-search context data.

This module must be runnable from the Microsoft GraphRAG virtual environment
because the main LogicGuard uv environment intentionally does not depend on the
heavy `graphrag` package. Set `PYTHONPATH=<logicguard>/src` and execute this
module with `tools/ms_graphrag/.venv/Scripts/python.exe`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import yaml

from logicguard.data.prepare import load_normalized_samples

if TYPE_CHECKING:
    from logicguard.ms_graphrag.query_time_defense import GraphRagTextUnitEvidence

_DOC_ID_PATTERN = re.compile(r"^Document ID:\s*(?P<doc_id>.+?)\s*$", re.MULTILINE)
_TITLE_PATTERN = re.compile(r"^Title:\s*(?P<title>.*?)\s*$", re.MULTILINE)
_SUPPORTED_LOCAL_SEARCH_OVERRIDES = {
    "text_unit_prop",
    "community_prop",
    "top_k_entities",
    "top_k_relationships",
    "max_context_tokens",
}


@dataclass(frozen=True, slots=True)
class OfficialLocalContextConfig:
    """Configuration for exporting official GraphRAG local-search contexts."""

    dataset: str
    sample_path: Path
    workspace_root: Path
    output_path: Path
    report_path: Path
    community_level: int = 2
    response_type: str = "Single Sentence"
    max_queries: int = 1
    verbose: bool = False
    local_search_overrides: dict[str, float | int] | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "OfficialLocalContextConfig":
        """Load YAML configuration with project-relative paths."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(payload["sample_path"]),
            workspace_root=resolve_project_path(payload["workspace_root"]),
            output_path=resolve_project_path(payload["output_path"]),
            report_path=resolve_project_path(payload["report_path"]),
            community_level=int(payload.get("community_level", 2)),
            response_type=str(payload.get("response_type", "Single Sentence")),
            max_queries=int(payload.get("max_queries", 1)),
            verbose=bool(payload.get("verbose", False)),
            local_search_overrides=_parse_local_search_overrides(payload.get("local_search_overrides")),
        )


def run_from_config(config: OfficialLocalContextConfig) -> list[dict[str, Any]]:
    """Run official `api.local_search` and write response/context JSONL."""

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")
    rows = asyncio.run(_run_official_local_search(config))
    write_official_context_rows(config.output_path, rows)
    write_official_context_report(config.report_path, config, rows)
    return rows


async def _run_official_local_search(config: OfficialLocalContextConfig) -> list[dict[str, Any]]:
    try:
        import graphrag.api as api
        from graphrag.cli.query import _resolve_output_files
        from graphrag.config.load_config import load_config
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Microsoft GraphRAG is not installed in this Python environment. "
            "Run this module with tools/ms_graphrag/.venv/Scripts/python.exe and PYTHONPATH=src."
        ) from exc

    workspace_root = config.workspace_root.resolve()
    output_dir = (workspace_root / "output").resolve()
    graph_config = load_config(
        root_dir=workspace_root,
        cli_overrides={"output_storage": {"base_dir": str(output_dir)}},
    )
    apply_local_search_overrides(graph_config, config.local_search_overrides or {})
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
    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    rows: list[dict[str, Any]] = []
    for sample in samples:
        response, context_data = await api.local_search(
            config=graph_config,
            entities=frames["entities"],
            communities=frames["communities"],
            community_reports=frames["community_reports"],
            text_units=frames["text_units"],
            relationships=frames["relationships"],
            covariates=frames["covariates"],
            community_level=config.community_level,
            response_type=config.response_type,
            query=sample.query,
            verbose=config.verbose,
        )
        rows.append(
            {
                "dataset": config.dataset,
                "query_id": sample.query_id,
                "query": sample.query,
                "expected_answer": sample.answer,
                "workspace_root": str(workspace_root),
                "community_level": config.community_level,
                "response_type": config.response_type,
                "response": str(response),
                "context_data": serialize_context_data(context_data),
            }
        )
    return rows


def serialize_context_data(context_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert official context-data DataFrames into JSON records."""

    serialized: dict[str, list[dict[str, Any]]] = {}
    for key, value in context_data.items():
        if isinstance(value, pd.DataFrame):
            records = value.to_dict(orient="records")
        elif isinstance(value, list):
            records = value
        else:
            records = []
        clean_records: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            clean_record = _json_safe_record(record)
            if key == "sources" and "text" in clean_record:
                source_text = str(clean_record["text"])
                clean_record["logicguard_doc_id"] = parse_doc_id_from_source_text(source_text)
                clean_record["title"] = parse_title_from_source_text(source_text)
            clean_records.append(clean_record)
        serialized[key] = clean_records
    return serialized


def apply_local_search_overrides(graph_config: Any, overrides: dict[str, float | int]) -> None:
    """Apply a small allowlisted set of local-search config overrides."""

    local_search = getattr(graph_config, "local_search")
    for key, value in overrides.items():
        if key not in _SUPPORTED_LOCAL_SEARCH_OVERRIDES:
            raise ValueError(f"Unsupported local_search override: {key}")
        if not hasattr(local_search, key):
            raise ValueError(f"GraphRAG local_search config has no field: {key}")
        setattr(local_search, key, value)


def extract_source_evidence(row: dict[str, Any]) -> list[GraphRagTextUnitEvidence]:
    """Extract ranked source evidence from one serialized official context row."""

    from logicguard.ms_graphrag.query_time_defense import GraphRagTextUnitEvidence

    context_data = row.get("context_data", {})
    if not isinstance(context_data, dict):
        return []
    sources = context_data.get("sources", [])
    if not isinstance(sources, list):
        return []

    evidence: list[GraphRagTextUnitEvidence] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        text = str(source.get("text", ""))
        source_id = str(source.get("id", index))
        doc_id = str(source.get("logicguard_doc_id") or parse_doc_id_from_source_text(text))
        title = str(source.get("title") or parse_title_from_source_text(text))
        evidence.append(
            GraphRagTextUnitEvidence(
                text_unit_id=f"official-source-{source_id}",
                human_readable_id=_safe_int(source_id, default=index),
                official_document_id=f"official-source-{source_id}",
                logicguard_doc_id=doc_id,
                title=title,
                text=text,
                n_tokens=len(text.split()),
                score=float(len(sources) - index),
                source_state="official_local_context",
            )
        )
    return evidence


def write_official_context_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write official context rows as UTF-8 JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_official_context_report(
    path: Path,
    config: OfficialLocalContextConfig,
    rows: list[dict[str, Any]],
) -> None:
    """Write a compact Chinese report for official local context export."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| query_id | sources | entities | relationships | reports | response preview |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        context = row.get("context_data", {})
        if not isinstance(context, dict):
            context = {}
        table_lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("query_id", "")),
                    str(len(context.get("sources", []))),
                    str(len(context.get("entities", []))),
                    str(len(context.get("relationships", []))),
                    str(len(context.get("reports", []))),
                    _compact_cell(str(row.get("response", ""))),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Microsoft GraphRAG official local context 导出报告",
            "",
            "## 实验目的",
            "",
            "本阶段直接调用 Microsoft GraphRAG Python `api.local_search`，导出官方 local search 的 `context_data`，包括 sources、entities、relationships 和 reports。该产物用于后续把 LogicGuard 接到真正的 official local query context 上。",
            "",
            "## 配置摘要",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 样本数：`{config.max_queries}`",
            f"- workspace：`{config.workspace_root}`",
            f"- community_level：`{config.community_level}`",
            f"- response_type：`{config.response_type}`",
            f"- local_search_overrides：`{config.local_search_overrides or {}}`",
            "",
            "## 导出结果",
            "",
            *table_lines,
            "",
            "## 产物路径",
            "",
            f"- JSONL：`{config.output_path}`",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def parse_doc_id_from_source_text(text: str) -> str:
    match = _DOC_ID_PATTERN.search(text)
    return match.group("doc_id").strip() if match else ""


def parse_title_from_source_text(text: str) -> str:
    match = _TITLE_PATTERN.search(text)
    return match.group("title").strip() if match else ""


def _parse_local_search_overrides(raw_value: object) -> dict[str, float | int] | None:
    if raw_value in (None, ""):
        return None
    if not isinstance(raw_value, dict):
        raise ValueError("local_search_overrides must be a mapping")
    overrides: dict[str, float | int] = {}
    for key, value in raw_value.items():
        name = str(key)
        if name not in _SUPPORTED_LOCAL_SEARCH_OVERRIDES:
            raise ValueError(f"Unsupported local_search override: {name}")
        if not isinstance(value, (int, float)):
            raise ValueError(f"local_search override must be numeric: {name}")
        overrides[name] = value
    return overrides


def _json_safe_record(record: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in record.items():
        if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
            clean[str(key)] = None
        elif isinstance(value, (list, tuple)):
            clean[str(key)] = list(value)
        else:
            clean[str(key)] = value
    return clean


def _safe_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _compact_cell(value: str, max_chars: int = 160) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Export official Microsoft GraphRAG local context data.")
    parser.add_argument("--config", type=Path, default=Path("configs/ms_graphrag_official_local_context_stage12.yaml"))
    args = parser.parse_args()
    rows = run_from_config(OfficialLocalContextConfig.from_yaml(args.config))
    for row in rows:
        context = row.get("context_data", {})
        sources = context.get("sources", []) if isinstance(context, dict) else []
        print(f"{row['dataset']}/{row['query_id']}: sources={len(sources)}, response={_compact_cell(str(row['response']))}")


if __name__ == "__main__":
    main()
