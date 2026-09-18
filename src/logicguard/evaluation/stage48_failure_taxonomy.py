"""Frozen Stage48 failure taxonomy for attack and prompt propagation audits.

The taxonomy is independent from answer outcomes. It assigns one terminal
category to every fixed-budget attempt and preserves the attempted denominator.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    write_inferred_csv,
    write_jsonl,
)


@dataclass(frozen=True, slots=True)
class FailureLabel:
    """One mutually exclusive terminal stage and category."""

    stage: str
    category: str


@dataclass(frozen=True, slots=True)
class ExposureCell:
    """One frozen full-corpus exposure artifact."""

    dataset: str
    attack_family: str
    path: Path


@dataclass(frozen=True, slots=True)
class Stage48FailureTaxonomyConfig:
    """Inputs and outputs for the offline Stage48 failure audit."""

    inventory_path: Path
    exposure_cells: tuple[ExposureCell, ...]
    required_evaluation_valid_per_cell: int
    prompt_source_limit: int
    rows_output_path: Path
    summary_output_path: Path
    summary_csv_output_path: Path
    report_path: Path

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage48FailureTaxonomyConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (project_root / candidate).resolve()
            )

        return cls(
            inventory_path=resolve(payload["inventory_path"]),
            exposure_cells=tuple(
                ExposureCell(
                    dataset=str(cell["dataset"]),
                    attack_family=str(cell["attack_family"]),
                    path=resolve(cell["path"]),
                )
                for cell in payload.get("exposure_cells", [])
            ),
            required_evaluation_valid_per_cell=int(
                payload.get("required_evaluation_valid_per_cell", 10)
            ),
            prompt_source_limit=int(payload.get("prompt_source_limit", 12)),
            rows_output_path=resolve(payload["rows_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            summary_csv_output_path=resolve(payload["summary_csv_output_path"]),
            report_path=resolve(payload["report_path"]),
        )


def classify_attack_validity(row: dict[str, Any]) -> FailureLabel:
    """Classify generation and evaluation validity without outcome leakage."""

    if not bool(row.get("generation_valid")):
        reason = str(row.get("invalid_reason", "")).strip()
        return FailureLabel("generation", reason or "generation_invalid_unclassified")
    if not bool(row.get("non_oracle_generation")):
        return FailureLabel("evaluation", "oracle_label_access")
    if not bool(row.get("target_is_wrong")):
        return FailureLabel("evaluation", "malicious_target_matches_gold")
    if str(row.get("attack_family", "")) == "candidate_collision" and not bool(
        row.get("wrong_collision_candidate")
    ):
        return FailureLabel("evaluation", "collision_candidate_is_gold_support")
    if not bool(row.get("evaluation_valid")):
        return FailureLabel("evaluation", "evaluation_invalid_unclassified")
    return FailureLabel("evaluation", "evaluation_valid")


def classify_prompt_propagation(
    row: dict[str, Any], *, prompt_source_limit: int
) -> FailureLabel:
    """Classify the first failed full-corpus propagation stage."""

    document_included = bool(row.get("index_document_included"))
    text_unit_included = bool(row.get("index_text_unit_included"))
    if not document_included and not text_unit_included:
        return FailureLabel("index", "missing_from_document_and_text_unit_index")
    if not document_included:
        return FailureLabel("index", "missing_from_document_index")
    if not text_unit_included:
        return FailureLabel("index", "missing_from_text_unit_index")
    if not bool(row.get("retrieved")):
        return FailureLabel("retrieval", "indexed_not_retrieved")

    source_exposed = bool(row.get("prompt_source_exposed"))
    target_exposed = bool(row.get("prompt_target_exposed"))
    if source_exposed and target_exposed:
        return FailureLabel("complete", "prompt_source_and_target_exposed")
    if source_exposed:
        return FailureLabel("prompt", "prompt_source_exposed_target_truncated")
    if target_exposed:
        return FailureLabel("prompt", "target_surface_without_attack_source")

    source_rank = row.get("source_rank")
    if isinstance(source_rank, (int, float)) and source_rank > prompt_source_limit:
        return FailureLabel("prompt", "retrieved_beyond_prompt_source_limit")
    return FailureLabel("prompt", "retrieved_source_missing_from_prompt")


def build_failure_rows(
    *,
    inventory_rows: list[dict[str, Any]],
    exposure_rows: list[dict[str, Any]],
    required_evaluation_valid_per_cell: int,
    prompt_source_limit: int,
) -> list[dict[str, Any]]:
    """Join frozen inventory/exposure rows and assign one terminal category."""

    if required_evaluation_valid_per_cell <= 0:
        raise ValueError("required_evaluation_valid_per_cell must be positive")
    if prompt_source_limit <= 0:
        raise ValueError("prompt_source_limit must be positive")

    inventory_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    evaluation_valid_counts: Counter[tuple[str, str]] = Counter()
    for row in inventory_rows:
        key = _row_key(row)
        if key in inventory_by_key:
            raise ValueError(f"Duplicate Stage48 inventory key: {key}")
        inventory_by_key[key] = row
        if bool(row.get("evaluation_valid")):
            evaluation_valid_counts[key[:2]] += 1

    exposure_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in exposure_rows:
        key = _row_key(row)
        if key in exposure_by_key:
            raise ValueError(f"Duplicate Stage48 exposure key: {key}")
        inventory = inventory_by_key.get(key)
        if inventory is None:
            raise ValueError(f"Exposure row has no frozen inventory row: {key}")
        if not bool(inventory.get("selected_for_reindex")):
            raise ValueError(f"Unselected attack has an exposure row: {key}")
        exposure_by_key[key] = row

    output: list[dict[str, Any]] = []
    for key, inventory in inventory_by_key.items():
        label = classify_attack_validity(inventory)
        exposure = exposure_by_key.get(key)
        if label.category == "evaluation_valid":
            if not bool(inventory.get("selected_for_reindex")):
                if (
                    evaluation_valid_counts[key[:2]]
                    < required_evaluation_valid_per_cell
                ):
                    label = FailureLabel("selection", "cell_below_reindex_minimum")
                else:
                    label = FailureLabel("selection", "fixed_quota_not_selected")
            elif exposure is None:
                label = FailureLabel("audit", "selected_missing_exposure_row")
            else:
                label = classify_prompt_propagation(
                    exposure, prompt_source_limit=prompt_source_limit
                )

        output.append(
            {
                **inventory,
                "index_included": bool(
                    exposure
                    and exposure.get("index_document_included")
                    and exposure.get("index_text_unit_included")
                ),
                "retrieved": bool(exposure and exposure.get("retrieved")),
                "source_rank": exposure.get("source_rank") if exposure else None,
                "prompt_source_exposed": bool(
                    exposure and exposure.get("prompt_source_exposed")
                ),
                "prompt_target_exposed": bool(
                    exposure and exposure.get("prompt_target_exposed")
                ),
                "prompt_exposed": bool(
                    exposure
                    and exposure.get("prompt_source_exposed")
                    and exposure.get("prompt_target_exposed")
                ),
                "failure_stage": label.stage,
                "failure_category": label.category,
            }
        )
    return sorted(
        output,
        key=lambda row: (
            str(row["dataset"]),
            str(row["attack_family"]),
            str(row["query_id"]),
        ),
    )


def summarize_failure_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build fixed-denominator funnel and category summaries."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["dataset"]), str(row["attack_family"]))].append(row)

    cells: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    for (dataset, family), group in sorted(grouped.items()):
        attempted = len(group)
        counts = Counter(str(row["failure_category"]) for row in group)
        cells.append(
            {
                "dataset": dataset,
                "attack_family": family,
                "attempted": attempted,
                "generation_valid": sum(bool(row["generation_valid"]) for row in group),
                "evaluation_valid": sum(bool(row["evaluation_valid"]) for row in group),
                "selected_for_reindex": sum(
                    bool(row["selected_for_reindex"]) for row in group
                ),
                "index_included": sum(bool(row["index_included"]) for row in group),
                "retrieved": sum(bool(row["retrieved"]) for row in group),
                "prompt_exposed": sum(bool(row["prompt_exposed"]) for row in group),
                "terminal_category_counts": dict(sorted(counts.items())),
            }
        )
        categories.extend(
            {
                "dataset": dataset,
                "attack_family": family,
                "attempted": attempted,
                "failure_stage": next(
                    str(row["failure_stage"])
                    for row in group
                    if row["failure_category"] == category
                ),
                "failure_category": category,
                "count": count,
                "attempted_rate": count / attempted if attempted else 0.0,
            }
            for category, count in sorted(counts.items())
        )
    return {
        "schema_version": 1,
        "taxonomy_status": "frozen_offline_stage48_audit",
        "attempted": len(rows),
        "cell_rows": cells,
        "category_rows": categories,
    }


def run_from_config(config: Stage48FailureTaxonomyConfig) -> dict[str, Any]:
    """Run the fully offline taxonomy audit and write auditable artifacts."""

    inventory_rows = load_jsonl(config.inventory_path)
    exposure_rows: list[dict[str, Any]] = []
    seen_cells: set[tuple[str, str]] = set()
    for cell in config.exposure_cells:
        cell_key = (cell.dataset, cell.attack_family)
        if cell_key in seen_cells:
            raise ValueError(f"Duplicate exposure cell in taxonomy config: {cell_key}")
        seen_cells.add(cell_key)
        rows = load_jsonl(cell.path)
        if any(_row_key(row)[:2] != cell_key for row in rows):
            raise ValueError(f"Exposure labels do not match config cell: {cell_key}")
        exposure_rows.extend(rows)

    failure_rows = build_failure_rows(
        inventory_rows=inventory_rows,
        exposure_rows=exposure_rows,
        required_evaluation_valid_per_cell=(config.required_evaluation_valid_per_cell),
        prompt_source_limit=config.prompt_source_limit,
    )
    summary = summarize_failure_rows(failure_rows)
    summary["protocol"] = {
        "required_evaluation_valid_per_cell": (
            config.required_evaluation_valid_per_cell
        ),
        "prompt_source_limit": config.prompt_source_limit,
        "answer_outcomes_used": False,
        "paid_api_calls": 0,
    }
    write_jsonl(config.rows_output_path, failure_rows)
    atomic_write_json(config.summary_output_path, summary)
    write_inferred_csv(config.summary_csv_output_path, summary["category_rows"])
    atomic_write_text(config.report_path, _render_report(summary))
    return summary


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("dataset", "")),
        str(row.get("attack_family", "")),
        str(row.get("query_id", "")),
    )


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Stage48 冻结失败分类审计",
        "",
        "> 本报告只读取 fixed-50 inventory 与既有 full-corpus exposure；不读取回答结果，不补样，不产生 API 调用。",
        "",
        "## 固定分母漏斗",
        "",
        "| 数据集 | 攻击家族 | attempted | generation-valid | evaluation-valid | selected | index | retrieved | prompt-exposed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["cell_rows"]:
        lines.append(
            f"| {row['dataset']} | {row['attack_family']} | {row['attempted']} | "
            f"{row['generation_valid']} | {row['evaluation_valid']} | "
            f"{row['selected_for_reindex']} | {row['index_included']} | "
            f"{row['retrieved']} | {row['prompt_exposed']} |"
        )
    lines.extend(
        [
            "",
            "## 互斥终止分类",
            "",
            "| 数据集 | 攻击家族 | 阶段 | 分类 | 数量 | attempted 占比 |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for row in summary["category_rows"]:
        lines.append(
            f"| {row['dataset']} | {row['attack_family']} | "
            f"{row['failure_stage']} | `{row['failure_category']}` | "
            f"{row['count']} | {row['attempted_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- `fixed_quota_not_selected` 是预注册固定配额造成的抽样状态，不是攻击失败。",
            "- `cell_below_reindex_minimum` 表示该家族未达到 10 条 evaluation-valid 门槛，不得以小分母继续建索引。",
            "- `prompt_source_exposed_target_truncated` 与 `retrieved_beyond_prompt_source_limit` 分别隔离字符截断和 top-k 选择故障。",
            "- `target_surface_without_attack_source` 不算攻击 Prompt 暴露，避免把其他来源中的同名字符串误归因给攻击文档。",
            "- 本分类不改变 Stage48 Gate A 已失败的冻结结论，也不授权重跑任何付费 namespace。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    result = run_from_config(Stage48FailureTaxonomyConfig.from_yaml(args.config))
    print(
        f"stage48_failure_taxonomy_rows={result['attempted']}, paid_api_calls=0",
        flush=True,
    )


if __name__ == "__main__":
    main()
