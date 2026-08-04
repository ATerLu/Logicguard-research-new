"""Stage35 source enrichment for recovered official GraphRAG contexts.

Stage34 showed that the main remaining failure mode is abstention, especially
rows where the rendered Stage33 context does not expose the gold answer string.
This module keeps the official GraphRAG and risk-non-oracle recovery outputs
fixed, then tests whether non-oracle clean-candidate enrichment can surface
missing evidence before another real LLM answer run.
"""

from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import write_inferred_csv as _write_csv
from logicguard.core.metrics import mean_defined as _avg
from rank_bm25 import BM25Okapi

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.defense.non_oracle_recovery import (
    NonOracleCandidateSource,
    load_candidate_sources,
)
from logicguard.evaluation.answerability_ablation import (
    _answerability_label,
    _contains_answer_phrase,
    _dedupe,
    _first_rank_with_answer,
    _first_rank_with_doc_id,
    _is_recovered_source,
    _load_jsonl,
    _ordered_intersection,
    _order_sources,
    _prompt_char_count,
    _ratio,
    _render_single_source_block,
    _source_doc_id,
    _source_records,
    _source_title,
    _tokens,
)

_METHOD_ORDER = {
    "risk_non_oracle_title_entity_bm25": 1,
    "stage35_query_bm25_append_top8": 2,
    "stage35_query_bm25_append_top12": 3,
    "stage35_query_bm25_append_top16": 4,
}

_POLICY_ORDER = {
    "stage33_title_overlap": 1,
    "query_bm25_append": 2,
    "query_bm25_rerank": 3,
    "oracle_support_append": 9,
}


@dataclass(frozen=True, slots=True)
class Stage35SourceEnrichmentConfig:
    """Paths and settings for Stage35 source enrichment."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    context_input_path: Path
    clean_reference_output_dir: Path
    audited_results_path: Path | None
    enriched_context_output_path: Path
    enrichment_rows_output_path: Path
    summary_output_path: Path
    examples_output_path: Path
    report_path: Path
    methods: list[str]
    enrichment_policies: list[str]
    max_sources_values: list[int]
    max_queries: int = 20
    max_chars_per_source: int = 450
    candidate_pool_top_k: int = 40
    baseline_max_sources: int = 8
    selected_policy: str = "query_bm25_append"
    selected_max_sources: int = 12
    stage_label: str = "Stage35"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage35SourceEnrichmentConfig":
        """Load a project-relative YAML config."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path | None:
            if raw in (None, ""):
                return None
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        audited = resolve(payload.get("audited_results_path"))
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),  # type: ignore[arg-type]
            query_integrity_path=resolve(payload["query_integrity_path"]),  # type: ignore[arg-type]
            context_input_path=resolve(payload["context_input_path"]),  # type: ignore[arg-type]
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),  # type: ignore[arg-type]
            audited_results_path=audited,
            enriched_context_output_path=resolve(
                payload["enriched_context_output_path"]
            ),  # type: ignore[arg-type]
            enrichment_rows_output_path=resolve(payload["enrichment_rows_output_path"]),  # type: ignore[arg-type]
            summary_output_path=resolve(payload["summary_output_path"]),  # type: ignore[arg-type]
            examples_output_path=resolve(payload["examples_output_path"]),  # type: ignore[arg-type]
            report_path=resolve(payload["report_path"]),  # type: ignore[arg-type]
            methods=[str(method) for method in payload.get("methods", [])],
            enrichment_policies=[
                str(policy) for policy in payload.get("enrichment_policies", [])
            ],
            max_sources_values=[
                int(value) for value in payload.get("max_sources_values", [])
            ],
            max_queries=int(payload.get("max_queries", 20)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 450)),
            candidate_pool_top_k=int(payload.get("candidate_pool_top_k", 40)),
            baseline_max_sources=int(payload.get("baseline_max_sources", 8)),
            selected_policy=str(payload.get("selected_policy", "query_bm25_append")),
            selected_max_sources=int(payload.get("selected_max_sources", 12)),
            stage_label=str(payload.get("stage_label", "Stage35")),
        )


@dataclass(frozen=True, slots=True)
class Stage35EnrichmentRow:
    """One query-method-policy row in the Stage35 enrichment ablation."""

    dataset: str
    query_id: str
    query: str
    method: str
    enrichment_policy: str
    ordering_uses_oracle: bool
    max_sources: int
    max_chars_per_source: int
    gold_answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    stage34_label: str
    stage34_reason: str
    baseline_context_has_gold_answer: bool
    baseline_support_context_has_gold_answer: bool
    context_doc_ids: list[str]
    added_doc_ids: list[str]
    added_support_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    full_support_hit: bool
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    context_has_gold_answer: bool
    support_context_has_gold_answer: bool
    gained_answer_surface: bool
    gained_support_answer_surface: bool
    first_gold_answer_rank: int | None
    first_support_rank: int | None
    source_count: int
    added_source_count: int
    recovered_source_count: int
    prompt_char_count: int
    estimated_prompt_tokens: int
    answerability_label: str
    source_summaries: list[dict[str, object]]
    sources: list[dict[str, Any]]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Stage35SummaryRow:
    """Aggregated Stage35 enrichment metrics."""

    dataset: str
    method: str
    enrichment_policy: str
    ordering_uses_oracle: bool
    max_sources: int
    query_count: int
    answer_surface_rate: float
    support_answer_surface_rate: float
    baseline_answer_surface_rate: float
    baseline_support_answer_surface_rate: float
    gained_answer_surface_rate: float
    gained_support_answer_surface_rate: float
    clean_answerable_rate: float
    support_hit_rate: float
    full_support_hit_rate: float
    unsafe_context_rate: float
    target_failure_count: int
    target_failure_gain_rate: float
    target_failure_support_gain_rate: float
    avg_source_count: float
    avg_added_source_count: float
    avg_estimated_prompt_tokens: float
    avg_first_gold_answer_rank: float

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


def run_from_config(
    config: Stage35SourceEnrichmentConfig,
) -> list[Stage35EnrichmentRow]:
    """Run Stage35 source enrichment and write all artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)
    context_rows = _load_jsonl(config.context_input_path)
    audited_rows = (
        _load_jsonl(config.audited_results_path)
        if config.audited_results_path and config.audited_results_path.exists()
        else []
    )
    candidate_sources = load_candidate_sources(config.clean_reference_output_dir)
    rows = build_stage35_enrichment_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        candidate_sources=candidate_sources,
        audited_rows=audited_rows,
        dataset=config.dataset,
        methods=config.methods,
        enrichment_policies=config.enrichment_policies,
        max_sources_values=config.max_sources_values,
        max_chars_per_source=config.max_chars_per_source,
        candidate_pool_top_k=config.candidate_pool_top_k,
        baseline_max_sources=config.baseline_max_sources,
    )
    summaries = summarize_stage35_rows(rows)
    enriched_context_rows = build_stage35_enriched_context_rows(
        context_rows=context_rows,
        enrichment_rows=rows,
        selected_policy=config.selected_policy,
        selected_max_sources=config.selected_max_sources,
    )
    write_stage35_outputs(
        config=config,
        rows=rows,
        summaries=summaries,
        enriched_context_rows=enriched_context_rows,
    )
    print(
        f"stage35_enrichment_rows={len(rows)}, "
        f"enriched_context_rows={len(enriched_context_rows)}"
    )
    return rows


def build_stage35_enrichment_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    candidate_sources: list[NonOracleCandidateSource],
    audited_rows: list[dict[str, Any]],
    dataset: str,
    methods: list[str],
    enrichment_policies: list[str],
    max_sources_values: list[int],
    max_chars_per_source: int,
    candidate_pool_top_k: int,
    baseline_max_sources: int = 8,
) -> list[Stage35EnrichmentRow]:
    """Build source-enrichment ablation rows over recovered contexts."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    allowed_methods = set(methods)
    integrity_by_query = {
        str(row.get("query_id", "")): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    audit_by_query = {
        str(row.get("query_id", "")): row
        for row in audited_rows
        if row.get("query_id") is not None
    }
    candidates_by_doc_id = {
        candidate.logicguard_doc_id: candidate for candidate in candidate_sources
    }

    rows: list[Stage35EnrichmentRow] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        method = str(context_row.get("method", "unknown"))
        if query_id not in samples_by_query:
            continue
        if allowed_methods and method not in allowed_methods:
            continue
        sample = samples_by_query[query_id]
        current_sources = _source_records(context_row)
        baseline_sources = _order_sources(
            sources=current_sources,
            query=sample.query,
            gold_answer=sample.answer,
            order_policy="title_query_overlap",
        )[:baseline_max_sources]
        baseline_context = _render_sources(
            baseline_sources,
            max_chars_per_source=max_chars_per_source,
        )
        baseline_has_answer = _contains_answer_phrase(baseline_context, sample.answer)
        support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        baseline_support_context = _render_sources(
            [
                source
                for source in baseline_sources
                if _source_doc_id(source) in set(support_doc_ids)
            ],
            max_chars_per_source=max_chars_per_source,
        )
        baseline_support_has_answer = _contains_answer_phrase(
            baseline_support_context,
            sample.answer,
        )
        candidate_hits = _rank_query_candidates(
            query=sample.query,
            candidate_sources=candidate_sources,
            top_k=candidate_pool_top_k,
        )
        changed_doc_ids = _string_list(
            integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        )
        audit = audit_by_query.get(query_id, {})
        for policy in enrichment_policies:
            full_sources = _enriched_sources(
                policy=policy,
                query=sample.query,
                gold_answer=sample.answer,
                support_doc_ids=[str(doc_id) for doc_id in sample.support_doc_ids],
                current_sources=current_sources,
                candidate_hits=candidate_hits,
                candidates_by_doc_id=candidates_by_doc_id,
                baseline_max_sources=baseline_max_sources,
            )
            for max_sources in max_sources_values:
                top_sources = full_sources[:max_sources]
                rows.append(
                    _build_enrichment_row(
                        dataset=dataset,
                        sample=sample,
                        method=method,
                        enrichment_policy=policy,
                        max_sources=max_sources,
                        max_chars_per_source=max_chars_per_source,
                        sources=top_sources,
                        base_doc_ids=_dedupe(
                            _source_doc_id(source) for source in baseline_sources
                        ),
                        changed_doc_ids=changed_doc_ids,
                        stage34_label=_stage34_label(audit),
                        stage34_reason=_stage34_reason(audit),
                        baseline_context_has_gold_answer=baseline_has_answer,
                        baseline_support_context_has_gold_answer=baseline_support_has_answer,
                    )
                )
    rows.sort(
        key=lambda row: (
            row.query_id,
            _METHOD_ORDER.get(row.method, 99),
            _POLICY_ORDER.get(row.enrichment_policy, 99),
            row.max_sources,
        )
    )
    return rows


def summarize_stage35_rows(rows: list[Stage35EnrichmentRow]) -> list[Stage35SummaryRow]:
    """Aggregate Stage35 rows by method, policy, and max-sources."""

    grouped: dict[tuple[str, str, int], list[Stage35EnrichmentRow]] = {}
    for row in rows:
        grouped.setdefault(
            (row.method, row.enrichment_policy, row.max_sources), []
        ).append(row)

    summaries: list[Stage35SummaryRow] = []
    for (method, policy, max_sources), group in grouped.items():
        total = len(group)
        target = [
            row
            for row in group
            if row.stage34_reason == "abstain_without_gold_answer_surface"
        ]
        summaries.append(
            Stage35SummaryRow(
                dataset=group[0].dataset,
                method=method,
                enrichment_policy=policy,
                ordering_uses_oracle=any(row.ordering_uses_oracle for row in group),
                max_sources=max_sources,
                query_count=total,
                answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer),
                    total,
                ),
                support_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.support_context_has_gold_answer),
                    total,
                ),
                baseline_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.baseline_context_has_gold_answer),
                    total,
                ),
                baseline_support_answer_surface_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.baseline_support_context_has_gold_answer
                    ),
                    total,
                ),
                gained_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.gained_answer_surface),
                    total,
                ),
                gained_support_answer_surface_rate=_ratio(
                    sum(1 for row in group if row.gained_support_answer_surface),
                    total,
                ),
                clean_answerable_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.answerability_label == "answerable_clean"
                    ),
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
                unsafe_context_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.answerability_label == "unsafe_context"
                    ),
                    total,
                ),
                target_failure_count=len(target),
                target_failure_gain_rate=_ratio(
                    sum(1 for row in target if row.gained_answer_surface),
                    len(target),
                ),
                target_failure_support_gain_rate=_ratio(
                    sum(1 for row in target if row.gained_support_answer_surface),
                    len(target),
                ),
                avg_source_count=_avg(row.source_count for row in group),
                avg_added_source_count=_avg(row.added_source_count for row in group),
                avg_estimated_prompt_tokens=_avg(
                    row.estimated_prompt_tokens for row in group
                ),
                avg_first_gold_answer_rank=_avg(
                    row.first_gold_answer_rank
                    for row in group
                    if row.first_gold_answer_rank is not None
                ),
            )
        )
    summaries.sort(
        key=lambda row: (
            _METHOD_ORDER.get(row.method, 99),
            _POLICY_ORDER.get(row.enrichment_policy, 99),
            row.max_sources,
        )
    )
    return summaries


def build_stage35_enriched_context_rows(
    *,
    context_rows: list[dict[str, Any]],
    enrichment_rows: list[Stage35EnrichmentRow],
    selected_policy: str,
    selected_max_sources: int,
) -> list[dict[str, Any]]:
    """Materialize selected enriched contexts for later LLM answer runs."""

    row_by_query_method = {
        (row.query_id, row.method): row
        for row in enrichment_rows
        if row.enrichment_policy == selected_policy
        and row.max_sources == selected_max_sources
    }
    output_rows: list[dict[str, Any]] = []
    for context_row in context_rows:
        key = (str(context_row.get("query_id", "")), str(context_row.get("method", "")))
        enrichment = row_by_query_method.get(key)
        if enrichment is None:
            continue
        row = deepcopy(context_row)
        context_data = row.get("context_data", {})
        if not isinstance(context_data, dict):
            context_data = {}
        context_data = deepcopy(context_data)
        context_data["sources"] = enrichment.sources
        row["context_data"] = context_data
        row["method"] = f"stage35_{selected_policy}_top{selected_max_sources}"
        row["stage35_base_method"] = enrichment.method
        row["stage35_enrichment_policy"] = selected_policy
        row["stage35_max_sources"] = selected_max_sources
        row["stage35_added_doc_ids"] = enrichment.added_doc_ids
        row["stage35_added_support_doc_ids"] = enrichment.added_support_doc_ids
        row["stage35_context_has_gold_answer"] = enrichment.context_has_gold_answer
        row["stage35_support_context_has_gold_answer"] = (
            enrichment.support_context_has_gold_answer
        )
        row["stage35_answerability_label"] = enrichment.answerability_label
        row["context_text"] = _render_sources(
            enrichment.sources,
            max_chars_per_source=enrichment.max_chars_per_source,
        )
        output_rows.append(row)
    output_rows.sort(key=lambda row: str(row.get("query_id", "")))
    return output_rows


def write_stage35_outputs(
    *,
    config: Stage35SourceEnrichmentConfig,
    rows: list[Stage35EnrichmentRow],
    summaries: list[Stage35SummaryRow],
    enriched_context_rows: list[dict[str, Any]],
) -> None:
    """Write Stage35 JSONL/CSV/report artifacts."""

    config.enrichment_rows_output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.enrichment_rows_output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    _write_csv(config.summary_output_path, [row.to_csv_row() for row in summaries])

    examples = _select_examples(rows)
    with config.examples_output_path.open("w", encoding="utf-8") as handle:
        for row in examples:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    config.enriched_context_output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.enriched_context_output_path.open("w", encoding="utf-8") as handle:
        for row in enriched_context_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    _write_stage35_report(
        config=config,
        rows=rows,
        summaries=summaries,
        examples=examples,
        enriched_context_rows=enriched_context_rows,
    )


def _rank_query_candidates(
    *,
    query: str,
    candidate_sources: list[NonOracleCandidateSource],
    top_k: int,
) -> list[tuple[NonOracleCandidateSource, float]]:
    if not candidate_sources or top_k <= 0:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    tokenized_corpus = [
        _tokens(f"{candidate.title} {candidate.text}")
        for candidate in candidate_sources
    ]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query_tokens)
    hits = [
        (candidate, float(scores[index]) if index < len(scores) else 0.0)
        for index, candidate in enumerate(candidate_sources)
    ]
    hits.sort(
        key=lambda item: (
            item[1],
            _title_query_overlap_for_candidate(query, item[0]),
            -item[0].human_readable_id,
        ),
        reverse=True,
    )
    return hits[:top_k]


def _enriched_sources(
    *,
    policy: str,
    query: str,
    gold_answer: str,
    support_doc_ids: list[str],
    current_sources: list[dict[str, Any]],
    candidate_hits: list[tuple[NonOracleCandidateSource, float]],
    candidates_by_doc_id: dict[str, NonOracleCandidateSource],
    baseline_max_sources: int,
) -> list[dict[str, Any]]:
    ordered_current = _order_sources(
        sources=current_sources,
        query=query,
        gold_answer=gold_answer,
        order_policy="title_query_overlap",
    )
    if policy == "stage33_title_overlap":
        return ordered_current

    if policy == "query_bm25_append":
        base_sources = ordered_current[:baseline_max_sources]
        return _append_candidates(
            base_sources=base_sources,
            candidates=[candidate for candidate, _ in candidate_hits],
            policy=policy,
            scores={
                candidate.logicguard_doc_id: score
                for candidate, score in candidate_hits
            },
        )

    if policy == "query_bm25_rerank":
        combined = _append_candidates(
            base_sources=ordered_current,
            candidates=[candidate for candidate, _ in candidate_hits],
            policy=policy,
            scores={
                candidate.logicguard_doc_id: score
                for candidate, score in candidate_hits
            },
        )
        return sorted(
            combined,
            key=lambda source: (
                -_query_source_score(query, source),
                not _is_recovered_source(source),
            ),
        )

    if policy == "oracle_support_append":
        base_sources = ordered_current[:baseline_max_sources]
        oracle_candidates = [
            candidates_by_doc_id[doc_id]
            for doc_id in support_doc_ids
            if doc_id in candidates_by_doc_id
        ]
        return _append_candidates(
            base_sources=base_sources,
            candidates=oracle_candidates,
            policy=policy,
            scores={
                candidate.logicguard_doc_id: 1.0 for candidate in oracle_candidates
            },
        )

    raise ValueError(f"Unknown Stage35 enrichment policy: {policy}")


def _append_candidates(
    *,
    base_sources: list[dict[str, Any]],
    candidates: list[NonOracleCandidateSource],
    policy: str,
    scores: dict[str, float],
) -> list[dict[str, Any]]:
    output = list(base_sources)
    seen = set(_source_doc_id(source) for source in output)
    for candidate in candidates:
        if candidate.logicguard_doc_id in seen:
            continue
        source = candidate.to_source_record()
        source["id"] = f"stage35-{policy}-{candidate.id}"
        source["stage35_enriched_candidate"] = True
        source["stage35_enrichment_policy"] = policy
        source["stage35_candidate_score"] = round(
            scores.get(candidate.logicguard_doc_id, 0.0), 6
        )
        output.append(source)
        seen.add(candidate.logicguard_doc_id)
    return output


def _build_enrichment_row(
    *,
    dataset: str,
    sample: NormalizedSample,
    method: str,
    enrichment_policy: str,
    max_sources: int,
    max_chars_per_source: int,
    sources: list[dict[str, Any]],
    base_doc_ids: list[str],
    changed_doc_ids: list[str],
    stage34_label: str,
    stage34_reason: str,
    baseline_context_has_gold_answer: bool,
    baseline_support_context_has_gold_answer: bool,
) -> Stage35EnrichmentRow:
    support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
    context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
    added_doc_ids = [
        doc_id for doc_id in context_doc_ids if doc_id not in set(base_doc_ids)
    ]
    support_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
    added_support_doc_ids = _ordered_intersection(support_doc_ids, added_doc_ids)
    recovered_support_doc_ids = _ordered_intersection(
        support_doc_ids,
        _dedupe(
            _source_doc_id(source) for source in sources if _is_recovered_source(source)
        ),
    )
    unrecovered_changed = _dedupe(
        _source_doc_id(source)
        for source in sources
        if _source_doc_id(source) in set(changed_doc_ids)
        and not _is_recovered_source(source)
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
    context_has_gold_answer = _contains_answer_phrase(rendered_context, sample.answer)
    support_blocks = [
        block
        for block, source in zip(rendered_blocks, sources, strict=True)
        if _source_doc_id(source) in set(support_doc_ids)
    ]
    support_context_has_gold_answer = _contains_answer_phrase(
        "\n\n".join(support_blocks),
        sample.answer,
    )
    prompt_char_count = _prompt_char_count(
        question=sample.query, context=rendered_context
    )
    return Stage35EnrichmentRow(
        dataset=dataset,
        query_id=sample.query_id,
        query=sample.query,
        method=method,
        enrichment_policy=enrichment_policy,
        ordering_uses_oracle=enrichment_policy.startswith("oracle_"),
        max_sources=max_sources,
        max_chars_per_source=max_chars_per_source,
        gold_answer=sample.answer,
        support_doc_ids=support_doc_ids,
        changed_support_doc_ids=changed_doc_ids,
        stage34_label=stage34_label,
        stage34_reason=stage34_reason,
        baseline_context_has_gold_answer=baseline_context_has_gold_answer,
        baseline_support_context_has_gold_answer=baseline_support_context_has_gold_answer,
        context_doc_ids=context_doc_ids,
        added_doc_ids=added_doc_ids,
        added_support_doc_ids=added_support_doc_ids,
        support_hit_doc_ids=support_hits,
        full_support_hit=set(support_doc_ids).issubset(set(context_doc_ids)),
        unrecovered_changed_doc_ids=unrecovered_changed,
        recovered_support_doc_ids=recovered_support_doc_ids,
        context_has_gold_answer=context_has_gold_answer,
        support_context_has_gold_answer=support_context_has_gold_answer,
        gained_answer_surface=(
            context_has_gold_answer and not baseline_context_has_gold_answer
        ),
        gained_support_answer_surface=(
            support_context_has_gold_answer
            and not baseline_support_context_has_gold_answer
        ),
        first_gold_answer_rank=_first_rank_with_answer(rendered_blocks, sample.answer),
        first_support_rank=_first_rank_with_doc_id(sources, set(support_doc_ids)),
        source_count=len(context_doc_ids),
        added_source_count=len(added_doc_ids),
        recovered_source_count=sum(
            1 for source in sources if _is_recovered_source(source)
        ),
        prompt_char_count=prompt_char_count,
        estimated_prompt_tokens=max(1, math.ceil(prompt_char_count / 4)),
        answerability_label=_answerability_label(
            context_has_gold_answer=context_has_gold_answer,
            support_hits=support_hits,
            unrecovered_changed=unrecovered_changed,
            source_count=len(context_doc_ids),
        ),
        source_summaries=_source_summaries(sources),
        sources=sources,
    )


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
                "stage35_enriched_candidate": bool(
                    source.get("stage35_enriched_candidate")
                ),
                "stage35_candidate_score": source.get("stage35_candidate_score"),
                "snippet": _snippet(str(source.get("text", ""))),
            }
        )
    return summaries


def _query_source_score(query: str, source: dict[str, Any]) -> float:
    tokens = set(_tokens(query))
    text_tokens = set(
        _tokens(" ".join([_source_title(source), str(source.get("text", ""))]))
    )
    overlap = (
        len(tokens & text_tokens) / math.sqrt(len(tokens) * len(text_tokens))
        if tokens and text_tokens
        else 0.0
    )
    candidate_score = float(source.get("stage35_candidate_score", 0.0) or 0.0)
    return (
        candidate_score
        + 2.0 * overlap
        + 0.5 * _title_query_overlap_for_source(query, source)
    )


def _title_query_overlap_for_source(query: str, source: dict[str, Any]) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(_source_title(source)))
    return (
        len(query_tokens & title_tokens)
        / math.sqrt(len(query_tokens) * len(title_tokens))
        if query_tokens and title_tokens
        else 0.0
    )


def _title_query_overlap_for_candidate(
    query: str,
    candidate: NonOracleCandidateSource,
) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(candidate.title))
    return (
        len(query_tokens & title_tokens)
        / math.sqrt(len(query_tokens) * len(title_tokens))
        if query_tokens and title_tokens
        else 0.0
    )


def _stage34_label(row: dict[str, Any]) -> str:
    return str(row.get("final_label") or row.get("stage29_label") or "")


def _stage34_reason(row: dict[str, Any]) -> str:
    return str(row.get("final_reason") or row.get("audit_reason") or "")


def _select_examples(rows: list[Stage35EnrichmentRow]) -> list[Stage35EnrichmentRow]:
    def priority(row: Stage35EnrichmentRow) -> tuple[int, str, str, int]:
        if (
            row.gained_answer_surface
            and row.stage34_reason == "abstain_without_gold_answer_surface"
        ):
            bucket = 0
        elif row.gained_answer_surface:
            bucket = 1
        elif row.answerability_label == "missing_answer_surface":
            bucket = 2
        elif row.ordering_uses_oracle:
            bucket = 3
        else:
            bucket = 9
        return (bucket, row.query_id, row.enrichment_policy, row.max_sources)

    selected: list[Stage35EnrichmentRow] = []
    seen: set[tuple[str, str, int]] = set()
    for row in sorted(rows, key=priority):
        key = (row.query_id, row.enrichment_policy, row.max_sources)
        if key in seen:
            continue
        selected.append(row)
        seen.add(key)
        if len(selected) >= 12:
            break
    return selected


def _write_stage35_report(
    *,
    config: Stage35SourceEnrichmentConfig,
    rows: list[Stage35EnrichmentRow],
    summaries: list[Stage35SummaryRow],
    examples: list[Stage35EnrichmentRow],
    enriched_context_rows: list[dict[str, Any]],
) -> None:
    has_audited_results = config.audited_results_path is not None
    summary_lines = [
        (
            "| 方法 | 扩展策略 | oracle? | max sources | query数 | answer surface | "
            "support answer surface | baseline support surface | support gain | clean answerable | "
            "审计目标支持增益 | support hit | full support | unsafe | avg tokens |"
            if has_audited_results
            else "| 方法 | 扩展策略 | oracle? | max sources | query数 | answer surface | "
            "support answer surface | baseline support surface | support gain | clean answerable | "
            "support hit | full support | unsafe | avg tokens |"
        ),
        (
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: |"
            if has_audited_results
            else "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: |"
        ),
    ]
    for row in summaries:
        line = (
            f"| `{row.method}` | `{row.enrichment_policy}` | "
            f"{int(row.ordering_uses_oracle)} | {row.max_sources} | "
            f"{row.query_count} | {row.answer_surface_rate:.4f} | "
            f"{row.support_answer_surface_rate:.4f} | "
            f"{row.baseline_support_answer_surface_rate:.4f} | "
            f"{row.gained_support_answer_surface_rate:.4f} | "
            f"{row.clean_answerable_rate:.4f}"
        )
        if has_audited_results:
            line += f" | {row.target_failure_support_gain_rate:.4f}"
        line += (
            f" | {row.support_hit_rate:.4f} | {row.full_support_hit_rate:.4f} | "
            f"{row.unsafe_context_rate:.4f} | {row.avg_estimated_prompt_tokens:.2f} |"
        )
        summary_lines.append(line)

    example_lines = [
        (
            "| query_id | 策略 | max sources | 审计原因 | label | gold answer | added docs | "
            "support hit | first answer rank |"
            if has_audited_results
            else "| query_id | 策略 | max sources | label | gold answer | added docs | support hit | "
            "first answer rank |"
        ),
        (
            "| --- | --- | ---: | --- | --- | --- | --- | --- | ---: |"
            if has_audited_results
            else "| --- | --- | ---: | --- | --- | --- | --- | ---: |"
        ),
    ]
    for row in examples:
        line = f"| `{row.query_id}` | `{row.enrichment_policy}` | {row.max_sources}"
        if has_audited_results:
            line += f" | `{row.stage34_reason}`"
        line += (
            f" | `{row.answerability_label}` | "
            f"`{_markdown_cell(row.gold_answer)}` | `{';'.join(row.added_doc_ids)}` | "
            f"`{';'.join(row.support_hit_doc_ids)}` | {row.first_gold_answer_rank or ''} |"
        )
        example_lines.append(line)

    if config.audited_results_path:
        purpose = (
            "在 recovered official GraphRAG sources 的基础上，从干净 candidate pool 追加非 oracle 候选源，"
            "评估能否改善先前回答审计中暴露的证据缺口。"
        )
    else:
        purpose = (
            "在 recovered official GraphRAG sources 的基础上，从干净 candidate pool 追加非 oracle 候选源，"
            "评估能否补回检索阶段遗漏的支持证据。"
        )

    content = "\n".join(
        [
            f"# {config.stage_label} 候选源扩展诊断",
            "",
            "## 实验目的",
            "",
            purpose,
            "",
            "## 重要边界",
            "",
            "- `query_bm25_append` 只使用 query 与 clean candidate 文本的 BM25/标题重叠，不使用 gold answer 或 support doc_id。",
            "- `oracle_support_append` 只作为诊断上界，使用 support doc_id，不能作为部署策略。",
            "- 本阶段是 answerability/source-enrichment proxy；真实回答收益需要后续 LLM answer run 复验。",
            "",
            "## 实验设置",
            "",
            f"- 数据集：`{config.dataset}`",
            f"- 输入 contexts：`{config.context_input_path.as_posix()}`",
            f"- clean candidate pool：`{config.clean_reference_output_dir.as_posix()}`",
            f"- 评估行数：`{len(rows)}`",
            f"- enriched context rows：`{len(enriched_context_rows)}`",
            f"- selected context：`{config.selected_policy}` + top-{config.selected_max_sources}",
            "",
            "## 汇总结果",
            "",
            *summary_lines,
            "",
            "## 主要结论",
            "",
            _stage35_conclusion(summaries),
            "",
            "## 代表样例",
            "",
            *example_lines,
            "",
            "## 产物路径",
            "",
            f"- 扩展后 context JSONL：`{config.enriched_context_output_path.as_posix()}`",
            f"- 扩展明细 JSONL：`{config.enrichment_rows_output_path.as_posix()}`",
            f"- 汇总 CSV：`{config.summary_output_path.as_posix()}`",
            f"- 代表样例 JSONL：`{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _stage35_conclusion(summaries: list[Stage35SummaryRow]) -> str:
    non_oracle = [row for row in summaries if not row.ordering_uses_oracle]
    oracle = [row for row in summaries if row.ordering_uses_oracle]
    lines: list[str] = []
    if non_oracle:
        best = max(
            non_oracle,
            key=lambda row: (
                row.clean_answerable_rate,
                row.support_answer_surface_rate,
                row.answer_surface_rate,
                row.target_failure_support_gain_rate,
                -row.avg_estimated_prompt_tokens,
            ),
        )
        lines.append(
            f"最佳非 oracle 设置是 `{best.enrichment_policy}` + top-{best.max_sources}，"
            f"support answer surface rate 为 `{best.support_answer_surface_rate:.4f}`，"
            f"clean answerable rate 为 `{best.clean_answerable_rate:.4f}`。"
        )
    if oracle:
        best_oracle = max(oracle, key=lambda row: row.clean_answerable_rate)
        lines.append(
            f"oracle support append 上界为 `{best_oracle.clean_answerable_rate:.4f}`，"
            "用于判断剩余缺口是否来自 candidate ranking，而不是回答 prompt。"
        )
    return "\n\n".join(lines) if lines else "未生成 Stage35 汇总结果。"


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


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return []


def _snippet(text: str, *, max_chars: int = 260) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _markdown_cell(text: str) -> str:
    return str(text).replace("|", "/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="运行 Stage35 source enrichment 诊断。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage35_source_enrichment_poisoned20.yaml"),
    )
    args = parser.parse_args()
    run_from_config(Stage35SourceEnrichmentConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
