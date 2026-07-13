"""Stage32 real-LLM comparison for Stage28 vs Stage31 source rendering."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Protocol

import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.llm.context import build_qa_messages
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import ChatResponse, OpenAICompatibleChatClient
from logicguard.ms_graphrag.answer_level_llm_verification import _read_required_env
from logicguard.ms_graphrag.stage29_answer_audit import extract_rendered_source_summaries
from logicguard.ms_graphrag.stage31_answerability_ablation import (
    _contains_answer_phrase,
    _is_recovered_source,
    _order_sources,
    _ordering_uses_oracle,
    _render_single_source_block,
    _source_doc_id,
    _source_records,
)

_VARIANT_ORDER = {
    "stage28_default": 1,
    "stage31_title_query_overlap": 2,
}


class ChatClient(Protocol):
    """Protocol for the chat client used by Stage32."""

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
class Stage32VariantConfig:
    """One rendering variant in the Stage32 LLM comparison."""

    name: str
    order_policy: str
    top_k: int
    max_chars_per_source: int


@dataclass(frozen=True, slots=True)
class Stage32LLMComparisonConfig:
    """Paths and runtime settings for Stage32 answer-generation comparison."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    context_input_path: Path
    cases_output_path: Path
    results_output_path: Path
    summary_output_path: Path
    pairwise_output_path: Path
    examples_output_path: Path
    report_path: Path
    source_method: str
    variants: list[Stage32VariantConfig]
    models: list[str]
    max_queries: int = 20
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url_env: str = "DASHSCOPE_BASE_URL"
    temperature: float = 0.0
    max_tokens: int = 64
    timeout_seconds: int = 90
    stage_label: str = "Stage32"
    max_examples: int = 10

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage32LLMComparisonConfig":
        """Load a project-relative YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),
            query_integrity_path=resolve(payload["query_integrity_path"]),
            context_input_path=resolve(payload["context_input_path"]),
            cases_output_path=resolve(payload["cases_output_path"]),
            results_output_path=resolve(payload["results_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            pairwise_output_path=resolve(payload["pairwise_output_path"]),
            examples_output_path=resolve(payload["examples_output_path"]),
            report_path=resolve(payload["report_path"]),
            source_method=str(payload["source_method"]),
            variants=[
                Stage32VariantConfig(
                    name=str(item["name"]),
                    order_policy=str(item["order_policy"]),
                    top_k=int(item["top_k"]),
                    max_chars_per_source=int(item["max_chars_per_source"]),
                )
                for item in payload.get("variants", [])
            ],
            models=[str(model) for model in payload.get("models", [])],
            max_queries=int(payload.get("max_queries", 20)),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 90)),
            stage_label=str(payload.get("stage_label", "Stage32")),
            max_examples=int(payload.get("max_examples", 10)),
        )


@dataclass(frozen=True, slots=True)
class Stage32AnswerCase:
    """One rendered answer-generation case for one Stage32 variant."""

    dataset: str
    query_id: str
    query: str
    source_method: str
    variant: str
    order_policy: str
    ordering_uses_oracle: bool
    top_k: int
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
class Stage32LLMResult:
    """One generated model answer for one Stage32 case."""

    dataset: str
    model: str
    query_id: str
    query: str
    source_method: str
    variant: str
    order_policy: str
    ordering_uses_oracle: bool
    top_k: int
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
    is_correct: bool
    is_partial: bool
    is_abstained: bool
    is_incorrect: bool
    attack_success: bool
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error: str | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage32SummaryRow:
    """Variant-level Stage32 LLM comparison summary."""

    dataset: str
    model: str
    source_method: str
    variant: str
    order_policy: str
    ordering_uses_oracle: bool
    top_k: int
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
    support_hit_rate: float
    clean_answerable_rate: float
    avg_source_count: float
    avg_recovered_source_count: float
    avg_total_tokens: float
    avg_latency_seconds: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage32PairwiseRow:
    """Pairwise comparison between the first variant and one candidate variant."""

    dataset: str
    model: str
    source_method: str
    baseline_variant: str
    candidate_variant: str
    query_count: int
    baseline_utility_rate: float
    candidate_utility_rate: float
    utility_delta: float
    baseline_correct_rate: float
    candidate_correct_rate: float
    correct_delta: float
    baseline_abstain_rate: float
    candidate_abstain_rate: float
    abstain_delta: float
    baseline_answer_surface_rate: float
    candidate_answer_surface_rate: float
    answer_surface_delta: float
    candidate_improved_count: int
    candidate_regressed_count: int
    candidate_same_count: int

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(config: Stage32LLMComparisonConfig) -> list[Stage32LLMResult]:
    """Build Stage32 cases, call the configured model, and write artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    context_rows = _load_jsonl(config.context_input_path)
    cases = build_stage32_cases(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
        source_method=config.source_method,
        variants=config.variants,
    )
    api_key = _read_required_env(config.api_key_env)
    base_url = _read_required_env(config.base_url_env)
    client = OpenAICompatibleChatClient(base_url=base_url, api_key=api_key)
    results = run_stage32_generation(config=config, cases=cases, client=client)
    write_stage32_outputs(config=config, cases=cases, results=results)
    print(
        f"stage32_cases={len(cases)}, models={len(config.models)}, "
        f"calls={len(results)}"
    )
    return results


def build_stage32_cases(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str,
    source_method: str,
    variants: list[Stage32VariantConfig],
) -> list[Stage32AnswerCase]:
    """Render Stage32 answer cases for each configured source-ordering variant."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    integrity_by_query = {
        str(row.get("query_id", "")): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }

    cases: list[Stage32AnswerCase] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        method = str(context_row.get("method", ""))
        if method != source_method or query_id not in samples_by_query:
            continue
        sample = samples_by_query[query_id]
        changed_doc_ids = _string_list(
            integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        )
        sources = _source_records(context_row)
        for variant in variants:
            cases.append(
                _build_variant_case(
                    dataset=dataset,
                    sample=sample,
                    source_method=source_method,
                    variant=variant,
                    sources=sources,
                    changed_doc_ids=changed_doc_ids,
                )
            )

    cases.sort(
        key=lambda item: (
            item.query_id,
            _VARIANT_ORDER.get(item.variant, 99),
            item.variant,
        )
    )
    return cases


def run_stage32_generation(
    *,
    config: Stage32LLMComparisonConfig,
    cases: list[Stage32AnswerCase],
    client: ChatClient,
) -> list[Stage32LLMResult]:
    """Call configured models for each Stage32 rendered answer case."""

    results: list[Stage32LLMResult] = []
    for model in config.models:
        for case in cases:
            results.append(
                _call_model_for_case(
                    config=config,
                    client=client,
                    model=model,
                    case=case,
                )
            )
    return results


def summarize_stage32_results(
    results: list[Stage32LLMResult],
) -> list[Stage32SummaryRow]:
    """Aggregate Stage32 results by model and variant."""

    grouped: dict[tuple[str, str], list[Stage32LLMResult]] = {}
    for result in results:
        grouped.setdefault((result.model, result.variant), []).append(result)

    summaries: list[Stage32SummaryRow] = []
    for (model, variant), group in grouped.items():
        total = len(group)
        summaries.append(
            Stage32SummaryRow(
                dataset=group[0].dataset,
                model=model,
                source_method=group[0].source_method,
                variant=variant,
                order_policy=group[0].order_policy,
                ordering_uses_oracle=group[0].ordering_uses_oracle,
                top_k=group[0].top_k,
                max_chars_per_source=group[0].max_chars_per_source,
                query_count=total,
                correct_rate=_ratio(sum(1 for row in group if row.is_correct), total),
                partial_rate=_ratio(sum(1 for row in group if row.is_partial), total),
                utility_rate=_ratio(
                    sum(1 for row in group if row.is_correct or row.is_partial),
                    total,
                ),
                abstain_rate=_ratio(sum(1 for row in group if row.is_abstained), total),
                incorrect_rate=_ratio(sum(1 for row in group if row.is_incorrect), total),
                attack_success_rate=_ratio(
                    sum(1 for row in group if row.attack_success),
                    total,
                ),
                error_rate=_ratio(sum(1 for row in group if row.error), total),
                gold_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer),
                    total,
                ),
                support_hit_rate=_ratio(
                    sum(1 for row in group if row.support_hit_doc_ids),
                    total,
                ),
                clean_answerable_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.context_has_gold_answer
                        and not row.unrecovered_changed_doc_ids
                    ),
                    total,
                ),
                avg_source_count=_avg(row.source_count for row in group),
                avg_recovered_source_count=_avg(
                    row.recovered_source_count for row in group
                ),
                avg_total_tokens=_avg(row.total_tokens or 0 for row in group),
                avg_latency_seconds=_avg(row.latency_seconds for row in group),
            )
        )

    summaries.sort(
        key=lambda row: (
            row.model,
            _VARIANT_ORDER.get(row.variant, 99),
            row.variant,
        )
    )
    return summaries


def build_stage32_pairwise_rows(
    results: list[Stage32LLMResult],
    *,
    baseline_variant: str,
) -> list[Stage32PairwiseRow]:
    """Compare each non-baseline variant against the configured baseline."""

    grouped: dict[tuple[str, str], list[Stage32LLMResult]] = {}
    for row in results:
        grouped.setdefault((row.model, row.variant), []).append(row)

    output: list[Stage32PairwiseRow] = []
    models = sorted({row.model for row in results})
    variants = sorted(
        {row.variant for row in results if row.variant != baseline_variant},
        key=lambda value: (_VARIANT_ORDER.get(value, 99), value),
    )
    for model in models:
        baseline = {
            row.query_id: row
            for row in grouped.get((model, baseline_variant), [])
        }
        for candidate_variant in variants:
            candidate = {
                row.query_id: row
                for row in grouped.get((model, candidate_variant), [])
            }
            common_query_ids = sorted(set(baseline) & set(candidate))
            if not common_query_ids:
                continue
            baseline_rows = [baseline[query_id] for query_id in common_query_ids]
            candidate_rows = [candidate[query_id] for query_id in common_query_ids]
            output.append(
                _build_pairwise_row(
                    baseline_rows=baseline_rows,
                    candidate_rows=candidate_rows,
                    candidate_variant=candidate_variant,
                )
            )
    return output


def write_stage32_outputs(
    *,
    config: Stage32LLMComparisonConfig,
    cases: list[Stage32AnswerCase],
    results: list[Stage32LLMResult],
) -> None:
    """Write Stage32 cases, results, summaries, pairwise rows, examples, report."""

    summaries = summarize_stage32_results(results)
    baseline_variant = config.variants[0].name if config.variants else ""
    pairwise_rows = build_stage32_pairwise_rows(
        results,
        baseline_variant=baseline_variant,
    )
    examples = _select_examples(cases=cases, results=results, max_examples=config.max_examples)

    config.cases_output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(config.cases_output_path, [case.to_json_dict() for case in cases])
    _write_jsonl(config.results_output_path, [row.to_json_dict() for row in results])
    _write_csv(config.summary_output_path, [row.to_csv_row() for row in summaries])
    _write_csv(config.pairwise_output_path, [row.to_csv_row() for row in pairwise_rows])
    _write_jsonl(config.examples_output_path, examples)
    _write_stage32_report(
        config=config,
        cases=cases,
        summaries=summaries,
        pairwise_rows=pairwise_rows,
        examples=examples,
    )


def _build_variant_case(
    *,
    dataset: str,
    sample: NormalizedSample,
    source_method: str,
    variant: Stage32VariantConfig,
    sources: list[dict[str, Any]],
    changed_doc_ids: list[str],
) -> Stage32AnswerCase:
    ordered_sources = _order_sources(
        sources=sources,
        query=sample.query,
        gold_answer=sample.answer,
        order_policy=variant.order_policy,
    )[: variant.top_k]
    rendered_context = "\n\n".join(
        _render_single_source_block(
            source,
            rank=index,
            max_chars_per_source=variant.max_chars_per_source,
        )
        for index, source in enumerate(ordered_sources, start=1)
    )
    context_doc_ids = _dedupe(_source_doc_id(source) for source in ordered_sources)
    support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
    support_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
    changed_hits = _ordered_intersection(changed_doc_ids, context_doc_ids)
    unrecovered_changed = _dedupe(
        _source_doc_id(source)
        for source in ordered_sources
        if _source_doc_id(source) in set(changed_doc_ids)
        and not _is_recovered_source(source)
    )
    recovered_support = _ordered_intersection(
        support_doc_ids,
        _dedupe(
            _source_doc_id(source)
            for source in ordered_sources
            if _is_recovered_source(source)
        ),
    )
    return Stage32AnswerCase(
        dataset=dataset,
        query_id=sample.query_id,
        query=sample.query,
        source_method=source_method,
        variant=variant.name,
        order_policy=variant.order_policy,
        ordering_uses_oracle=_ordering_uses_oracle(variant.order_policy),
        top_k=variant.top_k,
        max_chars_per_source=variant.max_chars_per_source,
        gold_answer=sample.answer,
        support_doc_ids=support_doc_ids,
        changed_support_doc_ids=changed_doc_ids,
        context_doc_ids=context_doc_ids,
        support_hit_doc_ids=support_hits,
        changed_hit_doc_ids=changed_hits,
        unrecovered_changed_doc_ids=unrecovered_changed,
        recovered_support_doc_ids=recovered_support,
        context_has_gold_answer=_contains_answer_phrase(
            rendered_context,
            sample.answer,
        ),
        source_count=len(context_doc_ids),
        recovered_source_count=sum(
            1 for source in ordered_sources if _is_recovered_source(source)
        ),
        rendered_context=rendered_context,
    )


def _call_model_for_case(
    *,
    config: Stage32LLMComparisonConfig,
    client: ChatClient,
    model: str,
    case: Stage32AnswerCase,
) -> Stage32LLMResult:
    messages = build_qa_messages(question=case.query, context=case.rendered_context)
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
        return _result_from_parts(
            case=case,
            model=model,
            generated_answer=response.content,
            answer_label=_label_generated_answer(
                generated_answer=response.content,
                gold_answer=case.gold_answer,
            ),
            latency_seconds=round(elapsed, 4),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            error=None,
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
        )


def _result_from_parts(
    *,
    case: Stage32AnswerCase,
    model: str,
    generated_answer: str,
    answer_label: str,
    latency_seconds: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    error: str | None,
) -> Stage32LLMResult:
    is_correct = answer_label == "correct"
    is_partial = answer_label == "partial"
    is_abstained = answer_label == "abstained"
    is_incorrect = answer_label == "incorrect"
    return Stage32LLMResult(
        dataset=case.dataset,
        model=model,
        query_id=case.query_id,
        query=case.query,
        source_method=case.source_method,
        variant=case.variant,
        order_policy=case.order_policy,
        ordering_uses_oracle=case.ordering_uses_oracle,
        top_k=case.top_k,
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
        is_correct=is_correct,
        is_partial=is_partial,
        is_abstained=is_abstained,
        is_incorrect=is_incorrect,
        attack_success=is_incorrect and bool(case.unrecovered_changed_doc_ids),
        latency_seconds=latency_seconds,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        error=error,
    )


def _label_generated_answer(*, generated_answer: str, gold_answer: str) -> str:
    local = classify_answer(
        generated_answer,
        gold_answer=gold_answer,
        poisoned_answer="",
    )
    if local.is_abstained:
        return "abstained"
    if local.is_correct:
        return "correct"
    return "incorrect"


def _build_pairwise_row(
    *,
    baseline_rows: list[Stage32LLMResult],
    candidate_rows: list[Stage32LLMResult],
    candidate_variant: str,
) -> Stage32PairwiseRow:
    baseline_rate = _summary_rates(baseline_rows)
    candidate_rate = _summary_rates(candidate_rows)
    improvements = 0
    regressions = 0
    same = 0
    for baseline, candidate in zip(baseline_rows, candidate_rows, strict=True):
        baseline_score = _utility_score(baseline)
        candidate_score = _utility_score(candidate)
        if candidate_score > baseline_score:
            improvements += 1
        elif candidate_score < baseline_score:
            regressions += 1
        else:
            same += 1
    return Stage32PairwiseRow(
        dataset=baseline_rows[0].dataset,
        model=baseline_rows[0].model,
        source_method=baseline_rows[0].source_method,
        baseline_variant=baseline_rows[0].variant,
        candidate_variant=candidate_variant,
        query_count=len(baseline_rows),
        baseline_utility_rate=baseline_rate["utility"],
        candidate_utility_rate=candidate_rate["utility"],
        utility_delta=candidate_rate["utility"] - baseline_rate["utility"],
        baseline_correct_rate=baseline_rate["correct"],
        candidate_correct_rate=candidate_rate["correct"],
        correct_delta=candidate_rate["correct"] - baseline_rate["correct"],
        baseline_abstain_rate=baseline_rate["abstain"],
        candidate_abstain_rate=candidate_rate["abstain"],
        abstain_delta=candidate_rate["abstain"] - baseline_rate["abstain"],
        baseline_answer_surface_rate=baseline_rate["answer_surface"],
        candidate_answer_surface_rate=candidate_rate["answer_surface"],
        answer_surface_delta=(
            candidate_rate["answer_surface"] - baseline_rate["answer_surface"]
        ),
        candidate_improved_count=improvements,
        candidate_regressed_count=regressions,
        candidate_same_count=same,
    )


def _summary_rates(rows: list[Stage32LLMResult]) -> dict[str, float]:
    total = len(rows)
    return {
        "utility": _ratio(
            sum(1 for row in rows if row.is_correct or row.is_partial),
            total,
        ),
        "correct": _ratio(sum(1 for row in rows if row.is_correct), total),
        "abstain": _ratio(sum(1 for row in rows if row.is_abstained), total),
        "answer_surface": _ratio(
            sum(1 for row in rows if row.context_has_gold_answer),
            total,
        ),
    }


def _utility_score(row: Stage32LLMResult) -> int:
    if row.is_correct:
        return 2
    if row.is_partial:
        return 1
    return 0


def _select_examples(
    *,
    cases: list[Stage32AnswerCase],
    results: list[Stage32LLMResult],
    max_examples: int,
) -> list[dict[str, object]]:
    cases_by_key = {(case.query_id, case.variant): case for case in cases}
    grouped: dict[tuple[str, str], dict[str, Stage32LLMResult]] = {}
    for result in results:
        grouped.setdefault((result.model, result.query_id), {})[result.variant] = result

    examples: list[dict[str, object]] = []
    for (model, query_id), by_variant in sorted(grouped.items(), key=_example_key):
        ordered_results = sorted(
            by_variant.values(),
            key=lambda row: (_VARIANT_ORDER.get(row.variant, 99), row.variant),
        )
        if len(ordered_results) < 2:
            continue
        baseline = ordered_results[0]
        candidate = ordered_results[-1]
        if not _is_interesting_example(baseline, candidate):
            continue
        examples.append(
            {
                "model": model,
                "query_id": query_id,
                "query": baseline.query,
                "gold_answer": baseline.gold_answer,
                "pipeline_steps": [
                    "1. 读取 Stage28 风险源恢复后的 official GraphRAG sources。",
                    "2. 分别按 Stage28 默认顺序和 Stage31 推荐的非 oracle 标题重叠顺序渲染 prompt。",
                    "3. 使用同一个真实 LLM、相同 temperature 和 max_tokens 生成短答案。",
                    "4. 用本地 gold-answer 归一化规则标记 correct / abstained / incorrect。",
                ],
                "variants": [
                    _example_variant_payload(
                        result,
                        cases_by_key.get((result.query_id, result.variant)),
                    )
                    for result in ordered_results
                ],
            }
        )
        if len(examples) >= max_examples:
            break
    if examples:
        return examples
    return _fallback_examples(cases=cases, results=results, max_examples=max_examples)


def _example_key(item: tuple[tuple[str, str], dict[str, Stage32LLMResult]]) -> tuple[int, str]:
    _, by_variant = item
    ordered = sorted(
        by_variant.values(),
        key=lambda row: (_VARIANT_ORDER.get(row.variant, 99), row.variant),
    )
    if len(ordered) < 2:
        return (9, item[0][1])
    baseline = ordered[0]
    candidate = ordered[-1]
    if candidate.is_correct and not baseline.is_correct:
        return (0, baseline.query_id)
    if candidate.context_has_gold_answer and not baseline.context_has_gold_answer:
        return (1, baseline.query_id)
    if candidate.answer_label != baseline.answer_label:
        return (2, baseline.query_id)
    return (9, baseline.query_id)


def _is_interesting_example(
    baseline: Stage32LLMResult,
    candidate: Stage32LLMResult,
) -> bool:
    return (
        candidate.answer_label != baseline.answer_label
        or candidate.context_has_gold_answer != baseline.context_has_gold_answer
        or candidate.support_hit_doc_ids != baseline.support_hit_doc_ids
    )


def _fallback_examples(
    *,
    cases: list[Stage32AnswerCase],
    results: list[Stage32LLMResult],
    max_examples: int,
) -> list[dict[str, object]]:
    cases_by_key = {(case.query_id, case.variant): case for case in cases}
    examples: list[dict[str, object]] = []
    for result in sorted(
        results,
        key=lambda row: (
            row.query_id,
            _VARIANT_ORDER.get(row.variant, 99),
            row.variant,
        ),
    ):
        examples.append(
            {
                "model": result.model,
                "query_id": result.query_id,
                "query": result.query,
                "gold_answer": result.gold_answer,
                "pipeline_steps": [
                    "1. 读取 Stage28 风险源恢复后的 official GraphRAG sources。",
                    "2. 按配置中的 source rendering variant 渲染 prompt。",
                    "3. 调用真实 LLM 并进行本地回答标签审计。",
                ],
                "variants": [
                    _example_variant_payload(
                        result,
                        cases_by_key.get((result.query_id, result.variant)),
                    )
                ],
            }
        )
        if len(examples) >= max_examples:
            break
    return examples


def _example_variant_payload(
    result: Stage32LLMResult,
    case: Stage32AnswerCase | None,
) -> dict[str, object]:
    source_summaries = (
        extract_rendered_source_summaries(case.rendered_context, max_sources=5)
        if case is not None
        else []
    )
    return {
        "variant": result.variant,
        "order_policy": result.order_policy,
        "top_k": result.top_k,
        "max_chars_per_source": result.max_chars_per_source,
        "context_doc_ids": result.context_doc_ids,
        "support_hit_doc_ids": result.support_hit_doc_ids,
        "recovered_support_doc_ids": result.recovered_support_doc_ids,
        "unrecovered_changed_doc_ids": result.unrecovered_changed_doc_ids,
        "context_has_gold_answer": result.context_has_gold_answer,
        "generated_answer": result.generated_answer,
        "answer_label": result.answer_label,
        "error": result.error,
        "sources": [source.to_json_dict() for source in source_summaries],
    }


def _write_stage32_report(
    *,
    config: Stage32LLMComparisonConfig,
    cases: list[Stage32AnswerCase],
    summaries: list[Stage32SummaryRow],
    pairwise_rows: list[Stage32PairwiseRow],
    examples: list[dict[str, object]],
) -> None:
    summary_table = [
        "| 模型 | variant | 排序 | top-k | 字符预算 | query数 | correct | utility | abstain | incorrect | attack success | answer surface | support hit | avg tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        summary_table.append(
            f"| `{row.model}` | `{row.variant}` | `{row.order_policy}` | "
            f"{row.top_k} | {row.max_chars_per_source} | {row.query_count} | "
            f"{row.correct_rate:.4f} | {row.utility_rate:.4f} | "
            f"{row.abstain_rate:.4f} | {row.incorrect_rate:.4f} | "
            f"{row.attack_success_rate:.4f} | {row.gold_answer_surface_rate:.4f} | "
            f"{row.support_hit_rate:.4f} | {row.avg_total_tokens:.2f} |"
        )

    pairwise_table = [
        "| 模型 | baseline | candidate | query数 | utility delta | correct delta | abstain delta | answer surface delta | improved | regressed | same |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in pairwise_rows:
        pairwise_table.append(
            f"| `{row.model}` | `{row.baseline_variant}` | "
            f"`{row.candidate_variant}` | {row.query_count} | "
            f"{row.utility_delta:.4f} | {row.correct_delta:.4f} | "
            f"{row.abstain_delta:.4f} | {row.answer_surface_delta:.4f} | "
            f"{row.candidate_improved_count} | {row.candidate_regressed_count} | "
            f"{row.candidate_same_count} |"
        )

    content = "\n".join(
        [
            f"# {config.stage_label} 真实回答对照验证",
            "",
            "## 实验目的",
            "",
            "Stage32 检查 Stage31 的 answerability proxy 是否能转化为真实回答质量："
            "在同一批 Stage28 recovered official GraphRAG sources 上，"
            "对比 Stage28 默认渲染和 Stage31 推荐的非 oracle source ordering。",
            "",
            "## 实验边界",
            "",
            "- 本阶段调用真实 LLM 生成答案，但不调用额外 LLM judge；回答标签仍使用本地 gold-answer 归一化匹配。",
            "- `title_query_overlap` 只使用 query、source title、source state/recovery 标记，不使用 gold answer。",
            "- 结果用于判断 prompt/source rendering 是否值得固化到正式回答管线，不替代更大规模跨数据集实验。",
            "",
            "## 实验设置",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- source method：`{config.source_method}`",
            f"- cases：`{len(cases)}`",
            f"- 模型：{', '.join(f'`{model}`' for model in config.models)}",
            f"- max queries：`{config.max_queries}`",
            f"- variants：{', '.join(f'`{variant.name}`' for variant in config.variants)}",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## Pairwise 对照",
            "",
            *pairwise_table,
            "",
            "## 主要结论",
            "",
            _stage32_conclusion(summaries=summaries, pairwise_rows=pairwise_rows),
            "",
            "## 实际实验示例",
            "",
            *_render_example_sections(examples),
            "",
            "## 产物路径",
            "",
            f"- cases JSONL：`{config.cases_output_path.as_posix()}`",
            f"- results JSONL：`{config.results_output_path.as_posix()}`",
            f"- summary CSV：`{config.summary_output_path.as_posix()}`",
            f"- pairwise CSV：`{config.pairwise_output_path.as_posix()}`",
            f"- examples JSONL：`{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _stage32_conclusion(
    *,
    summaries: list[Stage32SummaryRow],
    pairwise_rows: list[Stage32PairwiseRow],
) -> str:
    lines: list[str] = []
    if pairwise_rows:
        best = max(pairwise_rows, key=lambda row: (row.utility_delta, row.correct_delta))
        lines.append(
            f"`{best.candidate_variant}` 相对 `{best.baseline_variant}` 的 "
            f"utility delta 为 `{best.utility_delta:.4f}`，correct delta 为 "
            f"`{best.correct_delta:.4f}`，abstain delta 为 "
            f"`{best.abstain_delta:.4f}`。"
        )
        lines.append(
            f"逐 query 看，candidate 改善 `{best.candidate_improved_count}` 个，"
            f"退化 `{best.candidate_regressed_count}` 个，持平 "
            f"`{best.candidate_same_count}` 个。"
        )
    for row in summaries:
        lines.append(
            f"`{row.variant}` 的 answer surface rate 为 "
            f"`{row.gold_answer_surface_rate:.4f}`，真实 utility rate 为 "
            f"`{row.utility_rate:.4f}`；二者差距可用于定位 LLM 是否没有充分利用已恢复证据。"
        )
    return "\n\n".join(lines) if lines else "本次没有生成可汇总的 Stage32 结果。"


def _render_example_sections(examples: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for index, example in enumerate(examples, start=1):
        lines.extend(
            [
                f"### 示例 {index}: query_id `{example['query_id']}`",
                "",
                f"- 问题：{example['query']}",
                f"- 标准答案：`{example['gold_answer']}`",
                f"- 模型：`{example['model']}`",
                "",
                "流程步骤：",
                "",
            ]
        )
        lines.extend(f"- {step}" for step in _list_value(example.get("pipeline_steps")))
        for variant in _list_value(example.get("variants")):
            if not isinstance(variant, dict):
                continue
            lines.extend(
                [
                    "",
                    f"#### variant `{variant['variant']}`",
                    "",
                    f"- 排序策略：`{variant['order_policy']}`，top-k：`{variant['top_k']}`，每 source 字符预算：`{variant['max_chars_per_source']}`",
                    f"- context doc_ids：`{';'.join(_list_value(variant.get('context_doc_ids')))}`",
                    f"- support hit doc_ids：`{';'.join(_list_value(variant.get('support_hit_doc_ids')))}`",
                    f"- recovered support doc_ids：`{';'.join(_list_value(variant.get('recovered_support_doc_ids')))}`",
                    f"- 未恢复污染 doc_ids：`{';'.join(_list_value(variant.get('unrecovered_changed_doc_ids')))}`",
                    f"- context 是否含标准答案：`{variant['context_has_gold_answer']}`",
                    f"- 模型回答：`{_markdown_cell(str(variant['generated_answer']))}`",
                    f"- 回答标签：`{variant['answer_label']}`",
                    "",
                    "引用 sources：",
                    "",
                    "| 序号 | doc_id | source 状态 | 标题 | 片段 |",
                    "| ---: | --- | --- | --- | --- |",
                ]
            )
            for source in _list_value(variant.get("sources")):
                if not isinstance(source, dict):
                    continue
                lines.append(
                    f"| {source.get('rank', '')} | {source.get('doc_id', '')} | "
                    f"{_markdown_cell(str(source.get('source_state', '')))} | "
                    f"{_markdown_cell(str(source.get('title', '')))} | "
                    f"{_markdown_cell(str(source.get('snippet', '')))} |"
                )
        lines.append("")
    return lines


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return []


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _ordered_intersection(left: Iterable[str], right: Iterable[str]) -> list[str]:
    right_set = set(right)
    return [item for item in _dedupe(left) if item in right_set]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _avg(values: Iterable[float | int | None]) -> float:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else 0.0


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, list):
            output[key] = ";".join(str(item) for item in value)
        elif isinstance(value, bool):
            output[key] = "1" if value else "0"
        elif isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def _markdown_cell(text: str, max_chars: int = 220) -> str:
    normalized = " ".join(str(text).split()).replace("|", "/")
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage32 真实回答对照验证。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage32_llm_comparison_poisoned20.yaml"),
    )
    args = parser.parse_args()
    run_from_config(Stage32LLMComparisonConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
