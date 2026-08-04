"""One-command official Microsoft GraphRAG local-query LogicGuard pipeline.

The pipeline intentionally stays thin: Microsoft GraphRAG still builds the
official local-search context in its own virtual environment, and LogicGuard
still performs answer-time defense in the main uv environment. This module only
keeps the two steps reproducible and ordered from a single YAML configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.llm.provider import OpenAICompatibleChatClient
from logicguard.ms_graphrag.official_local_context import OfficialLocalContextConfig
from logicguard.ms_graphrag.query_time_defense import (
    QueryTimeDefenseConfig,
    QueryTimeDefenseResult,
    run_from_config as run_query_time_defense,
)

ContextExporter = Callable[[OfficialLocalContextConfig], None]
DefenseRunner = Callable[
    [QueryTimeDefenseConfig, OpenAICompatibleChatClient | None],
    list[QueryTimeDefenseResult],
]


@dataclass(frozen=True, slots=True)
class OfficialQueryPipelineConfig:
    """Configuration for the stage13 official-query LogicGuard pipeline."""

    project_root: Path
    dataset: str
    sample_path: Path
    poisoned_workspace_root: Path
    clean_reference_workspace_root: Path
    query_integrity_path: Path
    official_context_output_path: Path
    official_context_report_path: Path
    context_export_config_path: Path
    defense_output_path: Path
    defense_report_path: Path
    pipeline_report_path: Path
    graphrag_python_path: Path
    models: list[str]
    community_level: int = 2
    response_type: str = "Single Sentence"
    max_queries: int = 1
    verbose: bool = False
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url_env: str = "DASHSCOPE_BASE_URL"
    top_k: int = 4
    max_units: int = 4
    max_chars_per_unit: int = 900
    temperature: float = 0.0
    max_tokens: int = 64
    timeout_seconds: int = 90
    context_export_timeout_seconds: int = 600

    @classmethod
    def from_yaml(cls, path: Path) -> "OfficialQueryPipelineConfig":
        """Load a single pipeline YAML and resolve project-relative paths."""

        config_path = path.resolve()
        project_root = config_path.parents[1]
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            project_root=project_root,
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(str(payload["sample_path"])),
            poisoned_workspace_root=resolve_project_path(
                str(payload["poisoned_workspace_root"])
            ),
            clean_reference_workspace_root=resolve_project_path(
                str(payload["clean_reference_workspace_root"])
            ),
            query_integrity_path=resolve_project_path(
                str(payload["query_integrity_path"])
            ),
            official_context_output_path=resolve_project_path(
                str(payload["official_context_output_path"])
            ),
            official_context_report_path=resolve_project_path(
                str(payload["official_context_report_path"])
            ),
            context_export_config_path=resolve_project_path(
                str(payload["context_export_config_path"])
            ),
            defense_output_path=resolve_project_path(
                str(payload["defense_output_path"])
            ),
            defense_report_path=resolve_project_path(
                str(payload["defense_report_path"])
            ),
            pipeline_report_path=resolve_project_path(
                str(payload["pipeline_report_path"])
            ),
            graphrag_python_path=resolve_project_path(
                str(payload["graphrag_python_path"])
            ),
            models=[str(model) for model in payload["models"]],
            community_level=int(payload.get("community_level", 2)),
            response_type=str(payload.get("response_type", "Single Sentence")),
            max_queries=int(payload.get("max_queries", 1)),
            verbose=bool(payload.get("verbose", False)),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            top_k=int(payload.get("top_k", 4)),
            max_units=int(payload.get("max_units", 4)),
            max_chars_per_unit=int(payload.get("max_chars_per_unit", 900)),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 90)),
            context_export_timeout_seconds=int(
                payload.get("context_export_timeout_seconds", 600)
            ),
        )

    def to_official_context_config(self) -> OfficialLocalContextConfig:
        """Build the official GraphRAG local context export config."""

        return OfficialLocalContextConfig(
            dataset=self.dataset,
            sample_path=self.sample_path,
            workspace_root=self.poisoned_workspace_root,
            output_path=self.official_context_output_path,
            report_path=self.official_context_report_path,
            community_level=self.community_level,
            response_type=self.response_type,
            max_queries=self.max_queries,
            verbose=self.verbose,
        )

    def to_defense_config(self) -> QueryTimeDefenseConfig:
        """Build the LogicGuard answer-time defense config."""

        return QueryTimeDefenseConfig(
            dataset=self.dataset,
            sample_path=self.sample_path,
            poisoned_workspace_root=self.poisoned_workspace_root,
            clean_reference_workspace_root=self.clean_reference_workspace_root,
            query_integrity_path=self.query_integrity_path,
            output_path=self.defense_output_path,
            report_path=self.defense_report_path,
            models=self.models,
            official_context_path=self.official_context_output_path,
            evidence_source="official_local_context",
            api_key_env=self.api_key_env,
            base_url_env=self.base_url_env,
            max_queries=self.max_queries,
            top_k=self.top_k,
            max_units=self.max_units,
            max_chars_per_unit=self.max_chars_per_unit,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class OfficialQueryPipelineSummary:
    """Compact summary returned by a pipeline run."""

    dataset: str
    context_row_count: int
    defense_result_count: int
    correct_count: int
    abstained_count: int
    incorrect_count: int
    official_context_path: Path
    defense_output_path: Path
    pipeline_report_path: Path


def run_from_config(
    config: OfficialQueryPipelineConfig,
    *,
    client: OpenAICompatibleChatClient | None = None,
    context_exporter: ContextExporter | None = None,
    defense_runner: DefenseRunner | None = None,
) -> OfficialQueryPipelineSummary:
    """Export official local context, run LogicGuard defense, and report."""

    context_config = config.to_official_context_config()
    defense_config = config.to_defense_config()
    write_context_export_config(context_config, config.context_export_config_path)

    exporter = context_exporter or (
        lambda export_config: export_context_via_subprocess(config, export_config)
    )
    runner = defense_runner or _run_defense
    exporter(context_config)

    context_rows = load_jsonl_records(context_config.output_path)
    results = runner(defense_config, client)
    summary = OfficialQueryPipelineSummary(
        dataset=config.dataset,
        context_row_count=len(context_rows),
        defense_result_count=len(results),
        correct_count=sum(1 for result in results if result.is_correct),
        abstained_count=sum(1 for result in results if result.is_abstained),
        incorrect_count=sum(1 for result in results if result.is_incorrect),
        official_context_path=context_config.output_path,
        defense_output_path=defense_config.output_path,
        pipeline_report_path=config.pipeline_report_path,
    )
    write_pipeline_report(
        config.pipeline_report_path, config, context_rows, results, summary
    )
    return summary


def export_context_via_subprocess(
    pipeline_config: OfficialQueryPipelineConfig,
    context_config: OfficialLocalContextConfig,
) -> None:
    """Run official context export inside the Microsoft GraphRAG venv."""

    command = build_context_export_command(
        pipeline_config, pipeline_config.context_export_config_path
    )
    env = os.environ.copy()
    src_path = str(pipeline_config.project_root / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else src_path + os.pathsep + env["PYTHONPATH"]
    )
    completed = subprocess.run(
        command,
        cwd=pipeline_config.project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=pipeline_config.context_export_timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Official GraphRAG local context export failed.\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    if not context_config.output_path.exists():
        raise FileNotFoundError(
            f"Official context export did not create: {context_config.output_path}"
        )


def build_context_export_command(
    config: OfficialQueryPipelineConfig, export_config_path: Path
) -> list[str]:
    """Return the reproducible subprocess command used for context export."""

    return [
        str(config.graphrag_python_path),
        "-m",
        "logicguard.ms_graphrag.official_local_context",
        "--config",
        str(export_config_path),
    ]


def write_context_export_config(config: OfficialLocalContextConfig, path: Path) -> None:
    """Persist the derived official-context config for reproducibility."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": config.dataset,
        "sample_path": str(config.sample_path),
        "workspace_root": str(config.workspace_root),
        "output_path": str(config.output_path),
        "report_path": str(config.report_path),
        "community_level": config.community_level,
        "response_type": config.response_type,
        "max_queries": config.max_queries,
        "verbose": config.verbose,
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Read a UTF-8 JSONL artifact into dictionaries."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
    return records


def write_pipeline_report(
    path: Path,
    config: OfficialQueryPipelineConfig,
    context_rows: list[dict[str, Any]],
    results: list[QueryTimeDefenseResult],
    summary: OfficialQueryPipelineSummary,
) -> None:
    """Write a Chinese report for the one-command official-query pipeline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    context_lines = [
        "| query_id | sources | entities | relationships | reports | official response preview |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in context_rows:
        context_data = row.get("context_data", {})
        if not isinstance(context_data, dict):
            context_data = {}
        context_lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("query_id", "")),
                    str(len(context_data.get("sources", []))),
                    str(len(context_data.get("entities", []))),
                    str(len(context_data.get("relationships", []))),
                    str(len(context_data.get("reports", []))),
                    _compact_cell(str(row.get("response", ""))),
                ]
            )
            + " |"
        )

    result_lines = [
        "| model | variant | generated answer | correct | abstained | incorrect | changed docs | recovered docs |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        result_lines.append(
            "| "
            + " | ".join(
                [
                    result.model,
                    result.variant,
                    _compact_cell(result.generated_answer or result.error or ""),
                    str(int(result.is_correct)),
                    str(int(result.is_abstained)),
                    str(int(result.is_incorrect)),
                    str(result.changed_doc_count),
                    str(result.recovered_doc_count),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Microsoft GraphRAG official query pipeline 实验报告",
            "",
            "## 实验目的",
            "",
            "本阶段把 official local context 导出与 LogicGuard query-time 防御合并为一条可复用流水线。官方 GraphRAG 负责生成 local search 上下文，LogicGuard 在回答模型调用前对官方 sources 执行污染屏蔽与 clean-reference recovery。",
            "",
            "## 配置摘要",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 样本数：`{config.max_queries}`",
            f"- 模型：`{', '.join(config.models)}`",
            f"- GraphRAG Python：`{config.graphrag_python_path}`",
            f"- community_level：`{config.community_level}`",
            f"- response_type：`{config.response_type}`",
            "",
            "## official local context 导出概览",
            "",
            *context_lines,
            "",
            "## LogicGuard 防御结果",
            "",
            *result_lines,
            "",
            "## 汇总",
            "",
            f"- context rows：`{summary.context_row_count}`",
            f"- defense result rows：`{summary.defense_result_count}`",
            f"- 正确数：`{summary.correct_count}`",
            f"- 拒答数：`{summary.abstained_count}`",
            f"- 错误非拒答数：`{summary.incorrect_count}`",
            "",
            "## 产物路径",
            "",
            f"- derived context config：`{config.context_export_config_path}`",
            f"- official context JSONL：`{summary.official_context_path}`",
            f"- LogicGuard defense JSONL：`{summary.defense_output_path}`",
            f"- pipeline report：`{summary.pipeline_report_path}`",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _run_defense(
    config: QueryTimeDefenseConfig,
    client: OpenAICompatibleChatClient | None = None,
) -> list[QueryTimeDefenseResult]:
    return run_query_time_defense(config, client=client)


def _compact_cell(value: str, max_chars: int = 160) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run official GraphRAG local-query LogicGuard pipeline."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_official_query_pipeline_stage13.yaml"),
    )
    args = parser.parse_args()
    summary = run_from_config(OfficialQueryPipelineConfig.from_yaml(args.config))
    print(
        "official-query pipeline finished: "
        f"context_rows={summary.context_row_count}, "
        f"defense_results={summary.defense_result_count}, "
        f"correct={summary.correct_count}, "
        f"abstained={summary.abstained_count}, "
        f"incorrect={summary.incorrect_count}"
    )


if __name__ == "__main__":
    main()
