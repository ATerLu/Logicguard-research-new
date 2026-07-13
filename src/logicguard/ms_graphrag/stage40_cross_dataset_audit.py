"""Stage40 cross-dataset readiness audit for official GraphRAG experiments."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import yaml

REQUIRED_WORKSPACE_FILES = (
    "documents.parquet",
    "text_units.parquet",
    "entities.parquet",
    "relationships.parquet",
    "communities.parquet",
    "stats.json",
)

ASSET_LABELS = {
    "processed_samples": "processed samples",
    "clean_corpus": "clean corpus",
    "poisoned_corpus": "poisoned corpus",
    "query_integrity": "LogicPoison query integrity",
    "clean_workspace": "clean GraphRAG workspace output",
    "poisoned_workspace": "poisoned GraphRAG workspace output",
    "baseline_context": "official local baseline context",
    "broad_context": "official local broad context",
    "source_context": "query-guard source context",
    "risk_non_oracle_context": "risk non-oracle recovered context",
    "source_enrichment_context": "source enrichment context",
    "chain_targeted_context": "second-hop targeted context",
    "answer_judge_summary": "answer judge summary",
}


@dataclass(frozen=True, slots=True)
class Stage40DatasetSpec:
    """All paths Stage40 needs to audit one dataset."""

    dataset: str
    sample_path: Path
    clean_corpus_path: Path
    poisoned_corpus_path: Path
    query_integrity_path: Path
    clean_workspace_output_dir: Path
    poisoned_workspace_output_dir: Path
    baseline_context_path: Path
    broad_context_path: Path
    source_context_path: Path
    risk_non_oracle_context_path: Path
    source_enrichment_context_path: Path
    chain_targeted_context_path: Path
    answer_judge_summary_path: Path

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, object],
        project_root: Path,
    ) -> "Stage40DatasetSpec":
        """Load one dataset spec from project-relative YAML."""

        def resolve(key: str) -> Path:
            raw = payload[key]
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve("sample_path"),
            clean_corpus_path=resolve("clean_corpus_path"),
            poisoned_corpus_path=resolve("poisoned_corpus_path"),
            query_integrity_path=resolve("query_integrity_path"),
            clean_workspace_output_dir=resolve("clean_workspace_output_dir"),
            poisoned_workspace_output_dir=resolve("poisoned_workspace_output_dir"),
            baseline_context_path=resolve("baseline_context_path"),
            broad_context_path=resolve("broad_context_path"),
            source_context_path=resolve("source_context_path"),
            risk_non_oracle_context_path=resolve("risk_non_oracle_context_path"),
            source_enrichment_context_path=resolve("source_enrichment_context_path"),
            chain_targeted_context_path=resolve("chain_targeted_context_path"),
            answer_judge_summary_path=resolve("answer_judge_summary_path"),
        )


@dataclass(frozen=True, slots=True)
class Stage40CrossDatasetAuditConfig:
    """Stage40 audit settings and output paths."""

    datasets: list[Stage40DatasetSpec]
    asset_rows_output_path: Path
    summary_output_path: Path
    gap_actions_output_path: Path
    report_path: Path
    stage_label: str = "Stage40"
    required_workspace_files: tuple[str, ...] = REQUIRED_WORKSPACE_FILES

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage40CrossDatasetAuditConfig":
        """Load a project-relative Stage40 YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        datasets = [
            Stage40DatasetSpec.from_mapping(dict(item), project_root)
            for item in payload["datasets"]
        ]
        required_files = tuple(
            str(item)
            for item in payload.get(
                "required_workspace_files",
                REQUIRED_WORKSPACE_FILES,
            )
        )
        return cls(
            datasets=datasets,
            asset_rows_output_path=resolve(payload["asset_rows_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            gap_actions_output_path=resolve(payload["gap_actions_output_path"]),
            report_path=resolve(payload["report_path"]),
            stage_label=str(payload.get("stage_label", "Stage40")),
            required_workspace_files=required_files,
        )


@dataclass(frozen=True, slots=True)
class Stage40AssetRow:
    """One audited asset row."""

    dataset: str
    asset_kind: str
    path: str
    exists: bool
    ready: bool
    status: str
    blocking_for: str
    row_count: int | None
    file_count: int | None
    missing_required_files: list[str]
    note: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage40SummaryRow:
    """Dataset-level Stage40 readiness summary."""

    dataset: str
    processed_sample_rows: int
    query_integrity_rows: int
    processed_samples_ready: bool
    clean_corpus_ready: bool
    poisoned_corpus_ready: bool
    attack_integrity_ready: bool
    clean_workspace_ready: bool
    poisoned_workspace_ready: bool
    baseline_context_ready: bool
    broad_context_ready: bool
    source_context_ready: bool
    risk_non_oracle_context_ready: bool
    source_enrichment_context_ready: bool
    chain_targeted_context_ready: bool
    answer_judge_summary_ready: bool
    can_prepare_workspaces: bool
    can_run_official_query_export: bool
    can_run_source_recovery: bool
    can_run_source_enrichment: bool
    can_run_chain_diagnostics: bool
    can_run_answer_level_verification: bool
    missing_blockers: list[str]
    next_action: str

    def to_csv_row(self) -> dict[str, str]:
        return _stringify_row(asdict(self))


@dataclass(frozen=True, slots=True)
class Stage40GapAction:
    """One recommended action to unblock cross-dataset validation."""

    dataset: str
    action_order: int
    action: str
    reason: str
    commands: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def run_from_config(
    config: Stage40CrossDatasetAuditConfig,
) -> tuple[list[Stage40AssetRow], list[Stage40SummaryRow], list[Stage40GapAction]]:
    """Run Stage40 audit and write all artifacts."""

    asset_rows = build_stage40_asset_rows(
        config.datasets,
        required_workspace_files=config.required_workspace_files,
    )
    summaries = summarize_stage40_assets(asset_rows)
    gap_actions = build_stage40_gap_actions(summaries, config.datasets)
    write_stage40_outputs(
        config=config,
        asset_rows=asset_rows,
        summaries=summaries,
        gap_actions=gap_actions,
    )
    return asset_rows, summaries, gap_actions


def build_stage40_asset_rows(
    specs: list[Stage40DatasetSpec],
    *,
    required_workspace_files: tuple[str, ...] = REQUIRED_WORKSPACE_FILES,
) -> list[Stage40AssetRow]:
    """Audit all configured paths without calling GraphRAG or an LLM."""

    rows: list[Stage40AssetRow] = []
    for spec in specs:
        rows.extend(
            [
                _file_asset(
                    spec.dataset,
                    "processed_samples",
                    spec.sample_path,
                    "dataset_setup;workspace_preparation",
                ),
                _file_asset(
                    spec.dataset,
                    "clean_corpus",
                    spec.clean_corpus_path,
                    "workspace_preparation",
                ),
                _file_asset(
                    spec.dataset,
                    "poisoned_corpus",
                    spec.poisoned_corpus_path,
                    "workspace_preparation",
                ),
                _file_asset(
                    spec.dataset,
                    "query_integrity",
                    spec.query_integrity_path,
                    "query_guard;source_recovery;answer_verification",
                ),
                _workspace_asset(
                    spec.dataset,
                    "clean_workspace",
                    spec.clean_workspace_output_dir,
                    "candidate_pool;source_recovery;chain_diagnostics",
                    required_workspace_files,
                ),
                _workspace_asset(
                    spec.dataset,
                    "poisoned_workspace",
                    spec.poisoned_workspace_output_dir,
                    "official_local_context;query_guard",
                    required_workspace_files,
                ),
                _file_asset(
                    spec.dataset,
                    "baseline_context",
                    spec.baseline_context_path,
                    "query_guard_seed_planning",
                ),
                _file_asset(
                    spec.dataset,
                    "broad_context",
                    spec.broad_context_path,
                    "query_guard_evaluation",
                ),
                _file_asset(
                    spec.dataset,
                    "source_context",
                    spec.source_context_path,
                    "risk_non_oracle_recovery",
                ),
                _file_asset(
                    spec.dataset,
                    "risk_non_oracle_context",
                    spec.risk_non_oracle_context_path,
                    "source_enrichment",
                ),
                _file_asset(
                    spec.dataset,
                    "source_enrichment_context",
                    spec.source_enrichment_context_path,
                    "chain_completeness",
                ),
                _file_asset(
                    spec.dataset,
                    "chain_targeted_context",
                    spec.chain_targeted_context_path,
                    "answer_level_verification",
                ),
                _file_asset(
                    spec.dataset,
                    "answer_judge_summary",
                    spec.answer_judge_summary_path,
                    "answer_level_comparison",
                ),
            ]
        )
    return rows


def summarize_stage40_assets(rows: list[Stage40AssetRow]) -> list[Stage40SummaryRow]:
    """Aggregate asset rows into dataset-level readiness decisions."""

    grouped: dict[str, dict[str, Stage40AssetRow]] = {}
    for row in rows:
        grouped.setdefault(row.dataset, {})[row.asset_kind] = row

    summaries: list[Stage40SummaryRow] = []
    for dataset, by_kind in grouped.items():
        processed = _ready(by_kind, "processed_samples")
        clean_corpus = _ready(by_kind, "clean_corpus")
        poisoned_corpus = _ready(by_kind, "poisoned_corpus")
        query_integrity = _ready(by_kind, "query_integrity")
        clean_workspace = _ready(by_kind, "clean_workspace")
        poisoned_workspace = _ready(by_kind, "poisoned_workspace")
        baseline_context = _ready(by_kind, "baseline_context")
        broad_context = _ready(by_kind, "broad_context")
        source_context = _ready(by_kind, "source_context")
        risk_context = _ready(by_kind, "risk_non_oracle_context")
        enrichment_context = _ready(by_kind, "source_enrichment_context")
        chain_context = _ready(by_kind, "chain_targeted_context")
        judge_summary = _ready(by_kind, "answer_judge_summary")

        can_prepare = processed and clean_corpus and poisoned_corpus
        can_query_export = (
            processed
            and query_integrity
            and poisoned_workspace
            and baseline_context
            and broad_context
        )
        can_source_recovery = (
            processed and query_integrity and clean_workspace and source_context
        )
        can_enrich = processed and clean_workspace and risk_context
        can_chain = processed and clean_workspace and enrichment_context
        can_answer = processed and query_integrity and chain_context
        missing = _missing_blockers(by_kind)
        summaries.append(
            Stage40SummaryRow(
                dataset=dataset,
                processed_sample_rows=_row_count(by_kind, "processed_samples"),
                query_integrity_rows=_row_count(by_kind, "query_integrity"),
                processed_samples_ready=processed,
                clean_corpus_ready=clean_corpus,
                poisoned_corpus_ready=poisoned_corpus,
                attack_integrity_ready=query_integrity,
                clean_workspace_ready=clean_workspace,
                poisoned_workspace_ready=poisoned_workspace,
                baseline_context_ready=baseline_context,
                broad_context_ready=broad_context,
                source_context_ready=source_context,
                risk_non_oracle_context_ready=risk_context,
                source_enrichment_context_ready=enrichment_context,
                chain_targeted_context_ready=chain_context,
                answer_judge_summary_ready=judge_summary,
                can_prepare_workspaces=can_prepare,
                can_run_official_query_export=can_query_export,
                can_run_source_recovery=can_source_recovery,
                can_run_source_enrichment=can_enrich,
                can_run_chain_diagnostics=can_chain,
                can_run_answer_level_verification=can_answer,
                missing_blockers=missing,
                next_action=_next_action(
                    processed=processed,
                    clean_corpus=clean_corpus,
                    poisoned_corpus=poisoned_corpus,
                    query_integrity=query_integrity,
                    clean_workspace=clean_workspace,
                    poisoned_workspace=poisoned_workspace,
                    baseline_context=baseline_context,
                    broad_context=broad_context,
                    source_context=source_context,
                    risk_context=risk_context,
                    enrichment_context=enrichment_context,
                    chain_context=chain_context,
                    judge_summary=judge_summary,
                ),
            )
        )
    return sorted(summaries, key=lambda row: row.dataset)


def build_stage40_gap_actions(
    summaries: list[Stage40SummaryRow],
    specs: list[Stage40DatasetSpec],
) -> list[Stage40GapAction]:
    """Turn each dataset's next blocker into reproducible follow-up commands."""

    spec_by_dataset = {spec.dataset: spec for spec in specs}
    actions: list[Stage40GapAction] = []
    for summary in summaries:
        if summary.next_action == "ready_for_attribute_sentence_completeness_or_adaptive_attack":
            continue
        spec = spec_by_dataset[summary.dataset]
        action = summary.next_action
        actions.append(
            Stage40GapAction(
                dataset=summary.dataset,
                action_order=len(actions) + 1,
                action=action,
                reason=_action_reason(action),
                commands=_action_commands(action, spec),
            )
        )
    return actions


def write_stage40_outputs(
    *,
    config: Stage40CrossDatasetAuditConfig,
    asset_rows: list[Stage40AssetRow],
    summaries: list[Stage40SummaryRow],
    gap_actions: list[Stage40GapAction],
) -> None:
    """Write Stage40 JSONL/CSV/report artifacts."""

    _write_jsonl(
        config.asset_rows_output_path,
        [row.to_json_dict() for row in asset_rows],
    )
    _write_csv(config.summary_output_path, [row.to_csv_row() for row in summaries])
    _write_jsonl(
        config.gap_actions_output_path,
        [row.to_json_dict() for row in gap_actions],
    )
    _write_stage40_report(
        config=config,
        summaries=summaries,
        gap_actions=gap_actions,
    )


def _file_asset(
    dataset: str,
    asset_kind: str,
    path: Path,
    blocking_for: str,
) -> Stage40AssetRow:
    exists = path.is_file()
    row_count = _count_rows(path) if exists else None
    ready = exists and (row_count is None or row_count > 0)
    if ready:
        status = "ready"
        note = "file exists and is non-empty"
    elif exists:
        status = "empty"
        note = "file exists but has no data rows"
    else:
        status = "missing"
        note = "file is missing"
    return Stage40AssetRow(
        dataset=dataset,
        asset_kind=asset_kind,
        path=path.as_posix(),
        exists=exists,
        ready=ready,
        status=status,
        blocking_for=blocking_for,
        row_count=row_count,
        file_count=None,
        missing_required_files=[],
        note=note,
    )


def _workspace_asset(
    dataset: str,
    asset_kind: str,
    output_dir: Path,
    blocking_for: str,
    required_files: tuple[str, ...],
) -> Stage40AssetRow:
    exists = output_dir.is_dir()
    file_count = len([path for path in output_dir.iterdir() if path.is_file()]) if exists else 0
    missing = _missing_workspace_files(output_dir, required_files) if exists else list(required_files)
    ready = exists and not missing
    status = "ready" if ready else "incomplete" if exists else "missing"
    note = (
        "workspace output contains required GraphRAG files"
        if ready
        else "missing required GraphRAG output files"
    )
    return Stage40AssetRow(
        dataset=dataset,
        asset_kind=asset_kind,
        path=output_dir.as_posix(),
        exists=exists,
        ready=ready,
        status=status,
        blocking_for=blocking_for,
        row_count=None,
        file_count=file_count,
        missing_required_files=missing,
        note=note,
    )


def _missing_workspace_files(output_dir: Path, required_files: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for filename in required_files:
        path = output_dir / filename
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(filename)
    return missing


def _count_rows(path: Path) -> int | None:
    suffix = path.suffix.casefold()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    if suffix in {".json", ".yaml", ".yml"}:
        return None
    return None


def _ready(by_kind: dict[str, Stage40AssetRow], kind: str) -> bool:
    row = by_kind.get(kind)
    return bool(row and row.ready)


def _row_count(by_kind: dict[str, Stage40AssetRow], kind: str) -> int:
    row = by_kind.get(kind)
    return int(row.row_count or 0) if row else 0


def _missing_blockers(by_kind: dict[str, Stage40AssetRow]) -> list[str]:
    return [
        ASSET_LABELS.get(kind, kind)
        for kind, row in by_kind.items()
        if not row.ready
    ]


def _next_action(
    *,
    processed: bool,
    clean_corpus: bool,
    poisoned_corpus: bool,
    query_integrity: bool,
    clean_workspace: bool,
    poisoned_workspace: bool,
    baseline_context: bool,
    broad_context: bool,
    source_context: bool,
    risk_context: bool,
    enrichment_context: bool,
    chain_context: bool,
    judge_summary: bool,
) -> str:
    if not processed:
        return "build_processed_samples"
    if not clean_corpus or not poisoned_corpus:
        return "restore_logicpoison_official_corpora"
    if not query_integrity:
        return "run_logicpoison_query_integrity_export"
    if not clean_workspace or not poisoned_workspace:
        return "prepare_and_index_official_graphrag_workspaces"
    if not baseline_context or not broad_context:
        return "export_official_local_baseline_contexts"
    if not source_context:
        return "run_query_guard_context_export"
    if not risk_context:
        return "run_stage28_risk_non_oracle_recovery"
    if not enrichment_context:
        return "run_stage35_source_enrichment"
    if not chain_context:
        return "run_stage38_chain_completeness"
    if not judge_summary:
        return "run_answer_level_and_judge_validation"
    return "ready_for_attribute_sentence_completeness_or_adaptive_attack"


def _action_reason(action: str) -> str:
    reasons = {
        "build_processed_samples": "缺少 normalized query/sample 文件，不能进入 GraphRAG workspace 准备。",
        "restore_logicpoison_official_corpora": "缺少 clean 或 poisoned corpus，不能准备 clean/poisoned workspace。",
        "run_logicpoison_query_integrity_export": "缺少 query-level attack integrity，后续无法区分 query 是否被攻击影响。",
        "prepare_and_index_official_graphrag_workspaces": (
            "缺少 official GraphRAG output parquet，不能导出 source context。"
        ),
        "export_official_local_baseline_contexts": (
            "缺少 official local baseline/broad context，不能复用 Stage24 query-guard seed planning。"
        ),
        "run_query_guard_context_export": "缺少 full_query_guard source context，不能运行 recovery。",
        "run_stage28_risk_non_oracle_recovery": "缺少 risk non-oracle source recovery context。",
        "run_stage35_source_enrichment": "缺少 source enrichment context，不能诊断二跳证据。",
        "run_stage38_chain_completeness": "缺少 second-hop targeted context，不能做真实回答复验。",
        "run_answer_level_and_judge_validation": "缺少 answer/judge 汇总，不能纳入最终效果比较。",
    }
    return reasons.get(action, "存在未补齐的跨数据集实验资产。")


def _action_commands(action: str, spec: Stage40DatasetSpec) -> list[str]:
    dataset = spec.dataset
    if action == "prepare_and_index_official_graphrag_workspaces":
        clean_root = _workspace_root(spec.clean_workspace_output_dir)
        poisoned_root = _workspace_root(spec.poisoned_workspace_output_dir)
        return [
            _prepare_command(
                dataset=dataset,
                sample_path=spec.sample_path,
                corpus_path=spec.clean_corpus_path,
                workspace_root=clean_root,
            ),
            _prepare_command(
                dataset=dataset,
                sample_path=spec.sample_path,
                corpus_path=spec.poisoned_corpus_path,
                workspace_root=poisoned_root,
            ),
            f"graphrag init --root {_posix(clean_root)}",
            f"graphrag index --root {_posix(clean_root)} --method fast",
            f"graphrag init --root {_posix(poisoned_root)}",
            f"graphrag index --root {_posix(poisoned_root)} --method fast",
        ]
    config_name = f"configs/ms_graphrag_stage40_{dataset}.yaml"
    if action == "export_official_local_baseline_contexts":
        return [
            (
                "$env:PYTHONPATH='src'; tools\\ms_graphrag\\.venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.official_local_context "
                f"--config configs/ms_graphrag_stage40_{dataset}_official_local_baseline.yaml"
            ),
            (
                "$env:PYTHONPATH='src'; tools\\ms_graphrag\\.venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.official_local_context "
                f"--config configs/ms_graphrag_stage40_{dataset}_official_local_broad.yaml"
            ),
        ]
    if action == "run_query_guard_context_export":
        return [
            (
                ".venv\\Scripts\\python.exe -m logicguard.ms_graphrag.query_layer_seeding "
                f"--config {config_name}"
            ),
            (
                "$env:PYTHONPATH='src'; tools\\ms_graphrag\\.venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.query_layer_context "
                f"--config {config_name}"
            ),
            (
                ".venv\\Scripts\\python.exe -m logicguard.ms_graphrag.query_layer_evaluation "
                f"--config {config_name}"
            ),
        ]
    if action == "run_stage28_risk_non_oracle_recovery":
        return [
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.risk_non_oracle_source_recovery "
                f"--config configs/ms_graphrag_stage43_{dataset}_risk_non_oracle.yaml"
            )
        ]
    if action == "run_stage35_source_enrichment":
        return [
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.stage35_source_enrichment "
                f"--config configs/ms_graphrag_stage44_{dataset}_source_enrichment.yaml"
            )
        ]
    if action == "run_stage38_chain_completeness":
        return [
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.stage38_chain_completeness "
                f"--config configs/ms_graphrag_stage45_{dataset}_chain_completeness.yaml"
            )
        ]
    if action == "run_answer_level_and_judge_validation":
        if dataset in {"hotpotqa", "musique"}:
            return [
                (
                    ".venv\\Scripts\\python.exe -m "
                    "logicguard.ms_graphrag.stage46_answer_preflight "
                    f"--config configs/ms_graphrag_stage46_{dataset}_answer_preflight.yaml"
                ),
                (
                    ".venv\\Scripts\\python.exe -m "
                    "logicguard.ms_graphrag.answer_level_llm_verification "
                    f"--config configs/ms_graphrag_stage46_{dataset}_answer_llm.yaml"
                ),
                (
                    ".venv\\Scripts\\python.exe -m "
                    "logicguard.ms_graphrag.stage29_answer_audit "
                    f"--config configs/ms_graphrag_stage46_{dataset}_answer_audit.yaml"
                ),
                (
                    ".venv\\Scripts\\python.exe -m "
                    "logicguard.ms_graphrag.stage34_answer_judge_audit "
                    f"--config configs/ms_graphrag_stage46_{dataset}_answer_judge.yaml"
                ),
            ]
        return [
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.answer_level_llm_verification "
                f"--config configs/ms_graphrag_stage40_{dataset}_answer_llm.yaml"
            ),
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.stage29_answer_audit "
                f"--config configs/ms_graphrag_stage40_{dataset}_answer_audit.yaml"
            ),
            (
                ".venv\\Scripts\\python.exe -m "
                "logicguard.ms_graphrag.stage34_answer_judge_audit "
                f"--config configs/ms_graphrag_stage40_{dataset}_answer_judge.yaml"
            ),
        ]
    return []


def _prepare_command(
    *,
    dataset: str,
    sample_path: Path,
    corpus_path: Path,
    workspace_root: Path,
) -> str:
    return (
        ".venv\\Scripts\\python.exe -m logicguard.ms_graphrag.prepare_workspace "
        f"--dataset {dataset} "
        f"--sample-path {_posix(sample_path)} "
        f"--corpus-path {_posix(corpus_path)} "
        f"--workspace-root {_posix(workspace_root)} "
        "--doc-scope sample_support"
    )


def _workspace_root(output_dir: Path) -> Path:
    return output_dir.parent if output_dir.name == "output" else output_dir


def _posix(path: Path) -> str:
    return path.as_posix()


def _write_stage40_report(
    *,
    config: Stage40CrossDatasetAuditConfig,
    summaries: list[Stage40SummaryRow],
    gap_actions: list[Stage40GapAction],
) -> None:
    summary_table = [
        "| 数据集 | samples | integrity | clean idx | poisoned idx | baseline | broad | query context | recovery | enrichment | chain | judge | 下一步 |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summaries:
        summary_table.append(
            f"| `{row.dataset}` | {row.processed_sample_rows} | "
            f"{row.query_integrity_rows} | {_status(row.clean_workspace_ready)} | "
            f"{_status(row.poisoned_workspace_ready)} | "
            f"{_status(row.baseline_context_ready)} | "
            f"{_status(row.broad_context_ready)} | "
            f"{_status(row.source_context_ready)} | "
            f"{_status(row.risk_non_oracle_context_ready)} | "
            f"{_status(row.source_enrichment_context_ready)} | "
            f"{_status(row.chain_targeted_context_ready)} | "
            f"{_status(row.answer_judge_summary_ready)} | "
            f"`{row.next_action}` |"
        )

    action_lines = [
        "| 数据集 | 阻断动作 | 原因 |",
        "| --- | --- | --- |",
    ]
    if gap_actions:
        for action in gap_actions:
            action_lines.append(
                f"| `{action.dataset}` | `{action.action}` | {action.reason} |"
            )
    else:
        action_lines.append("| 全部 | 无 | 当前配置的数据集均已具备后续验证资产。 |")
    command_lines = _gap_command_lines(gap_actions)

    ready_datasets = [
        row.dataset
        for row in summaries
        if row.next_action == "ready_for_attribute_sentence_completeness_or_adaptive_attack"
    ]
    blocked_datasets = [row.dataset for row in summaries if row.dataset not in ready_datasets]
    content = "\n".join(
        [
            "# Stage40 跨数据集 official GraphRAG readiness 审计",
            "",
            "## 实验目的",
            "",
            (
                "Stage40 的目标不是重新调用 GraphRAG 或 LLM，而是把 2WikiMultihopQA、"
                "HotpotQA、MuSiQue 是否具备 official GraphRAG source-level recovery "
                "和 chain-level 复核条件审计清楚。"
            ),
            "",
            "本阶段坚持一个原则：不能把缺索引的数据集计入防御效果结论。",
            "",
            "## 资产审计汇总",
            "",
            *summary_table,
            "",
            "## 当前结论",
            "",
            _stage40_conclusion(ready_datasets, blocked_datasets),
            "",
            "## 阻断项与补齐动作",
            "",
            *action_lines,
            "",
            "## 关键补齐命令",
            "",
            *command_lines,
            "",
            "## 输出文件",
            "",
            f"- asset rows JSONL：`{config.asset_rows_output_path.as_posix()}`",
            f"- summary CSV：`{config.summary_output_path.as_posix()}`",
            f"- gap actions JSONL：`{config.gap_actions_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _gap_command_lines(gap_actions: list[Stage40GapAction]) -> list[str]:
    if not gap_actions:
        return ["当前没有阻断项。"]
    lines: list[str] = []
    for action in gap_actions:
        lines.extend(
            [
                f"### {action.dataset} / {action.action}",
                "",
                "```powershell",
                *action.commands,
                "```",
                "",
            ]
        )
    return lines


def _stage40_conclusion(ready_datasets: list[str], blocked_datasets: list[str]) -> str:
    ready = ", ".join(f"`{name}`" for name in ready_datasets) or "无"
    blocked = ", ".join(f"`{name}`" for name in blocked_datasets) or "无"
    return (
        f"- 已具备完整 Stage28/35/38/answer-judge 复核资产的数据集：{ready}。\n"
        f"- 尚不能进入跨数据集防御效果比较的数据集：{blocked}。\n"
        "- 因此 Stage40 的科学结论是 readiness/gap 结论，而不是新的 attack success 或 utility 结果。"
    )


def _status(value: bool) -> str:
    return "ready" if value else "missing"


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in row.items():
        if isinstance(value, bool):
            output[key] = "true" if value else "false"
        elif isinstance(value, float):
            output[key] = f"{value:.4f}"
        elif isinstance(value, list):
            output[key] = ";".join(str(item) for item in value)
        elif value is None:
            output[key] = ""
        else:
            output[key] = str(value)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stage40 cross-dataset official GraphRAG readiness audit."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage40_cross_dataset_audit.yaml"),
    )
    args = parser.parse_args()
    _, summaries, gap_actions = run_from_config(
        Stage40CrossDatasetAuditConfig.from_yaml(args.config)
    )
    print(f"stage40_datasets={len(summaries)}, gap_actions={len(gap_actions)}")


if __name__ == "__main__":
    main()
