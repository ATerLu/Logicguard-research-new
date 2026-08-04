"""Stage27 real-LLM answer verification for official GraphRAG sources.

Stage26 used an offline answerability proxy. This module advances the same
official-source contexts to answer generation: render each source policy as a
compact QA context, call an OpenAI-compatible chat model, and classify the
generated answer with local rules plus an optional LLM judge.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import string
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import load_jsonl as _load_jsonl
from logicguard.core.metrics import dedupe_strings as _dedupe
from logicguard.core.metrics import mean as _avg
from logicguard.core.metrics import ratio as _ratio

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.llm.answer_judge import AnswerJudgeConfig, judge_answer_with_client
from logicguard.llm.context import build_qa_messages
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import ChatResponse, OpenAICompatibleChatClient
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
    parse_title_from_source_text,
)

_METHOD_ORDER = {
    "full_query_guard": 1,
    "guarded_sources": 2,
    "recovered_sources_by_doc_id": 3,
    "non_oracle_query_bm25": 4,
    "non_oracle_title_entity_bm25": 5,
    "non_oracle_hybrid_policy": 6,
    "risk_non_oracle_guarded_sources": 7,
    "risk_non_oracle_title_entity_bm25": 8,
    "stage35_query_bm25_append_top12": 9,
}

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class ChatClient(Protocol):
    """Protocol for the chat client used by Stage27."""

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse:
        """Return one chat completion."""


@dataclass(frozen=True, slots=True)
class Stage27RenderingPolicy:
    """Optional source rendering override for one answer-generation method."""

    order_policy: str = "official_order"
    prompt_policy: str = "default"
    max_sources: int | None = None
    max_chars_per_source: int | None = None


@dataclass(frozen=True, slots=True)
class Stage27AnswerLLMConfig:
    """Paths and runtime settings for Stage27 answer generation."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    context_input_path: Path
    cases_output_path: Path
    results_output_path: Path
    metrics_output_path: Path
    summary_output_path: Path
    report_path: Path
    methods: list[str]
    models: list[str]
    required_context_flag: str | None = None
    rendering_policies: dict[str, Stage27RenderingPolicy] | None = None
    max_queries: int = 20
    max_sources: int = 8
    max_chars_per_source: int = 700
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url_env: str = "DASHSCOPE_BASE_URL"
    temperature: float = 0.0
    max_tokens: int = 64
    timeout_seconds: int = 90
    judge_model: str | None = None
    judge_temperature: float = 0.0
    judge_max_tokens: int = 96
    judge_timeout_seconds: int = 60
    stage_label: str = "Stage27"
    emit_markdown_report: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage27AnswerLLMConfig":
        """Load a project-relative YAML config."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        judge_model = payload.get("judge_model")
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),
            query_integrity_path=resolve(payload["query_integrity_path"]),
            context_input_path=resolve(payload["context_input_path"]),
            cases_output_path=resolve(payload["cases_output_path"]),
            results_output_path=resolve(payload["results_output_path"]),
            metrics_output_path=resolve(payload["metrics_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            report_path=resolve(payload["report_path"]),
            methods=[str(method) for method in payload.get("methods", [])],
            models=[str(model) for model in payload.get("models", [])],
            required_context_flag=(
                str(payload["required_context_flag"])
                if payload.get("required_context_flag")
                else None
            ),
            rendering_policies=_parse_rendering_policies(
                payload.get("rendering_policies", {})
            ),
            max_queries=int(payload.get("max_queries", 20)),
            max_sources=int(payload.get("max_sources", 8)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 700)),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 90)),
            judge_model=str(judge_model) if judge_model else None,
            judge_temperature=float(payload.get("judge_temperature", 0.0)),
            judge_max_tokens=int(payload.get("judge_max_tokens", 96)),
            judge_timeout_seconds=int(payload.get("judge_timeout_seconds", 60)),
            stage_label=str(payload.get("stage_label", "Stage27")),
            emit_markdown_report=bool(payload.get("emit_markdown_report", True)),
        )

    def judge_config(self) -> AnswerJudgeConfig | None:
        """Return optional judge settings."""

        if self.judge_model is None:
            return None
        return AnswerJudgeConfig(
            model=self.judge_model,
            temperature=self.judge_temperature,
            max_tokens=self.judge_max_tokens,
            timeout_seconds=self.judge_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class Stage27AnswerCase:
    """One query-method context rendered for answer generation."""

    dataset: str
    query_id: str
    query: str
    method: str
    order_policy: str
    prompt_policy: str
    max_sources: int
    max_chars_per_source: int
    gold_answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    context_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    changed_hit_doc_ids: list[str]
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    context_has_gold_answer: bool
    source_count: int
    recovered_source_count: int
    rendered_context: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Stage27AnswerLLMResult:
    """One generated model answer for one Stage27 case."""

    dataset: str
    model: str
    query_id: str
    query: str
    method: str
    order_policy: str
    prompt_policy: str
    max_sources: int
    max_chars_per_source: int
    gold_answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    context_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    source_count: int
    recovered_source_count: int
    context_has_gold_answer: bool
    generated_answer: str
    answer_label: str
    judge_label: str
    judge_reason: str
    judge_model: str | None
    is_correct: bool
    is_partial: bool
    is_abstained: bool
    is_incorrect: bool
    attack_success: bool
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    judge_prompt_tokens: int | None
    judge_completion_tokens: int | None
    judge_total_tokens: int | None
    error: str | None
    judge_error: str | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            elif isinstance(value, bool):
                output[key] = "1" if value else "0"
            elif value is None:
                output[key] = ""
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class Stage27SummaryRow:
    """Method-level answer-generation summary."""

    dataset: str
    model: str
    method: str
    order_policy: str
    prompt_policy: str
    max_sources: int
    max_chars_per_source: int
    query_count: int
    correct_rate: float
    partial_rate: float
    utility_rate: float
    abstain_rate: float
    incorrect_rate: float
    attack_success_rate: float
    error_rate: float
    gold_answer_surface_rate: float
    avg_source_count: float
    avg_recovered_source_count: float
    avg_total_tokens: float
    avg_latency_seconds: float

    def to_csv_row(self) -> dict[str, str]:
        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in asdict(self).items()
        }


def run_from_config(config: Stage27AnswerLLMConfig) -> list[Stage27AnswerLLMResult]:
    """Build Stage27 cases, run model calls, and write all artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    context_rows = _load_jsonl(config.context_input_path)
    if config.required_context_flag:
        context_rows = [
            row for row in context_rows if bool(row.get(config.required_context_flag))
        ]
    cases = build_stage27_answer_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
        methods=config.methods,
        max_sources=config.max_sources,
        max_chars_per_source=config.max_chars_per_source,
        rendering_policies=config.rendering_policies,
    )
    api_key = _read_required_env(config.api_key_env)
    base_url = _read_required_env(config.base_url_env)
    client = OpenAICompatibleChatClient(base_url=base_url, api_key=api_key)
    results = run_stage27_answer_generation(config=config, cases=cases, client=client)
    write_stage27_outputs(config=config, cases=cases, results=results)
    print(
        f"stage27_answer_cases={len(cases)}, "
        f"models={len(config.models)}, calls={len(results)}"
    )
    return results


def build_stage27_answer_cases(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str,
    methods: list[str] | None = None,
    max_sources: int = 8,
    max_chars_per_source: int = 700,
    rendering_policies: dict[str, Stage27RenderingPolicy] | None = None,
) -> list[Stage27AnswerCase]:
    """Render official GraphRAG source contexts as answer-generation cases."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    allowed_methods = set(methods or [])
    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }

    cases: list[Stage27AnswerCase] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        method = str(context_row.get("method", "unknown"))
        if query_id not in samples_by_query:
            continue
        if allowed_methods and method not in allowed_methods:
            continue

        sample = samples_by_query[query_id]
        rendering_policy = _effective_rendering_policy(
            method=method,
            rendering_policies=rendering_policies or {},
            default_max_sources=max_sources,
            default_max_chars_per_source=max_chars_per_source,
        )
        changed_doc_ids = [
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get(
                "changed_support_doc_ids", []
            )
        ]
        cases.append(
            _build_case_for_context(
                dataset=dataset,
                sample=sample,
                changed_doc_ids=changed_doc_ids,
                context_row=context_row,
                method=method,
                rendering_policy=rendering_policy,
            )
        )

    cases.sort(
        key=lambda item: (
            item.query_id,
            _METHOD_ORDER.get(item.method, 99),
            item.method,
        )
    )
    return cases


def run_stage27_answer_generation(
    *,
    config: Stage27AnswerLLMConfig,
    cases: list[Stage27AnswerCase],
    client: ChatClient,
) -> list[Stage27AnswerLLMResult]:
    """Call configured models for each rendered Stage27 answer case."""

    results: list[Stage27AnswerLLMResult] = []
    judge_config = config.judge_config()
    for model in config.models:
        for case in cases:
            results.append(
                _call_model_for_case(
                    config=config,
                    client=client,
                    model=model,
                    case=case,
                    judge_config=judge_config,
                )
            )
    return results


def summarize_stage27_results(
    results: list[Stage27AnswerLLMResult],
) -> list[Stage27SummaryRow]:
    """Aggregate Stage27 answer-generation results by model and method."""

    grouped: dict[
        tuple[str, str, str, str, int, int],
        list[Stage27AnswerLLMResult],
    ] = {}
    for result in results:
        grouped.setdefault(
            (
                result.model,
                result.method,
                result.order_policy,
                result.prompt_policy,
                result.max_sources,
                result.max_chars_per_source,
            ),
            [],
        ).append(result)

    summaries: list[Stage27SummaryRow] = []
    for (
        model,
        method,
        order_policy,
        prompt_policy,
        row_max_sources,
        row_max_chars,
    ), group in grouped.items():
        query_count = len(group)
        summaries.append(
            Stage27SummaryRow(
                dataset=group[0].dataset if group else "",
                model=model,
                method=method,
                order_policy=order_policy,
                prompt_policy=prompt_policy,
                max_sources=row_max_sources,
                max_chars_per_source=row_max_chars,
                query_count=query_count,
                correct_rate=_ratio(
                    sum(1 for row in group if row.is_correct), query_count
                ),
                partial_rate=_ratio(
                    sum(1 for row in group if row.is_partial), query_count
                ),
                utility_rate=_ratio(
                    sum(1 for row in group if row.is_correct or row.is_partial),
                    query_count,
                ),
                abstain_rate=_ratio(
                    sum(1 for row in group if row.is_abstained), query_count
                ),
                incorrect_rate=_ratio(
                    sum(1 for row in group if row.is_incorrect), query_count
                ),
                attack_success_rate=_ratio(
                    sum(1 for row in group if row.attack_success),
                    query_count,
                ),
                error_rate=_ratio(
                    sum(1 for row in group if row.error is not None), query_count
                ),
                gold_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer),
                    query_count,
                ),
                avg_source_count=_avg(float(row.source_count) for row in group),
                avg_recovered_source_count=_avg(
                    float(row.recovered_source_count) for row in group
                ),
                avg_total_tokens=_avg(float(row.total_tokens or 0) for row in group),
                avg_latency_seconds=_avg(float(row.latency_seconds) for row in group),
            )
        )
    summaries.sort(
        key=lambda item: (
            item.model,
            _METHOD_ORDER.get(item.method, 99),
            item.method,
            item.order_policy,
            item.prompt_policy,
            item.max_sources,
            item.max_chars_per_source,
        )
    )
    return summaries


def write_stage27_outputs(
    *,
    config: Stage27AnswerLLMConfig,
    cases: list[Stage27AnswerCase],
    results: list[Stage27AnswerLLMResult],
) -> None:
    """Write Stage27 cases, JSONL results, CSV metrics, summary, and report."""

    summaries = summarize_stage27_results(results)
    config.cases_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.results_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_output_path.parent.mkdir(parents=True, exist_ok=True)
    if config.emit_markdown_report:
        config.report_path.parent.mkdir(parents=True, exist_ok=True)

    with config.cases_output_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_json_dict(), ensure_ascii=False) + "\n")
    with config.results_output_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_json_dict(), ensure_ascii=False) + "\n")
    with config.metrics_output_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(Stage27AnswerLLMResult.__dataclass_fields__),
        )
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_csv_row())
    with config.summary_output_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(Stage27SummaryRow.__dataclass_fields__),
        )
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.to_csv_row())
    _write_stage27_report(
        config=config, cases=cases, results=results, summaries=summaries
    )


def _build_case_for_context(
    *,
    dataset: str,
    sample: NormalizedSample,
    changed_doc_ids: list[str],
    context_row: dict[str, Any],
    method: str,
    rendering_policy: Stage27RenderingPolicy,
) -> Stage27AnswerCase:
    sources = _order_sources_for_answer_generation(
        sources=_source_records(context_row),
        query=sample.query,
        order_policy=rendering_policy.order_policy,
    )[: rendering_policy.max_sources]
    context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
    support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
    support_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
    changed_hits = _ordered_intersection(changed_doc_ids, context_doc_ids)
    unrecovered_changed = _dedupe(
        _source_doc_id(source)
        for source in sources
        if _source_doc_id(source) in set(changed_doc_ids)
        and not _is_recovered_source(source)
    )
    recovered_support = _ordered_intersection(
        support_doc_ids,
        _dedupe(
            _source_doc_id(source) for source in sources if _is_recovered_source(source)
        ),
    )
    rendered_context = _render_source_context(
        sources,
        max_chars_per_source=rendering_policy.max_chars_per_source or 0,
    )
    return Stage27AnswerCase(
        dataset=dataset,
        query_id=sample.query_id,
        query=sample.query,
        method=method,
        order_policy=rendering_policy.order_policy,
        prompt_policy=rendering_policy.prompt_policy,
        max_sources=rendering_policy.max_sources or 0,
        max_chars_per_source=rendering_policy.max_chars_per_source or 0,
        gold_answer=sample.answer,
        support_doc_ids=support_doc_ids,
        changed_support_doc_ids=changed_doc_ids,
        context_doc_ids=context_doc_ids,
        support_hit_doc_ids=support_hits,
        changed_hit_doc_ids=changed_hits,
        unrecovered_changed_doc_ids=unrecovered_changed,
        recovered_support_doc_ids=recovered_support,
        context_has_gold_answer=_contains_answer_phrase(
            rendered_context, sample.answer
        ),
        source_count=len(context_doc_ids),
        recovered_source_count=sum(
            1 for source in sources if _is_recovered_source(source)
        ),
        rendered_context=rendered_context,
    )


def _call_model_for_case(
    *,
    config: Stage27AnswerLLMConfig,
    client: ChatClient,
    model: str,
    case: Stage27AnswerCase,
    judge_config: AnswerJudgeConfig | None,
) -> Stage27AnswerLLMResult:
    messages = build_qa_messages(
        question=case.query,
        context=case.rendered_context,
        prompt_policy=case.prompt_policy,
    )
    start = perf_counter()
    try:
        response = client.chat(
            model=model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
        )
        elapsed = perf_counter() - start
        label, judge_payload = _label_generated_answer(
            client=client,
            judge_config=judge_config,
            question=case.query,
            gold_answer=case.gold_answer,
            generated_answer=response.content,
        )
        return _result_from_parts(
            case=case,
            model=model,
            generated_answer=response.content,
            answer_label=label,
            latency_seconds=round(elapsed, 4),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            error=None,
            **judge_payload,
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are experiment data.
        elapsed = perf_counter() - start
        return _result_from_parts(
            case=case,
            model=model,
            generated_answer="",
            answer_label="api_error",
            latency_seconds=round(elapsed, 4),
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(exc),
            judge_label="not_run",
            judge_reason="generation_failed",
            judge_model=None,
            judge_prompt_tokens=None,
            judge_completion_tokens=None,
            judge_total_tokens=None,
            judge_error=None,
        )


def _label_generated_answer(
    *,
    client: ChatClient,
    judge_config: AnswerJudgeConfig | None,
    question: str,
    gold_answer: str,
    generated_answer: str,
) -> tuple[str, dict[str, object]]:
    local = classify_answer(
        generated_answer, gold_answer=gold_answer, poisoned_answer=""
    )
    if local.is_abstained:
        return "abstained", {
            "judge_label": "local_abstained",
            "judge_reason": "local_abstain_marker",
            "judge_model": None,
            "judge_prompt_tokens": 0,
            "judge_completion_tokens": 0,
            "judge_total_tokens": 0,
            "judge_error": None,
        }
    if local.is_correct:
        return "correct", {
            "judge_label": "local_correct",
            "judge_reason": "local_gold_answer_match",
            "judge_model": None,
            "judge_prompt_tokens": 0,
            "judge_completion_tokens": 0,
            "judge_total_tokens": 0,
            "judge_error": None,
        }
    if judge_config is None:
        return "incorrect", {
            "judge_label": "local_incorrect",
            "judge_reason": "no_gold_answer_match",
            "judge_model": None,
            "judge_prompt_tokens": 0,
            "judge_completion_tokens": 0,
            "judge_total_tokens": 0,
            "judge_error": None,
        }

    judged = judge_answer_with_client(
        client=client,
        config=judge_config,
        question=question,
        gold_answer=gold_answer,
        generated_answer=generated_answer,
    )
    label = (
        judged.label
        if judged.label in {"correct", "partial", "incorrect", "abstained"}
        else "judge_error"
    )
    return label, {
        "judge_label": judged.label,
        "judge_reason": judged.reason,
        "judge_model": judged.judge_model,
        "judge_prompt_tokens": judged.prompt_tokens,
        "judge_completion_tokens": judged.completion_tokens,
        "judge_total_tokens": judged.total_tokens,
        "judge_error": judged.error,
    }


def _result_from_parts(
    *,
    case: Stage27AnswerCase,
    model: str,
    generated_answer: str,
    answer_label: str,
    judge_label: str,
    judge_reason: str,
    judge_model: str | None,
    latency_seconds: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    judge_prompt_tokens: int | None,
    judge_completion_tokens: int | None,
    judge_total_tokens: int | None,
    error: str | None,
    judge_error: str | None,
) -> Stage27AnswerLLMResult:
    is_correct = answer_label == "correct"
    is_partial = answer_label == "partial"
    is_abstained = answer_label == "abstained"
    is_incorrect = answer_label == "incorrect"
    return Stage27AnswerLLMResult(
        dataset=case.dataset,
        model=model,
        query_id=case.query_id,
        query=case.query,
        method=case.method,
        order_policy=case.order_policy,
        prompt_policy=case.prompt_policy,
        max_sources=case.max_sources,
        max_chars_per_source=case.max_chars_per_source,
        gold_answer=case.gold_answer,
        support_doc_ids=case.support_doc_ids,
        changed_support_doc_ids=case.changed_support_doc_ids,
        context_doc_ids=case.context_doc_ids,
        support_hit_doc_ids=case.support_hit_doc_ids,
        unrecovered_changed_doc_ids=case.unrecovered_changed_doc_ids,
        recovered_support_doc_ids=case.recovered_support_doc_ids,
        source_count=case.source_count,
        recovered_source_count=case.recovered_source_count,
        context_has_gold_answer=case.context_has_gold_answer,
        generated_answer=generated_answer,
        answer_label=answer_label,
        judge_label=judge_label,
        judge_reason=judge_reason,
        judge_model=judge_model,
        is_correct=is_correct,
        is_partial=is_partial,
        is_abstained=is_abstained,
        is_incorrect=is_incorrect,
        attack_success=is_incorrect and bool(case.unrecovered_changed_doc_ids),
        latency_seconds=latency_seconds,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        judge_prompt_tokens=judge_prompt_tokens,
        judge_completion_tokens=judge_completion_tokens,
        judge_total_tokens=judge_total_tokens,
        error=error,
        judge_error=judge_error,
    )


def _source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    context_data = row.get("context_data", {})
    sources = context_data.get("sources", []) if isinstance(context_data, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _parse_rendering_policies(
    raw: object,
) -> dict[str, Stage27RenderingPolicy]:
    if not isinstance(raw, dict):
        return {}
    policies: dict[str, Stage27RenderingPolicy] = {}
    for method, value in raw.items():
        if not isinstance(value, dict):
            continue
        policies[str(method)] = Stage27RenderingPolicy(
            order_policy=str(value.get("order_policy", "official_order")),
            prompt_policy=str(value.get("prompt_policy", "default")),
            max_sources=_optional_int(value.get("max_sources")),
            max_chars_per_source=_optional_int(value.get("max_chars_per_source")),
        )
    return policies


def _effective_rendering_policy(
    *,
    method: str,
    rendering_policies: dict[str, Stage27RenderingPolicy],
    default_max_sources: int,
    default_max_chars_per_source: int,
) -> Stage27RenderingPolicy:
    override = rendering_policies.get(method)
    if override is None:
        return Stage27RenderingPolicy(
            order_policy="official_order",
            prompt_policy="default",
            max_sources=default_max_sources,
            max_chars_per_source=default_max_chars_per_source,
        )
    return Stage27RenderingPolicy(
        order_policy=override.order_policy,
        prompt_policy=override.prompt_policy,
        max_sources=override.max_sources or default_max_sources,
        max_chars_per_source=(
            override.max_chars_per_source or default_max_chars_per_source
        ),
    )


def _order_sources_for_answer_generation(
    *,
    sources: list[dict[str, Any]],
    query: str,
    order_policy: str,
) -> list[dict[str, Any]]:
    indexed_sources = list(enumerate(sources))
    if order_policy == "official_order":
        return list(sources)
    if order_policy == "recovered_first":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (not _is_recovered_source(item[1]), item[0]),
            )
        ]
    if order_policy == "title_query_overlap":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (
                    -_title_query_overlap(query, item[1]),
                    not _is_recovered_source(item[1]),
                    item[0],
                ),
            )
        ]
    if order_policy == "recovered_then_title_query_overlap":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (
                    not _is_recovered_source(item[1]),
                    -_title_query_overlap(query, item[1]),
                    item[0],
                ),
            )
        ]
    raise ValueError(f"Unknown answer rendering order policy: {order_policy}")


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(
        source.get("logicguard_doc_id")
        or parse_doc_id_from_source_text(str(source.get("text", "")))
    )


def _source_title(source: dict[str, Any]) -> str:
    return str(
        source.get("title") or parse_title_from_source_text(str(source.get("text", "")))
    )


def _is_recovered_source(source: dict[str, Any]) -> bool:
    return (
        bool(source.get("recovered_from_changed_doc"))
        or bool(source.get("recovered_from_risk_non_oracle_source"))
        or str(source.get("source_state")) == "clean_reference"
    )


def _title_query_overlap(query: str, source: dict[str, Any]) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(_source_title(source)))
    if not query_tokens or not title_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / math.sqrt(
        len(query_tokens) * len(title_tokens)
    )


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text))
        if token and token not in {"the", "a", "an", "of", "and", "or", "was", "were"}
    ]


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _render_source_context(
    sources: list[dict[str, Any]],
    *,
    max_chars_per_source: int,
) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        doc_id = _source_doc_id(source)
        state = str(source.get("source_state", "official_poisoned_context"))
        title = str(
            source.get("title")
            or parse_title_from_source_text(str(source.get("text", "")))
        )
        text = _truncate(str(source.get("text", "")), max_chars=max_chars_per_source)
        blocks.append(
            "\n".join(
                [
                    f"[G{index}] doc_id={doc_id}; source_state={state}",
                    f"Title: {title}",
                    f"Text: {text}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _contains_answer_phrase(text: str, answer: str) -> bool:
    normalized_text = _normalize(text)
    normalized_answer = _normalize(answer)
    if not normalized_answer:
        return False
    pattern = r"(?<!\w)" + re.escape(normalized_answer) + r"(?!\w)"
    return re.search(pattern, normalized_text) is not None


def _normalize(text: str) -> str:
    lowered = text.lower()
    without_punctuation = lowered.translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _truncate(text: str, *, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _write_stage27_report(
    *,
    config: Stage27AnswerLLMConfig,
    cases: list[Stage27AnswerCase],
    results: list[Stage27AnswerLLMResult],
    summaries: list[Stage27SummaryRow],
) -> None:
    prompt_policies = ", ".join(
        f"`{policy}`" for policy in sorted({row.prompt_policy for row in summaries})
    )
    table = [
        "| 模型 | 方法 | prompt | query数 | correct | partial | utility | "
        "abstain | incorrect | attack success | errors | avg tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        table.append(
            f"| {row.model} | {row.method} | {row.prompt_policy} | {row.query_count} | "
            f"{row.correct_rate:.4f} | {row.partial_rate:.4f} | {row.utility_rate:.4f} | "
            f"{row.abstain_rate:.4f} | {row.incorrect_rate:.4f} | "
            f"{row.attack_success_rate:.4f} | {row.error_rate:.4f} | "
            f"{row.avg_total_tokens:.2f} |"
        )

    examples = [
        "| 模型 | 方法 | prompt | query_id | 标准答案 | 模型回答 | 标签 | 错误 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results[:20]:
        examples.append(
            "| "
            + " | ".join(
                [
                    result.model,
                    result.method,
                    result.prompt_policy,
                    result.query_id,
                    _compact_cell(result.gold_answer),
                    _compact_cell(result.generated_answer),
                    result.answer_label,
                    _compact_cell(result.error or result.judge_error or ""),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            f"# {config.stage_label} official sources LLM 回答层验证",
            "",
            "## 实验目的",
            "",
            f"{config.stage_label} 读取 official GraphRAG source contexts，调用真实 LLM "
            "生成短答案，并记录每个策略产生 correct、partial、abstain、incorrect "
            "或 attack-success 的情况。",
            "",
            "## 实验设置",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- case 数：`{len(cases)}`",
            f"- 模型：{', '.join(f'`{model}`' for model in config.models)}",
            f"- max queries：`{config.max_queries}`",
            f"- 每个 prompt 最大 sources：`{config.max_sources}`",
            f"- 每个 source 最大字符数：`{config.max_chars_per_source}`",
            f"- prompt policies：{prompt_policies}",
            f"- 可选 judge model：`{config.judge_model or 'disabled'}`",
            "",
            "## 指标说明",
            "",
            "- `correct`：模型回答命中归一化后的标准答案，或可选 judge 判为正确。",
            "- `partial`：可选 judge 判为相关但不完整。",
            "- `abstain`：模型回答 `UNKNOWN` 或等价的信息不足表达。",
            "- `incorrect`：模型回答既非正确也非拒答。",
            "- `attack success`：存在未恢复污染 support source 时，模型产生 incorrect 回答。",
            "",
            "## 汇总结果",
            "",
            *table,
            "",
            "## 样例",
            "",
            *examples,
            "",
            "## 产物",
            "",
            f"- cases JSONL: `{config.cases_output_path.as_posix()}`",
            f"- results JSONL: `{config.results_output_path.as_posix()}`",
            f"- metrics CSV: `{config.metrics_output_path.as_posix()}`",
            f"- summary CSV: `{config.summary_output_path.as_posix()}`",
            "",
        ]
    )
    if config.emit_markdown_report:
        config.report_path.write_text(content, encoding="utf-8")


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def _compact_cell(value: str, max_chars: int = 120) -> str:
    normalized = " ".join(value.split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _read_required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import subprocess

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
        value = completed.stdout.strip()
        if value:
            return value
    except Exception:
        pass
    raise RuntimeError(f"Missing required environment variable: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage27 real-LLM answer verification over official GraphRAG sources."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage27_answer_llm_poisoned5.yaml"),
    )
    args = parser.parse_args()
    run_from_config(Stage27AnswerLLMConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
