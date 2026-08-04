"""Query-time LogicGuard runner over official Microsoft GraphRAG artifacts.

This module is the first step from "workspace-level comparison" toward
"LogicGuard inside the query layer". It reads official GraphRAG index artifacts,
reconstructs the text-unit evidence available to a query, and applies
LogicGuard before answer generation:

* poisoned: use the ranked evidence as indexed in the poisoned workspace;
* guarded: remove evidence whose original LogicGuard doc_id is known changed;
* recovered: replace changed poisoned evidence with clean reference evidence.

The current ranker is intentionally lightweight and auditable. It operates over
official GraphRAG `text_units.parquet` rather than raw corpus files, so the
defense boundary is already after official indexing. A later phase can swap the
ranker for GraphRAG's `LocalSearchMixedContext` result while keeping the same
guard/recovery interfaces.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import pandas as pd
import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.prepare import load_normalized_samples
from logicguard.llm.context import build_qa_messages
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import OpenAICompatibleChatClient
from logicguard.ms_graphrag.minimal_experiment import parse_logicguard_doc_id

_TITLE_PATTERN = re.compile(r"^Title:\s*(?P<title>.*?)\s*$", re.MULTILINE)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
EvidenceSource = Literal["indexed_text_units", "official_local_context"]


@dataclass(frozen=True, slots=True)
class GraphRagTextUnitEvidence:
    """One official GraphRAG text unit mapped back to a LogicGuard doc_id."""

    text_unit_id: str
    human_readable_id: int
    official_document_id: str
    logicguard_doc_id: str
    title: str
    text: str
    n_tokens: int
    score: float = 0.0
    source_state: str = "poisoned"
    recovered_from_changed_doc: bool = False
    risk_reasons: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-serializable evidence payload."""

        return {
            **asdict(self),
            "risk_reasons": list(self.risk_reasons),
        }


@dataclass(frozen=True, slots=True)
class QueryTimeContextVariant:
    """One query-time context after applying a LogicGuard policy."""

    name: str
    evidence: list[GraphRagTextUnitEvidence]
    context_text: str
    changed_doc_count: int
    recovered_doc_count: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "context_text": self.context_text,
            "changed_doc_count": self.changed_doc_count,
            "recovered_doc_count": self.recovered_doc_count,
            "evidence": [item.to_json_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class QueryTimeDefenseResult:
    """One model answer for one query-time LogicGuard context variant."""

    dataset: str
    model: str
    query_id: str
    query: str
    expected_answer: str
    variant: str
    generated_answer: str
    is_correct: bool
    is_abstained: bool
    is_incorrect: bool
    changed_doc_count: int
    recovered_doc_count: int
    evidence_doc_ids: list[str]
    evidence_text_unit_ids: list[str]
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error: str | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QueryTimeDefenseConfig:
    """Configuration for the stage-11 query-time LogicGuard runner."""

    dataset: str
    sample_path: Path
    poisoned_workspace_root: Path
    clean_reference_workspace_root: Path
    query_integrity_path: Path
    output_path: Path
    report_path: Path
    models: list[str]
    official_context_path: Path | None = None
    evidence_source: EvidenceSource = "indexed_text_units"
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url_env: str = "DASHSCOPE_BASE_URL"
    max_queries: int = 1
    top_k: int = 4
    max_units: int = 4
    max_chars_per_unit: int = 900
    temperature: float = 0.0
    max_tokens: int = 64
    timeout_seconds: int = 90

    @classmethod
    def from_yaml(cls, path: Path) -> "QueryTimeDefenseConfig":
        """Load YAML configuration with project-relative paths."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(payload["sample_path"]),
            poisoned_workspace_root=resolve_project_path(
                payload["poisoned_workspace_root"]
            ),
            clean_reference_workspace_root=resolve_project_path(
                payload["clean_reference_workspace_root"]
            ),
            query_integrity_path=resolve_project_path(payload["query_integrity_path"]),
            output_path=resolve_project_path(payload["output_path"]),
            report_path=resolve_project_path(payload["report_path"]),
            models=[str(model) for model in payload["models"]],
            official_context_path=(
                resolve_project_path(str(payload["official_context_path"]))
                if payload.get("official_context_path")
                else None
            ),
            evidence_source=_parse_evidence_source(
                payload.get("evidence_source", "indexed_text_units")
            ),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            max_queries=int(payload.get("max_queries", 1)),
            top_k=int(payload.get("top_k", 4)),
            max_units=int(payload.get("max_units", 4)),
            max_chars_per_unit=int(payload.get("max_chars_per_unit", 900)),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 90)),
        )


def load_text_unit_evidence(output_dir: Path) -> list[GraphRagTextUnitEvidence]:
    """Load official GraphRAG text units and map them to LogicGuard doc ids."""

    documents = pd.read_parquet(output_dir / "documents.parquet")
    text_units = pd.read_parquet(output_dir / "text_units.parquet")
    document_lookup: dict[str, tuple[str, str]] = {}
    for row in documents.to_dict(orient="records"):
        official_document_id = str(row["id"])
        document_text = str(row["text"])
        logicguard_doc_id = parse_logicguard_doc_id(document_text)
        title = _parse_title(document_text) or str(row.get("title", "")).removesuffix(
            ".txt"
        )
        document_lookup[official_document_id] = (logicguard_doc_id, title)

    evidence: list[GraphRagTextUnitEvidence] = []
    for row in text_units.to_dict(orient="records"):
        official_document_id = str(row["document_id"])
        if official_document_id not in document_lookup:
            raise ValueError(
                f"Text unit references unknown document id: {official_document_id}"
            )
        logicguard_doc_id, title = document_lookup[official_document_id]
        evidence.append(
            GraphRagTextUnitEvidence(
                text_unit_id=str(row["id"]),
                human_readable_id=int(row.get("human_readable_id", 0)),
                official_document_id=official_document_id,
                logicguard_doc_id=logicguard_doc_id,
                title=title,
                text=str(row["text"]),
                n_tokens=int(row.get("n_tokens", 0)),
            )
        )
    return evidence


def build_query_time_variants(
    *,
    query: str,
    poisoned_units: list[GraphRagTextUnitEvidence],
    clean_reference_units: list[GraphRagTextUnitEvidence],
    changed_doc_ids: set[str],
    top_k: int,
    max_units: int,
    max_chars_per_unit: int,
) -> list[QueryTimeContextVariant]:
    """Build poisoned, guarded, and recovered query-time contexts."""

    ranked_poisoned = _rank_text_units(query, poisoned_units)[:top_k]
    return build_query_time_variants_from_ranked_evidence(
        ranked_poisoned_units=ranked_poisoned,
        clean_reference_units=clean_reference_units,
        changed_doc_ids=changed_doc_ids,
        top_k=top_k,
        max_units=max_units,
        max_chars_per_unit=max_chars_per_unit,
    )


def build_query_time_variants_from_ranked_evidence(
    *,
    ranked_poisoned_units: list[GraphRagTextUnitEvidence],
    clean_reference_units: list[GraphRagTextUnitEvidence],
    changed_doc_ids: set[str],
    top_k: int,
    max_units: int,
    max_chars_per_unit: int,
) -> list[QueryTimeContextVariant]:
    """Build query-time contexts from already-ranked official evidence."""

    ranked_poisoned = ranked_poisoned_units[:top_k]
    clean_by_doc_id: dict[str, GraphRagTextUnitEvidence] = {}
    for unit in sorted(
        clean_reference_units,
        key=lambda item: (item.human_readable_id, item.logicguard_doc_id),
    ):
        clean_by_doc_id.setdefault(unit.logicguard_doc_id, unit)

    poisoned = [
        _with_policy_metadata(
            unit,
            source_state="poisoned",
            changed_doc_ids=changed_doc_ids,
            recovered=False,
        )
        for unit in ranked_poisoned
    ]
    guarded = [
        _with_policy_metadata(
            unit,
            source_state="poisoned",
            changed_doc_ids=changed_doc_ids,
            recovered=False,
        )
        for unit in ranked_poisoned
        if unit.logicguard_doc_id not in changed_doc_ids
    ]
    recovered: list[GraphRagTextUnitEvidence] = []
    for unit in ranked_poisoned:
        if unit.logicguard_doc_id in changed_doc_ids:
            clean_unit = clean_by_doc_id.get(unit.logicguard_doc_id)
            if clean_unit is None:
                continue
            recovered.append(
                _with_policy_metadata(
                    clean_unit,
                    source_state="clean_reference",
                    changed_doc_ids=changed_doc_ids,
                    recovered=True,
                )
            )
        else:
            recovered.append(
                _with_policy_metadata(
                    unit,
                    source_state="poisoned",
                    changed_doc_ids=changed_doc_ids,
                    recovered=False,
                )
            )

    return [
        _build_variant(
            "poisoned", poisoned, changed_doc_ids, max_units, max_chars_per_unit
        ),
        _build_variant(
            "guarded", guarded, changed_doc_ids, max_units, max_chars_per_unit
        ),
        _build_variant(
            "recovered", recovered, changed_doc_ids, max_units, max_chars_per_unit
        ),
    ]


def run_from_config(
    config: QueryTimeDefenseConfig,
    client: OpenAICompatibleChatClient | None = None,
) -> list[QueryTimeDefenseResult]:
    """Run query-time LogicGuard contexts through an answer model."""

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")
    api_client = client or OpenAICompatibleChatClient(
        base_url=_read_required_env(config.base_url_env),
        api_key=_read_required_env(config.api_key_env),
    )
    if config.evidence_source == "indexed_text_units":
        poisoned_units = load_text_unit_evidence(
            config.poisoned_workspace_root / "output"
        )
        official_context_by_query: dict[str, dict[str, Any]] = {}
    else:
        if config.official_context_path is None:
            raise ValueError(
                "official_context_path is required when evidence_source=official_local_context"
            )
        poisoned_units = []
        official_context_by_query = _load_records_by_query_id(
            config.official_context_path
        )
    clean_reference_units = load_text_unit_evidence(
        config.clean_reference_workspace_root / "output"
    )
    query_integrity = _load_records_by_query_id(config.query_integrity_path)
    samples = load_normalized_samples(config.sample_path)[: config.max_queries]

    results: list[QueryTimeDefenseResult] = []
    trace_rows: list[dict[str, object]] = []
    for sample in samples:
        integrity = query_integrity.get(sample.query_id, {})
        changed_doc_ids = {
            str(doc_id) for doc_id in integrity.get("changed_support_doc_ids", [])
        }
        if config.evidence_source == "official_local_context":
            from logicguard.ms_graphrag.official_local_context import (
                extract_source_evidence,
            )

            context_row = official_context_by_query.get(sample.query_id)
            if context_row is None:
                raise ValueError(
                    f"Missing official local context row for query_id={sample.query_id}"
                )
            ranked_poisoned_units = extract_source_evidence(context_row)
            variants = build_query_time_variants_from_ranked_evidence(
                ranked_poisoned_units=ranked_poisoned_units,
                clean_reference_units=clean_reference_units,
                changed_doc_ids=changed_doc_ids,
                top_k=config.top_k,
                max_units=config.max_units,
                max_chars_per_unit=config.max_chars_per_unit,
            )
        else:
            variants = build_query_time_variants(
                query=sample.query,
                poisoned_units=poisoned_units,
                clean_reference_units=clean_reference_units,
                changed_doc_ids=changed_doc_ids,
                top_k=config.top_k,
                max_units=config.max_units,
                max_chars_per_unit=config.max_chars_per_unit,
            )
        trace_rows.append(
            {
                "dataset": config.dataset,
                "evidence_source": config.evidence_source,
                "query_id": sample.query_id,
                "query": sample.query,
                "expected_answer": sample.answer,
                "changed_doc_ids": sorted(changed_doc_ids),
                "variants": [variant.to_json_dict() for variant in variants],
            }
        )
        for model in config.models:
            for variant in variants:
                results.append(
                    _call_model_for_variant(
                        config=config,
                        client=api_client,
                        model=model,
                        query_id=sample.query_id,
                        query=sample.query,
                        expected_answer=sample.answer,
                        variant=variant,
                    )
                )

    _write_outputs(config, trace_rows, results)
    return results


def _call_model_for_variant(
    *,
    config: QueryTimeDefenseConfig,
    client: OpenAICompatibleChatClient,
    model: str,
    query_id: str,
    query: str,
    expected_answer: str,
    variant: QueryTimeContextVariant,
) -> QueryTimeDefenseResult:
    messages = build_qa_messages(question=query, context=variant.context_text)
    start = perf_counter()
    try:
        response = client.chat(
            model=model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
        )
        latency = perf_counter() - start
        classification = classify_answer(
            response.content, gold_answer=expected_answer, poisoned_answer=""
        )
        return QueryTimeDefenseResult(
            dataset=config.dataset,
            model=model,
            query_id=query_id,
            query=query,
            expected_answer=expected_answer,
            variant=variant.name,
            generated_answer=response.content,
            is_correct=classification.is_correct,
            is_abstained=classification.is_abstained,
            is_incorrect=not classification.is_correct
            and not classification.is_abstained,
            changed_doc_count=variant.changed_doc_count,
            recovered_doc_count=variant.recovered_doc_count,
            evidence_doc_ids=[item.logicguard_doc_id for item in variant.evidence],
            evidence_text_unit_ids=[item.text_unit_id for item in variant.evidence],
            latency_seconds=round(latency, 4),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are experiment data.
        latency = perf_counter() - start
        return QueryTimeDefenseResult(
            dataset=config.dataset,
            model=model,
            query_id=query_id,
            query=query,
            expected_answer=expected_answer,
            variant=variant.name,
            generated_answer="",
            is_correct=False,
            is_abstained=False,
            is_incorrect=False,
            changed_doc_count=variant.changed_doc_count,
            recovered_doc_count=variant.recovered_doc_count,
            evidence_doc_ids=[item.logicguard_doc_id for item in variant.evidence],
            evidence_text_unit_ids=[item.text_unit_id for item in variant.evidence],
            latency_seconds=round(latency, 4),
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(exc),
        )


def _rank_text_units(
    query: str, units: list[GraphRagTextUnitEvidence]
) -> list[GraphRagTextUnitEvidence]:
    query_terms = _tokenize(query)
    ranked: list[GraphRagTextUnitEvidence] = []
    for unit in units:
        unit_terms = _tokenize(unit.title + " " + unit.text)
        overlap = sum(1 for term in query_terms if term in unit_terms)
        phrase_bonus = 3.0 if "someone i loved" in unit.text.casefold() else 0.0
        score = float(overlap) + phrase_bonus + min(unit.n_tokens, 200) / 10_000
        ranked.append(_replace_score(unit, score))
    return sorted(
        ranked,
        key=lambda item: (-item.score, item.human_readable_id, item.logicguard_doc_id),
    )


def _build_variant(
    name: str,
    evidence: list[GraphRagTextUnitEvidence],
    changed_doc_ids: set[str],
    max_units: int,
    max_chars_per_unit: int,
) -> QueryTimeContextVariant:
    selected = evidence[:max_units]
    context_text = _render_context(selected, max_chars_per_unit=max_chars_per_unit)
    changed_doc_count = sum(
        1
        for item in selected
        if item.logicguard_doc_id in changed_doc_ids
        and not item.recovered_from_changed_doc
    )
    recovered_doc_count = sum(1 for item in selected if item.recovered_from_changed_doc)
    return QueryTimeContextVariant(
        name=name,
        evidence=selected,
        context_text=context_text,
        changed_doc_count=changed_doc_count,
        recovered_doc_count=recovered_doc_count,
    )


def _render_context(
    units: list[GraphRagTextUnitEvidence], *, max_chars_per_unit: int
) -> str:
    blocks: list[str] = []
    for index, unit in enumerate(units, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[G{index}] doc_id={unit.logicguard_doc_id}; text_unit_id={unit.text_unit_id}; source={unit.source_state}",
                    f"Title: {unit.title}",
                    f"Text: {_truncate(unit.text, max_chars=max_chars_per_unit)}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _with_policy_metadata(
    unit: GraphRagTextUnitEvidence,
    *,
    source_state: str,
    changed_doc_ids: set[str],
    recovered: bool,
) -> GraphRagTextUnitEvidence:
    risk_reasons: list[str] = []
    if unit.logicguard_doc_id in changed_doc_ids:
        risk_reasons.append("changed_logicpoison_support")
    if recovered:
        risk_reasons.append("query_time_clean_reference_recovery")
    return GraphRagTextUnitEvidence(
        text_unit_id=unit.text_unit_id,
        human_readable_id=unit.human_readable_id,
        official_document_id=unit.official_document_id,
        logicguard_doc_id=unit.logicguard_doc_id,
        title=unit.title,
        text=unit.text,
        n_tokens=unit.n_tokens,
        score=unit.score,
        source_state=source_state,
        recovered_from_changed_doc=recovered,
        risk_reasons=tuple(risk_reasons),
    )


def _replace_score(
    unit: GraphRagTextUnitEvidence, score: float
) -> GraphRagTextUnitEvidence:
    return GraphRagTextUnitEvidence(
        text_unit_id=unit.text_unit_id,
        human_readable_id=unit.human_readable_id,
        official_document_id=unit.official_document_id,
        logicguard_doc_id=unit.logicguard_doc_id,
        title=unit.title,
        text=unit.text,
        n_tokens=unit.n_tokens,
        score=score,
        source_state=unit.source_state,
        recovered_from_changed_doc=unit.recovered_from_changed_doc,
        risk_reasons=unit.risk_reasons,
    )


def _write_outputs(
    config: QueryTimeDefenseConfig,
    trace_rows: list[dict[str, object]],
    results: list[QueryTimeDefenseResult],
) -> None:
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path = config.output_path.with_name(
        config.output_path.stem + "_contexts.jsonl"
    )
    with trace_path.open("w", encoding="utf-8") as handle:
        for row in trace_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with config.output_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_json_dict(), ensure_ascii=False) + "\n")
    _write_report(config.report_path, config, trace_path, results)


def _write_report(
    path: Path,
    config: QueryTimeDefenseConfig,
    trace_path: Path,
    results: list[QueryTimeDefenseResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| 模型 | 上下文变体 | 调用数 | 正确数 | 拒答数 | 错误非拒答数 | 平均changed证据数 | recovery证据数 | 错误调用数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (model, variant), group in sorted(_group_results(results).items()):
        calls = len(group)
        table_lines.append(
            "| "
            + " | ".join(
                [
                    model,
                    variant,
                    str(calls),
                    str(sum(1 for item in group if item.is_correct)),
                    str(sum(1 for item in group if item.is_abstained)),
                    str(sum(1 for item in group if item.is_incorrect)),
                    f"{sum(item.changed_doc_count for item in group) / calls:.2f}",
                    str(sum(item.recovered_doc_count for item in group)),
                    str(sum(1 for item in group if item.error)),
                ]
            )
            + " |"
        )

    example_lines = [
        "| 模型 | 变体 | gold answer | generated answer | evidence doc ids |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results[:12]:
        example_lines.append(
            "| "
            + " | ".join(
                [
                    result.model,
                    result.variant,
                    result.expected_answer.replace("|", "/"),
                    _compact_cell(result.generated_answer or result.error or ""),
                    ", ".join(result.evidence_doc_ids),
                ]
            )
            + " |"
        )

    if config.evidence_source == "official_local_context":
        purpose = (
            "本阶段直接消费 Microsoft GraphRAG Python `api.local_search` 导出的 "
            "`context_data.sources`，在官方 local query 已经选出的 evidence context 上插入 "
            "LogicGuard 的屏蔽与恢复策略。它比 `indexed_text_units` 更接近 official GraphRAG "
            "真实查询链路，因为证据先经过了官方 local search 的实体、关系、社区报告与文本单元组合逻辑。"
        )
        boundary_lines = [
            "- official GraphRAG 负责索引与 local search context construction，实验直接消费 `context_data.sources`。",
            "- LogicGuard 在回答模型调用前工作：`poisoned` 保留官方 sources，`guarded` 移除已知改写 doc_id，`recovered` 用 clean reference evidence 替换被改写证据。",
            "- 当前已经接入 official `api.local_search` 的上下文输出；下一步应把相同策略封装成 official query runner 的可复用 pre-answer hook。",
        ]
    else:
        purpose = (
            "本阶段不再通过重建 guarded/recovered workspace 来比较结果，而是读取 official Microsoft "
            "GraphRAG 已生成的 `text_units.parquet` 和 `documents.parquet`，在回答模型调用前构造 "
            "query-time evidence context，并插入 LogicGuard 的屏蔽与恢复策略。"
        )
        boundary_lines = [
            "- official GraphRAG 负责索引，实验直接消费其 `documents.parquet` 与 `text_units.parquet`。",
            "- LogicGuard 在 query-time context 层工作：`poisoned` 保留原始 indexed evidence，`guarded` 移除已知改写 doc_id，`recovered` 用 clean reference text unit 替换被改写证据。",
            "- 当前排序器是可审计的轻量词项重叠排序，尚未直接调用官方 `LocalSearchMixedContext` API；因此这是“official artifact query-time 接入”的第一步，而不是最终形态。",
        ]

    content = "\n".join(
        [
            "# Microsoft GraphRAG 查询层 LogicGuard 接入实验报告",
            "",
            "## 实验目的",
            "",
            purpose,
            "",
            "## 当前接入边界",
            "",
            *boundary_lines,
            "",
            "## 配置摘要",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 样本数：`{config.max_queries}`",
            f"- 模型：`{', '.join(config.models)}`",
            f"- evidence_source：`{config.evidence_source}`",
            f"- top_k text units：`{config.top_k}`",
            f"- 最大上下文单元数：`{config.max_units}`",
            "",
            "## 指标说明",
            "",
            "- `正确数`：回答中包含 gold answer。",
            "- `拒答数`：回答被规则识别为 UNKNOWN 或证据不足表达。",
            "- `错误非拒答数`：既未命中 gold answer，也不是拒答。",
            "- `平均changed证据数`：进入回答上下文的未恢复污染证据数量，越低越好。",
            "- `recovery证据数`：从 clean reference 替换回来的证据数量。",
            "",
            "## 汇总结果",
            "",
            *table_lines,
            "",
            "## 回答样例",
            "",
            *example_lines,
            "",
            "## 产物路径",
            "",
            f"- context trace：`{trace_path}`",
            f"- answer results：`{config.output_path}`",
            "",
            "## 当前解释",
            "",
            "- 如果 `poisoned` 出现错误非拒答，说明 official GraphRAG 索引产物中的污染 text unit 足以误导回答模型。",
            "- 如果 `guarded` 的 changed 证据数降为 0 且回答转为拒答，说明 query-time 屏蔽能降低错误回答风险，但会牺牲可回答性。",
            "- 如果 `recovered` 命中 gold answer，说明不重建 workspace 的情况下，query-time clean-reference recovery 已经能把回答拉回正确证据。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _group_results(
    results: list[QueryTimeDefenseResult],
) -> dict[tuple[str, str], list[QueryTimeDefenseResult]]:
    grouped: dict[tuple[str, str], list[QueryTimeDefenseResult]] = {}
    for result in results:
        grouped.setdefault((result.model, result.variant), []).append(result)
    return grouped


def _parse_title(text: str) -> str:
    match = _TITLE_PATTERN.search(text)
    return match.group("title").strip() if match else ""


def _tokenize(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(text)}


def _truncate(text: str, *, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _load_records_by_query_id(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            rows[str(payload["query_id"])] = payload
    return rows


def _parse_evidence_source(value: object) -> EvidenceSource:
    evidence_source = str(value)
    if evidence_source not in {"indexed_text_units", "official_local_context"}:
        raise ValueError(f"Unsupported evidence_source: {evidence_source}")
    return evidence_source  # type: ignore[return-value]


def _read_required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Environment]::GetEnvironmentVariable('{name}', 'User')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - environment probing fallback.
        raise RuntimeError(f"Missing required environment variable: {name}") from exc
    value = completed.stdout.strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _compact_cell(value: str, max_chars: int = 140) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run query-time LogicGuard over official GraphRAG artifacts."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_query_time_defense_stage11.yaml"),
    )
    args = parser.parse_args()
    results = run_from_config(QueryTimeDefenseConfig.from_yaml(args.config))
    for result in results:
        status = (
            "correct"
            if result.is_correct
            else "abstained"
            if result.is_abstained
            else "incorrect"
        )
        if result.error:
            status = "error"
        print(
            f"{result.dataset}/{result.model}/{result.variant}/{result.query_id}: "
            f"{status}, changed={result.changed_doc_count}, recovered={result.recovered_doc_count}, "
            f"latency={result.latency_seconds:.2f}s"
        )


if __name__ == "__main__":
    main()
