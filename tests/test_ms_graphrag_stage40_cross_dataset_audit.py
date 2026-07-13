import csv
import json
from pathlib import Path

from logicguard.ms_graphrag.stage40_cross_dataset_audit import (
    Stage40CrossDatasetAuditConfig,
    Stage40DatasetSpec,
    build_stage40_asset_rows,
    build_stage40_gap_actions,
    summarize_stage40_assets,
    write_stage40_outputs,
)


def test_stage40_marks_dataset_ready_when_required_assets_exist(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "ready")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])
    _write_workspace(spec.clean_workspace_output_dir)
    _write_workspace(spec.poisoned_workspace_output_dir)
    _write_jsonl(spec.baseline_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.broad_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.risk_non_oracle_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_enrichment_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.chain_targeted_context_path, [{"query_id": "q1"}])
    _write_csv(spec.answer_judge_summary_path, [{"query_count": "1"}])

    rows = build_stage40_asset_rows([spec])
    summaries = summarize_stage40_assets(rows)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.dataset == "ready"
    assert summary.can_prepare_workspaces is True
    assert summary.can_run_official_query_export is True
    assert summary.can_run_source_recovery is True
    assert summary.can_run_chain_diagnostics is True
    assert summary.can_run_answer_level_verification is True
    assert summary.next_action == "ready_for_attribute_sentence_completeness_or_adaptive_attack"


def test_stage40_blocks_cross_dataset_validation_without_graphrag_workspaces(
    tmp_path: Path,
) -> None:
    spec = _make_spec(tmp_path, "hotpotqa")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])

    rows = build_stage40_asset_rows([spec])
    summary = summarize_stage40_assets(rows)[0]
    actions = build_stage40_gap_actions([summary], [spec])

    assert summary.can_prepare_workspaces is True
    assert summary.clean_workspace_ready is False
    assert summary.poisoned_workspace_ready is False
    assert summary.can_run_source_recovery is False
    assert summary.can_run_chain_diagnostics is False
    assert summary.next_action == "prepare_and_index_official_graphrag_workspaces"
    assert actions[0].action == "prepare_and_index_official_graphrag_workspaces"
    assert "prepare_workspace" in actions[0].commands[0]
    assert "graphrag index" in "\n".join(actions[0].commands)


def test_stage40_points_source_recovery_gap_to_stage43_config(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "hotpotqa")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])
    _write_workspace(spec.clean_workspace_output_dir)
    _write_workspace(spec.poisoned_workspace_output_dir)
    _write_jsonl(spec.baseline_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.broad_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_context_path, [{"query_id": "q1"}])

    summary = summarize_stage40_assets(build_stage40_asset_rows([spec]))[0]
    action = build_stage40_gap_actions([summary], [spec])[0]

    assert summary.next_action == "run_stage28_risk_non_oracle_recovery"
    assert "ms_graphrag_stage43_hotpotqa_risk_non_oracle.yaml" in action.commands[0]


def test_stage40_points_source_enrichment_gap_to_stage44_config(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "musique")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])
    _write_workspace(spec.clean_workspace_output_dir)
    _write_workspace(spec.poisoned_workspace_output_dir)
    _write_jsonl(spec.baseline_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.broad_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.risk_non_oracle_context_path, [{"query_id": "q1"}])

    summary = summarize_stage40_assets(build_stage40_asset_rows([spec]))[0]
    action = build_stage40_gap_actions([summary], [spec])[0]

    assert summary.next_action == "run_stage35_source_enrichment"
    assert "ms_graphrag_stage44_musique_source_enrichment.yaml" in action.commands[0]


def test_stage40_points_chain_gap_to_stage45_config(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "hotpotqa")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])
    _write_workspace(spec.clean_workspace_output_dir)
    _write_workspace(spec.poisoned_workspace_output_dir)
    _write_jsonl(spec.baseline_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.broad_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.risk_non_oracle_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_enrichment_context_path, [{"query_id": "q1"}])

    summary = summarize_stage40_assets(build_stage40_asset_rows([spec]))[0]
    action = build_stage40_gap_actions([summary], [spec])[0]

    assert summary.next_action == "run_stage38_chain_completeness"
    assert "ms_graphrag_stage45_hotpotqa_chain_completeness.yaml" in action.commands[0]


def test_stage40_points_cross_dataset_answer_gap_to_stage46_configs(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "hotpotqa")
    _write_jsonl(spec.sample_path, [{"query_id": "q1", "query": "Q?", "answer": "A"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])
    _write_workspace(spec.clean_workspace_output_dir)
    _write_workspace(spec.poisoned_workspace_output_dir)
    _write_jsonl(spec.baseline_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.broad_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.risk_non_oracle_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.source_enrichment_context_path, [{"query_id": "q1"}])
    _write_jsonl(spec.chain_targeted_context_path, [{"query_id": "q1"}])

    summary = summarize_stage40_assets(build_stage40_asset_rows([spec]))[0]
    action = build_stage40_gap_actions([summary], [spec])[0]

    assert action.action == "run_answer_level_and_judge_validation"
    assert "stage46_hotpotqa_answer_preflight.yaml" in action.commands[0]
    assert "stage46_hotpotqa_answer_judge.yaml" in action.commands[-1]


def test_stage40_writes_jsonl_csv_gap_actions_and_chinese_report(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, "toy")
    _write_jsonl(spec.sample_path, [{"query_id": "q1"}])
    _write_jsonl(spec.clean_corpus_path, [{"_id": "d1", "text": "clean"}])
    _write_jsonl(spec.poisoned_corpus_path, [{"_id": "d1", "text": "poisoned"}])
    _write_jsonl(spec.query_integrity_path, [{"query_id": "q1"}])

    rows = build_stage40_asset_rows([spec])
    summaries = summarize_stage40_assets(rows)
    actions = build_stage40_gap_actions(summaries, [spec])
    config = Stage40CrossDatasetAuditConfig(
        datasets=[spec],
        asset_rows_output_path=tmp_path / "asset_rows.jsonl",
        summary_output_path=tmp_path / "summary.csv",
        gap_actions_output_path=tmp_path / "gap_actions.jsonl",
        report_path=tmp_path / "report.md",
        stage_label="Stage40",
    )

    write_stage40_outputs(
        config=config,
        asset_rows=rows,
        summaries=summaries,
        gap_actions=actions,
    )

    saved_asset = json.loads(config.asset_rows_output_path.read_text(encoding="utf-8").splitlines()[0])
    assert saved_asset["dataset"] == "toy"
    with config.summary_output_path.open("r", encoding="utf-8-sig", newline="") as handle:
        saved_summary = list(csv.DictReader(handle))
    assert saved_summary[0]["next_action"] == "prepare_and_index_official_graphrag_workspaces"
    saved_action = json.loads(
        config.gap_actions_output_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert saved_action["dataset"] == "toy"
    report_text = config.report_path.read_text(encoding="utf-8")
    assert report_text.startswith("# Stage40 跨数据集 official GraphRAG readiness 审计")
    assert "不能把缺索引的数据集计入防御效果结论" in report_text


def _make_spec(tmp_path: Path, dataset: str) -> Stage40DatasetSpec:
    root = tmp_path / dataset
    return Stage40DatasetSpec(
        dataset=dataset,
        sample_path=root / "debug_50.jsonl",
        clean_corpus_path=root / "clean" / "corpus.jsonl",
        poisoned_corpus_path=root / "poisoned" / "corpus.jsonl",
        query_integrity_path=root / "query_integrity.jsonl",
        clean_workspace_output_dir=root / "clean_workspace" / "output",
        poisoned_workspace_output_dir=root / "poisoned_workspace" / "output",
        baseline_context_path=root / "baseline.jsonl",
        broad_context_path=root / "broad.jsonl",
        source_context_path=root / "source_context.jsonl",
        risk_non_oracle_context_path=root / "risk_non_oracle.jsonl",
        source_enrichment_context_path=root / "source_enrichment.jsonl",
        chain_targeted_context_path=root / "chain_targeted.jsonl",
        answer_judge_summary_path=root / "judge_summary.csv",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_workspace(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "documents.parquet",
        "text_units.parquet",
        "entities.parquet",
        "relationships.parquet",
        "communities.parquet",
        "stats.json",
    ):
        (output_dir / filename).write_text("x", encoding="utf-8")
