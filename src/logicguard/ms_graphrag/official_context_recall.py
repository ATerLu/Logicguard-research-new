"""Diagnose official GraphRAG local context recall for LogicGuard experiments."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.official_local_context import parse_doc_id_from_source_text
from logicguard.ms_graphrag.official_query_metrics import load_jsonl_records


@dataclass(frozen=True, slots=True)
class OfficialContextRecallRow:
    """One query-level recall diagnosis over official `context_data.sources`."""

    query_id: str
    query: str
    expected_answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    trusted_support_doc_ids: list[str]
    context_doc_ids: list[str]
    gold_support_hit_ids: list[str]
    changed_support_hit_ids: list[str]
    trusted_support_hit_ids: list[str]
    gold_support_recall: float
    changed_support_exposure: float
    trusted_support_recall: float
    official_response_status: str
    poisoned_outcome: str
    guarded_outcome: str
    recovered_outcome: str
    diagnosis: str

    def to_csv_row(self) -> dict[str, str]:
        """Return stable CSV strings with list fields joined by semicolons."""

        row = asdict(self)
        output: dict[str, str] = {}
        for key, value in row.items():
            if isinstance(value, float):
                output[key] = f"{value:.4f}"
            elif isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class OfficialContextRecallSummary:
    """Aggregate recall diagnosis for one experiment."""

    query_count: int
    avg_gold_support_recall: float
    avg_changed_support_exposure: float
    avg_trusted_support_recall: float
    context_recall_failure_count: int
    attack_recovered_count: int
    blocked_not_recovered_count: int
    attack_not_successful_count: int
    needs_review_count: int


def build_context_recall_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
) -> list[OfficialContextRecallRow]:
    """Build per-query context recall rows from existing experiment artifacts."""

    integrity_by_query = {
        str(row["query_id"]): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }
    context_by_query = {
        str(row["query_id"]): row
        for row in context_rows
        if row.get("query_id") is not None
    }
    outcomes_by_query = _build_variant_outcomes(result_rows)

    recall_rows: list[OfficialContextRecallRow] = []
    for sample in samples:
        integrity = integrity_by_query.get(sample.query_id, {})
        context = context_by_query.get(sample.query_id, {})
        support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
        changed_doc_ids = [
            str(doc_id) for doc_id in integrity.get("changed_support_doc_ids", [])
        ]
        trusted_doc_ids = [
            doc_id for doc_id in support_doc_ids if doc_id not in set(changed_doc_ids)
        ]
        context_doc_ids = _extract_context_doc_ids(context)

        gold_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
        changed_hits = _ordered_intersection(changed_doc_ids, context_doc_ids)
        trusted_hits = _ordered_intersection(trusted_doc_ids, context_doc_ids)
        outcomes = outcomes_by_query.get(sample.query_id, {})
        poisoned_outcome = outcomes.get("poisoned", "missing")
        guarded_outcome = outcomes.get("guarded", "missing")
        recovered_outcome = outcomes.get("recovered", "missing")
        gold_recall = _ratio(len(gold_hits), len(support_doc_ids))
        row = OfficialContextRecallRow(
            query_id=sample.query_id,
            query=sample.query,
            expected_answer=sample.answer,
            support_doc_ids=support_doc_ids,
            changed_support_doc_ids=changed_doc_ids,
            trusted_support_doc_ids=trusted_doc_ids,
            context_doc_ids=context_doc_ids,
            gold_support_hit_ids=gold_hits,
            changed_support_hit_ids=changed_hits,
            trusted_support_hit_ids=trusted_hits,
            gold_support_recall=gold_recall,
            changed_support_exposure=_ratio(len(changed_hits), len(changed_doc_ids)),
            trusted_support_recall=_ratio(len(trusted_hits), len(trusted_doc_ids)),
            official_response_status=_official_response_status(
                str(context.get("response", ""))
            ),
            poisoned_outcome=poisoned_outcome,
            guarded_outcome=guarded_outcome,
            recovered_outcome=recovered_outcome,
            diagnosis=_diagnose(
                gold_support_recall=gold_recall,
                poisoned_outcome=poisoned_outcome,
                guarded_outcome=guarded_outcome,
                recovered_outcome=recovered_outcome,
            ),
        )
        recall_rows.append(row)
    return recall_rows


def summarize_context_recall(
    rows: list[OfficialContextRecallRow],
) -> OfficialContextRecallSummary:
    """Aggregate context recall and diagnosis counts."""

    query_count = len(rows)
    diagnosis_counts = Counter(row.diagnosis for row in rows)
    return OfficialContextRecallSummary(
        query_count=query_count,
        avg_gold_support_recall=_average(row.gold_support_recall for row in rows),
        avg_changed_support_exposure=_average(
            row.changed_support_exposure for row in rows
        ),
        avg_trusted_support_recall=_average(row.trusted_support_recall for row in rows),
        context_recall_failure_count=diagnosis_counts["context_recall_failure"],
        attack_recovered_count=diagnosis_counts["attack_recovered"],
        blocked_not_recovered_count=diagnosis_counts["blocked_not_recovered"],
        attack_not_successful_count=diagnosis_counts["attack_not_successful"],
        needs_review_count=diagnosis_counts["needs_review"],
    )


def write_context_recall_artifacts(
    *,
    csv_path: Path,
    report_path: Path,
    rows: list[OfficialContextRecallRow],
    source_context_path: Path,
    source_results_path: Path | None,
) -> None:
    """Write query-level recall CSV and a compact Chinese report."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(OfficialContextRecallRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())

    summary = summarize_context_recall(rows)
    table_lines = [
        "| query_id | gold_support_recall | changed_exposure | trusted_recall | poisoned | guarded | recovered | diagnosis | context_doc_ids |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.query_id,
                    f"{row.gold_support_recall:.4f}",
                    f"{row.changed_support_exposure:.4f}",
                    f"{row.trusted_support_recall:.4f}",
                    row.poisoned_outcome,
                    row.guarded_outcome,
                    row.recovered_outcome,
                    row.diagnosis,
                    ";".join(row.context_doc_ids),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Microsoft GraphRAG official context 召回诊断报告",
            "",
            "## 召回指标说明",
            "",
            "- `gold_support_recall`：official `context_data.sources` 命中的 gold support docs 比例。",
            "- `changed_support_exposure`：已知 changed support docs 进入 official context 的比例，用于观察污染证据暴露。",
            "- `trusted_support_recall`：未被污染的 trusted support docs 进入 official context 的比例，用于观察干净证据是否可用。",
            "- `diagnosis`：结合 context 召回与 answer outcome 的失败类型标记。",
            "",
            "## 汇总",
            "",
            f"- query_count：`{summary.query_count}`",
            f"- avg_gold_support_recall：`{summary.avg_gold_support_recall:.4f}`",
            f"- avg_changed_support_exposure：`{summary.avg_changed_support_exposure:.4f}`",
            f"- avg_trusted_support_recall：`{summary.avg_trusted_support_recall:.4f}`",
            f"- context_recall_failure_count：`{summary.context_recall_failure_count}`",
            f"- attack_recovered_count：`{summary.attack_recovered_count}`",
            f"- blocked_not_recovered_count：`{summary.blocked_not_recovered_count}`",
            f"- attack_not_successful_count：`{summary.attack_not_successful_count}`",
            f"- needs_review_count：`{summary.needs_review_count}`",
            "",
            "## Query 明细",
            "",
            *table_lines,
            "",
            "## 产物路径",
            "",
            f"- source context：`{source_context_path.as_posix()}`",
            f"- source results：`{source_results_path.as_posix()}`"
            if source_results_path
            else "- source results：未提供",
            f"- CSV：`{csv_path.as_posix()}`",
            f"- report：`{report_path.as_posix()}`",
            "",
        ]
    )
    report_path.write_text(content, encoding="utf-8")


def _build_variant_outcomes(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    outcomes: dict[str, dict[str, str]] = {}
    for row in rows:
        query_id = row.get("query_id")
        variant = row.get("variant")
        if query_id is None or variant is None:
            continue
        outcomes.setdefault(str(query_id), {})[str(variant)] = _answer_outcome(row)
    return outcomes


def _answer_outcome(row: dict[str, Any]) -> str:
    if row.get("error"):
        return "error"
    if bool(row.get("is_correct")):
        return "correct"
    if bool(row.get("is_abstained")):
        return "abstained"
    if bool(row.get("is_incorrect")):
        return "incorrect"
    return "unknown"


def _extract_context_doc_ids(row: dict[str, Any]) -> list[str]:
    context_data = row.get("context_data", {})
    if not isinstance(context_data, dict):
        return []
    sources = context_data.get("sources", [])
    if not isinstance(sources, list):
        return []
    doc_ids: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        doc_id = str(
            source.get("logicguard_doc_id")
            or parse_doc_id_from_source_text(str(source.get("text", "")))
        )
        if doc_id and doc_id not in doc_ids:
            doc_ids.append(doc_id)
    return doc_ids


def _ordered_intersection(
    reference_order: list[str], candidates: list[str]
) -> list[str]:
    candidate_set = set(candidates)
    return [doc_id for doc_id in reference_order if doc_id in candidate_set]


def _official_response_status(response: str) -> str:
    normalized = response.strip().lower()
    if not normalized:
        return "missing"
    if (
        "i don't know" in normalized
        or "do not know" in normalized
        or "unknown" in normalized
    ):
        return "abstained"
    return "answered"


def _diagnose(
    *,
    gold_support_recall: float,
    poisoned_outcome: str,
    guarded_outcome: str,
    recovered_outcome: str,
) -> str:
    if gold_support_recall == 0:
        return "context_recall_failure"
    if poisoned_outcome == "incorrect" and recovered_outcome == "correct":
        return "attack_recovered"
    if (
        poisoned_outcome == "incorrect"
        and guarded_outcome == "abstained"
        and recovered_outcome != "correct"
    ):
        return "blocked_not_recovered"
    if poisoned_outcome != "incorrect":
        return "attack_not_successful"
    return "needs_review"


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _average(values: Any) -> float:
    collected = list(values)
    return sum(collected) / len(collected) if collected else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose official GraphRAG context recall."
    )
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--query-integrity", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    rows = build_context_recall_rows(
        samples=load_normalized_samples(args.samples),
        integrity_rows=load_jsonl_records(args.query_integrity),
        context_rows=load_jsonl_records(args.contexts),
        result_rows=load_jsonl_records(args.results) if args.results else [],
    )
    write_context_recall_artifacts(
        csv_path=args.csv,
        report_path=args.report,
        rows=rows,
        source_context_path=args.contexts,
        source_results_path=args.results,
    )
    summary = summarize_context_recall(rows)
    print(
        f"diagnosed {summary.query_count} queries: "
        f"avg_gold_support_recall={summary.avg_gold_support_recall:.4f}, "
        f"context_recall_failure={summary.context_recall_failure_count}"
    )


if __name__ == "__main__":
    main()
