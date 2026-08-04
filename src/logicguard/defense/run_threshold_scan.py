"""Threshold-grid evaluation for LogicGuard guarded context settings."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.defense.reranker import build_guarded_trace, rerank_trace
from logicguard.defense.run_logicguard import (
    calculate_suppression_stats,
    find_changed_doc_ids,
    load_document_fingerprints,
    load_global_entity_support_counts,
    load_poisoned_doc_ids_by_query,
    load_reference_doc_ids,
    load_traces_jsonl,
    summarize_defense_run,
)
from logicguard.graph.schemas import RetrievalTrace


@dataclass(frozen=True, slots=True)
class ThresholdScanConfig:
    """Configuration for one full-query threshold scan."""

    dataset: str
    run_name: str
    reference_corpus_path: Path
    reference_corpus_entity_path: Path
    clean_corpus_path: Path
    clean_trace_path: Path
    clean_corpus_entity_path: Path
    entity_swap_corpus_path: Path
    entity_swap_trace_path: Path
    entity_swap_corpus_entity_path: Path
    entity_swap_attack_metadata_path: Path
    bridge_corpus_path: Path
    bridge_trace_path: Path
    bridge_corpus_entity_path: Path
    bridge_attack_metadata_path: Path
    output_root: Path
    report_path: Path
    top_k: int
    risk_penalties: list[float]
    risk_thresholds: list[float]

    @classmethod
    def from_yaml(cls, path: Path) -> "ThresholdScanConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            run_name=str(payload["run_name"]),
            reference_corpus_path=resolve_project_path(
                payload["reference_corpus_path"]
            ),
            reference_corpus_entity_path=resolve_project_path(
                payload["reference_corpus_entity_path"]
            ),
            clean_corpus_path=resolve_project_path(payload["clean_corpus_path"]),
            clean_trace_path=resolve_project_path(payload["clean_trace_path"]),
            clean_corpus_entity_path=resolve_project_path(
                payload["clean_corpus_entity_path"]
            ),
            entity_swap_corpus_path=resolve_project_path(
                payload["entity_swap_corpus_path"]
            ),
            entity_swap_trace_path=resolve_project_path(
                payload["entity_swap_trace_path"]
            ),
            entity_swap_corpus_entity_path=resolve_project_path(
                payload["entity_swap_corpus_entity_path"]
            ),
            entity_swap_attack_metadata_path=resolve_project_path(
                payload["entity_swap_attack_metadata_path"]
            ),
            bridge_corpus_path=resolve_project_path(payload["bridge_corpus_path"]),
            bridge_trace_path=resolve_project_path(payload["bridge_trace_path"]),
            bridge_corpus_entity_path=resolve_project_path(
                payload["bridge_corpus_entity_path"]
            ),
            bridge_attack_metadata_path=resolve_project_path(
                payload["bridge_attack_metadata_path"]
            ),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            top_k=int(payload.get("top_k", 10)),
            risk_penalties=[float(value) for value in payload["risk_penalties"]],
            risk_thresholds=[float(value) for value in payload["risk_thresholds"]],
        )

    def output_dir(self) -> Path:
        return self.output_root / self.dataset / self.run_name


@dataclass(frozen=True, slots=True)
class ThresholdScanRow:
    """One threshold-grid result row."""

    dataset: str
    run_name: str
    risk_penalty: float
    risk_threshold: float
    clean_hit_before: float
    clean_hit_guarded: float
    clean_gold_recall_before: float
    clean_gold_recall_guarded: float
    clean_trusted_gold_recall_before: float
    clean_trusted_gold_recall_guarded: float
    clean_corrupted_gold_docs: int
    clean_suppressed_gold: int
    entity_exposure_before: float
    entity_exposure_guarded: float
    entity_hit_before: float
    entity_hit_guarded: float
    entity_gold_recall_before: float
    entity_gold_recall_guarded: float
    entity_trusted_gold_recall_before: float
    entity_trusted_gold_recall_guarded: float
    entity_corrupted_gold_docs: int
    entity_suppressed_gold: int
    entity_suppressed_poisoned: int
    entity_suppressed_changed: int
    bridge_exposure_before: float
    bridge_exposure_guarded: float
    bridge_hit_before: float
    bridge_hit_guarded: float
    bridge_gold_recall_before: float
    bridge_gold_recall_guarded: float
    bridge_trusted_gold_recall_before: float
    bridge_trusted_gold_recall_guarded: float
    bridge_corrupted_gold_docs: int
    bridge_suppressed_gold: int
    bridge_suppressed_poisoned: int
    bridge_suppressed_changed: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_threshold_pair(
    *,
    dataset: str,
    run_name: str,
    risk_penalty: float,
    risk_threshold: float,
    top_k: int,
    clean_traces: list[RetrievalTrace],
    entity_traces: list[RetrievalTrace],
    bridge_traces: list[RetrievalTrace],
    reference_doc_ids: set[str],
    clean_global_support: dict[str, int],
    entity_global_support: dict[str, int],
    bridge_global_support: dict[str, int],
    entity_poisoned_doc_ids_by_query: dict[str, set[str]],
    bridge_poisoned_doc_ids_by_query: dict[str, set[str]],
    clean_changed_doc_ids: set[str],
    entity_changed_doc_ids: set[str],
    bridge_changed_doc_ids: set[str],
) -> ThresholdScanRow:
    """Evaluate one risk setting against clean, Entity Swap, and Bridge Injection traces."""

    clean_reranked = [
        rerank_trace(
            trace,
            risk_penalty=risk_penalty,
            global_entity_support_counts=clean_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=clean_changed_doc_ids,
        )
        for trace in clean_traces
    ]
    clean_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=risk_penalty,
            risk_threshold=risk_threshold,
            global_entity_support_counts=clean_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=clean_changed_doc_ids,
        )
        for trace in clean_traces
    ]
    entity_reranked = [
        rerank_trace(
            trace,
            risk_penalty=risk_penalty,
            global_entity_support_counts=entity_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=entity_changed_doc_ids,
        )
        for trace in entity_traces
    ]
    entity_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=risk_penalty,
            risk_threshold=risk_threshold,
            global_entity_support_counts=entity_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=entity_changed_doc_ids,
        )
        for trace in entity_traces
    ]
    bridge_reranked = [
        rerank_trace(
            trace,
            risk_penalty=risk_penalty,
            global_entity_support_counts=bridge_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=bridge_changed_doc_ids,
        )
        for trace in bridge_traces
    ]
    bridge_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=risk_penalty,
            risk_threshold=risk_threshold,
            global_entity_support_counts=bridge_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=bridge_changed_doc_ids,
        )
        for trace in bridge_traces
    ]

    clean_metrics = summarize_defense_run(
        name="Clean",
        before_traces=clean_traces,
        reranked_traces=clean_reranked,
        guarded_traces=clean_guarded,
        poisoned_doc_ids_by_query={},
        changed_doc_ids=clean_changed_doc_ids,
        top_k=top_k,
    )
    entity_metrics = summarize_defense_run(
        name="Entity Swap",
        before_traces=entity_traces,
        reranked_traces=entity_reranked,
        guarded_traces=entity_guarded,
        poisoned_doc_ids_by_query=entity_poisoned_doc_ids_by_query,
        changed_doc_ids=entity_changed_doc_ids,
        top_k=top_k,
    )
    bridge_metrics = summarize_defense_run(
        name="Bridge Injection",
        before_traces=bridge_traces,
        reranked_traces=bridge_reranked,
        guarded_traces=bridge_guarded,
        poisoned_doc_ids_by_query=bridge_poisoned_doc_ids_by_query,
        changed_doc_ids=bridge_changed_doc_ids,
        top_k=top_k,
    )
    entity_suppression = calculate_suppression_stats(
        entity_reranked,
        entity_guarded,
        entity_poisoned_doc_ids_by_query,
        changed_doc_ids=entity_changed_doc_ids,
    )
    bridge_suppression = calculate_suppression_stats(
        bridge_reranked,
        bridge_guarded,
        bridge_poisoned_doc_ids_by_query,
        changed_doc_ids=bridge_changed_doc_ids,
    )

    return ThresholdScanRow(
        dataset=dataset,
        run_name=run_name,
        risk_penalty=risk_penalty,
        risk_threshold=risk_threshold,
        clean_hit_before=clean_metrics.before_hit_at_k,
        clean_hit_guarded=clean_metrics.guarded_hit_at_k,
        clean_gold_recall_before=clean_metrics.before_gold_recall_at_k,
        clean_gold_recall_guarded=clean_metrics.guarded_gold_recall_at_k,
        clean_trusted_gold_recall_before=clean_metrics.before_trusted_gold_recall_at_k,
        clean_trusted_gold_recall_guarded=clean_metrics.guarded_trusted_gold_recall_at_k,
        clean_corrupted_gold_docs=clean_metrics.corrupted_gold_doc_count,
        clean_suppressed_gold=clean_metrics.suppressed_gold_candidates,
        entity_exposure_before=entity_metrics.before_exposure_at_k or 0.0,
        entity_exposure_guarded=entity_metrics.guarded_exposure_at_k or 0.0,
        entity_hit_before=entity_metrics.before_hit_at_k,
        entity_hit_guarded=entity_metrics.guarded_hit_at_k,
        entity_gold_recall_before=entity_metrics.before_gold_recall_at_k,
        entity_gold_recall_guarded=entity_metrics.guarded_gold_recall_at_k,
        entity_trusted_gold_recall_before=entity_metrics.before_trusted_gold_recall_at_k,
        entity_trusted_gold_recall_guarded=entity_metrics.guarded_trusted_gold_recall_at_k,
        entity_corrupted_gold_docs=entity_metrics.corrupted_gold_doc_count,
        entity_suppressed_gold=entity_metrics.suppressed_gold_candidates,
        entity_suppressed_poisoned=entity_suppression["suppressed_poisoned_candidates"],
        entity_suppressed_changed=entity_suppression["suppressed_changed_candidates"],
        bridge_exposure_before=bridge_metrics.before_exposure_at_k or 0.0,
        bridge_exposure_guarded=bridge_metrics.guarded_exposure_at_k or 0.0,
        bridge_hit_before=bridge_metrics.before_hit_at_k,
        bridge_hit_guarded=bridge_metrics.guarded_hit_at_k,
        bridge_gold_recall_before=bridge_metrics.before_gold_recall_at_k,
        bridge_gold_recall_guarded=bridge_metrics.guarded_gold_recall_at_k,
        bridge_trusted_gold_recall_before=bridge_metrics.before_trusted_gold_recall_at_k,
        bridge_trusted_gold_recall_guarded=bridge_metrics.guarded_trusted_gold_recall_at_k,
        bridge_corrupted_gold_docs=bridge_metrics.corrupted_gold_doc_count,
        bridge_suppressed_gold=bridge_metrics.suppressed_gold_candidates,
        bridge_suppressed_poisoned=bridge_suppression["suppressed_poisoned_candidates"],
        bridge_suppressed_changed=bridge_suppression["suppressed_changed_candidates"],
    )


def run_from_config(config: ThresholdScanConfig) -> list[ThresholdScanRow]:
    clean_traces = load_traces_jsonl(config.clean_trace_path)
    entity_traces = load_traces_jsonl(config.entity_swap_trace_path)
    bridge_traces = load_traces_jsonl(config.bridge_trace_path)
    reference_doc_ids = load_reference_doc_ids(config.reference_corpus_entity_path)
    reference_fingerprints = load_document_fingerprints(config.reference_corpus_path)
    clean_changed_doc_ids = find_changed_doc_ids(
        reference_fingerprints,
        load_document_fingerprints(config.clean_corpus_path),
    )
    entity_changed_doc_ids = find_changed_doc_ids(
        reference_fingerprints,
        load_document_fingerprints(config.entity_swap_corpus_path),
    )
    bridge_changed_doc_ids = find_changed_doc_ids(
        reference_fingerprints,
        load_document_fingerprints(config.bridge_corpus_path),
    )
    rows = [
        evaluate_threshold_pair(
            dataset=config.dataset,
            run_name=config.run_name,
            risk_penalty=penalty,
            risk_threshold=threshold,
            top_k=config.top_k,
            clean_traces=clean_traces,
            entity_traces=entity_traces,
            bridge_traces=bridge_traces,
            reference_doc_ids=reference_doc_ids,
            clean_global_support=load_global_entity_support_counts(
                config.clean_corpus_entity_path
            ),
            entity_global_support=load_global_entity_support_counts(
                config.entity_swap_corpus_entity_path
            ),
            bridge_global_support=load_global_entity_support_counts(
                config.bridge_corpus_entity_path
            ),
            entity_poisoned_doc_ids_by_query=load_poisoned_doc_ids_by_query(
                config.entity_swap_attack_metadata_path
            ),
            bridge_poisoned_doc_ids_by_query=load_poisoned_doc_ids_by_query(
                config.bridge_attack_metadata_path
            ),
            clean_changed_doc_ids=clean_changed_doc_ids,
            entity_changed_doc_ids=entity_changed_doc_ids,
            bridge_changed_doc_ids=bridge_changed_doc_ids,
        )
        for penalty in config.risk_penalties
        for threshold in config.risk_thresholds
    ]
    write_scan_outputs(config, rows)
    print(
        f"{config.dataset}/{config.run_name}: threshold_rows={len(rows)}, best={_best_row(rows).risk_threshold:.2f}"
    )
    return rows


def write_scan_outputs(
    config: ThresholdScanConfig, rows: list[ThresholdScanRow]
) -> None:
    output_dir = config.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "threshold_scan_rows.jsonl"
    csv_path = output_dir / "threshold_scan_rows.csv"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].to_json_dict()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_json_dict())
    _write_report(config.report_path, rows, jsonl_path, csv_path)


def _write_report(
    path: Path, rows: list[ThresholdScanRow], jsonl_path: Path, csv_path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    best = _best_row(rows)
    table_lines = [
        "| penalty | threshold | clean recall | entity exposure | entity nominal recall | entity trusted recall | entity corrupted gold | entity gold filtered | bridge exposure | bridge trusted recall |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    f"{row.risk_penalty:.2f}",
                    f"{row.risk_threshold:.2f}",
                    f"{row.clean_gold_recall_guarded:.4f}",
                    f"{row.entity_exposure_guarded:.4f}",
                    f"{row.entity_gold_recall_guarded:.4f}",
                    f"{row.entity_trusted_gold_recall_guarded:.4f}",
                    str(row.entity_corrupted_gold_docs),
                    str(row.entity_suppressed_gold),
                    f"{row.bridge_exposure_guarded:.4f}",
                    f"{row.bridge_trusted_gold_recall_guarded:.4f}",
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            f"# LogicGuard Threshold Scan: {best.dataset} {best.run_name}",
            "",
            "## Output Files",
            "",
            f"- JSONL rows: `{jsonl_path}`",
            f"- CSV rows: `{csv_path}`",
            "",
            "## Best Row",
            "",
            f"- risk_penalty: `{best.risk_penalty:.2f}`",
            f"- risk_threshold: `{best.risk_threshold:.2f}`",
            f"- clean gold_recall@10: `{best.clean_gold_recall_guarded:.4f}`",
            f"- Entity Swap exposure@10: `{best.entity_exposure_guarded:.4f}`",
            f"- Bridge Injection exposure@10: `{best.bridge_exposure_guarded:.4f}`",
            f"- Entity Swap trusted_recall@10: `{best.entity_trusted_gold_recall_guarded:.4f}`",
            f"- Bridge Injection trusted_recall@10: `{best.bridge_trusted_gold_recall_guarded:.4f}`",
            f"- Entity Swap corrupted gold docs: `{best.entity_corrupted_gold_docs}`",
            f"- Entity Swap gold filtered: `{best.entity_suppressed_gold}`",
            f"- Bridge Injection gold filtered: `{best.bridge_suppressed_gold}`",
            "",
            "## Grid Results",
            "",
            *table_lines,
            "",
            "## Metric Notes",
            "",
            "`entity nominal recall` is the qrels-based gold recall and still treats changed gold documents "
            "as gold. `entity trusted recall` excludes changed/corrupted gold support documents from the "
            "denominator, which better reflects security-sensitive evidence quality. `entity corrupted gold` "
            "counts gold evidence occurrences across queries, not unique document ids.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _best_row(rows: list[ThresholdScanRow]) -> ThresholdScanRow:
    return sorted(
        rows,
        key=lambda row: (
            row.entity_exposure_guarded + row.bridge_exposure_guarded,
            -(row.clean_gold_recall_guarded),
            row.clean_suppressed_gold,
            row.risk_threshold,
            row.risk_penalty,
        ),
    )[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run LogicGuard full-query threshold scan."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicguard_threshold_scan_full_500.yaml"),
        help="Path to the threshold scan YAML config.",
    )
    args = parser.parse_args()
    run_from_config(ThresholdScanConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
