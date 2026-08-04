"""Stage25 non-oracle sources-level recovery over official GraphRAG contexts.

Stage23/24 used doc_id oracle replacement to estimate the upper bound of
sources-level recovery. Stage25 keeps the same official GraphRAG context export
but replaces changed source rows through a trusted clean candidate pool ranked
from query, source title, and entity evidence.
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
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import load_jsonl as _load_jsonl
from logicguard.core.metrics import dedupe_strings as _dedupe
from logicguard.core.metrics import mean as _avg
from logicguard.core.metrics import ratio as _ratio
from rank_bm25 import BM25Okapi

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
    parse_title_from_source_text,
)
from logicguard.defense.oracle_recovery import load_clean_reference_sources

NON_ORACLE_METHODS = (
    "non_oracle_query_bm25",
    "non_oracle_title_entity_bm25",
    "non_oracle_hybrid_policy",
)

_METHOD_ORDER = {
    "mixed_baseline": 0,
    "full_query_guard": 1,
    "guarded_sources": 2,
    "recovered_sources_by_doc_id": 3,
    "non_oracle_query_bm25": 4,
    "non_oracle_title_entity_bm25": 5,
    "non_oracle_hybrid_policy": 6,
}

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "with",
}


@dataclass(frozen=True, slots=True)
class NonOracleCandidateSource:
    """One clean trusted source candidate for Stage25 retrieval."""

    id: str
    text_unit_id: str
    logicguard_doc_id: str
    official_document_id: str
    human_readable_id: int
    title: str
    text: str
    n_tokens: int
    source_state: str = "clean_reference"

    @classmethod
    def from_source_record(cls, record: dict[str, Any]) -> "NonOracleCandidateSource":
        """Create a candidate from a Stage23 clean-reference source record."""

        return cls(
            id=str(record.get("id", "")),
            text_unit_id=str(record.get("text_unit_id") or record.get("id", "")),
            logicguard_doc_id=str(record.get("logicguard_doc_id", "")),
            official_document_id=str(record.get("official_document_id", "")),
            human_readable_id=int(record.get("human_readable_id", 0) or 0),
            title=str(record.get("title", "")),
            text=str(record.get("text", "")),
            n_tokens=int(record.get("n_tokens", 0) or 0),
            source_state=str(record.get("source_state", "clean_reference")),
        )

    def to_source_record(self) -> dict[str, Any]:
        """Convert the candidate back into a GraphRAG-compatible source row."""

        return {
            "id": self.id,
            "text_unit_id": self.text_unit_id,
            "official_document_id": self.official_document_id,
            "human_readable_id": self.human_readable_id,
            "logicguard_doc_id": self.logicguard_doc_id,
            "title": self.title,
            "text": self.text,
            "n_tokens": self.n_tokens,
            "source_state": self.source_state,
            "recovered_from_changed_doc": False,
            "risk_reasons": [],
        }


@dataclass(frozen=True, slots=True)
class NonOracleCandidateHit:
    """Ranked Stage25 candidate with transparent score components."""

    candidate: NonOracleCandidateSource
    score: float
    score_breakdown: dict[str, float]


@dataclass(frozen=True, slots=True)
class Stage25NonOracleRecoveryConfig:
    """Paths and settings for one Stage25 non-oracle recovery run."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    source_context_path: Path
    baseline_context_path: Path | None
    clean_reference_output_dir: Path
    context_output_path: Path
    metrics_output_path: Path
    summary_output_path: Path
    report_path: Path
    input_method_name: str = "full_query_guard"
    max_queries: int = 50
    stage_label: str = "Stage25"
    top_k_candidates: int = 5
    min_candidate_score: float = 0.01

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage25NonOracleRecoveryConfig":
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

        baseline = resolve(payload.get("baseline_context_path"))
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),  # type: ignore[arg-type]
            query_integrity_path=resolve(payload["query_integrity_path"]),  # type: ignore[arg-type]
            source_context_path=resolve(payload["source_context_path"]),  # type: ignore[arg-type]
            baseline_context_path=baseline,
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),  # type: ignore[arg-type]
            context_output_path=resolve(payload["context_output_path"]),  # type: ignore[arg-type]
            metrics_output_path=resolve(payload["metrics_output_path"]),  # type: ignore[arg-type]
            summary_output_path=resolve(payload["summary_output_path"]),  # type: ignore[arg-type]
            report_path=resolve(payload["report_path"]),  # type: ignore[arg-type]
            input_method_name=str(payload.get("input_method_name", "full_query_guard")),
            max_queries=int(payload.get("max_queries", 50)),
            stage_label=str(payload.get("stage_label", "Stage25")),
            top_k_candidates=int(payload.get("top_k_candidates", 5)),
            min_candidate_score=float(payload.get("min_candidate_score", 0.01)),
        )


@dataclass(frozen=True, slots=True)
class Stage25MetricRow:
    """Query-level metrics for Stage25 context variants."""

    dataset: str
    query_id: str
    query: str
    method: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    trusted_support_doc_ids: list[str]
    context_doc_ids: list[str]
    gold_support_hit_ids: list[str]
    changed_support_hit_ids: list[str]
    unrecovered_changed_support_hit_ids: list[str]
    recovered_support_hit_ids: list[str]
    trusted_support_hit_ids: list[str]
    replacement_doc_ids: list[str]
    replacement_hit_doc_ids: list[str]
    bad_replacement_doc_ids: list[str]
    same_doc_id_recovery_ids: list[str]
    gold_support_recall: float
    changed_support_exposure: float
    trusted_support_recall: float
    oracle_gap: float
    replacement_hit_rate: float
    bad_replacement_rate: float
    same_doc_id_recovery_rate: float
    empty_context: int
    source_count: int
    source_row_count: int
    recovered_source_count: int
    filtered_source_count: int

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            elif isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class Stage25SummaryRow:
    """Method-level averages across Stage25 queries."""

    dataset: str
    method: str
    query_count: int
    avg_gold_support_recall: float
    avg_changed_support_exposure: float
    avg_trusted_support_recall: float
    avg_oracle_gap: float
    avg_replacement_hit_rate: float
    avg_bad_replacement_rate: float
    avg_same_doc_id_recovery_rate: float
    empty_context_rate: float
    avg_source_count: float
    avg_source_row_count: float
    avg_recovered_source_count: float
    avg_filtered_source_count: float

    def to_csv_row(self) -> dict[str, str]:
        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in asdict(self).items()
        }


def load_candidate_sources(output_dir: Path) -> list[NonOracleCandidateSource]:
    """Load trusted clean-reference text units as a ranked candidate pool."""

    records = load_clean_reference_sources(output_dir)
    candidates = [
        NonOracleCandidateSource.from_source_record(record)
        for record in records.values()
    ]
    candidates.sort(key=lambda item: (item.human_readable_id, item.logicguard_doc_id))
    return candidates


def rank_non_oracle_candidates(
    *,
    query: str,
    source: dict[str, Any],
    candidate_sources: list[NonOracleCandidateSource],
    entities: list[str] | None = None,
    method: str = "non_oracle_hybrid_policy",
    top_k: int = 5,
) -> list[NonOracleCandidateHit]:
    """Rank clean candidates without direct doc_id lookup."""

    if method not in NON_ORACLE_METHODS:
        raise ValueError(f"Unknown Stage25 non-oracle method: {method}")
    if not candidate_sources:
        return []

    entities = entities or []
    query_tokens = _tokens(query)
    title_tokens = _tokens(str(source.get("title", "")))
    entity_tokens = _tokens(" ".join(entities))
    tokenized_corpus = [
        _tokens(_candidate_search_text(candidate)) for candidate in candidate_sources
    ]
    bm25_scores = _bm25_scores(tokenized_corpus, query_tokens)

    hits: list[NonOracleCandidateHit] = []
    for index, candidate in enumerate(candidate_sources):
        candidate_text = _candidate_search_text(candidate)
        query_bm25 = float(bm25_scores[index]) if index < len(bm25_scores) else 0.0
        title_overlap = _overlap_score(title_tokens, _tokens(candidate.title))
        entity_overlap = _entity_overlap_score(entities, entity_tokens, candidate_text)
        source_rank_prior = _source_rank_prior(candidate)
        risk_penalty = 0.0

        if method == "non_oracle_query_bm25":
            score = query_bm25 + 0.05 * source_rank_prior
        elif method == "non_oracle_title_entity_bm25":
            score = 0.25 * query_bm25 + 1.40 * title_overlap + 1.10 * entity_overlap
            score += 0.05 * source_rank_prior
        else:
            score = query_bm25 + 1.25 * title_overlap + 0.90 * entity_overlap
            score += 0.05 * source_rank_prior - risk_penalty

        hits.append(
            NonOracleCandidateHit(
                candidate=candidate,
                score=score,
                score_breakdown={
                    "query_bm25": query_bm25,
                    "title_overlap": title_overlap,
                    "entity_overlap": entity_overlap,
                    "source_rank_prior": source_rank_prior,
                    "risk_penalty": risk_penalty,
                    "doc_id_lookup": 0.0,
                },
            )
        )

    hits.sort(
        key=lambda hit: (
            hit.score,
            hit.score_breakdown["title_overlap"],
            hit.score_breakdown["entity_overlap"],
        ),
        reverse=True,
    )
    return hits[:top_k]


def build_stage25_context_rows(
    *,
    source_context_rows: list[dict[str, Any]],
    integrity_rows: list[dict[str, Any]],
    candidate_sources: list[NonOracleCandidateSource],
    clean_reference_sources: dict[str, dict[str, Any]] | None = None,
    input_method_name: str = "full_query_guard",
    top_k_candidates: int = 5,
    min_candidate_score: float = 0.01,
) -> list[dict[str, Any]]:
    """Create pass-through, oracle, guarded, and non-oracle recovered contexts."""

    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    output_rows: list[dict[str, Any]] = []
    for context_row in source_context_rows:
        row_method = str(context_row.get("method", input_method_name))
        if row_method != input_method_name:
            continue
        query_id = str(context_row["query_id"])
        changed_doc_ids = {
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get(
                "changed_support_doc_ids", []
            )
        }
        annotated_sources = [
            _annotate_official_source(source, changed_doc_ids=changed_doc_ids)
            for source in _source_records(context_row)
        ]
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method=input_method_name,
                sources=annotated_sources,
                policy="source_passthrough",
                filtered_doc_ids=[],
                recovered_doc_ids=[],
            )
        )
        output_rows.append(
            _build_guarded_context_row(
                base_row=context_row,
                annotated_sources=annotated_sources,
                changed_doc_ids=changed_doc_ids,
            )
        )
        if clean_reference_sources is not None:
            output_rows.append(
                _build_doc_id_oracle_context_row(
                    base_row=context_row,
                    annotated_sources=annotated_sources,
                    changed_doc_ids=changed_doc_ids,
                    clean_reference_sources=clean_reference_sources,
                )
            )
        for method in NON_ORACLE_METHODS:
            output_rows.append(
                _build_non_oracle_context_row(
                    base_row=context_row,
                    annotated_sources=annotated_sources,
                    changed_doc_ids=changed_doc_ids,
                    candidate_sources=candidate_sources,
                    method=method,
                    top_k_candidates=top_k_candidates,
                    min_candidate_score=min_candidate_score,
                )
            )
    return output_rows


def build_stage25_metric_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str = "",
) -> list[Stage25MetricRow]:
    """Evaluate source-level recall, exposure, and replacement quality."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    partial_rows: list[dict[str, Any]] = []
    for context_row in context_rows:
        query_id = str(context_row["query_id"])
        sample = samples_by_query.get(query_id)
        if sample is None:
            continue
        sources = _source_records(context_row)
        support_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_ids = [
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get(
                "changed_support_doc_ids", []
            )
        ]
        changed_set = set(changed_ids)
        support_set = set(support_ids)
        trusted_ids = [doc_id for doc_id in support_ids if doc_id not in changed_set]
        context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
        gold_hits = _ordered_intersection(support_ids, context_doc_ids)
        changed_hits = _ordered_intersection(changed_ids, context_doc_ids)
        trusted_hits = _ordered_intersection(trusted_ids, context_doc_ids)
        unrecovered_changed = _dedupe(
            _source_doc_id(source)
            for source in sources
            if _source_doc_id(source) in changed_set
            and not _is_recovered_source(source)
        )
        recovered_doc_ids = _dedupe(
            _source_doc_id(source) for source in sources if _is_recovered_source(source)
        )
        replacement_hit_ids = _ordered_intersection(changed_ids, recovered_doc_ids)
        bad_replacement_ids = [
            doc_id for doc_id in recovered_doc_ids if doc_id not in support_set
        ]
        partial_rows.append(
            {
                "dataset": dataset,
                "query_id": query_id,
                "query": sample.query,
                "method": str(context_row.get("method", "unknown")),
                "support_doc_ids": support_ids,
                "changed_support_doc_ids": changed_ids,
                "trusted_support_doc_ids": trusted_ids,
                "context_doc_ids": context_doc_ids,
                "gold_support_hit_ids": gold_hits,
                "changed_support_hit_ids": changed_hits,
                "unrecovered_changed_support_hit_ids": _ordered_intersection(
                    changed_ids,
                    unrecovered_changed,
                ),
                "recovered_support_hit_ids": replacement_hit_ids,
                "trusted_support_hit_ids": trusted_hits,
                "replacement_doc_ids": recovered_doc_ids,
                "replacement_hit_doc_ids": replacement_hit_ids,
                "bad_replacement_doc_ids": bad_replacement_ids,
                "same_doc_id_recovery_ids": replacement_hit_ids,
                "gold_support_recall": _ratio(len(gold_hits), len(support_ids)),
                "changed_support_exposure": _ratio(
                    len(unrecovered_changed),
                    len(changed_ids),
                ),
                "trusted_support_recall": _ratio(len(trusted_hits), len(trusted_ids)),
                "replacement_hit_rate": _ratio(
                    len(replacement_hit_ids), len(changed_ids)
                ),
                "bad_replacement_rate": _ratio(
                    len(bad_replacement_ids),
                    len(recovered_doc_ids),
                ),
                "same_doc_id_recovery_rate": _ratio(
                    len(replacement_hit_ids),
                    len(changed_ids),
                ),
                "empty_context": 1 if not sources else 0,
                "source_count": len(context_doc_ids),
                "source_row_count": len(sources),
                "recovered_source_count": sum(
                    1 for source in sources if _is_recovered_source(source)
                ),
                "filtered_source_count": len(
                    context_row.get("filtered_source_doc_ids", [])
                ),
            }
        )

    oracle_recall_by_query = {
        row["query_id"]: float(row["gold_support_recall"])
        for row in partial_rows
        if row["method"] == "recovered_sources_by_doc_id"
    }
    rows: list[Stage25MetricRow] = []
    for row in partial_rows:
        oracle_recall = oracle_recall_by_query.get(
            row["query_id"], float(row["gold_support_recall"])
        )
        row["oracle_gap"] = max(0.0, oracle_recall - float(row["gold_support_recall"]))
        rows.append(Stage25MetricRow(**row))
    return rows


def summarize_stage25_metrics(rows: list[Stage25MetricRow]) -> list[Stage25SummaryRow]:
    """Aggregate Stage25 metrics by method."""

    grouped: dict[str, list[Stage25MetricRow]] = {}
    for row in rows:
        grouped.setdefault(row.method, []).append(row)
    summaries: list[Stage25SummaryRow] = []
    for method, group in grouped.items():
        summaries.append(
            Stage25SummaryRow(
                dataset=group[0].dataset if group else "",
                method=method,
                query_count=len(group),
                avg_gold_support_recall=_avg(row.gold_support_recall for row in group),
                avg_changed_support_exposure=_avg(
                    row.changed_support_exposure for row in group
                ),
                avg_trusted_support_recall=_avg(
                    row.trusted_support_recall for row in group
                ),
                avg_oracle_gap=_avg(row.oracle_gap for row in group),
                avg_replacement_hit_rate=_avg(
                    row.replacement_hit_rate for row in group
                ),
                avg_bad_replacement_rate=_avg(
                    row.bad_replacement_rate for row in group
                ),
                avg_same_doc_id_recovery_rate=_avg(
                    row.same_doc_id_recovery_rate for row in group
                ),
                empty_context_rate=_avg(float(row.empty_context) for row in group),
                avg_source_count=_avg(float(row.source_count) for row in group),
                avg_source_row_count=_avg(float(row.source_row_count) for row in group),
                avg_recovered_source_count=_avg(
                    float(row.recovered_source_count) for row in group
                ),
                avg_filtered_source_count=_avg(
                    float(row.filtered_source_count) for row in group
                ),
            )
        )
    summaries.sort(key=lambda row: (_METHOD_ORDER.get(row.method, 99), row.method))
    return summaries


def run_from_config(config: Stage25NonOracleRecoveryConfig) -> list[Stage25MetricRow]:
    """Run Stage25 non-oracle recovery and write outputs."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    clean_sources = load_clean_reference_sources(config.clean_reference_output_dir)
    candidate_sources = [
        NonOracleCandidateSource.from_source_record(record)
        for record in clean_sources.values()
    ]
    candidate_sources.sort(
        key=lambda item: (item.human_readable_id, item.logicguard_doc_id)
    )
    source_context_rows = _load_jsonl(config.source_context_path)[: config.max_queries]
    context_rows: list[dict[str, Any]] = []
    if config.baseline_context_path is not None:
        context_rows.extend(
            _baseline_context_row(row)
            for row in _load_jsonl(config.baseline_context_path)[: config.max_queries]
        )
    context_rows.extend(
        build_stage25_context_rows(
            source_context_rows=source_context_rows,
            integrity_rows=integrity_rows,
            candidate_sources=candidate_sources,
            clean_reference_sources=clean_sources,
            input_method_name=config.input_method_name,
            top_k_candidates=config.top_k_candidates,
            min_candidate_score=config.min_candidate_score,
        )
    )
    metric_rows = build_stage25_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
    )
    write_stage25_outputs(
        config=config, context_rows=context_rows, metric_rows=metric_rows
    )
    return metric_rows


def write_stage25_outputs(
    *,
    config: Stage25NonOracleRecoveryConfig,
    context_rows: list[dict[str, Any]],
    metric_rows: list[Stage25MetricRow],
) -> None:
    """Write Stage25 context JSONL, metric CSV, summary CSV, and report."""

    summaries = summarize_stage25_metrics(metric_rows)
    config.context_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    with config.context_output_path.open("w", encoding="utf-8") as handle:
        for row in context_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with config.metrics_output_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(Stage25MetricRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in metric_rows:
            writer.writerow(row.to_csv_row())
    with config.summary_output_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(Stage25SummaryRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.to_csv_row())
    _write_stage25_report(config, summaries)


def _build_guarded_context_row(
    *,
    base_row: dict[str, Any],
    annotated_sources: list[dict[str, Any]],
    changed_doc_ids: set[str],
) -> dict[str, Any]:
    guarded_sources = [
        source
        for source in annotated_sources
        if str(source.get("logicguard_doc_id", "")) not in changed_doc_ids
    ]
    filtered_doc_ids = _dedupe(
        source.get("logicguard_doc_id", "")
        for source in annotated_sources
        if str(source.get("logicguard_doc_id", "")) in changed_doc_ids
    )
    return _build_context_row(
        base_row=base_row,
        method="guarded_sources",
        sources=guarded_sources,
        policy="filter_changed_sources",
        filtered_doc_ids=filtered_doc_ids,
        recovered_doc_ids=[],
    )


def _build_doc_id_oracle_context_row(
    *,
    base_row: dict[str, Any],
    annotated_sources: list[dict[str, Any]],
    changed_doc_ids: set[str],
    clean_reference_sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    recovered_sources: list[dict[str, Any]] = []
    recovered_doc_ids: list[str] = []
    missing_doc_ids: list[str] = []
    for source in annotated_sources:
        doc_id = str(source.get("logicguard_doc_id", ""))
        if doc_id not in changed_doc_ids:
            recovered_sources.append(source)
            continue
        clean_source = clean_reference_sources.get(doc_id)
        if clean_source is None:
            missing_doc_ids.append(doc_id)
            continue
        recovered_sources.append(
            _recovered_source(
                clean_source,
                original_source=source,
                method="recovered_sources_by_doc_id",
                score=1.0,
                score_breakdown={"doc_id_lookup": 1.0},
            )
        )
        recovered_doc_ids.append(doc_id)
    return _build_context_row(
        base_row=base_row,
        method="recovered_sources_by_doc_id",
        sources=recovered_sources,
        policy="replace_changed_sources_with_clean_doc_id_reference",
        filtered_doc_ids=_dedupe(missing_doc_ids),
        recovered_doc_ids=_dedupe(recovered_doc_ids),
    )


def _build_non_oracle_context_row(
    *,
    base_row: dict[str, Any],
    annotated_sources: list[dict[str, Any]],
    changed_doc_ids: set[str],
    candidate_sources: list[NonOracleCandidateSource],
    method: str,
    top_k_candidates: int,
    min_candidate_score: float,
) -> dict[str, Any]:
    recovered_sources: list[dict[str, Any]] = []
    recovered_doc_ids: list[str] = []
    filtered_doc_ids: list[str] = []
    entities = _extract_entities(base_row)
    for source in annotated_sources:
        doc_id = str(source.get("logicguard_doc_id", ""))
        if doc_id not in changed_doc_ids:
            recovered_sources.append(source)
            continue
        hits = rank_non_oracle_candidates(
            query=str(base_row.get("query", "")),
            source=source,
            candidate_sources=candidate_sources,
            entities=entities,
            method=method,
            top_k=top_k_candidates,
        )
        best = next((hit for hit in hits if hit.score >= min_candidate_score), None)
        if best is None:
            filtered_doc_ids.append(doc_id)
            continue
        recovered_sources.append(
            _recovered_source(
                best.candidate.to_source_record(),
                original_source=source,
                method=method,
                score=best.score,
                score_breakdown=best.score_breakdown,
            )
        )
        recovered_doc_ids.append(best.candidate.logicguard_doc_id)
    return _build_context_row(
        base_row=base_row,
        method=method,
        sources=recovered_sources,
        policy="replace_changed_sources_with_non_oracle_candidates",
        filtered_doc_ids=_dedupe(filtered_doc_ids),
        recovered_doc_ids=_dedupe(recovered_doc_ids),
    )


def _build_context_row(
    *,
    base_row: dict[str, Any],
    method: str,
    sources: list[dict[str, Any]],
    policy: str,
    filtered_doc_ids: list[str],
    recovered_doc_ids: list[str],
) -> dict[str, Any]:
    row = deepcopy(base_row)
    context_data = row.get("context_data", {})
    if not isinstance(context_data, dict):
        context_data = {}
    context_data = deepcopy(context_data)
    context_data["sources"] = sources
    row["context_data"] = context_data
    row["method"] = method
    row["stage25_policy"] = policy
    row["filtered_source_doc_ids"] = filtered_doc_ids
    row["recovered_source_doc_ids"] = recovered_doc_ids
    row["context_text"] = _render_source_context(sources)
    return row


def _baseline_context_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(row)
    copied["method"] = "mixed_baseline"
    context_data = copied.get("context_data", {})
    if isinstance(context_data, dict):
        context_data = deepcopy(context_data)
        context_data["sources"] = [
            _annotate_official_source(source, changed_doc_ids=set())
            for source in context_data.get("sources", [])
            if isinstance(source, dict)
        ]
        copied["context_data"] = context_data
    copied.setdefault("stage25_policy", "baseline_passthrough")
    copied.setdefault("filtered_source_doc_ids", [])
    copied.setdefault("recovered_source_doc_ids", [])
    return copied


def _annotate_official_source(
    source: dict[str, Any],
    *,
    changed_doc_ids: set[str],
) -> dict[str, Any]:
    record = dict(source)
    text = str(record.get("text", ""))
    doc_id = str(record.get("logicguard_doc_id") or parse_doc_id_from_source_text(text))
    title = str(record.get("title") or parse_title_from_source_text(text))
    record["logicguard_doc_id"] = doc_id
    record["title"] = title
    record["source_state"] = str(
        record.get("source_state") or "official_poisoned_context"
    )
    record["recovered_from_changed_doc"] = bool(
        record.get("recovered_from_changed_doc", False)
    )
    risk_reasons = [str(reason) for reason in record.get("risk_reasons", [])]
    if doc_id in changed_doc_ids and not record["recovered_from_changed_doc"]:
        risk_reasons.append("changed_logicpoison_support")
    record["risk_reasons"] = _dedupe(risk_reasons)
    return record


def _recovered_source(
    clean_source: dict[str, Any],
    *,
    original_source: dict[str, Any],
    method: str,
    score: float,
    score_breakdown: dict[str, float],
) -> dict[str, Any]:
    record = dict(clean_source)
    record["id"] = (
        f"stage25-{method}-{original_source.get('id', record.get('id', 'source'))}"
    )
    record["source_state"] = "clean_reference"
    record["recovered_from_changed_doc"] = True
    record["recovered_from_source_id"] = str(original_source.get("id", ""))
    record["recovery_method"] = method
    record["candidate_doc_id"] = _source_doc_id(record)
    record["candidate_score"] = round(float(score), 6)
    record["candidate_score_breakdown"] = {
        key: round(float(value), 6) for key, value in score_breakdown.items()
    }
    record["risk_reasons"] = [
        "changed_logicpoison_support",
        "stage25_non_oracle_candidate_recovery",
    ]
    return record


def _candidate_search_text(candidate: NonOracleCandidateSource) -> str:
    return f"{candidate.title}\n{candidate.text}"


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text))
        if token and token not in _STOPWORDS
    ]


def _bm25_scores(
    tokenized_corpus: list[list[str]], query_tokens: list[str]
) -> list[float]:
    if not tokenized_corpus or not query_tokens:
        return [0.0 for _ in tokenized_corpus]
    scorer = BM25Okapi(tokenized_corpus)
    return [float(score) for score in scorer.get_scores(query_tokens)]


def _overlap_score(needle_tokens: list[str], haystack_tokens: list[str]) -> float:
    if not needle_tokens or not haystack_tokens:
        return 0.0
    needle = set(needle_tokens)
    haystack = set(haystack_tokens)
    return len(needle & haystack) / math.sqrt(len(needle) * len(haystack))


def _entity_overlap_score(
    entities: list[str],
    entity_tokens: list[str],
    candidate_text: str,
) -> float:
    if not entities and not entity_tokens:
        return 0.0
    lowered = candidate_text.lower()
    phrase_hits = sum(1 for entity in entities if entity and entity.lower() in lowered)
    phrase_score = _ratio(phrase_hits, len([entity for entity in entities if entity]))
    token_score = _overlap_score(entity_tokens, _tokens(candidate_text))
    return 0.65 * phrase_score + 0.35 * token_score


def _source_rank_prior(candidate: NonOracleCandidateSource) -> float:
    if candidate.human_readable_id <= 0:
        return 0.0
    return 1.0 / math.sqrt(candidate.human_readable_id)


def _extract_entities(row: dict[str, Any]) -> list[str]:
    entities: list[str] = []
    for key in ("include_entity_names", "unknown_entity_names"):
        value = row.get(key, [])
        if isinstance(value, list):
            entities.extend(str(item) for item in value if item)
    context_data = row.get("context_data", {})
    if isinstance(context_data, dict):
        for entity in context_data.get("entities", []):
            if not isinstance(entity, dict):
                continue
            value = entity.get("entity") or entity.get("title") or entity.get("name")
            if value:
                entities.append(str(value))
    return _dedupe(entities)


def _source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    context_data = row.get("context_data", {})
    sources = context_data.get("sources", []) if isinstance(context_data, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(
        source.get("logicguard_doc_id")
        or parse_doc_id_from_source_text(str(source.get("text", "")))
    )


def _is_recovered_source(source: dict[str, Any]) -> bool:
    return (
        bool(source.get("recovered_from_changed_doc"))
        or str(source.get("source_state")) == "clean_reference"
    )


def _render_source_context(sources: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        doc_id = _source_doc_id(source)
        title = str(
            source.get("title")
            or parse_title_from_source_text(str(source.get("text", "")))
        )
        state = str(source.get("source_state", "official_poisoned_context"))
        text = " ".join(str(source.get("text", "")).split())
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


def _write_stage25_report(
    config: Stage25NonOracleRecoveryConfig,
    summaries: list[Stage25SummaryRow],
) -> None:
    summary_table = [
        "| method | queries | gold recall | changed exposure | oracle gap | replacement hit | bad replacement | same-doc recovery | avg recovered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        summary_table.append(
            f"| {row.method} | {row.query_count} | {row.avg_gold_support_recall:.4f} | "
            f"{row.avg_changed_support_exposure:.4f} | {row.avg_oracle_gap:.4f} | "
            f"{row.avg_replacement_hit_rate:.4f} | {row.avg_bad_replacement_rate:.4f} | "
            f"{row.avg_same_doc_id_recovery_rate:.4f} | {row.avg_recovered_source_count:.2f} |"
        )

    full = next(
        (row for row in summaries if row.method == config.input_method_name), None
    )
    oracle = next(
        (row for row in summaries if row.method == "recovered_sources_by_doc_id"), None
    )
    hybrid = next(
        (row for row in summaries if row.method == "non_oracle_hybrid_policy"), None
    )
    guarded = next((row for row in summaries if row.method == "guarded_sources"), None)
    delta_lines = ["- 缺少关键对照方法，无法计算主要变化。"]
    if full and guarded and oracle and hybrid:
        delta_lines = [
            f"- full_query_guard: gold recall {full.avg_gold_support_recall:.4f}, "
            f"changed exposure {full.avg_changed_support_exposure:.4f}.",
            f"- guarded_sources: gold recall {guarded.avg_gold_support_recall:.4f}, "
            f"changed exposure {guarded.avg_changed_support_exposure:.4f}.",
            f"- oracle recovered_sources_by_doc_id: gold recall "
            f"{oracle.avg_gold_support_recall:.4f}, changed exposure "
            f"{oracle.avg_changed_support_exposure:.4f}.",
            f"- non_oracle_hybrid_policy: gold recall {hybrid.avg_gold_support_recall:.4f}, "
            f"changed exposure {hybrid.avg_changed_support_exposure:.4f}, "
            f"oracle gap {hybrid.avg_oracle_gap:.4f}.",
        ]

    content = "\n".join(
        [
            f"# Microsoft GraphRAG {config.stage_label} 非 oracle Sources 级 Recovery 实验报告",
            "",
            "## 实验目的",
            "",
            f"{config.stage_label} 在 official GraphRAG local search 已导出的 "
            "`context_data.sources` 上运行。它先沿用 Stage23/24 的风险 oracle "
            "触发，即用 changed source 标记决定哪些 source 需要替换；随后不再按 "
            "doc_id 直接取 clean source，而是从 trusted clean text unit 候选池中用 "
            "query、source title 和 GraphRAG entity evidence 排序选取替换项。",
            "",
            "## 边界说明",
            "",
            "- 本阶段是 doc_id-blind / gold-blind candidate recovery，不是完整无 oracle 防御。",
            "- `changed_support_doc_ids` 只用于风险触发和离线评估，不作为候选排序特征。",
            "- `recovered_sources_by_doc_id` 保留为 Stage23/24 oracle 上界，用于计算 oracle gap。",
            "- `same-doc recovery` 只说明排序结果碰巧选回同一 gold doc_id，不表示使用了 doc_id lookup。",
            "- 当前仍是 context-only 指标，回答层 ASR/EM/F1 需要后续 LLM 评估补齐。",
            "",
            "## 方法",
            "",
            "- `non_oracle_query_bm25`: 仅用 query BM25 和很弱的候选顺序先验。",
            "- `non_oracle_title_entity_bm25`: 以 source title overlap 与 entity overlap 为主，query BM25 为辅。",
            "- `non_oracle_hybrid_policy`: 综合 query BM25、title overlap、entity overlap 与弱先验。",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## 主要对照",
            "",
            *delta_lines,
            "",
            "## 产物路径",
            "",
            f"- context JSONL: `{config.context_output_path.as_posix()}`",
            f"- query metrics CSV: `{config.metrics_output_path.as_posix()}`",
            f"- method summary CSV: `{config.summary_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage25 non-oracle sources-level recovery."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage25_non_oracle_sources_poisoned50.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(Stage25NonOracleRecoveryConfig.from_yaml(args.config))
    print(f"stage25_metric_rows={len(rows)}")


if __name__ == "__main__":
    main()
