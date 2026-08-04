"""Build and audit the frozen LogicGuard experiment registry.

Stage19 does not rerun experiments. It binds each published conclusion to a
stable experiment identifier and to the exact configuration, input, output,
and report files that support it. SHA-256 hashes make later accidental changes
visible without copying the potentially large experiment artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import yaml


ALLOWED_CATEGORIES = {
    "infrastructure",
    "simulation",
    "logicpoison_official",
    "microsoft_graphrag_official",
}
ALLOWED_STATUSES = {"completed", "diagnostic", "partial"}
ALLOWED_COST_CLASSES = {"local", "api-low", "api-high"}
PATH_ROLES = ("config", "input", "output", "report")


@dataclass(frozen=True, slots=True)
class ExperimentRegistryEntry:
    """One frozen experiment and the evidence needed to audit it."""

    experiment_id: str
    main_stage: str
    legacy_stage: str
    name: str
    category: str
    status: str
    datasets: list[str]
    query_count: int
    retriever: str
    attack: str
    defense: str
    models: list[str]
    metric_version: str
    cost_class: str
    config_paths: list[Path]
    input_paths: list[Path]
    output_paths: list[Path]
    report_paths: list[Path]
    key_result: str
    limitations: str
    reproduction_command: str


@dataclass(frozen=True, slots=True)
class ExperimentRegistryConfig:
    """Registry metadata, output locations, and all frozen experiments."""

    registry_version: str
    frozen_at: str
    project_root: Path
    source_path: Path
    csv_path: Path
    manifest_path: Path
    report_path: Path
    experiments: list[ExperimentRegistryEntry]

    @classmethod
    def from_yaml(cls, path: Path) -> "ExperimentRegistryConfig":
        """Load a registry whose relative paths are anchored at the project root."""

        source_path = path.resolve()
        project_root = source_path.parents[1]
        with source_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        if not isinstance(payload, dict):
            raise ValueError("实验注册表 YAML 顶层必须是对象。")

        outputs = payload.get("outputs")
        raw_experiments = payload.get("experiments")
        if not isinstance(outputs, dict) or not isinstance(raw_experiments, list):
            raise ValueError("实验注册表必须包含 outputs 对象和 experiments 列表。")

        def resolve(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        def resolve_many(raw_paths: object) -> list[Path]:
            if raw_paths is None:
                return []
            if not isinstance(raw_paths, list):
                raise ValueError("config/input/output/report_paths 必须是列表。")
            return [resolve(str(item)) for item in raw_paths]

        experiments: list[ExperimentRegistryEntry] = []
        for raw in raw_experiments:
            if not isinstance(raw, dict):
                raise ValueError("experiments 中每一项都必须是对象。")
            experiments.append(
                ExperimentRegistryEntry(
                    experiment_id=str(raw["experiment_id"]),
                    main_stage=str(raw["main_stage"]),
                    legacy_stage=str(raw.get("legacy_stage", "")),
                    name=str(raw["name"]),
                    category=str(raw["category"]),
                    status=str(raw["status"]),
                    datasets=[str(item) for item in raw.get("datasets", [])],
                    query_count=int(raw["query_count"]),
                    retriever=str(raw["retriever"]),
                    attack=str(raw["attack"]),
                    defense=str(raw["defense"]),
                    models=[str(item) for item in raw.get("models", [])],
                    metric_version=str(raw["metric_version"]),
                    cost_class=str(raw["cost_class"]),
                    config_paths=resolve_many(raw.get("config_paths")),
                    input_paths=resolve_many(raw.get("input_paths")),
                    output_paths=resolve_many(raw.get("output_paths")),
                    report_paths=resolve_many(raw.get("report_paths")),
                    key_result=str(raw["key_result"]),
                    limitations=str(raw["limitations"]),
                    reproduction_command=str(raw["reproduction_command"]),
                )
            )

        return cls(
            registry_version=str(payload["registry_version"]),
            frozen_at=str(payload["frozen_at"]),
            project_root=project_root,
            source_path=source_path,
            csv_path=resolve(str(outputs["csv_path"])),
            manifest_path=resolve(str(outputs["manifest_path"])),
            report_path=resolve(str(outputs["report_path"])),
            experiments=experiments,
        )


@dataclass(frozen=True, slots=True)
class FrozenArtifact:
    """A hashed file connected to one experiment and one evidence role."""

    experiment_id: str
    role: str
    path: str
    exists: bool
    size_bytes: int | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class RegistryWriteSummary:
    """Compact result returned after writing registry artifacts."""

    experiment_count: int
    artifact_count: int
    missing_artifact_count: int
    category_counts: dict[str, int]


def validate_registry(config: ExperimentRegistryConfig) -> None:
    """Reject ambiguous identifiers and invalid controlled vocabulary values."""

    identifiers = [entry.experiment_id for entry in config.experiments]
    duplicates = sorted(
        identifier for identifier, count in Counter(identifiers).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"发现重复实验编号：{', '.join(duplicates)}")
    if not identifiers:
        raise ValueError("实验注册表不能为空。")

    for entry in config.experiments:
        if entry.category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"{entry.experiment_id} 使用了未知 category：{entry.category}"
            )
        if entry.status not in ALLOWED_STATUSES:
            raise ValueError(f"{entry.experiment_id} 使用了未知 status：{entry.status}")
        if entry.cost_class not in ALLOWED_COST_CLASSES:
            raise ValueError(
                f"{entry.experiment_id} 使用了未知 cost_class：{entry.cost_class}"
            )
        if entry.query_count < 0:
            raise ValueError(f"{entry.experiment_id} 的 query_count 不能为负数。")
        if not entry.metric_version.strip() or not entry.reproduction_command.strip():
            raise ValueError(f"{entry.experiment_id} 缺少指标版本或复现命令。")


def collect_frozen_artifacts(config: ExperimentRegistryConfig) -> list[FrozenArtifact]:
    """Hash every declared evidence file, preserving its experiment-level role."""

    artifacts = [
        _freeze_artifact(
            experiment_id="REGISTRY",
            role="config",
            path=config.source_path,
            project_root=config.project_root,
        )
    ]
    for entry in config.experiments:
        role_paths = {
            "config": entry.config_paths,
            "input": entry.input_paths,
            "output": entry.output_paths,
            "report": entry.report_paths,
        }
        for role in PATH_ROLES:
            for path in role_paths[role]:
                artifacts.append(
                    _freeze_artifact(
                        experiment_id=entry.experiment_id,
                        role=role,
                        path=path,
                        project_root=config.project_root,
                    )
                )
    return artifacts


def write_registry_artifacts(
    config: ExperimentRegistryConfig,
    *,
    strict: bool = True,
) -> RegistryWriteSummary:
    """Validate, hash, and write CSV, JSON manifest, and Chinese audit report."""

    validate_registry(config)
    artifacts = collect_frozen_artifacts(config)
    missing = [artifact for artifact in artifacts if not artifact.exists]
    if strict and missing:
        missing_paths = ", ".join(artifact.path for artifact in missing[:5])
        raise FileNotFoundError(f"存在 {len(missing)} 个缺失冻结证据：{missing_paths}")

    category_counts = dict(
        sorted(Counter(entry.category for entry in config.experiments).items())
    )
    summary = RegistryWriteSummary(
        experiment_count=len(config.experiments),
        artifact_count=len(artifacts),
        missing_artifact_count=len(missing),
        category_counts=category_counts,
    )
    _write_registry_csv(config)
    _write_manifest(config, artifacts, summary)
    _write_report(config, artifacts, summary)
    return summary


def _freeze_artifact(
    *, experiment_id: str, role: str, path: Path, project_root: Path
) -> FrozenArtifact:
    """Create one manifest row without mutating the source artifact."""

    display_path = _display_path(path, project_root)
    if not path.is_file():
        return FrozenArtifact(experiment_id, role, display_path, False, None, None)
    return FrozenArtifact(
        experiment_id=experiment_id,
        role=role,
        path=display_path,
        exists=True,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
    )


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash large corpora incrementally so Stage19 stays memory bounded."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _write_registry_csv(config: ExperimentRegistryConfig) -> None:
    config.csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "experiment_id",
        "main_stage",
        "legacy_stage",
        "name",
        "category",
        "status",
        "datasets",
        "query_count",
        "retriever",
        "attack",
        "defense",
        "models",
        "metric_version",
        "cost_class",
        "config_paths",
        "input_paths",
        "output_paths",
        "report_paths",
        "key_result",
        "limitations",
        "reproduction_command",
    ]
    with config.csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for entry in config.experiments:
            writer.writerow(_entry_to_csv_row(entry, config.project_root))


def _entry_to_csv_row(
    entry: ExperimentRegistryEntry, project_root: Path
) -> dict[str, object]:
    row: dict[str, object] = asdict(entry)
    row["datasets"] = ";".join(entry.datasets)
    row["models"] = ";".join(entry.models)
    for key in ("config_paths", "input_paths", "output_paths", "report_paths"):
        row[key] = ";".join(
            _display_path(path, project_root) for path in getattr(entry, key)
        )
    return row


def _write_manifest(
    config: ExperimentRegistryConfig,
    artifacts: list[FrozenArtifact],
    summary: RegistryWriteSummary,
) -> None:
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "registry_version": config.registry_version,
        "frozen_at": config.frozen_at,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "experiment_count": summary.experiment_count,
        "artifact_count": summary.artifact_count,
        "missing_artifact_count": summary.missing_artifact_count,
        "category_counts": summary.category_counts,
        "artifacts": [asdict(artifact) for artifact in artifacts],
    }
    config.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_report(
    config: ExperimentRegistryConfig,
    artifacts: list[FrozenArtifact],
    summary: RegistryWriteSummary,
) -> None:
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    category_labels = {
        "infrastructure": "数据与基础设施",
        "simulation": "自建模拟攻击与轻量基线",
        "logicpoison_official": "LogicPoison 官方污染语料",
        "microsoft_graphrag_official": "Microsoft GraphRAG 官方查询链",
    }
    experiment_table = [
        "| 实验编号 | 类别 | 状态 | 数据集 | Query 数 | 指标版本 | 成本级别 |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for entry in config.experiments:
        experiment_table.append(
            f"| {entry.experiment_id} | {category_labels[entry.category]} | {entry.status} | "
            f"{', '.join(entry.datasets)} | {entry.query_count} | {entry.metric_version} | {entry.cost_class} |"
        )
    missing = [artifact for artifact in artifacts if not artifact.exists]
    missing_lines = [
        f"- `{artifact.experiment_id}` / `{artifact.role}`：`{artifact.path}`"
        for artifact in missing
    ]
    if not missing_lines:
        missing_lines = ["- 无。所有登记证据均存在并已计算 SHA-256。"]

    content = "\n".join(
        [
            "# Stage19 实验冻结与可复现性报告",
            "",
            "## 冻结目的",
            "",
            "本阶段不重跑高成本实验，也不修改历史结果；只建立稳定编号、证据路径与文件哈希，"
            "使论文结论可以追溯到明确的配置、输入、输出和报告。",
            "",
            "## 冻结摘要",
            "",
            f"- 注册表版本：`{config.registry_version}`",
            f"- 冻结日期：`{config.frozen_at}`",
            f"- 实验记录：`{summary.experiment_count}`",
            f"- 冻结证据文件：`{summary.artifact_count}`",
            f"- 缺失证据：`{summary.missing_artifact_count}`",
            f"- 注册表 CSV：`{_display_path(config.csv_path, config.project_root)}`",
            f"- SHA-256 清单：`{_display_path(config.manifest_path, config.project_root)}`",
            "",
            "## 指标版本说明",
            "",
            "- `retrieval-v1`：hit、gold/trusted recall、changed/poisoned exposure 等检索层指标。",
            "- `answer-judge-v1`：correct、partial、Utility、UNKNOWN 和错误非拒答率。",
            "- `official-context-v1`：official sources 的 support recall、changed exposure 与实体命中诊断。",
            "- `integrity-v1`：数据条数、字段完整性、clean/poisoned 差异和来源追踪。",
            "",
            "## 实验登记",
            "",
            *experiment_table,
            "",
            "## 缺失证据检查",
            "",
            *missing_lines,
            "",
            "## 复现边界",
            "",
            "- `local` 实验可以在项目 Python 环境中复现，不调用外部 LLM。",
            "- `api-low` 和 `api-high` 会调用模型 API 或执行 Microsoft GraphRAG 索引，需单独确认成本。",
            "- 历史文件不覆盖；新实验应新增唯一编号和输出目录。",
            "- Stage18 是召回诊断证据，不等同于完成的端到端防御效果。",
            "",
        ]
    )
    config.report_path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成并审计 LogicGuard Stage19 实验注册表。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/stage19_experiment_registry.yaml"),
        help="实验注册表 YAML 路径。",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="允许历史证据缺失并将其写入报告；正式冻结不应使用。",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = ExperimentRegistryConfig.from_yaml(args.config)
    summary = write_registry_artifacts(config, strict=not args.allow_missing)
    print(
        "registry_written "
        f"experiments={summary.experiment_count} "
        f"artifacts={summary.artifact_count} "
        f"missing={summary.missing_artifact_count}"
    )


if __name__ == "__main__":
    main()
