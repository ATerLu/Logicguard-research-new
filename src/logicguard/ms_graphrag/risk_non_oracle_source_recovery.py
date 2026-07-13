"""Stage28 risk-non-oracle recovery for official GraphRAG sources.

Stage25 made recovery doc-id blind but still used changed-support labels to
decide which sources were risky. Stage28 removes that risk oracle: source risk
is detected from clean-candidate consistency signals that are available at
inference time, while changed labels are used only by offline metrics.
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

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.non_oracle_source_recovery import (
    NonOracleCandidateSource,
    load_candidate_sources,
    rank_non_oracle_candidates,
)
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
    parse_title_from_source_text,
)

_METHOD_ORDER = {
    "full_query_guard": 1,
    "risk_non_oracle_guarded_sources": 2,
    "risk_non_oracle_title_entity_bm25": 3,
}

_WORD_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9\-]+\b")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_ENTITY_STOPWORDS = {
    "Born",
    "Document",
    "For",
    "Her",
    "His",
    "Known",
    "Since",
    "The",
    "They",
    "This",
    "Title",
    "When",
    "With",
}
_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "with",
}


@dataclass(frozen=True, slots=True)
class SourceRiskResult:
    """Risk detector output for one official source row."""

    is_risky: bool
    risk_score: float
    risk_reasons: list[str]
    candidate_doc_id: str
    candidate_title: str
    candidate_score: float
    title_overlap: float
    text_token_jaccard: float
    entity_drift: float
    candidate: NonOracleCandidateSource | None


@dataclass(frozen=True, slots=True)
class Stage28RiskNonOracleRecoveryConfig:
    """Paths and settings for one Stage28 risk-non-oracle recovery run."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    source_context_path: Path
    clean_reference_output_dir: Path
    context_output_path: Path
    metrics_output_path: Path
    summary_output_path: Path
    report_path: Path
    input_method_name: str = "full_query_guard"
    max_queries: int = 20
    stage_label: str = "Stage28"
    top_k_candidates: int = 5
    min_candidate_score: float = 0.01
    entity_drift_threshold: float = 0.20
    title_overlap_threshold: float = 0.80

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage28RiskNonOracleRecoveryConfig":
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
            source_context_path=resolve(payload["source_context_path"]),
            clean_reference_output_dir=resolve(payload["clean_reference_output_dir"]),
            context_output_path=resolve(payload["context_output_path"]),
            metrics_output_path=resolve(payload["metrics_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            report_path=resolve(payload["report_path"]),
            input_method_name=str(payload.get("input_method_name", "full_query_guard")),
            max_queries=int(payload.get("max_queries", 20)),
            stage_label=str(payload.get("stage_label", "Stage28")),
            top_k_candidates=int(payload.get("top_k_candidates", 5)),
            min_candidate_score=float(payload.get("min_candidate_score", 0.01)),
            entity_drift_threshold=float(payload.get("entity_drift_threshold", 0.20)),
            title_overlap_threshold=float(payload.get("title_overlap_threshold", 0.80)),
        )


@dataclass(frozen=True, slots=True)
class Stage28MetricRow:
    """Query-level metrics for Stage28 risk-non-oracle policies."""

    dataset: str
    query_id: str
    query: str
    method: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    context_doc_ids: list[str]
    gold_support_hit_ids: list[str]
    changed_support_hit_ids: list[str]
    unrecovered_changed_support_hit_ids: list[str]
    recovered_support_hit_ids: list[str]
    risk_detected_doc_ids: list[str]
    risk_true_positive_doc_ids: list[str]
    risk_false_positive_doc_ids: list[str]
    risk_false_negative_doc_ids: list[str]
    replacement_doc_ids: list[str]
    gold_support_recall: float
    changed_support_exposure: float
    risk_recall: float
    risk_precision: float
    risk_false_positive_rate: float
    empty_context: int
    source_count: int
    recovered_source_count: int
    filtered_source_count: int
    risk_detected_source_count: int

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
class Stage28SummaryRow:
    """Method-level averages for Stage28."""

    dataset: str
    method: str
    query_count: int
    avg_gold_support_recall: float
    avg_changed_support_exposure: float
    avg_risk_recall: float
    avg_risk_precision: float
    avg_risk_false_positive_rate: float
    empty_context_rate: float
    avg_source_count: float
    avg_recovered_source_count: float
    avg_filtered_source_count: float
    avg_risk_detected_source_count: float

    def to_csv_row(self) -> dict[str, str]:
        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in asdict(self).items()
        }


def detect_non_oracle_source_risk(
    *,
    query: str,
    source: dict[str, Any],
    candidate_sources: list[NonOracleCandidateSource],
    entities: list[str] | None = None,
    top_k_candidates: int = 5,
    min_candidate_score: float = 0.01,
    entity_drift_threshold: float = 0.20,
    title_overlap_threshold: float = 0.80,
) -> SourceRiskResult:
    """Detect source risk without changed labels or doc_id lookup."""

    candidate = _best_clean_candidate(
        query=query,
        source=source,
        candidate_sources=candidate_sources,
        entities=entities or [],
        top_k_candidates=top_k_candidates,
        min_candidate_score=min_candidate_score,
    )
    if candidate is None:
        return SourceRiskResult(
            is_risky=False,
            risk_score=0.0,
            risk_reasons=[],
            candidate_doc_id="",
            candidate_title="",
            candidate_score=0.0,
            title_overlap=0.0,
            text_token_jaccard=0.0,
            entity_drift=0.0,
            candidate=None,
        )

    source_text = str(source.get("text", ""))
    candidate_text = candidate.text
    source_body = _source_body(source_text)
    candidate_body = _source_body(candidate_text)
    title_overlap = _title_overlap(str(source.get("title", "")), candidate.title)
    text_jaccard = _token_jaccard(source_body, candidate_body)
    entity_drift = _entity_drift(source_body, candidate_body)
    risk_score = entity_drift * max(title_overlap, 0.01) * (1.0 - 0.25 * text_jaccard)
    is_risky = title_overlap >= title_overlap_threshold and entity_drift >= entity_drift_threshold
    reasons = ["clean_candidate_entity_drift"] if is_risky else []
    return SourceRiskResult(
        is_risky=is_risky,
        risk_score=round(risk_score, 6),
        risk_reasons=reasons,
        candidate_doc_id=candidate.logicguard_doc_id,
        candidate_title=candidate.title,
        candidate_score=1.0 if _normalized_title(source) == _normalize_title(candidate.title) else 0.0,
        title_overlap=round(title_overlap, 6),
        text_token_jaccard=round(text_jaccard, 6),
        entity_drift=round(entity_drift, 6),
        candidate=candidate,
    )


def build_stage28_context_rows(
    *,
    source_context_rows: list[dict[str, Any]],
    candidate_sources: list[NonOracleCandidateSource],
    input_method_name: str = "full_query_guard",
    top_k_candidates: int = 5,
    min_candidate_score: float = 0.01,
    entity_drift_threshold: float = 0.20,
    title_overlap_threshold: float = 0.80,
) -> list[dict[str, Any]]:
    """Build Stage28 contexts without risk labels as inputs."""

    output_rows: list[dict[str, Any]] = []
    for context_row in source_context_rows:
        if str(context_row.get("method", input_method_name)) != input_method_name:
            continue
        entities = _extract_entities(context_row)
        detections = [
            detect_non_oracle_source_risk(
                query=str(context_row.get("query", "")),
                source=source,
                candidate_sources=candidate_sources,
                entities=entities,
                top_k_candidates=top_k_candidates,
                min_candidate_score=min_candidate_score,
                entity_drift_threshold=entity_drift_threshold,
                title_overlap_threshold=title_overlap_threshold,
            )
            for source in _source_records(context_row)
        ]
        annotated_sources = [
            _annotate_source_with_risk(source, risk)
            for source, risk in zip(_source_records(context_row), detections, strict=True)
        ]
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method=input_method_name,
                sources=annotated_sources,
                policy="source_passthrough_with_risk_non_oracle_scores",
                filtered_doc_ids=[],
                risk_doc_ids=_risky_doc_ids(annotated_sources),
                recovered_doc_ids=[],
            )
        )
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method="risk_non_oracle_guarded_sources",
                sources=[
                    source
                    for source in annotated_sources
                    if not bool(source.get("risk_non_oracle_detected"))
                ],
                policy="filter_risk_non_oracle_sources",
                filtered_doc_ids=_risky_doc_ids(annotated_sources),
                risk_doc_ids=_risky_doc_ids(annotated_sources),
                recovered_doc_ids=[],
            )
        )
        recovered_sources, recovered_doc_ids, filtered_doc_ids = _recover_risky_sources(
            annotated_sources,
            detections,
        )
        output_rows.append(
            _build_context_row(
                base_row=context_row,
                method="risk_non_oracle_title_entity_bm25",
                sources=recovered_sources,
                policy="replace_risk_non_oracle_sources_with_clean_candidates",
                filtered_doc_ids=filtered_doc_ids,
                risk_doc_ids=_risky_doc_ids(annotated_sources),
                recovered_doc_ids=recovered_doc_ids,
            )
        )
    return output_rows


def build_stage28_metric_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str = "",
) -> list[Stage28MetricRow]:
    """Evaluate Stage28 source risk and recovery outputs."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    global_changed_ids = _dedupe(
        doc_id
        for row in integrity_rows
        for doc_id in row.get("changed_support_doc_ids", [])
    )
    global_changed_set = set(global_changed_ids)
    rows: list[Stage28MetricRow] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        sample = samples_by_query.get(query_id)
        if sample is None:
            continue
        sources = _source_records(context_row)
        support_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_ids = [
            str(doc_id)
            for doc_id in integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        ]
        context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
        risk_detected = _dedupe(context_row.get("risk_detected_source_doc_ids", []))
        if not risk_detected:
            risk_detected = _dedupe(
                source.get("logicguard_doc_id", "")
                for source in sources
                if bool(source.get("risk_non_oracle_detected"))
            )
        risk_scope_doc_ids = _dedupe(
            [
                *context_doc_ids,
                *risk_detected,
                *context_row.get("filtered_source_doc_ids", []),
                *context_row.get("recovered_source_doc_ids", []),
            ]
        )
        context_global_changed = _ordered_intersection(global_changed_ids, risk_scope_doc_ids)
        true_positive = _ordered_intersection(global_changed_ids, risk_detected)
        false_positive = [doc_id for doc_id in risk_detected if doc_id not in global_changed_set]
        false_negative = [
            doc_id for doc_id in context_global_changed if doc_id not in set(risk_detected)
        ]
        unrecovered_changed = _dedupe(
            _source_doc_id(source)
            for source in sources
            if _source_doc_id(source) in set(changed_ids) and not _is_recovered_source(source)
        )
        recovered_support = _ordered_intersection(
            support_ids,
            _dedupe(
                _source_doc_id(source)
                for source in sources
                if _is_recovered_source(source)
            ),
        )
        rows.append(
            Stage28MetricRow(
                dataset=dataset,
                query_id=query_id,
                query=sample.query,
                method=str(context_row.get("method", "unknown")),
                support_doc_ids=support_ids,
                changed_support_doc_ids=changed_ids,
                context_doc_ids=context_doc_ids,
                gold_support_hit_ids=_ordered_intersection(support_ids, context_doc_ids),
                changed_support_hit_ids=_ordered_intersection(changed_ids, context_doc_ids),
                unrecovered_changed_support_hit_ids=_ordered_intersection(
                    changed_ids,
                    unrecovered_changed,
                ),
                recovered_support_hit_ids=recovered_support,
                risk_detected_doc_ids=risk_detected,
                risk_true_positive_doc_ids=true_positive,
                risk_false_positive_doc_ids=false_positive,
                risk_false_negative_doc_ids=false_negative,
                replacement_doc_ids=_dedupe(context_row.get("recovered_source_doc_ids", [])),
                gold_support_recall=_ratio(
                    len(_ordered_intersection(support_ids, context_doc_ids)),
                    len(support_ids),
                ),
                changed_support_exposure=_ratio(len(unrecovered_changed), len(changed_ids)),
                risk_recall=_ratio(len(true_positive), len(context_global_changed)),
                risk_precision=_ratio(len(true_positive), len(risk_detected)),
                risk_false_positive_rate=_ratio(
                    len(false_positive),
                    max(1, len(context_doc_ids) - len(context_global_changed)),
                ),
                empty_context=1 if not sources else 0,
                source_count=len(context_doc_ids),
                recovered_source_count=sum(1 for source in sources if _is_recovered_source(source)),
                filtered_source_count=len(context_row.get("filtered_source_doc_ids", [])),
                risk_detected_source_count=len(risk_detected),
            )
        )
    rows.sort(key=lambda item: (item.query_id, _METHOD_ORDER.get(item.method, 99), item.method))
    return rows


def summarize_stage28_metrics(rows: list[Stage28MetricRow]) -> list[Stage28SummaryRow]:
    """Aggregate Stage28 metrics by method."""

    grouped: dict[str, list[Stage28MetricRow]] = {}
    for row in rows:
        grouped.setdefault(row.method, []).append(row)
    summaries: list[Stage28SummaryRow] = []
    for method, group in grouped.items():
        query_count = len(group)
        summaries.append(
            Stage28SummaryRow(
                dataset=group[0].dataset if group else "",
                method=method,
                query_count=query_count,
                avg_gold_support_recall=_avg(row.gold_support_recall for row in group),
                avg_changed_support_exposure=_avg(row.changed_support_exposure for row in group),
                avg_risk_recall=_avg(row.risk_recall for row in group),
                avg_risk_precision=_avg(row.risk_precision for row in group),
                avg_risk_false_positive_rate=_avg(row.risk_false_positive_rate for row in group),
                empty_context_rate=_avg(float(row.empty_context) for row in group),
                avg_source_count=_avg(float(row.source_count) for row in group),
                avg_recovered_source_count=_avg(float(row.recovered_source_count) for row in group),
                avg_filtered_source_count=_avg(float(row.filtered_source_count) for row in group),
                avg_risk_detected_source_count=_avg(
                    float(row.risk_detected_source_count) for row in group
                ),
            )
        )
    summaries.sort(key=lambda item: (_METHOD_ORDER.get(item.method, 99), item.method))
    return summaries


def run_from_config(config: Stage28RiskNonOracleRecoveryConfig) -> list[Stage28MetricRow]:
    """Run Stage28 risk-non-oracle recovery and write artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)
    candidate_sources = load_candidate_sources(config.clean_reference_output_dir)
    source_context_rows = _load_jsonl(config.source_context_path)[: config.max_queries]
    context_rows = build_stage28_context_rows(
        source_context_rows=source_context_rows,
        candidate_sources=candidate_sources,
        input_method_name=config.input_method_name,
        top_k_candidates=config.top_k_candidates,
        min_candidate_score=config.min_candidate_score,
        entity_drift_threshold=config.entity_drift_threshold,
        title_overlap_threshold=config.title_overlap_threshold,
    )
    metric_rows = build_stage28_metric_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
    )
    write_stage28_outputs(config=config, context_rows=context_rows, metric_rows=metric_rows)
    return metric_rows


def write_stage28_outputs(
    *,
    config: Stage28RiskNonOracleRecoveryConfig,
    context_rows: list[dict[str, Any]],
    metric_rows: list[Stage28MetricRow],
) -> None:
    """Write Stage28 contexts, metrics, summary, and report."""

    summaries = summarize_stage28_metrics(metric_rows)
    config.context_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    with config.context_output_path.open("w", encoding="utf-8") as handle:
        for row in context_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with config.metrics_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage28MetricRow.__dataclass_fields__))
        writer.writeheader()
        for row in metric_rows:
            writer.writerow(row.to_csv_row())
    with config.summary_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage28SummaryRow.__dataclass_fields__))
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.to_csv_row())
    _write_stage28_report(config, summaries)


def _best_clean_candidate(
    *,
    query: str,
    source: dict[str, Any],
    candidate_sources: list[NonOracleCandidateSource],
    entities: list[str],
    top_k_candidates: int,
    min_candidate_score: float,
) -> NonOracleCandidateSource | None:
    source_title = _normalized_title(source)
    exact = [
        candidate
        for candidate in candidate_sources
        if _normalize_title(candidate.title) == source_title
    ]
    if exact:
        return sorted(exact, key=lambda item: (item.human_readable_id, item.logicguard_doc_id))[0]
    hits = rank_non_oracle_candidates(
        query=query,
        source=source,
        candidate_sources=candidate_sources,
        entities=entities,
        method="non_oracle_title_entity_bm25",
        top_k=top_k_candidates,
    )
    best = next((hit for hit in hits if hit.score >= min_candidate_score), None)
    return best.candidate if best else None


def _recover_risky_sources(
    annotated_sources: list[dict[str, Any]],
    detections: list[SourceRiskResult],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    recovered_sources: list[dict[str, Any]] = []
    recovered_doc_ids: list[str] = []
    filtered_doc_ids: list[str] = []
    for source, risk in zip(annotated_sources, detections, strict=True):
        if not risk.is_risky:
            recovered_sources.append(source)
            continue
        if risk.candidate is None:
            filtered_doc_ids.append(_source_doc_id(source))
            continue
        recovered_sources.append(_recovered_source(risk.candidate, original_source=source, risk=risk))
        recovered_doc_ids.append(risk.candidate.logicguard_doc_id)
    return recovered_sources, _dedupe(recovered_doc_ids), _dedupe(filtered_doc_ids)


def _annotate_source_with_risk(
    source: dict[str, Any],
    risk: SourceRiskResult,
) -> dict[str, Any]:
    record = dict(source)
    record["logicguard_doc_id"] = _source_doc_id(record)
    record["title"] = str(record.get("title") or parse_title_from_source_text(str(record.get("text", ""))))
    record["source_state"] = str(record.get("source_state") or "official_poisoned_context")
    record["risk_non_oracle_detected"] = risk.is_risky
    record["risk_non_oracle_score"] = risk.risk_score
    record["risk_non_oracle_reasons"] = risk.risk_reasons
    record["risk_non_oracle_candidate_doc_id"] = risk.candidate_doc_id
    record["risk_non_oracle_candidate_title"] = risk.candidate_title
    record["risk_non_oracle_features"] = {
        "title_overlap": risk.title_overlap,
        "text_token_jaccard": risk.text_token_jaccard,
        "entity_drift": risk.entity_drift,
        "candidate_score": risk.candidate_score,
    }
    return record


def _recovered_source(
    candidate: NonOracleCandidateSource,
    *,
    original_source: dict[str, Any],
    risk: SourceRiskResult,
) -> dict[str, Any]:
    record = candidate.to_source_record()
    record["id"] = f"stage28-risk-non-oracle-{original_source.get('id', record.get('id', 'source'))}"
    record["source_state"] = "clean_reference"
    record["recovered_from_risk_non_oracle_source"] = True
    record["recovered_from_changed_doc"] = False
    record["recovered_from_source_id"] = str(original_source.get("id", ""))
    record["recovery_method"] = "risk_non_oracle_title_entity_bm25"
    record["risk_non_oracle_detected"] = True
    record["risk_non_oracle_score"] = risk.risk_score
    record["risk_non_oracle_reasons"] = risk.risk_reasons
    record["risk_non_oracle_candidate_doc_id"] = risk.candidate_doc_id
    record["risk_non_oracle_candidate_title"] = risk.candidate_title
    record["risk_non_oracle_features"] = {
        "title_overlap": risk.title_overlap,
        "text_token_jaccard": risk.text_token_jaccard,
        "entity_drift": risk.entity_drift,
        "candidate_score": risk.candidate_score,
    }
    return record


def _build_context_row(
    *,
    base_row: dict[str, Any],
    method: str,
    sources: list[dict[str, Any]],
    policy: str,
    filtered_doc_ids: list[str],
    risk_doc_ids: list[str],
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
    row["stage28_policy"] = policy
    row["filtered_source_doc_ids"] = _dedupe(filtered_doc_ids)
    row["risk_detected_source_doc_ids"] = _dedupe(risk_doc_ids)
    row["recovered_source_doc_ids"] = _dedupe(recovered_doc_ids)
    row["context_text"] = _render_source_context(sources)
    return row


def _source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    context_data = row.get("context_data", {})
    sources = context_data.get("sources", []) if isinstance(context_data, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(source.get("logicguard_doc_id") or parse_doc_id_from_source_text(str(source.get("text", ""))))


def _is_recovered_source(source: dict[str, Any]) -> bool:
    return bool(source.get("recovered_from_risk_non_oracle_source")) or (
        bool(source.get("recovered_from_changed_doc")) or str(source.get("source_state")) == "clean_reference"
    )


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


def _risky_doc_ids(sources: list[dict[str, Any]]) -> list[str]:
    return _dedupe(
        _source_doc_id(source)
        for source in sources
        if bool(source.get("risk_non_oracle_detected"))
    )


def _render_source_context(sources: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        doc_id = _source_doc_id(source)
        title = str(source.get("title") or parse_title_from_source_text(str(source.get("text", ""))))
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


def _title_overlap(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / math.sqrt(len(left_tokens) * len(right_tokens))


def _entity_drift(left: str, right: str) -> float:
    left_entities = _entity_tokens(left)
    right_entities = _entity_tokens(right)
    if not left_entities and not right_entities:
        return 0.0
    union = left_entities | right_entities
    return len(union - (left_entities & right_entities)) / len(union)


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens and not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _entity_tokens(text: str) -> set[str]:
    return {
        match.group(0).lower()
        for match in _WORD_PATTERN.finditer(text)
        if len(match.group(0)) > 2
        and (match.group(0)[0].isupper() or match.group(0).isupper())
        and match.group(0) not in _ENTITY_STOPWORDS
    }


def _source_body(text: str) -> str:
    parts = re.split(r"\bTitle:\s*[^\n]+\n+", text, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip()
    return text


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text))
        if token and token not in _TOKEN_STOPWORDS
    ]


def _normalized_title(source: dict[str, Any]) -> str:
    return _normalize_title(str(source.get("title") or parse_title_from_source_text(str(source.get("text", "")))))


def _normalize_title(title: str) -> str:
    return " ".join(_tokens(title))


def _write_stage28_report(
    config: Stage28RiskNonOracleRecoveryConfig,
    summaries: list[Stage28SummaryRow],
) -> None:
    table = [
        "| method | queries | gold recall | changed exposure | risk recall | risk precision | risk FP rate | avg filtered | avg recovered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        table.append(
            f"| {row.method} | {row.query_count} | {row.avg_gold_support_recall:.4f} | "
            f"{row.avg_changed_support_exposure:.4f} | {row.avg_risk_recall:.4f} | "
            f"{row.avg_risk_precision:.4f} | {row.avg_risk_false_positive_rate:.4f} | "
            f"{row.avg_filtered_source_count:.2f} | {row.avg_recovered_source_count:.2f} |"
        )
    content = "\n".join(
        [
            f"# {config.stage_label} 非 Oracle 风险识别与官方来源恢复",
            "",
            "## 实验目的",
            "",
            "本阶段以 clean candidate consistency 风险检测器替代 changed-support 风险标签。"
            "运行时不读取 changed 标签；changed-support 元数据仅用于离线指标计算。",
            "",
            "## 风险检测与恢复机制",
            "",
            "- 优先用 source 标题精确匹配 clean candidate；无精确匹配时使用 title/entity/BM25 排序。",
            "- 比较当前 source 与 candidate 的大写实体词漂移。",
            "- 当标题重合度和实体漂移均超过阈值时，将 source 标为高风险。",
            "",
            "## 汇总结果",
            "",
            *table,
            "",
            "## 产物",
            "",
            f"- context JSONL: `{config.context_output_path.as_posix()}`",
            f"- query metrics CSV: `{config.metrics_output_path.as_posix()}`",
            f"- method summary CSV: `{config.summary_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


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


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def _dedupe(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _avg(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage28 risk-non-oracle official source recovery."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage28_risk_non_oracle_sources_poisoned20.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(Stage28RiskNonOracleRecoveryConfig.from_yaml(args.config))
    print(f"stage28_metric_rows={len(rows)}")


if __name__ == "__main__":
    main()
