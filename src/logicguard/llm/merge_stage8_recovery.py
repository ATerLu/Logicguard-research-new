"""Merge stage-8 non-oracle recovered answers with stage-6 baselines."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.llm.run_stage6_summary import (
    Stage6DatasetConfig,
    Stage6SummaryConfig,
    write_stage6_report,
)


@dataclass(frozen=True, slots=True)
class Stage8MergeDatasetConfig:
    """One dataset merge source for stage-8 answer-level reporting."""

    name: str
    baseline_judged_path: Path
    recovered_judged_path: Path
    merged_output_path: Path


@dataclass(frozen=True, slots=True)
class Stage8MergeConfig:
    """Configuration for replacing oracle recovered rows with stage-8 rows."""

    datasets: list[Stage8MergeDatasetConfig]
    combined_jsonl_path: Path
    report_path: Path
    report_title: str
    experiment_description: str

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage8MergeConfig":
        """Load YAML configuration with project-relative paths."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            datasets=[
                Stage8MergeDatasetConfig(
                    name=str(item["name"]),
                    baseline_judged_path=resolve_project_path(item["baseline_judged_path"]),
                    recovered_judged_path=resolve_project_path(item["recovered_judged_path"]),
                    merged_output_path=resolve_project_path(item["merged_output_path"]),
                )
                for item in payload["datasets"]
            ],
            combined_jsonl_path=resolve_project_path(payload["combined_jsonl_path"]),
            report_path=resolve_project_path(payload["report_path"]),
            report_title=str(payload["report_title"]),
            experiment_description=str(payload["experiment_description"]),
        )


def merge_stage8_recovery_outputs(config: Stage8MergeConfig) -> list[dict[str, object]]:
    """Write per-dataset and combined judged rows for stage-8 reporting."""

    combined_rows: list[dict[str, object]] = []
    for dataset in config.datasets:
        baseline_rows = _load_jsonl(dataset.baseline_judged_path)
        recovered_rows = _load_jsonl(dataset.recovered_judged_path)
        merged_rows = [
            dict(row, dataset=dataset.name)
            for row in baseline_rows
            if str(row.get("context_variant")) != "recovered"
        ]
        merged_rows.extend(dict(row, dataset=dataset.name) for row in recovered_rows)
        _write_jsonl(dataset.merged_output_path, merged_rows)
        combined_rows.extend(merged_rows)

    _write_jsonl(config.combined_jsonl_path, combined_rows)
    report_config = Stage6SummaryConfig(
        datasets=[
            Stage6DatasetConfig(name=dataset.name, judged_results_path=dataset.merged_output_path)
            for dataset in config.datasets
        ],
        combined_jsonl_path=config.combined_jsonl_path,
        report_path=config.report_path,
        report_title=config.report_title,
        experiment_description=config.experiment_description,
    )
    write_stage6_report(report_config, combined_rows)
    print(f"stage8_merged_rows={len(combined_rows)}, datasets={len(config.datasets)}")
    return combined_rows


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge stage-8 non-oracle recovered answer results.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_stage8_answer_merge.yaml"),
        help="Path to the stage-8 answer merge YAML config.",
    )
    args = parser.parse_args()
    merge_stage8_recovery_outputs(Stage8MergeConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
