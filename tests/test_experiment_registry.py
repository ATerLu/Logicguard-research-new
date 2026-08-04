import csv
import hashlib
import json
from pathlib import Path

import pytest

from logicguard.reports.experiment_registry import (
    ExperimentRegistryConfig,
    validate_registry,
    write_registry_artifacts,
)


def test_registry_config_resolves_project_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_dir = project_root / "configs"
    config_dir.mkdir(parents=True)
    input_path = project_root / "data" / "sample.jsonl"
    output_path = project_root / "outputs" / "metrics.jsonl"
    report_path = project_root / "outputs" / "reports" / "report.md"
    for path in (input_path, output_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8")
    config_path = config_dir / "registry.yaml"
    config_path.write_text(
        _registry_yaml(input_path="data/sample.jsonl"),
        encoding="utf-8",
    )

    config = ExperimentRegistryConfig.from_yaml(config_path)

    assert config.project_root == project_root.resolve()
    assert config.experiments[0].input_paths == [input_path.resolve()]
    assert config.csv_path == project_root / "docs" / "registry.csv"


def test_validate_registry_rejects_duplicate_experiment_ids(tmp_path: Path) -> None:
    config_path = _write_registry_fixture(tmp_path, duplicate=True)
    config = ExperimentRegistryConfig.from_yaml(config_path)

    with pytest.raises(ValueError, match="重复实验编号"):
        validate_registry(config)


def test_strict_registry_freeze_rejects_missing_artifacts(tmp_path: Path) -> None:
    config_path = _write_registry_fixture(tmp_path, input_path="data/missing.jsonl")
    config = ExperimentRegistryConfig.from_yaml(config_path)

    with pytest.raises(FileNotFoundError, match="缺失冻结证据"):
        write_registry_artifacts(config, strict=True)


def test_write_registry_artifacts_outputs_csv_manifest_and_chinese_report(
    tmp_path: Path,
) -> None:
    config_path = _write_registry_fixture(tmp_path)
    config = ExperimentRegistryConfig.from_yaml(config_path)
    input_path = config.experiments[0].input_paths[0]

    summary = write_registry_artifacts(config, strict=True)

    with config.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    report = config.report_path.read_text(encoding="utf-8")
    input_artifact = next(
        item for item in manifest["artifacts"] if item["path"] == "data/sample.jsonl"
    )

    assert summary.experiment_count == 1
    assert summary.missing_artifact_count == 0
    assert rows[0]["experiment_id"] == "LG-T01"
    assert rows[0]["query_count"] == "10"
    assert manifest["registry_version"] == "1.0"
    assert (
        input_artifact["sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    )
    assert "实验冻结与可复现性报告" in report
    assert "缺失证据：`0`" in report


def _write_registry_fixture(
    tmp_path: Path,
    *,
    duplicate: bool = False,
    input_path: str = "data/sample.jsonl",
) -> Path:
    project_root = tmp_path / "project"
    config_dir = project_root / "configs"
    config_dir.mkdir(parents=True)
    for relative_path in (
        "data/sample.jsonl",
        "outputs/metrics.jsonl",
        "outputs/reports/report.md",
    ):
        path = project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path, encoding="utf-8")
    experiments = _experiment_yaml(input_path=input_path)
    if duplicate:
        experiments += "\n" + _experiment_yaml(input_path=input_path)
    config_path = config_dir / "registry.yaml"
    config_path.write_text(_registry_yaml(experiments=experiments), encoding="utf-8")
    return config_path


def _registry_yaml(
    *, experiments: str | None = None, input_path: str = "data/sample.jsonl"
) -> str:
    experiment_rows = experiments or _experiment_yaml(input_path=input_path)
    return "\n".join(
        [
            'registry_version: "1.0"',
            'frozen_at: "2026-06-20"',
            "outputs:",
            "  csv_path: docs/registry.csv",
            "  manifest_path: outputs/registry/manifest.json",
            "  report_path: outputs/reports/freeze.md",
            "experiments:",
            experiment_rows.rstrip(),
            "",
        ]
    )


def _experiment_yaml(*, input_path: str) -> str:
    return "\n".join(
        [
            "  - experiment_id: LG-T01",
            "    main_stage: T",
            "    legacy_stage: test",
            "    name: 测试实验",
            "    category: simulation",
            "    status: completed",
            "    datasets: [demo]",
            "    query_count: 10",
            "    retriever: BM25",
            "    attack: demo",
            "    defense: LogicGuard",
            "    models: [none]",
            "    metric_version: v1",
            "    cost_class: local",
            "    config_paths: []",
            f"    input_paths: [{input_path}]",
            "    output_paths: [outputs/metrics.jsonl]",
            "    report_paths: [outputs/reports/report.md]",
            "    key_result: 测试结果",
            "    limitations: 测试限制",
            "    reproduction_command: python -m demo",
        ]
    )
