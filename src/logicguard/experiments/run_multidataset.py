"""Run the full LogicGuard retrieval-security pipeline on multiple datasets.

The lower-level modules intentionally operate on one dataset at a time because
that keeps baseline, attack, and defense runners easy to test. This module is a
thin orchestration layer: it derives the per-dataset configs, executes the same
steps for every benchmark, and writes one compact cross-dataset summary report.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from logicguard.attack.run_bridge_injection import (
    BridgeInjectionRunConfig,
    run_from_config as run_bridge_injection_from_config,
)
from logicguard.attack.run_entity_swap import EntitySwapRunConfig, run_from_config as run_entity_swap_from_config
from logicguard.data.prepare import prepare_dataset
from logicguard.defense.run_threshold_scan import (
    ThresholdScanConfig,
    ThresholdScanRow,
    run_from_config as run_threshold_scan_from_config,
)
from logicguard.graph.run_baseline import BaselineConfig, run_from_config as run_baseline_from_config


@dataclass(frozen=True, slots=True)
class MultiDatasetExperimentConfig:
    """Configuration for running the same full_500 experiment on several datasets."""

    datasets: list[str]
    raw_data_root: Path
    processed_data_root: Path
    report_root: Path
    baseline_output_root: Path
    entity_swap_output_root: Path
    bridge_injection_output_root: Path
    threshold_scan_output_root: Path
    summary_output_root: Path
    summary_report_path: Path
    run_name: str
    debug_size: int
    max_attacks: int
    top_k: int
    max_depth: int
    risk_penalties: list[float]
    risk_thresholds: list[float]

    @classmethod
    def from_yaml(cls, path: Path) -> "MultiDatasetExperimentConfig":
        """Load a multi-dataset config with paths relative to the project root."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            datasets=[str(dataset) for dataset in payload["datasets"]],
            raw_data_root=resolve_project_path(payload["raw_data_root"]),
            processed_data_root=resolve_project_path(payload["processed_data_root"]),
            report_root=resolve_project_path(payload["report_root"]),
            baseline_output_root=resolve_project_path(payload["baseline_output_root"]),
            entity_swap_output_root=resolve_project_path(payload["entity_swap_output_root"]),
            bridge_injection_output_root=resolve_project_path(payload["bridge_injection_output_root"]),
            threshold_scan_output_root=resolve_project_path(payload["threshold_scan_output_root"]),
            summary_output_root=resolve_project_path(payload["summary_output_root"]),
            summary_report_path=resolve_project_path(payload["summary_report_path"]),
            run_name=str(payload.get("run_name", "full_500")),
            debug_size=int(payload.get("debug_size", 50)),
            max_attacks=int(payload.get("max_attacks", 500)),
            top_k=int(payload.get("top_k", 10)),
            max_depth=int(payload.get("max_depth", 3)),
            risk_penalties=[float(value) for value in payload["risk_penalties"]],
            risk_thresholds=[float(value) for value in payload["risk_thresholds"]],
        )

    def sample_path(self, dataset: str) -> Path:
        """Return the normalized sample file used by full-query experiments."""

        return self.processed_data_root / dataset / "samples.jsonl"

    def baseline_config(self, dataset: str) -> BaselineConfig:
        """Create the single-dataset baseline config for `dataset`."""

        return BaselineConfig(
            dataset=dataset,
            raw_data_root=self.raw_data_root,
            sample_path=self.sample_path(dataset),
            output_root=self.baseline_output_root,
            report_root=self.report_root,
            run_name=self.run_name,
            top_k=self.top_k,
            max_depth=self.max_depth,
        )

    def entity_swap_config(self, dataset: str) -> EntitySwapRunConfig:
        """Create the single-dataset Entity Swap config for `dataset`."""

        return EntitySwapRunConfig(
            dataset=dataset,
            raw_data_root=self.raw_data_root,
            sample_path=self.sample_path(dataset),
            output_root=self.entity_swap_output_root,
            report_root=self.report_root,
            run_name=self.run_name,
            max_attacks=self.max_attacks,
            top_k=self.top_k,
            max_depth=self.max_depth,
        )

    def bridge_injection_config(self, dataset: str) -> BridgeInjectionRunConfig:
        """Create the single-dataset Bridge Injection config for `dataset`."""

        return BridgeInjectionRunConfig(
            dataset=dataset,
            raw_data_root=self.raw_data_root,
            sample_path=self.sample_path(dataset),
            output_root=self.bridge_injection_output_root,
            report_root=self.report_root,
            run_name=self.run_name,
            max_attacks=self.max_attacks,
            top_k=self.top_k,
            max_depth=self.max_depth,
        )

    def threshold_scan_config(self, dataset: str) -> ThresholdScanConfig:
        """Create the single-dataset LogicGuard threshold scan config."""

        reference_corpus_path = self.raw_data_root / dataset / "corpus.jsonl"
        baseline_root = self.baseline_output_root / dataset
        entity_root = self.entity_swap_output_root / dataset
        bridge_root = self.bridge_injection_output_root / dataset

        return ThresholdScanConfig(
            dataset=dataset,
            run_name=self.run_name,
            reference_corpus_path=reference_corpus_path,
            reference_corpus_entity_path=baseline_root / "corpus_entities.jsonl",
            clean_corpus_path=reference_corpus_path,
            clean_trace_path=baseline_root / f"{self.run_name}_traces.jsonl",
            clean_corpus_entity_path=baseline_root / "corpus_entities.jsonl",
            entity_swap_corpus_path=entity_root / "poisoned_corpus.jsonl",
            entity_swap_trace_path=entity_root / f"poisoned_{self.run_name}_traces.jsonl",
            entity_swap_corpus_entity_path=entity_root / "poisoned_corpus_entities.jsonl",
            entity_swap_attack_metadata_path=entity_root / "entity_swap_metadata.jsonl",
            bridge_corpus_path=bridge_root / "bridge_poisoned_corpus.jsonl",
            bridge_trace_path=bridge_root / f"bridge_poisoned_{self.run_name}_traces.jsonl",
            bridge_corpus_entity_path=bridge_root / "bridge_poisoned_corpus_entities.jsonl",
            bridge_attack_metadata_path=bridge_root / "bridge_injection_metadata.jsonl",
            output_root=self.threshold_scan_output_root,
            report_path=self.report_root / f"logicguard_threshold_scan_{dataset}_{self.run_name}.md",
            top_k=self.top_k,
            risk_penalties=self.risk_penalties,
            risk_thresholds=self.risk_thresholds,
        )

    def summary_dir(self) -> Path:
        """Return the directory that stores machine-readable aggregate rows."""

        return self.summary_output_root / self.run_name


@dataclass(frozen=True, slots=True)
class MultiDatasetSummaryRow:
    """Best-threshold summary for one dataset."""

    dataset: str
    run_name: str
    risk_penalty: float
    risk_threshold: float
    clean_gold_recall_guarded: float
    entity_exposure_before: float
    entity_exposure_guarded: float
    entity_gold_recall_guarded: float
    entity_trusted_gold_recall_guarded: float
    entity_corrupted_gold_docs: int
    entity_suppressed_gold: int
    bridge_exposure_before: float
    bridge_exposure_guarded: float
    bridge_gold_recall_guarded: float
    bridge_trusted_gold_recall_guarded: float
    bridge_suppressed_gold: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def run_multidataset_pipeline(
    config: MultiDatasetExperimentConfig,
    *,
    datasets: list[str] | None = None,
    prepare: bool = True,
    baseline: bool = True,
    attacks: bool = True,
    scan: bool = True,
) -> list[MultiDatasetSummaryRow]:
    """Execute selected pipeline stages for every requested dataset.

    Each stage calls the already-tested single-dataset runner. Keeping this
    function as orchestration avoids duplicating attack or defense logic here.
    """

    selected_datasets = datasets or config.datasets
    summary_rows: list[MultiDatasetSummaryRow] = []

    for dataset in selected_datasets:
        if dataset not in config.datasets:
            raise ValueError(f"Dataset {dataset!r} is not listed in the multi-dataset config")

        if prepare:
            summary = prepare_dataset(
                dataset_name=dataset,
                raw_data_root=config.raw_data_root,
                processed_data_root=config.processed_data_root,
                report_root=config.report_root,
                debug_size=config.debug_size,
            )
            print(f"{dataset}: data status={summary.status}, queries={summary.queries}")

        if baseline:
            run_baseline_from_config(config.baseline_config(dataset))

        if attacks:
            run_entity_swap_from_config(config.entity_swap_config(dataset))
            run_bridge_injection_from_config(config.bridge_injection_config(dataset))

        if scan:
            rows = run_threshold_scan_from_config(config.threshold_scan_config(dataset))
            summary_rows.append(_to_summary_row(_best_row(rows)))

    if summary_rows:
        _write_summary_outputs(config, summary_rows)

    return summary_rows


def _best_row(rows: list[ThresholdScanRow]) -> ThresholdScanRow:
    """Select the same best row used by the per-dataset threshold scan report."""

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


def _to_summary_row(row: ThresholdScanRow) -> MultiDatasetSummaryRow:
    return MultiDatasetSummaryRow(
        dataset=row.dataset,
        run_name=row.run_name,
        risk_penalty=row.risk_penalty,
        risk_threshold=row.risk_threshold,
        clean_gold_recall_guarded=row.clean_gold_recall_guarded,
        entity_exposure_before=row.entity_exposure_before,
        entity_exposure_guarded=row.entity_exposure_guarded,
        entity_gold_recall_guarded=row.entity_gold_recall_guarded,
        entity_trusted_gold_recall_guarded=row.entity_trusted_gold_recall_guarded,
        entity_corrupted_gold_docs=row.entity_corrupted_gold_docs,
        entity_suppressed_gold=row.entity_suppressed_gold,
        bridge_exposure_before=row.bridge_exposure_before,
        bridge_exposure_guarded=row.bridge_exposure_guarded,
        bridge_gold_recall_guarded=row.bridge_gold_recall_guarded,
        bridge_trusted_gold_recall_guarded=row.bridge_trusted_gold_recall_guarded,
        bridge_suppressed_gold=row.bridge_suppressed_gold,
    )


def _write_summary_outputs(config: MultiDatasetExperimentConfig, rows: list[MultiDatasetSummaryRow]) -> None:
    summary_dir = config.summary_dir()
    summary_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = summary_dir / "multidataset_summary_rows.jsonl"
    csv_path = summary_dir / "multidataset_summary_rows.csv"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].to_json_dict()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_json_dict())

    _write_summary_report(config.summary_report_path, rows, jsonl_path, csv_path)


def _write_summary_report(
    path: Path,
    rows: list[MultiDatasetSummaryRow],
    jsonl_path: Path,
    csv_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| dataset | threshold | clean recall | entity exposure | entity trusted recall | entity corrupted gold | bridge exposure | bridge trusted recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.dataset,
                    f"{row.risk_threshold:.2f}",
                    f"{row.clean_gold_recall_guarded:.4f}",
                    f"{row.entity_exposure_before:.4f} -> {row.entity_exposure_guarded:.4f}",
                    f"{row.entity_trusted_gold_recall_guarded:.4f}",
                    str(row.entity_corrupted_gold_docs),
                    f"{row.bridge_exposure_before:.4f} -> {row.bridge_exposure_guarded:.4f}",
                    f"{row.bridge_trusted_gold_recall_guarded:.4f}",
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicGuard Multi-Dataset Summary",
            "",
            "## Output Files",
            "",
            f"- JSONL rows: `{jsonl_path}`",
            f"- CSV rows: `{csv_path}`",
            "",
            "## Best Threshold Rows",
            "",
            *table_lines,
            "",
            "## Notes",
            "",
            "Each row reports the best threshold selected by minimizing guarded Entity Swap and Bridge Injection exposure, "
            "then preferring higher clean recall. `trusted recall` excludes changed/corrupted gold support documents.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LogicGuard experiments across multiple datasets.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/multidataset_full_500.yaml"),
        help="Path to the multi-dataset YAML config.",
    )
    parser.add_argument(
        "--datasets",
        nargs="*",
        default=None,
        help="Optional subset of datasets from the config.",
    )
    parser.add_argument("--skip-prepare", action="store_true", help="Reuse existing normalized data artifacts.")
    parser.add_argument("--skip-baseline", action="store_true", help="Reuse existing clean baseline artifacts.")
    parser.add_argument("--skip-attacks", action="store_true", help="Reuse existing attack artifacts.")
    parser.add_argument("--skip-scan", action="store_true", help="Skip LogicGuard threshold scans.")
    args = parser.parse_args()

    run_multidataset_pipeline(
        MultiDatasetExperimentConfig.from_yaml(args.config),
        datasets=args.datasets,
        prepare=not args.skip_prepare,
        baseline=not args.skip_baseline,
        attacks=not args.skip_attacks,
        scan=not args.skip_scan,
    )


if __name__ == "__main__":
    main()

