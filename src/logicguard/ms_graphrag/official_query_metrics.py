"""Aggregate official GraphRAG query-time LogicGuard results.

This module turns per-query answer rows into paper-friendly metrics. It is kept
independent from GraphRAG and LLM clients so it can be rerun cheaply whenever an
experiment JSONL changes.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class OfficialQueryMetricRow:
    """Metrics for one model and one LogicGuard context variant."""

    model: str
    variant: str
    calls: int
    correct_count: int
    abstained_count: int
    incorrect_non_abstain_count: int
    correct_rate: float
    abstain_rate: float
    incorrect_non_abstain_rate: float
    avg_changed_doc_count: float
    avg_recovered_doc_count: float

    def to_csv_row(self) -> dict[str, str]:
        """Return stable string values for CSV export."""

        row = asdict(self)
        return {
            key: f"{value:.4f}" if isinstance(value, float) else str(value)
            for key, value in row.items()
        }


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Load UTF-8 JSONL records."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(payload)
    return records


def summarize_defense_results(rows: list[dict[str, Any]]) -> list[OfficialQueryMetricRow]:
    """Summarize answer rows by `(model, variant)`."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("model", "")), str(row.get("variant", "")))].append(row)

    metrics: list[OfficialQueryMetricRow] = []
    for (model, variant), group in sorted(grouped.items()):
        calls = len(group)
        correct_count = sum(1 for row in group if bool(row.get("is_correct")))
        abstained_count = sum(1 for row in group if bool(row.get("is_abstained")))
        incorrect_count = sum(1 for row in group if bool(row.get("is_incorrect")))
        changed_sum = sum(_as_int(row.get("changed_doc_count")) for row in group)
        recovered_sum = sum(_as_int(row.get("recovered_doc_count")) for row in group)
        metrics.append(
            OfficialQueryMetricRow(
                model=model,
                variant=variant,
                calls=calls,
                correct_count=correct_count,
                abstained_count=abstained_count,
                incorrect_non_abstain_count=incorrect_count,
                correct_rate=_ratio(correct_count, calls),
                abstain_rate=_ratio(abstained_count, calls),
                incorrect_non_abstain_rate=_ratio(incorrect_count, calls),
                avg_changed_doc_count=changed_sum / calls if calls else 0.0,
                avg_recovered_doc_count=recovered_sum / calls if calls else 0.0,
            )
        )
    return metrics


def write_metric_artifacts(
    *,
    csv_path: Path,
    report_path: Path,
    metrics: list[OfficialQueryMetricRow],
    source_results_path: Path,
    source_context_path: Path | None,
) -> None:
    """Write CSV metrics and a compact Chinese markdown report."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(OfficialQueryMetricRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow(row.to_csv_row())

    table_lines = [
        "| model | variant | calls | 正确率 | 拒答率 | 错误非拒答率 | 平均changed证据数 | 平均recovery证据数 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.model,
                    row.variant,
                    str(row.calls),
                    f"{row.correct_rate:.4f}",
                    f"{row.abstain_rate:.4f}",
                    f"{row.incorrect_non_abstain_rate:.4f}",
                    f"{row.avg_changed_doc_count:.2f}",
                    f"{row.avg_recovered_doc_count:.2f}",
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# Microsoft GraphRAG official query LogicGuard 指标汇总",
            "",
            "## 指标说明",
            "",
            "- `正确率`：回答包含 gold answer 的比例。",
            "- `拒答率`：回答被判定为 UNKNOWN 或证据不足表达的比例。",
            "- `错误非拒答率`：既没有命中 gold answer、也没有拒答的比例；在 poisoned 条件下可近似观察攻击成功风险。",
            "- `平均changed证据数`：进入回答上下文的已知污染证据数量均值，越低越好。",
            "- `平均recovery证据数`：由 clean reference 替换回来的证据数量均值，用于观察恢复机制介入强度。",
            "",
            "## 汇总表",
            "",
            *table_lines,
            "",
            "## 产物路径",
            "",
            f"- source results：`{_display_path(source_results_path)}`",
            f"- source context：`{_display_path(source_context_path)}`" if source_context_path else "- source context：未提供",
            f"- CSV：`{_display_path(csv_path)}`",
            f"- report：`{_display_path(report_path)}`",
            "",
        ]
    )
    report_path.write_text(content, encoding="utf-8")


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _display_path(path: Path) -> str:
    return path.as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate official GraphRAG LogicGuard query metrics.")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, default=None)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    rows = load_jsonl_records(args.results)
    metrics = summarize_defense_results(rows)
    write_metric_artifacts(
        csv_path=args.csv,
        report_path=args.report,
        metrics=metrics,
        source_results_path=args.results,
        source_context_path=args.contexts,
    )
    print(f"aggregated {len(rows)} result rows into {len(metrics)} metric rows")


if __name__ == "__main__":
    main()
