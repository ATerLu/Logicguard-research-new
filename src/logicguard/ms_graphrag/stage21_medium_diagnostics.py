"""Stage21 medium-scale diagnostics over Microsoft GraphRAG indexed artifacts.

Stage20 proved that candidate-space repair can rescue five support-only queries
inside an official LocalSearchMixedContext. Stage21 deliberately asks a smaller
but more scalable question: when the indexed graph contains 50 queries and many
cross-query distractor documents, do guard and recovery still improve the
evidence passed to an answer model?

The input here is still official Microsoft GraphRAG output parquet files. The
ranking layer is intentionally local and auditable because the available
50-query poisoned workspace is a minimal workflow without community reports, so
it cannot be consumed by GraphRAG's full local-search context builder.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from rank_bm25 import BM25Plus

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample

_DOC_ID_PATTERN = re.compile(r"^Document ID:\s*(?P<doc_id>.+?)\s*$", re.MULTILINE)
_TITLE_PATTERN = re.compile(r"^Title:\s*(?P<title>.*?)\s*$", re.MULTILINE)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "or",
    "the",
    "to",
    "was",
    "which",
    "who",
    "whose",
}
_METHOD_ORDER = {
    "poisoned_bm25": 0,
    "title_boosted_poisoned": 1,
    "guarded_filter": 2,
    "recovered_by_doc_id": 3,
    "clean_bm25_reference": 4,
}


@dataclass(frozen=True, slots=True)
class Stage21RunConfig:
    """Project-relative configuration for one Stage21 diagnostic run."""

    dataset: str
    sample_path: Path
    poisoned_output_dir: Path
    clean_output_dir: Path
    query_integrity_path: Path
    evidence_output_path: Path
    metrics_output_path: Path
    summary_output_path: Path
    report_path: Path
    max_queries: int = 50
    top_k_values: list[int] | None = None
    title_boost: float = 2.0
    changed_docs_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage21RunConfig":
        """Load a YAML config and resolve paths relative to the project root."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: str | None) -> Path | None:
            if raw in (None, ""):
                return None
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        top_k_values = [int(value) for value in payload.get("top_k_values", [5, 10])]
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(str(payload["sample_path"])),  # type: ignore[arg-type]
            poisoned_output_dir=resolve(str(payload["poisoned_output_dir"])),  # type: ignore[arg-type]
            clean_output_dir=resolve(str(payload["clean_output_dir"])),  # type: ignore[arg-type]
            query_integrity_path=resolve(str(payload["query_integrity_path"])),  # type: ignore[arg-type]
            changed_docs_path=resolve(payload.get("changed_docs_path")),
            evidence_output_path=resolve(str(payload["evidence_output_path"])),  # type: ignore[arg-type]
            metrics_output_path=resolve(str(payload["metrics_output_path"])),  # type: ignore[arg-type]
            summary_output_path=resolve(str(payload["summary_output_path"])),  # type: ignore[arg-type]
            report_path=resolve(str(payload["report_path"])),  # type: ignore[arg-type]
            max_queries=int(payload.get("max_queries", 50)),
            top_k_values=top_k_values,
            title_boost=float(payload.get("title_boost", 2.0)),
        )


@dataclass(frozen=True, slots=True)
class Stage21TextUnit:
    """One GraphRAG text unit mapped back to the original LogicGuard doc id."""

    text_unit_id: str
    human_readable_id: int
    official_document_id: str
    logicguard_doc_id: str
    title: str
    text: str
    n_tokens: int

    def to_ranked(
        self,
        *,
        score: float,
        rank: int,
        source_state: str,
        recovered_from_changed_doc: bool = False,
        risk_reasons: tuple[str, ...] = (),
    ) -> "Stage21RankedEvidence":
        """Attach rank and policy metadata without mutating the source unit."""

        return Stage21RankedEvidence(
            text_unit_id=self.text_unit_id,
            human_readable_id=self.human_readable_id,
            official_document_id=self.official_document_id,
            logicguard_doc_id=self.logicguard_doc_id,
            title=self.title,
            text=self.text,
            n_tokens=self.n_tokens,
            score=score,
            rank=rank,
            source_state=source_state,
            recovered_from_changed_doc=recovered_from_changed_doc,
            risk_reasons=risk_reasons,
        )


@dataclass(frozen=True, slots=True)
class Stage21RankedEvidence:
    """One ranked evidence item after a Stage21 retrieval/defense variant."""

    text_unit_id: str
    human_readable_id: int
    official_document_id: str
    logicguard_doc_id: str
    title: str
    text: str
    n_tokens: int
    score: float
    rank: int
    source_state: str
    recovered_from_changed_doc: bool = False
    risk_reasons: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, Any]:
        """Return a stable JSON payload for evidence traces."""

        payload = asdict(self)
        payload["risk_reasons"] = list(self.risk_reasons)
        return payload


@dataclass(frozen=True, slots=True)
class Stage21MetricRow:
    """Query-level retrieval and safety metrics for one method/top-k setting."""

    dataset: str
    top_k: int
    query_id: str
    query: str
    method: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    trusted_support_doc_ids: list[str]
    evidence_doc_ids: list[str]
    gold_hit_ids: list[str]
    changed_gold_hit_ids: list[str]
    trusted_gold_hit_ids: list[str]
    returned_count: int
    hit_at_k: float
    gold_recall_at_k: float
    precision_at_k: float
    distractor_ratio_at_k: float
    mrr_at_k: float
    changed_doc_exposure_at_k: float
    changed_gold_exposure_at_k: float
    trusted_gold_recall_at_k: float
    empty_context: int
    changed_evidence_count: int
    recovered_evidence_count: int

    def to_csv_row(self) -> dict[str, str]:
        """Format values for a spreadsheet-friendly UTF-8 CSV."""

        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            elif isinstance(value, list):
                output[key] = ";".join(value)
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class Stage21SummaryRow:
    """Method-level average metrics across all Stage21 queries."""

    dataset: str
    top_k: int
    method: str
    query_count: int
    avg_hit_at_k: float
    avg_gold_recall_at_k: float
    avg_precision_at_k: float
    avg_distractor_ratio_at_k: float
    avg_mrr_at_k: float
    avg_changed_doc_exposure_at_k: float
    avg_changed_gold_exposure_at_k: float
    avg_trusted_gold_recall_at_k: float
    empty_context_rate: float
    avg_returned_count: float
    avg_changed_evidence_count: float
    avg_recovered_evidence_count: float

    def to_csv_row(self) -> dict[str, str]:
        """Format values for a spreadsheet-friendly UTF-8 CSV."""

        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in asdict(self).items()
        }


def load_stage21_text_units(output_dir: Path) -> list[Stage21TextUnit]:
    """Load GraphRAG document/text-unit parquet files and restore source ids."""

    documents_path = output_dir / "documents.parquet"
    text_units_path = output_dir / "text_units.parquet"
    if not documents_path.exists():
        raise FileNotFoundError(f"Missing GraphRAG documents parquet: {documents_path}")
    if not text_units_path.exists():
        raise FileNotFoundError(f"Missing GraphRAG text_units parquet: {text_units_path}")

    documents_frame = pd.read_parquet(documents_path)
    text_units_frame = pd.read_parquet(text_units_path)
    document_lookup: dict[str, tuple[str, str]] = {}
    for row in documents_frame.to_dict(orient="records"):
        official_document_id = str(row["id"])
        document_text = str(row.get("text", ""))
        logicguard_doc_id = _parse_doc_id(document_text)
        title = _parse_title(document_text) or str(row.get("title", "")).removesuffix(".txt")
        document_lookup[official_document_id] = (logicguard_doc_id, title)

    units: list[Stage21TextUnit] = []
    for row in text_units_frame.to_dict(orient="records"):
        official_document_id = str(row["document_id"])
        if official_document_id not in document_lookup:
            raise ValueError(f"Text unit references unknown document id: {official_document_id}")
        logicguard_doc_id, fallback_title = document_lookup[official_document_id]
        text = str(row.get("text", ""))
        units.append(
            Stage21TextUnit(
                text_unit_id=str(row["id"]),
                human_readable_id=int(row.get("human_readable_id", 0) or 0),
                official_document_id=official_document_id,
                logicguard_doc_id=logicguard_doc_id,
                title=_parse_title(text) or fallback_title,
                text=text,
                n_tokens=int(row.get("n_tokens", 0) or 0),
            )
        )
    return units


def rank_text_units_bm25(
    query: str,
    units: list[Stage21TextUnit],
    *,
    top_k: int,
    title_boost: float,
) -> list[Stage21RankedEvidence]:
    """Rank evidence with BM25 over text plus an optional title-overlap boost."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not units:
        return []
    tokenized_texts = [_tokenize(unit.text) for unit in units]
    query_tokens = _tokenize(query)
    ranker = BM25Plus(tokenized_texts)
    bm25_scores = [float(score) for score in ranker.get_scores(query_tokens)]
    query_token_set = set(query_tokens)
    scored: list[tuple[float, Stage21TextUnit]] = []
    for unit, bm25_score in zip(units, bm25_scores, strict=True):
        title_overlap = len(query_token_set.intersection(_tokenize(unit.title)))
        score = bm25_score + title_boost * title_overlap
        scored.append((score, unit))
    scored.sort(key=lambda item: (-item[0], item[1].human_readable_id, item[1].logicguard_doc_id))
    return [
        unit.to_ranked(score=round(score, 6), rank=rank, source_state="poisoned")
        for rank, (score, unit) in enumerate(scored[:top_k], start=1)
    ]


def build_stage21_method_contexts(
    *,
    query: str,
    poisoned_units: list[Stage21TextUnit],
    clean_reference_units: list[Stage21TextUnit],
    changed_doc_ids: set[str],
    top_k: int,
    title_boost: float,
) -> dict[str, list[Stage21RankedEvidence]]:
    """Build all Stage21 retrieval/defense variants for one query."""

    poisoned_plain = _annotate_known_changed(
        rank_text_units_bm25(query, poisoned_units, top_k=top_k, title_boost=0.0),
        changed_doc_ids=changed_doc_ids,
        source_state="poisoned",
    )
    poisoned_title = _annotate_known_changed(
        rank_text_units_bm25(query, poisoned_units, top_k=top_k, title_boost=title_boost),
        changed_doc_ids=changed_doc_ids,
        source_state="poisoned",
    )
    guarded = [
        _rerank(item, rank=rank)
        for rank, item in enumerate(
            [item for item in poisoned_title if item.logicguard_doc_id not in changed_doc_ids],
            start=1,
        )
    ]
    recovered = _recover_changed_evidence(
        ranked=poisoned_title,
        clean_reference_units=clean_reference_units,
        changed_doc_ids=changed_doc_ids,
    )
    clean_reference = [
        _with_source_state(item, source_state="clean_reference")
        for item in rank_text_units_bm25(
            query,
            clean_reference_units,
            top_k=top_k,
            title_boost=title_boost,
        )
    ]
    return {
        "poisoned_bm25": poisoned_plain,
        "title_boosted_poisoned": poisoned_title,
        "guarded_filter": guarded,
        "recovered_by_doc_id": recovered,
        "clean_bm25_reference": clean_reference,
    }


def build_stage21_metric_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    contexts_by_query: dict[str, dict[str, list[Stage21RankedEvidence]]],
    top_k: int,
    dataset: str = "",
) -> list[Stage21MetricRow]:
    """Compute gold metrics after retrieval/defense contexts are already built."""

    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    rows: list[Stage21MetricRow] = []
    for sample in samples:
        methods = contexts_by_query.get(sample.query_id, {})
        integrity = integrity_by_query.get(sample.query_id, {})
        support_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_support_ids = [str(doc_id) for doc_id in integrity.get("changed_support_doc_ids", [])]
        changed_support_set = set(changed_support_ids)
        trusted_support_ids = [doc_id for doc_id in support_ids if doc_id not in changed_support_set]
        for method, evidence in methods.items():
            selected = evidence[:top_k]
            evidence_doc_ids = _dedupe(item.logicguard_doc_id for item in selected)
            gold_hits = _ordered_intersection(support_ids, evidence_doc_ids)
            changed_hits = _ordered_intersection(changed_support_ids, evidence_doc_ids)
            trusted_hits = _ordered_intersection(trusted_support_ids, evidence_doc_ids)
            changed_items = [
                item
                for item in selected
                if _is_unrecovered_changed_evidence(item, changed_support_set)
            ]
            changed_gold_doc_ids = _dedupe(
                item.logicguard_doc_id
                for item in changed_items
                if item.logicguard_doc_id in changed_support_set
            )
            rows.append(
                Stage21MetricRow(
                    dataset=dataset,
                    top_k=top_k,
                    query_id=sample.query_id,
                    query=sample.query,
                    method=method,
                    support_doc_ids=support_ids,
                    changed_support_doc_ids=changed_support_ids,
                    trusted_support_doc_ids=trusted_support_ids,
                    evidence_doc_ids=evidence_doc_ids,
                    gold_hit_ids=gold_hits,
                    changed_gold_hit_ids=changed_hits,
                    trusted_gold_hit_ids=trusted_hits,
                    returned_count=len(selected),
                    hit_at_k=1.0 if gold_hits else 0.0,
                    gold_recall_at_k=_ratio(len(gold_hits), len(support_ids)),
                    precision_at_k=_ratio(len(gold_hits), len(selected)),
                    distractor_ratio_at_k=_ratio(len(selected) - len(gold_hits), len(selected)),
                    mrr_at_k=_mrr(support_ids, evidence_doc_ids),
                    changed_doc_exposure_at_k=1.0 if changed_items else 0.0,
                    changed_gold_exposure_at_k=_ratio(
                        len(changed_gold_doc_ids),
                        len(changed_support_ids),
                    ),
                    trusted_gold_recall_at_k=_ratio(len(trusted_hits), len(trusted_support_ids)),
                    empty_context=1 if not selected else 0,
                    changed_evidence_count=len(changed_items),
                    recovered_evidence_count=sum(
                        1 for item in selected if item.recovered_from_changed_doc
                    ),
                )
            )
    return rows


def summarize_stage21_metrics(rows: list[Stage21MetricRow]) -> list[Stage21SummaryRow]:
    """Aggregate Stage21 query rows by dataset, top-k, and method."""

    grouped: dict[tuple[str, int, str], list[Stage21MetricRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.dataset, row.top_k, row.method)].append(row)
    summaries: list[Stage21SummaryRow] = []
    for (dataset, top_k, method), group in grouped.items():
        summaries.append(
            Stage21SummaryRow(
                dataset=dataset,
                top_k=top_k,
                method=method,
                query_count=len(group),
                avg_hit_at_k=_avg(row.hit_at_k for row in group),
                avg_gold_recall_at_k=_avg(row.gold_recall_at_k for row in group),
                avg_precision_at_k=_avg(row.precision_at_k for row in group),
                avg_distractor_ratio_at_k=_avg(row.distractor_ratio_at_k for row in group),
                avg_mrr_at_k=_avg(row.mrr_at_k for row in group),
                avg_changed_doc_exposure_at_k=_avg(
                    row.changed_doc_exposure_at_k for row in group
                ),
                avg_changed_gold_exposure_at_k=_avg(
                    row.changed_gold_exposure_at_k for row in group
                ),
                avg_trusted_gold_recall_at_k=_avg(
                    row.trusted_gold_recall_at_k for row in group
                ),
                empty_context_rate=_avg(float(row.empty_context) for row in group),
                avg_returned_count=_avg(float(row.returned_count) for row in group),
                avg_changed_evidence_count=_avg(float(row.changed_evidence_count) for row in group),
                avg_recovered_evidence_count=_avg(
                    float(row.recovered_evidence_count) for row in group
                ),
            )
        )
    summaries.sort(key=lambda row: (row.top_k, _METHOD_ORDER.get(row.method, 99), row.method))
    return summaries


def run_from_config(config: Stage21RunConfig) -> list[Stage21MetricRow]:
    """Run Stage21 diagnostics and write all machine/human-readable artifacts."""

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")
    top_k_values = config.top_k_values or [5, 10]
    if any(top_k < 1 for top_k in top_k_values):
        raise ValueError("top_k_values must all be positive")

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)
    changed_doc_ids = _load_global_changed_doc_ids(
        changed_docs_path=config.changed_docs_path,
        integrity_rows=integrity_rows,
    )
    poisoned_units = load_stage21_text_units(config.poisoned_output_dir)
    clean_units = load_stage21_text_units(config.clean_output_dir)
    evidence_rows: list[dict[str, Any]] = []
    metric_rows: list[Stage21MetricRow] = []

    for top_k in top_k_values:
        contexts_by_query: dict[str, dict[str, list[Stage21RankedEvidence]]] = {}
        for sample in samples:
            contexts = build_stage21_method_contexts(
                query=sample.query,
                poisoned_units=poisoned_units,
                clean_reference_units=clean_units,
                changed_doc_ids=changed_doc_ids,
                top_k=top_k,
                title_boost=config.title_boost,
            )
            contexts_by_query[sample.query_id] = contexts
            evidence_rows.extend(
                _evidence_trace_rows(
                    dataset=config.dataset,
                    top_k=top_k,
                    sample=sample,
                    contexts=contexts,
                )
            )
        metric_rows.extend(
            build_stage21_metric_rows(
                samples=samples,
                integrity_rows=integrity_rows,
                contexts_by_query=contexts_by_query,
                top_k=top_k,
                dataset=config.dataset,
            )
        )

    write_stage21_outputs(config=config, evidence_rows=evidence_rows, metric_rows=metric_rows)
    return metric_rows


def write_stage21_outputs(
    *,
    config: Stage21RunConfig,
    evidence_rows: list[dict[str, Any]],
    metric_rows: list[Stage21MetricRow],
) -> None:
    """Write evidence traces, query metrics, summaries, and a Chinese report."""

    summaries = summarize_stage21_metrics(metric_rows)
    config.evidence_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.metrics_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.summary_output_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    with config.evidence_output_path.open("w", encoding="utf-8") as handle:
        for row in evidence_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with config.metrics_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage21MetricRow.__dataclass_fields__))
        writer.writeheader()
        for row in metric_rows:
            writer.writerow(row.to_csv_row())
    with config.summary_output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Stage21SummaryRow.__dataclass_fields__))
        writer.writeheader()
        for row in summaries:
            writer.writerow(row.to_csv_row())
    _write_stage21_report(config, summaries)


def _recover_changed_evidence(
    *,
    ranked: list[Stage21RankedEvidence],
    clean_reference_units: list[Stage21TextUnit],
    changed_doc_ids: set[str],
) -> list[Stage21RankedEvidence]:
    clean_by_doc_id: dict[str, Stage21TextUnit] = {}
    for unit in sorted(clean_reference_units, key=lambda item: (item.human_readable_id, item.text_unit_id)):
        clean_by_doc_id.setdefault(unit.logicguard_doc_id, unit)

    recovered: list[Stage21RankedEvidence] = []
    for item in ranked:
        if item.logicguard_doc_id not in changed_doc_ids:
            recovered.append(item)
            continue
        clean_unit = clean_by_doc_id.get(item.logicguard_doc_id)
        if clean_unit is None:
            continue
        recovered.append(
            clean_unit.to_ranked(
                score=item.score,
                rank=item.rank,
                source_state="clean_reference",
                recovered_from_changed_doc=True,
                risk_reasons=("known_changed_doc", "recovered_from_clean_reference"),
            )
        )
    return [_rerank(item, rank=rank) for rank, item in enumerate(recovered, start=1)]


def _is_unrecovered_changed_evidence(
    item: Stage21RankedEvidence,
    query_changed_support_ids: set[str],
) -> bool:
    """Return True only for polluted evidence that has not been clean-recovered."""

    if item.recovered_from_changed_doc or item.source_state == "clean_reference":
        return False
    return item.logicguard_doc_id in query_changed_support_ids or "known_changed_doc" in item.risk_reasons


def _annotate_known_changed(
    ranked: list[Stage21RankedEvidence],
    *,
    changed_doc_ids: set[str],
    source_state: str,
) -> list[Stage21RankedEvidence]:
    return [
        Stage21RankedEvidence(
            text_unit_id=item.text_unit_id,
            human_readable_id=item.human_readable_id,
            official_document_id=item.official_document_id,
            logicguard_doc_id=item.logicguard_doc_id,
            title=item.title,
            text=item.text,
            n_tokens=item.n_tokens,
            score=item.score,
            rank=item.rank,
            source_state=source_state,
            recovered_from_changed_doc=item.recovered_from_changed_doc,
            risk_reasons=(
                ("known_changed_doc",)
                if item.logicguard_doc_id in changed_doc_ids
                else item.risk_reasons
            ),
        )
        for item in ranked
    ]


def _with_source_state(item: Stage21RankedEvidence, *, source_state: str) -> Stage21RankedEvidence:
    return Stage21RankedEvidence(
        text_unit_id=item.text_unit_id,
        human_readable_id=item.human_readable_id,
        official_document_id=item.official_document_id,
        logicguard_doc_id=item.logicguard_doc_id,
        title=item.title,
        text=item.text,
        n_tokens=item.n_tokens,
        score=item.score,
        rank=item.rank,
        source_state=source_state,
        recovered_from_changed_doc=item.recovered_from_changed_doc,
        risk_reasons=item.risk_reasons,
    )


def _rerank(item: Stage21RankedEvidence, *, rank: int) -> Stage21RankedEvidence:
    return Stage21RankedEvidence(
        text_unit_id=item.text_unit_id,
        human_readable_id=item.human_readable_id,
        official_document_id=item.official_document_id,
        logicguard_doc_id=item.logicguard_doc_id,
        title=item.title,
        text=item.text,
        n_tokens=item.n_tokens,
        score=item.score,
        rank=rank,
        source_state=item.source_state,
        recovered_from_changed_doc=item.recovered_from_changed_doc,
        risk_reasons=item.risk_reasons,
    )


def _evidence_trace_rows(
    *,
    dataset: str,
    top_k: int,
    sample: NormalizedSample,
    contexts: dict[str, list[Stage21RankedEvidence]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method, evidence in contexts.items():
        rows.append(
            {
                "dataset": dataset,
                "top_k": top_k,
                "query_id": sample.query_id,
                "query": sample.query,
                "method": method,
                "evidence": [item.to_json_dict() for item in evidence],
            }
        )
    return rows


def _write_stage21_report(config: Stage21RunConfig, summaries: list[Stage21SummaryRow]) -> None:
    summary_table = [
        "| top_k | method | queries | hit@k | gold_recall | precision | 干扰文档比例 | MRR | changed曝光 | changed-gold曝光 | trusted召回 | 空上下文率 | 平均返回数 | 平均恢复数 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        summary_table.append(
            f"| {row.top_k} | {row.method} | {row.query_count} | {row.avg_hit_at_k:.4f} | "
            f"{row.avg_gold_recall_at_k:.4f} | {row.avg_precision_at_k:.4f} | "
            f"{row.avg_distractor_ratio_at_k:.4f} | {row.avg_mrr_at_k:.4f} | "
            f"{row.avg_changed_doc_exposure_at_k:.4f} | {row.avg_changed_gold_exposure_at_k:.4f} | "
            f"{row.avg_trusted_gold_recall_at_k:.4f} | {row.empty_context_rate:.4f} | "
            f"{row.avg_returned_count:.2f} | {row.avg_recovered_evidence_count:.2f} |"
        )

    top10 = {row.method: row for row in summaries if row.top_k == 10}
    poisoned = top10.get("poisoned_bm25")
    guarded = top10.get("guarded_filter")
    recovered = top10.get("recovered_by_doc_id")
    delta_lines = ["- 未找到 top_k=10 的主对照，无法计算主变化。"]
    if poisoned and guarded and recovered:
        delta_lines = [
            f"- guard 后 changed 文档曝光：{poisoned.avg_changed_doc_exposure_at_k:.4f} -> {guarded.avg_changed_doc_exposure_at_k:.4f}。",
            f"- guard 后 gold recall：{poisoned.avg_gold_recall_at_k:.4f} -> {guarded.avg_gold_recall_at_k:.4f}。",
            f"- recovery 后 gold recall：{guarded.avg_gold_recall_at_k:.4f} -> {recovered.avg_gold_recall_at_k:.4f}。",
            f"- recovery 平均替换证据数：{recovered.avg_recovered_evidence_count:.2f}。",
        ]

    content = "\n".join(
        [
            "# Microsoft GraphRAG Stage21 中等规模查询诊断报告",
            "",
            "## 实验目的",
            "",
            "Stage21 使用 2WikiMultihopQA 的 debug_50 样本，以及 Microsoft GraphRAG minimal workflow 已经生成的 50-query clean/poisoned indexed artifacts。目标是在更大的共享索引空间中观察 LogicGuard 的 guard 与 recovery 是否仍然能降低污染证据暴露，并恢复可用证据。",
            "",
            "## 重要边界",
            "",
            "- 本阶段读取的是 official Microsoft GraphRAG 产出的 parquet 中间表，包括 documents、text_units、entities、relationships、communities。",
            "- 当前 50-query poisoned minimal workspace 没有 community_reports.parquet，因此本阶段不是完整 LocalSearchMixedContext 实验。",
            "- 排名层使用可审计 BM25/title-boost，本质是 official indexed artifact 级诊断；下一步仍需补齐 poisoned query-ready workspace 后再跑完整 official local query。",
            "- gold support 只在检索完成后用于评价，不参与排名、过滤或恢复。",
            "",
            "## 指标说明",
            "",
            "- hit@k：top-k 中是否至少命中一个正确支撑文档。",
            "- gold_recall：top-k 命中的正确支撑文档比例。",
            "- precision：top-k 中正确支撑文档所占比例。",
            "- 干扰文档比例：top-k 中非正确支撑文档所占比例，越低说明返回证据越集中。",
            "- MRR：第一个正确支撑文档的倒数排名，越高说明正确证据排得越靠前。",
            "- changed曝光：top-k 中是否出现未被恢复的污染证据；clean reference 或 recovered 证据不计为污染暴露。",
            "- changed-gold曝光：被改写的 gold support 中，有多少以未恢复污染证据形式进入 top-k。",
            "- trusted召回：未被改写的 gold support 的召回比例。",
            "- 空上下文率：guard/recovery 后没有任何证据可返回的 query 比例。",
            "",
            "## 汇总结果",
            "",
            *summary_table,
            "",
            "## 主对照变化",
            "",
            *delta_lines,
            "",
            "## 当前解释",
            "",
            "- 如果 guarded_filter 的 changed曝光明显下降，说明 provenance/content-integrity 风格的过滤确实能阻断已知污染证据进入回答上下文。",
            "- 如果 guarded_filter 的 gold_recall 同时明显下降，说明单纯过滤会牺牲可回答性，因为 LogicPoison 改写的是原位 support 文档。",
            "- 如果 recovered_by_doc_id 的 gold_recall 回升，说明 clean-reference recovery 能在不重建 GraphRAG 索引的情况下恢复可用证据。",
            "- 如果 title_boosted_poisoned 相比 poisoned_bm25 提升有限，说明中等规模共享图中的问题不只是词面标题召回，而是需要更强的 official query-layer trace 与实体映射修复。",
            "",
            "## 产物路径",
            "",
            f"- evidence JSONL：`{config.evidence_output_path.as_posix()}`",
            f"- query 指标 CSV：`{config.metrics_output_path.as_posix()}`",
            f"- method 汇总 CSV：`{config.summary_output_path.as_posix()}`",
            f"- 报告：`{config.report_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


def _load_global_changed_doc_ids(
    *,
    changed_docs_path: Path | None,
    integrity_rows: list[dict[str, Any]],
) -> set[str]:
    if changed_docs_path and changed_docs_path.exists():
        return {
            str(row["doc_id"])
            for row in _load_jsonl(changed_docs_path)
            if row.get("doc_id") is not None and bool(row.get("changed", True))
        }
    changed: set[str] = set()
    for row in integrity_rows:
        changed.update(str(doc_id) for doc_id in row.get("changed_support_doc_ids", []))
    return changed


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


def _parse_doc_id(text: str) -> str:
    match = _DOC_ID_PATTERN.search(text)
    if not match:
        raise ValueError("GraphRAG document text does not contain `Document ID:`")
    return match.group("doc_id").strip()


def _parse_title(text: str) -> str:
    match = _TITLE_PATTERN.search(text)
    return match.group("title").strip() if match else ""


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in (raw.casefold() for raw in _TOKEN_PATTERN.findall(value))
        if len(token) > 1 and token not in _STOPWORDS
    ]


def _ordered_intersection(expected: list[str], observed: list[str]) -> list[str]:
    observed_set = set(observed)
    return [value for value in expected if value in observed_set]


def _dedupe(values: Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mrr(support_doc_ids: list[str], evidence_doc_ids: list[str]) -> float:
    support_set = set(support_doc_ids)
    for index, doc_id in enumerate(evidence_doc_ids, start=1):
        if doc_id in support_set:
            return 1.0 / index
    return 0.0


def _avg(values: Any) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage21 medium diagnostics over Microsoft GraphRAG indexed artifacts."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage21_medium_diagnostics.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(Stage21RunConfig.from_yaml(args.config))
    print(f"stage21_metric_rows={len(rows)}")


if __name__ == "__main__":
    main()
