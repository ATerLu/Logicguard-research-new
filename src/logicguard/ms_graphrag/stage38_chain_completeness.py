"""Stage38 chain-completeness diagnostics and second-hop evidence append.

Stage37 showed that answer surface is not enough for multi-hop QA: a context can
contain the predicted answer string while still missing the document that proves
the second-hop property. Stage38 makes that failure mode explicit and tests a
non-oracle, bridge-entity append policy over trusted clean GraphRAG candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from rank_bm25 import BM25Okapi

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.non_oracle_source_recovery import (
    NonOracleCandidateSource,
    load_candidate_sources,
)
from logicguard.ms_graphrag.stage31_answerability_ablation import (
    _contains_answer_phrase,
    _dedupe,
    _first_rank_with_answer,
    _first_rank_with_doc_id,
    _is_recovered_source,
    _load_jsonl,
    _ordered_intersection,
    _prompt_char_count,
    _render_single_source_block,
    _source_doc_id,
    _source_records,
    _source_title,
    _tokens,
)

_METHOD_ORDER = {
    "stage35_query_bm25_append_top8": 1,
    "stage35_query_bm25_append_top12": 2,
    "stage35_query_bm25_append_top16": 3,
    "stage38_second_hop_append_top14": 4,
    "stage38_second_hop_append_top16": 5,
}

_DIAGNOSIS_ORDER = {
    "complete_answered": 1,
    "complete_but_abstained": 2,
    "complete_but_unanswered": 3,
    "complete_support_without_answer_surface": 3,
    "answer_surface_without_full_chain": 4,
    "partial_support_missing_second_hop": 5,
    "full_support_without_answer_surface": 6,
    "missing_all_support": 7,
    "unsafe_context": 8,
}

_ENTITY_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9'.-]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9'.-]*|of|the|and|a|an|de|del|la|le|van|von|da|di|du))*"
)

_ENTITY_BLOCKLIST = {
    "document id",
    "title",
    "text",
    "source",
    "references",
    "g",
}


@dataclass(frozen=True, slots=True)
class Stage38ChainCompletenessConfig:
    """Paths and settings for Stage38 chain-completeness diagnostics."""

    dataset: str
    sample_path: Path
    context_input_path: Path
    clean_reference_output_dir: Path
    judged_results_path: Path | None
    chain_rows_output_path: Path
    summary_output_path: Path
    targeted_context_output_path: Path
    examples_output_path: Path
    report_path: Path
    methods: list[str]
    max_queries: int = 20
    max_sources: int = 14
    max_chars_per_source: int = 450
    candidate_pool_top_k: int = 80
    stage_label: str = "Stage38"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage38ChainCompletenessConfig":
        """Load a project-relative YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path | None:
            if raw in (None, ""):
                return None
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),  # type: ignore[arg-type]
            context_input_path=resolve(payload["context_input_path"]),  # type: ignore[arg-type]
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),  # type: ignore[arg-type]
            judged_results_path=resolve(payload.get("judged_results_path")),
            chain_rows_output_path=resolve(payload["chain_rows_output_path"]),  # type: ignore[arg-type]
            summary_output_path=resolve(payload["summary_output_path"]),  # type: ignore[arg-type]
            targeted_context_output_path=resolve(payload["targeted_context_output_path"]),  # type: ignore[arg-type]
            examples_output_path=resolve(payload["examples_output_path"]),  # type: ignore[arg-type]
            report_path=resolve(payload["report_path"]),  # type: ignore[arg-type]
            methods=[str(method) for method in payload.get("methods", [])],
            max_queries=int(payload.get("max_queries", 20)),
            max_sources=int(payload.get("max_sources", 14)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 450)),
            candidate_pool_top_k=int(payload.get("candidate_pool_top_k", 80)),
            stage_label=str(payload.get("stage_label", "Stage38")),
        )


@dataclass(frozen=True, slots=True)
class Stage38ChainRow:
    """One query-method row with baseline and targeted chain diagnostics."""

    dataset: str
    query_id: str
    query: str
    method: str
    max_sources: int
    max_chars_per_source: int
    gold_answer: str
    final_label: str
    final_reason: str
    generated_answer: str
    final_attack_success: bool
    support_doc_ids: list[str]
    context_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    missing_support_doc_ids: list[str]
    full_support_hit: bool
    support_coverage_rate: float
    context_has_gold_answer: bool
    support_context_has_gold_answer: bool
    first_gold_answer_rank: int | None
    first_support_rank: int | None
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    chain_complete: bool
    chain_diagnosis: str
    bridge_terms: list[str]
    targeted_context_doc_ids: list[str]
    targeted_added_doc_ids: list[str]
    targeted_added_support_doc_ids: list[str]
    targeted_support_hit_doc_ids: list[str]
    targeted_missing_support_doc_ids: list[str]
    targeted_full_support_hit: bool
    targeted_support_coverage_rate: float
    targeted_context_has_gold_answer: bool
    targeted_support_context_has_gold_answer: bool
    targeted_chain_complete: bool
    targeted_chain_diagnosis: str
    targeted_first_gold_answer_rank: int | None
    targeted_first_support_rank: int | None
    targeted_gain_full_support: bool
    targeted_gain_chain_complete: bool
    source_count: int
    targeted_source_count: int
    targeted_added_source_count: int
    prompt_char_count: int
    estimated_prompt_tokens: int
    targeted_prompt_char_count: int
    targeted_estimated_prompt_tokens: int
    source_summaries: list[dict[str, object]]
    targeted_source_summaries: list[dict[str, object]]
    sources: list[dict[str, Any]]
    targeted_sources: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Stage38SummaryRow:
    """Method-level Stage38 aggregate metrics."""

    dataset: str
    method: str
    query_count: int
    answer_audit_available: bool
    final_utility_rate: float | None
    final_attack_success_rate: float | None
    answer_surface_rate: float
    support_answer_surface_rate: float
    support_hit_rate: float
    full_support_hit_rate: float
    chain_complete_rate: float
    answer_surface_without_full_chain_rate: float
    partial_support_missing_second_hop_rate: float
    missing_all_support_rate: float
    complete_but_abstained_rate: float
    targeted_answer_surface_rate: float
    targeted_support_answer_surface_rate: float
    targeted_full_support_hit_rate: float
    targeted_chain_complete_rate: float
    targeted_full_support_gain_rate: float
    targeted_chain_complete_gain_rate: float
    targeted_added_support_rate: float
    avg_source_count: float
    avg_targeted_source_count: float
    avg_added_source_count: float
    avg_estimated_prompt_tokens: float
    avg_targeted_estimated_prompt_tokens: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(config: Stage38ChainCompletenessConfig) -> list[Stage38ChainRow]:
    """Run Stage38 diagnostics and write all artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    context_rows = _load_jsonl(config.context_input_path)
    judged_rows = (
        _load_jsonl(config.judged_results_path)
        if config.judged_results_path and config.judged_results_path.exists()
        else []
    )
    candidate_sources = load_candidate_sources(config.clean_reference_output_dir)
    rows = build_stage38_chain_rows(
        samples=samples,
        context_rows=context_rows,
        candidate_sources=candidate_sources,
        judged_rows=judged_rows,
        dataset=config.dataset,
        methods=config.methods,
        max_sources=config.max_sources,
        max_chars_per_source=config.max_chars_per_source,
        candidate_pool_top_k=config.candidate_pool_top_k,
    )
    summaries = summarize_stage38_rows(rows)
    targeted_context_rows = build_stage38_targeted_context_rows(
        context_rows=context_rows,
        chain_rows=rows,
        selected_max_sources=config.max_sources,
    )
    write_stage38_outputs(
        config=config,
        rows=rows,
        summaries=summaries,
        targeted_context_rows=targeted_context_rows,
    )
    print(
        f"stage38_chain_rows={len(rows)}, "
        f"targeted_context_rows={len(targeted_context_rows)}"
    )
    return rows


def build_stage38_chain_rows(
    *,
    samples: list[NormalizedSample],
    context_rows: list[dict[str, Any]],
    candidate_sources: list[NonOracleCandidateSource],
    judged_rows: list[dict[str, Any]],
    dataset: str,
    methods: list[str],
    max_sources: int,
    max_chars_per_source: int,
    candidate_pool_top_k: int,
) -> list[Stage38ChainRow]:
    """Build chain-completeness rows with a non-oracle second-hop append."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    allowed_methods = set(methods)
    judged_by_query_method = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row
        for row in judged_rows
        if row.get("query_id") is not None
    }
    judged_by_query = {
        str(row.get("query_id", "")): row
        for row in judged_rows
        if row.get("query_id") is not None
    }

    rows: list[Stage38ChainRow] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        method = str(context_row.get("method", "unknown"))
        if query_id not in samples_by_query:
            continue
        if allowed_methods and method not in allowed_methods:
            continue
        sample = samples_by_query[query_id]
        judged = judged_by_query_method.get((query_id, method), judged_by_query.get(query_id, {}))
        current_sources = _source_records(context_row)
        base_sources = current_sources[:max_sources]
        bridge_terms = _bridge_terms(base_sources, query=sample.query)
        candidate_hits = _rank_bridge_candidates(
            query=sample.query,
            bridge_terms=bridge_terms,
            candidate_sources=candidate_sources,
            existing_doc_ids=set(_source_doc_id(source) for source in base_sources),
            top_k=candidate_pool_top_k,
        )
        targeted_sources = _append_second_hop_candidates(
            base_sources=base_sources,
            candidate_hits=candidate_hits,
            max_sources=max_sources,
            bridge_terms=bridge_terms,
        )
        rows.append(
            _build_chain_row(
                dataset=dataset,
                sample=sample,
                method=method,
                max_sources=max_sources,
                max_chars_per_source=max_chars_per_source,
                sources=base_sources,
                targeted_sources=targeted_sources,
                bridge_terms=bridge_terms,
                judged=judged,
            )
        )

    rows.sort(key=lambda row: (row.query_id, _METHOD_ORDER.get(row.method, 99), row.method))
    return rows


def summarize_stage38_rows(rows: list[Stage38ChainRow]) -> list[Stage38SummaryRow]:
    """Aggregate Stage38 rows by method."""

    grouped: dict[str, list[Stage38ChainRow]] = {}
    for row in rows:
        grouped.setdefault(row.method, []).append(row)

    summaries: list[Stage38SummaryRow] = []
    for method, group in grouped.items():
        total = len(group)
        answer_audit_available = any(bool(row.final_label) for row in group)
        summaries.append(
            Stage38SummaryRow(
                dataset=group[0].dataset,
                method=method,
                query_count=total,
                answer_audit_available=answer_audit_available,
                final_utility_rate=(
                    _ratio(
                        sum(
                            1
                            for row in group
                            if row.final_label in {"correct", "partial"}
                        ),
                        total,
                    )
                    if answer_audit_available
                    else None
                ),
                final_attack_success_rate=(
                    _ratio(
                        sum(1 for row in group if row.final_attack_success),
                        total,
                    )
                    if answer_audit_available
                    else None
                ),
                answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer),
                    total,
                ),
                support_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.support_context_has_gold_answer),
                    total,
                ),
                support_hit_rate=_ratio(
                    sum(1 for row in group if row.support_hit_doc_ids),
                    total,
                ),
                full_support_hit_rate=_ratio(
                    sum(1 for row in group if row.full_support_hit),
                    total,
                ),
                chain_complete_rate=_ratio(
                    sum(1 for row in group if row.chain_complete),
                    total,
                ),
                answer_surface_without_full_chain_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.chain_diagnosis == "answer_surface_without_full_chain"
                    ),
                    total,
                ),
                partial_support_missing_second_hop_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.chain_diagnosis == "partial_support_missing_second_hop"
                    ),
                    total,
                ),
                missing_all_support_rate=_ratio(
                    sum(1 for row in group if row.chain_diagnosis == "missing_all_support"),
                    total,
                ),
                complete_but_abstained_rate=_ratio(
                    sum(1 for row in group if row.chain_diagnosis == "complete_but_abstained"),
                    total,
                ),
                targeted_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.targeted_context_has_gold_answer),
                    total,
                ),
                targeted_support_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.targeted_support_context_has_gold_answer),
                    total,
                ),
                targeted_full_support_hit_rate=_ratio(
                    sum(1 for row in group if row.targeted_full_support_hit),
                    total,
                ),
                targeted_chain_complete_rate=_ratio(
                    sum(1 for row in group if row.targeted_chain_complete),
                    total,
                ),
                targeted_full_support_gain_rate=_ratio(
                    sum(1 for row in group if row.targeted_gain_full_support),
                    total,
                ),
                targeted_chain_complete_gain_rate=_ratio(
                    sum(1 for row in group if row.targeted_gain_chain_complete),
                    total,
                ),
                targeted_added_support_rate=_ratio(
                    sum(1 for row in group if row.targeted_added_support_doc_ids),
                    total,
                ),
                avg_source_count=_avg(row.source_count for row in group),
                avg_targeted_source_count=_avg(row.targeted_source_count for row in group),
                avg_added_source_count=_avg(row.targeted_added_source_count for row in group),
                avg_estimated_prompt_tokens=_avg(
                    row.estimated_prompt_tokens for row in group
                ),
                avg_targeted_estimated_prompt_tokens=_avg(
                    row.targeted_estimated_prompt_tokens for row in group
                ),
            )
        )
    summaries.sort(key=lambda row: (_METHOD_ORDER.get(row.method, 99), row.method))
    return summaries


def build_stage38_targeted_context_rows(
    *,
    context_rows: list[dict[str, Any]],
    chain_rows: list[Stage38ChainRow],
    selected_max_sources: int,
) -> list[dict[str, Any]]:
    """Materialize Stage38 targeted contexts for later real LLM answer runs."""

    row_by_query_method = {
        (row.query_id, row.method): row
        for row in chain_rows
        if row.max_sources == selected_max_sources
    }
    output_rows: list[dict[str, Any]] = []
    for context_row in context_rows:
        key = (str(context_row.get("query_id", "")), str(context_row.get("method", "")))
        chain_row = row_by_query_method.get(key)
        if chain_row is None:
            continue
        row = deepcopy(context_row)
        context_data = row.get("context_data", {})
        if not isinstance(context_data, dict):
            context_data = {}
        context_data = deepcopy(context_data)
        context_data["sources"] = chain_row.targeted_sources
        row["context_data"] = context_data
        row["method"] = f"stage38_second_hop_append_top{selected_max_sources}"
        row["stage38_base_method"] = chain_row.method
        row["stage38_bridge_terms"] = chain_row.bridge_terms
        row["stage38_targeted_added_doc_ids"] = chain_row.targeted_added_doc_ids
        row["stage38_targeted_added_support_doc_ids"] = (
            chain_row.targeted_added_support_doc_ids
        )
        row["stage38_chain_diagnosis"] = chain_row.chain_diagnosis
        row["stage38_targeted_chain_diagnosis"] = chain_row.targeted_chain_diagnosis
        row["stage38_targeted_chain_complete"] = chain_row.targeted_chain_complete
        row["stage38_targeted_full_support_hit"] = chain_row.targeted_full_support_hit
        row["context_text"] = _render_sources(
            chain_row.targeted_sources,
            max_chars_per_source=chain_row.max_chars_per_source,
        )
        output_rows.append(row)
    output_rows.sort(key=lambda row: str(row.get("query_id", "")))
    return output_rows


def write_stage38_outputs(
    *,
    config: Stage38ChainCompletenessConfig,
    rows: list[Stage38ChainRow],
    summaries: list[Stage38SummaryRow],
    targeted_context_rows: list[dict[str, Any]],
) -> None:
    """Write Stage38 JSONL/CSV/report artifacts."""

    _write_jsonl(config.chain_rows_output_path, [row.to_json_dict() for row in rows])
    _write_csv(config.summary_output_path, [row.to_csv_row() for row in summaries])
    examples = _select_examples(rows)
    _write_jsonl(config.examples_output_path, [row.to_json_dict() for row in examples])
    _write_jsonl(config.targeted_context_output_path, targeted_context_rows)
    _write_stage38_report(
        config=config,
        rows=rows,
        summaries=summaries,
        examples=examples,
        targeted_context_rows=targeted_context_rows,
    )


def _build_chain_row(
    *,
    dataset: str,
    sample: NormalizedSample,
    method: str,
    max_sources: int,
    max_chars_per_source: int,
    sources: list[dict[str, Any]],
    targeted_sources: list[dict[str, Any]],
    bridge_terms: list[str],
    judged: dict[str, Any],
) -> Stage38ChainRow:
    support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
    context_metrics = _context_chain_metrics(
        sample=sample,
        sources=sources,
        max_chars_per_source=max_chars_per_source,
        support_doc_ids=support_doc_ids,
    )
    targeted_metrics = _context_chain_metrics(
        sample=sample,
        sources=targeted_sources,
        max_chars_per_source=max_chars_per_source,
        support_doc_ids=support_doc_ids,
    )
    context_doc_ids = context_metrics["context_doc_ids"]
    targeted_doc_ids = targeted_metrics["context_doc_ids"]
    targeted_added_doc_ids = [
        doc_id for doc_id in targeted_doc_ids if doc_id not in set(context_doc_ids)
    ]
    targeted_added_support_doc_ids = _ordered_intersection(
        support_doc_ids,
        targeted_added_doc_ids,
    )
    chain_complete = _chain_complete(context_metrics)
    targeted_chain_complete = _chain_complete(targeted_metrics)
    chain_diagnosis = _chain_diagnosis(
        metrics=context_metrics,
        final_label=str(judged.get("final_label", "")),
    )
    targeted_chain_diagnosis = _chain_diagnosis(
        metrics=targeted_metrics,
        final_label=str(judged.get("final_label", "")),
    )

    prompt_char_count = _prompt_char_count(
        question=sample.query,
        context=str(context_metrics["rendered_context"]),
    )
    targeted_prompt_char_count = _prompt_char_count(
        question=sample.query,
        context=str(targeted_metrics["rendered_context"]),
    )
    return Stage38ChainRow(
        dataset=dataset,
        query_id=sample.query_id,
        query=sample.query,
        method=method,
        max_sources=max_sources,
        max_chars_per_source=max_chars_per_source,
        gold_answer=sample.answer,
        final_label=str(judged.get("final_label", "")),
        final_reason=str(judged.get("final_reason", "")),
        generated_answer=str(judged.get("generated_answer", "")),
        final_attack_success=_truthy(judged.get("final_attack_success")),
        support_doc_ids=support_doc_ids,
        context_doc_ids=list(context_doc_ids),
        support_hit_doc_ids=list(context_metrics["support_hit_doc_ids"]),
        missing_support_doc_ids=list(context_metrics["missing_support_doc_ids"]),
        full_support_hit=bool(context_metrics["full_support_hit"]),
        support_coverage_rate=float(context_metrics["support_coverage_rate"]),
        context_has_gold_answer=bool(context_metrics["context_has_gold_answer"]),
        support_context_has_gold_answer=bool(
            context_metrics["support_context_has_gold_answer"]
        ),
        first_gold_answer_rank=context_metrics["first_gold_answer_rank"],  # type: ignore[arg-type]
        first_support_rank=context_metrics["first_support_rank"],  # type: ignore[arg-type]
        unrecovered_changed_doc_ids=list(context_metrics["unrecovered_changed_doc_ids"]),
        recovered_support_doc_ids=list(context_metrics["recovered_support_doc_ids"]),
        chain_complete=chain_complete,
        chain_diagnosis=chain_diagnosis,
        bridge_terms=bridge_terms,
        targeted_context_doc_ids=list(targeted_doc_ids),
        targeted_added_doc_ids=targeted_added_doc_ids,
        targeted_added_support_doc_ids=targeted_added_support_doc_ids,
        targeted_support_hit_doc_ids=list(targeted_metrics["support_hit_doc_ids"]),
        targeted_missing_support_doc_ids=list(targeted_metrics["missing_support_doc_ids"]),
        targeted_full_support_hit=bool(targeted_metrics["full_support_hit"]),
        targeted_support_coverage_rate=float(targeted_metrics["support_coverage_rate"]),
        targeted_context_has_gold_answer=bool(
            targeted_metrics["context_has_gold_answer"]
        ),
        targeted_support_context_has_gold_answer=bool(
            targeted_metrics["support_context_has_gold_answer"]
        ),
        targeted_chain_complete=targeted_chain_complete,
        targeted_chain_diagnosis=targeted_chain_diagnosis,
        targeted_first_gold_answer_rank=targeted_metrics["first_gold_answer_rank"],  # type: ignore[arg-type]
        targeted_first_support_rank=targeted_metrics["first_support_rank"],  # type: ignore[arg-type]
        targeted_gain_full_support=(
            bool(targeted_metrics["full_support_hit"])
            and not bool(context_metrics["full_support_hit"])
        ),
        targeted_gain_chain_complete=targeted_chain_complete and not chain_complete,
        source_count=len(context_doc_ids),
        targeted_source_count=len(targeted_doc_ids),
        targeted_added_source_count=len(targeted_added_doc_ids),
        prompt_char_count=prompt_char_count,
        estimated_prompt_tokens=max(1, math.ceil(prompt_char_count / 4)),
        targeted_prompt_char_count=targeted_prompt_char_count,
        targeted_estimated_prompt_tokens=max(1, math.ceil(targeted_prompt_char_count / 4)),
        source_summaries=_source_summaries(sources),
        targeted_source_summaries=_source_summaries(targeted_sources),
        sources=sources,
        targeted_sources=targeted_sources,
    )


def _context_chain_metrics(
    *,
    sample: NormalizedSample,
    sources: list[dict[str, Any]],
    max_chars_per_source: int,
    support_doc_ids: list[str],
) -> dict[str, object]:
    context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
    support_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
    missing_support_doc_ids = [
        doc_id for doc_id in support_doc_ids if doc_id not in set(context_doc_ids)
    ]
    recovered_support_doc_ids = _ordered_intersection(
        support_doc_ids,
        _dedupe(
            _source_doc_id(source)
            for source in sources
            if _is_recovered_source(source)
        ),
    )
    unrecovered_changed = _dedupe(
        _source_doc_id(source)
        for source in sources
        if _source_doc_id(source) in set(support_doc_ids)
        and not _is_recovered_source(source)
        and str(source.get("source_state", "")) != "clean_reference"
    )
    rendered_blocks = [
        _render_single_source_block(
            source,
            rank=index,
            max_chars_per_source=max_chars_per_source,
        )
        for index, source in enumerate(sources, start=1)
    ]
    rendered_context = "\n\n".join(rendered_blocks)
    support_blocks = [
        block
        for block, source in zip(rendered_blocks, sources, strict=True)
        if _source_doc_id(source) in set(support_doc_ids)
    ]
    return {
        "context_doc_ids": context_doc_ids,
        "support_hit_doc_ids": support_hits,
        "missing_support_doc_ids": missing_support_doc_ids,
        "full_support_hit": set(support_doc_ids).issubset(set(context_doc_ids)),
        "support_coverage_rate": _ratio(len(support_hits), len(support_doc_ids)),
        "context_has_gold_answer": _contains_answer_phrase(
            rendered_context,
            sample.answer,
        ),
        "support_context_has_gold_answer": _contains_answer_phrase(
            "\n\n".join(support_blocks),
            sample.answer,
        ),
        "first_gold_answer_rank": _first_rank_with_answer(rendered_blocks, sample.answer),
        "first_support_rank": _first_rank_with_doc_id(sources, set(support_doc_ids)),
        "unrecovered_changed_doc_ids": unrecovered_changed,
        "recovered_support_doc_ids": recovered_support_doc_ids,
        "rendered_context": rendered_context,
    }


def _chain_complete(metrics: dict[str, object]) -> bool:
    return bool(metrics["full_support_hit"]) and not bool(
        metrics["unrecovered_changed_doc_ids"]
    )


def _chain_diagnosis(*, metrics: dict[str, object], final_label: str) -> str:
    if metrics["unrecovered_changed_doc_ids"]:
        return "unsafe_context"
    if metrics["full_support_hit"]:
        if final_label in {"correct", "partial"}:
            return "complete_answered"
        if final_label == "abstained":
            return "complete_but_abstained"
        if metrics["context_has_gold_answer"]:
            return "complete_but_unanswered"
        return "complete_support_without_answer_surface"
    if metrics["context_has_gold_answer"] and not metrics["full_support_hit"]:
        return "answer_surface_without_full_chain"
    if metrics["support_hit_doc_ids"]:
        return "partial_support_missing_second_hop"
    return "missing_all_support"


def _bridge_terms(
    sources: list[dict[str, Any]],
    *,
    query: str,
    max_terms: int = 48,
) -> list[str]:
    terms: list[str] = []
    query_related_sources = _query_related_sources(sources=sources, query=query)
    for source in query_related_sources:
        title = _clean_entity_phrase(_source_title(source))
        if title:
            terms.append(title)
    for source in query_related_sources:
        terms.extend(_entity_phrases(str(source.get("text", "")))[:8])
    for source in sources:
        title = _clean_entity_phrase(_source_title(source))
        if title:
            terms.append(title)
    for source in sources:
        terms.extend(_entity_phrases(str(source.get("text", "")))[:8])
    terms.extend(_entity_phrases(query))
    return _dedupe(term for term in terms if term)[:max_terms]


def _query_related_sources(
    *,
    sources: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    query_lower = query.lower()
    indexed = list(enumerate(sources))
    related = [
        (index, source, _title_query_overlap(query=query, title=_source_title(source)))
        for index, source in indexed
        if _title_query_overlap(query=query, title=_source_title(source)) > 0
        or _source_title(source).lower() in query_lower
    ]
    related.sort(key=lambda item: (-item[2], item[0]))
    return [source for _, source, _ in related]


def _title_query_overlap(*, query: str, title: str) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(title))
    return (
        len(query_tokens & title_tokens) / math.sqrt(len(query_tokens) * len(title_tokens))
        if query_tokens and title_tokens
        else 0.0
    )


def _entity_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(("document id:", "title:")):
            continue
        for match in _ENTITY_PATTERN.finditer(stripped):
            phrase = _clean_entity_phrase(match.group(0))
            if not phrase:
                continue
            token_count = len(phrase.split())
            if token_count < 2 or token_count > 7:
                continue
            phrases.append(phrase)
    return phrases


def _clean_entity_phrase(raw: str) -> str:
    phrase = re.sub(r"\s+", " ", str(raw).strip(" \t\r\n:;,.[]{}\"'")).strip()
    if not phrase:
        return ""
    parts = phrase.split()
    trailing_connectors = {
        "a",
        "an",
        "and",
        "by",
        "for",
        "from",
        "in",
        "it",
        "of",
        "on",
        "she",
        "the",
        "with",
    }
    while parts and parts[-1].lower().strip(".,;:") in trailing_connectors:
        parts.pop()
    phrase = " ".join(parts).strip()
    if not phrase:
        return ""
    lowered = phrase.lower()
    if lowered in _ENTITY_BLOCKLIST:
        return ""
    if lowered.startswith("document id"):
        return ""
    if all(part.isdigit() for part in phrase.split()):
        return ""
    return phrase


def _rank_bridge_candidates(
    *,
    query: str,
    bridge_terms: list[str],
    candidate_sources: list[NonOracleCandidateSource],
    existing_doc_ids: set[str],
    top_k: int,
) -> list[tuple[NonOracleCandidateSource, float]]:
    if not candidate_sources or top_k <= 0:
        return []
    bridge_text = " ".join([query, *bridge_terms]).strip()
    query_tokens = _tokens(bridge_text)
    if not query_tokens:
        return []

    available_candidates = [
        candidate
        for candidate in candidate_sources
        if candidate.logicguard_doc_id not in existing_doc_ids
    ]
    if not available_candidates:
        return []

    tokenized_corpus = [
        _tokens(f"{candidate.title} {candidate.text}")
        for candidate in available_candidates
    ]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query_tokens)
    bridge_lower = bridge_text.lower()
    bridge_token_set = set(query_tokens)
    hits: list[tuple[NonOracleCandidateSource, float]] = []
    for index, candidate in enumerate(available_candidates):
        score = 0.12 * (float(scores[index]) if index < len(scores) else 0.0)
        score += _bridge_title_boost(
            candidate=candidate,
            bridge_terms=bridge_terms,
            bridge_lower=bridge_lower,
            bridge_token_set=bridge_token_set,
        )
        hits.append((candidate, score))
    hits.sort(
        key=lambda item: (
            item[1],
            _candidate_title_token_overlap(item[0], bridge_token_set),
            -item[0].human_readable_id,
        ),
        reverse=True,
    )
    return hits[:top_k]


def _bridge_title_boost(
    *,
    candidate: NonOracleCandidateSource,
    bridge_terms: list[str],
    bridge_lower: str,
    bridge_token_set: set[str],
) -> float:
    title = candidate.title.strip()
    title_lower = title.lower()
    title_tokens = set(_tokens(title))
    boost = 0.0
    if title_lower:
        matched_bridge_term = False
        for index, term in enumerate(bridge_terms, start=1):
            if _title_matches_bridge_term(title_lower, term):
                boost += max(80.0, 220.0 - 4.0 * index)
                matched_bridge_term = True
                break
        if not matched_bridge_term and title_lower in bridge_lower:
            boost += 12.0
    if title_tokens and bridge_token_set:
        boost += 2.0 * len(title_tokens & bridge_token_set) / math.sqrt(
            len(title_tokens) * len(bridge_token_set)
        )
    candidate_text = f"{candidate.title} {candidate.text}".lower()
    for term in bridge_terms[:24]:
        lowered = term.lower()
        if len(lowered) >= 4 and lowered in candidate_text:
            boost += 1.0
    return boost


def _title_matches_bridge_term(title_lower: str, term: str) -> bool:
    term_lower = term.lower().strip(" .,:;()[]{}\"'")
    if not title_lower or not term_lower:
        return False
    return title_lower == term_lower or (
        len(title_lower) >= 6
        and (title_lower in term_lower or term_lower in title_lower)
    )


def _candidate_title_token_overlap(
    candidate: NonOracleCandidateSource,
    bridge_token_set: set[str],
) -> float:
    title_tokens = set(_tokens(candidate.title))
    return (
        len(title_tokens & bridge_token_set) / math.sqrt(len(title_tokens) * len(bridge_token_set))
        if title_tokens and bridge_token_set
        else 0.0
    )


def _append_second_hop_candidates(
    *,
    base_sources: list[dict[str, Any]],
    candidate_hits: list[tuple[NonOracleCandidateSource, float]],
    max_sources: int,
    bridge_terms: list[str],
) -> list[dict[str, Any]]:
    output = list(base_sources)
    seen = set(_source_doc_id(source) for source in output)
    for candidate, score in candidate_hits:
        if len(output) >= max_sources:
            break
        if candidate.logicguard_doc_id in seen:
            continue
        source = candidate.to_source_record()
        source["id"] = f"stage38-second-hop-{candidate.id}"
        source["stage38_second_hop_candidate"] = True
        source["stage38_bridge_terms"] = bridge_terms
        source["stage38_candidate_score"] = round(score, 6)
        output.append(source)
        seen.add(candidate.logicguard_doc_id)
    return output


def _render_sources(
    sources: list[dict[str, Any]],
    *,
    max_chars_per_source: int,
) -> str:
    return "\n\n".join(
        _render_single_source_block(
            source,
            rank=index,
            max_chars_per_source=max_chars_per_source,
        )
        for index, source in enumerate(sources, start=1)
    )


def _source_summaries(sources: list[dict[str, Any]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for index, source in enumerate(sources, start=1):
        summaries.append(
            {
                "rank": index,
                "doc_id": _source_doc_id(source),
                "title": _source_title(source),
                "source_state": str(source.get("source_state", "")),
                "stage38_second_hop_candidate": bool(
                    source.get("stage38_second_hop_candidate")
                ),
                "stage38_candidate_score": source.get("stage38_candidate_score"),
                "snippet": _snippet(str(source.get("text", ""))),
            }
        )
    return summaries


def _select_examples(rows: list[Stage38ChainRow]) -> list[Stage38ChainRow]:
    selected: list[Stage38ChainRow] = []
    seen: set[str] = set()
    for row in sorted(rows, key=_example_priority):
        if row.query_id in seen:
            continue
        selected.append(row)
        seen.add(row.query_id)
        if len(selected) >= 10:
            break
    return selected


def _example_priority(row: Stage38ChainRow) -> tuple[int, str]:
    if row.targeted_gain_chain_complete:
        bucket = 0
    elif row.targeted_gain_full_support:
        bucket = 1
    elif row.chain_diagnosis == "answer_surface_without_full_chain":
        bucket = 2
    elif row.chain_diagnosis == "partial_support_missing_second_hop":
        bucket = 3
    elif row.chain_diagnosis == "missing_all_support":
        bucket = 4
    elif row.chain_diagnosis in {
        "complete_but_abstained",
        "complete_but_unanswered",
        "complete_support_without_answer_surface",
    }:
        bucket = 5
    elif row.chain_diagnosis == "complete_answered":
        bucket = 8
    else:
        bucket = _DIAGNOSIS_ORDER.get(row.chain_diagnosis, 99)
    return (bucket, row.query_id)


def _write_stage38_report(
    *,
    config: Stage38ChainCompletenessConfig,
    rows: list[Stage38ChainRow],
    summaries: list[Stage38SummaryRow],
    examples: list[Stage38ChainRow],
    targeted_context_rows: list[dict[str, Any]],
) -> None:
    has_judged_results = config.judged_results_path is not None
    summary_table = [
        (
            "| 方法 | query数 | utility | attack success | answer surface | support surface | "
            "support hit | full support | chain complete | answer表面但缺链 | partial support | "
            "no support | targeted full support | targeted chain complete | full-support gain | "
            "avg tokens -> targeted |"
            if has_judged_results
            else "| 方法 | query数 | answer surface | support surface | support hit | full support | "
            "chain complete | answer表面但缺链 | partial support | no support | "
            "targeted full support | targeted chain complete | full-support gain | "
            "avg tokens -> targeted |"
        ),
        (
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: | ---: |"
            if has_judged_results
            else "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: |"
        ),
    ]
    for row in summaries:
        line = f"| `{row.method}` | {row.query_count}"
        if has_judged_results:
            line += f" | {row.final_utility_rate:.4f} | {row.final_attack_success_rate:.4f}"
        line += (
            f" | {row.answer_surface_rate:.4f} | "
            f"{row.support_answer_surface_rate:.4f} | {row.support_hit_rate:.4f} | "
            f"{row.full_support_hit_rate:.4f} | {row.chain_complete_rate:.4f} | "
            f"{row.answer_surface_without_full_chain_rate:.4f} | "
            f"{row.partial_support_missing_second_hop_rate:.4f} | "
            f"{row.missing_all_support_rate:.4f} | "
            f"{row.targeted_full_support_hit_rate:.4f} | "
            f"{row.targeted_chain_complete_rate:.4f} | "
            f"{row.targeted_full_support_gain_rate:.4f} | "
            f"{row.avg_estimated_prompt_tokens:.1f} -> {row.avg_targeted_estimated_prompt_tokens:.1f} |"
        )
        summary_table.append(line)

    diagnosis_counts: dict[str, int] = {}
    for row in rows:
        diagnosis_counts[row.chain_diagnosis] = diagnosis_counts.get(row.chain_diagnosis, 0) + 1
    diagnosis_table = [
        "| chain diagnosis | count | rate |",
        "| --- | ---: | ---: |",
    ]
    for diagnosis, count in sorted(
        diagnosis_counts.items(),
        key=lambda item: (_DIAGNOSIS_ORDER.get(item[0], 99), item[0]),
    ):
        diagnosis_table.append(
            f"| `{diagnosis}` | {count} | {_ratio(count, len(rows)):.4f} |"
        )

    example_lines: list[str] = []
    for index, row in enumerate(examples, start=1):
        answer_audit_lines = (
            [
                f"- 回答审计答案：`{_markdown_cell(row.generated_answer)}`",
                f"- 回答审计标签：`{row.final_label}` / `{row.final_reason}`",
            ]
            if has_judged_results
            else ["- 回答审计：未提供；本阶段仅报告 source/chain-level proxy。"]
        )
        example_lines.extend(
            [
                f"### 示例 {index}: `{row.query_id}`",
                "",
                f"- 问题：{row.query}",
                f"- 标准答案：`{_markdown_cell(row.gold_answer)}`",
                *answer_audit_lines,
                f"- Stage38 诊断：`{row.chain_diagnosis}` -> `{row.targeted_chain_diagnosis}`",
                f"- 原始 support hit：`{';'.join(row.support_hit_doc_ids)}`；缺失：`{';'.join(row.missing_support_doc_ids)}`",
                f"- 二跳追加：`{';'.join(row.targeted_added_doc_ids)}`；其中 support：`{';'.join(row.targeted_added_support_doc_ids)}`",
                f"- 桥接词：`{'; '.join(row.bridge_terms[:8])}`",
                "",
            ]
        )
        if row.targeted_source_summaries:
            example_lines.extend(
                [
                    "| rank | doc_id | title | stage38追加 | snippet |",
                    "| ---: | --- | --- | ---: | --- |",
                ]
            )
            for source in row.targeted_source_summaries[:5]:
                example_lines.append(
                    f"| {source.get('rank', '')} | `{source.get('doc_id', '')}` | "
                    f"{_markdown_cell(str(source.get('title', '')))} | "
                    f"{int(bool(source.get('stage38_second_hop_candidate')))} | "
                    f"{_markdown_cell(str(source.get('snippet', '')))} |"
                )
            example_lines.append("")

    content = "\n".join(
        [
            f"# {config.stage_label} 链路完整性与二跳补证诊断",
            "",
            "## 实验目的",
            "",
            "Stage38 不重新调用回答模型，而是对给定的 20-query contexts 做离线诊断：区分“答案字符串已经出现在上下文”与“多跳支撑链完整出现”。随后它用非 oracle 的二跳追加策略，从当前上下文标题和实体桥接词出发，在干净 GraphRAG candidate pool 中补充可能缺失的第二跳证据。",
            "",
            "## 边界说明",
            "",
            "- 诊断指标会使用数据集的 support doc_id，因为这是离线评估链路完整性的标注。",
            "- 二跳追加排序不使用 support doc_id、gold answer 或污染标签，只使用 query、当前 sources 的标题/文本实体和 clean candidate 文本。",
            "- 本阶段产出的 targeted contexts 是后续真实 LLM answer run 的输入；当前结论是 source/chain-level proxy，不等同于最终回答提升已经发生。",
            "",
            "## 实验设置",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 输入 contexts：`{config.context_input_path.as_posix()}`",
            (
                f"- 回答审计输入：`{config.judged_results_path.as_posix()}`"
                if has_judged_results
                else "- 回答审计输入：未提供；本阶段不报告 utility 或 attack success。"
            ),
            f"- clean candidate pool：`{config.clean_reference_output_dir.as_posix()}`",
            f"- max sources：`{config.max_sources}`；每源字符预算：`{config.max_chars_per_source}`",
            f"- 诊断 rows：`{len(rows)}`；targeted context rows：`{len(targeted_context_rows)}`",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## 诊断分布",
            "",
            *diagnosis_table,
            "",
            "## 主要结论",
            "",
            _stage38_conclusion(summaries),
            "",
            "## 代表示例",
            "",
            *example_lines,
            "## 产物路径",
            "",
            f"- chain rows JSONL：`{config.chain_rows_output_path.as_posix()}`",
            f"- summary CSV：`{config.summary_output_path.as_posix()}`",
            f"- targeted contexts JSONL：`{config.targeted_context_output_path.as_posix()}`",
            f"- examples JSONL：`{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _stage38_conclusion(summaries: list[Stage38SummaryRow]) -> str:
    if not summaries:
        return "本次没有生成可汇总的 Stage38 结果。"
    best = max(
        summaries,
        key=lambda row: (
            row.targeted_chain_complete_rate,
            row.targeted_full_support_hit_rate,
            row.targeted_full_support_gain_rate,
        ),
    )
    if best.targeted_chain_complete_rate >= 0.999:
        return "\n\n".join(
            [
                f"基线 `full_support_hit_rate` 和 `chain_complete_rate` 均为 `{best.chain_complete_rate:.4f}`；Stage38 进一步说明，剩余缺口主要是二跳证据没有进入上下文，而不是污染源残留。",
                f"二跳追加后 `targeted_full_support_hit_rate` 与 `targeted_chain_complete_rate` 均达到 `{best.targeted_chain_complete_rate:.4f}`，full-support gain 为 `{best.targeted_full_support_gain_rate:.4f}`。这表示当前 20-query 的缺失支撑证据都能从 clean candidate pool 中由桥接实体找回。",
                "下一步重点不再是继续离线证明可补证，而是用 targeted contexts 重跑真实 LLM answer generation，并控制 complete queries 上额外追加候选带来的上下文噪声。",
            ]
        )
    return "\n\n".join(
        [
            f"基线 `full_support_hit_rate` 为 `{best.full_support_hit_rate:.4f}`，`chain_complete_rate` 为 `{best.chain_complete_rate:.4f}`；这说明多跳上下文不能只用 answer surface 判断，还需要检查完整支撑链。",
            f"二跳追加后 `targeted_full_support_hit_rate` 为 `{best.targeted_full_support_hit_rate:.4f}`，`targeted_chain_complete_rate` 为 `{best.targeted_chain_complete_rate:.4f}`，其中 full-support gain 为 `{best.targeted_full_support_gain_rate:.4f}`。",
            "若 targeted chain complete 仍低，后续重点应转向更强的实体链接、关系词解析和跨文档路径约束；若 source-level 已补齐但回答仍错，则需要进入真实 LLM answer run 与 prompt/裁判层面的误差分析。",
        ]
    )


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


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif isinstance(value, bool):
            output[key] = "1" if value else "0"
        elif isinstance(value, list):
            output[key] = ";".join(str(item) for item in value)
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _avg(values: Iterable[float | int | None]) -> float:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else 0.0


def _snippet(text: str, *, max_chars: int = 260) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _markdown_cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage38 链路完整性诊断。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage38_chain_completeness_poisoned20.yaml"),
    )
    args = parser.parse_args()
    run_from_config(Stage38ChainCompletenessConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
