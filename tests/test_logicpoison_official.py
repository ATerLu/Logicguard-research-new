from pathlib import Path

from logicguard.data.logicpoison_official import (
    LogicPoisonOfficialConfig,
    build_corpus_diff_records,
    build_query_integrity_records,
    load_logicpoison_pair,
    run_from_config,
    summarize_logicpoison_pair,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_official.yaml"
LOCAL_DATA_ROOT = PROJECT_ROOT / "data" / "logicpoison_official"


def test_logicpoison_official_config_uses_project_local_data_copy() -> None:
    config = LogicPoisonOfficialConfig.from_yaml(CONFIG_PATH)

    assert config.clean_data_root == LOCAL_DATA_ROOT / "clean"
    assert config.poisoned_data_root == LOCAL_DATA_ROOT / "poisoned"
    assert config.output_root == PROJECT_ROOT / "outputs" / "attacks" / "logicpoison_official"
    assert config.report_path == PROJECT_ROOT / "outputs" / "reports" / "LogicPoison污染语料可用性验证报告.md"
    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]


def test_load_logicpoison_pair_keeps_clean_and_poisoned_ids_aligned() -> None:
    config = LogicPoisonOfficialConfig.from_yaml(CONFIG_PATH)

    pair = load_logicpoison_pair(config, "2wikimultihopqa")

    assert pair.dataset == "2wikimultihopqa"
    assert len(pair.clean.queries) == 500
    assert len(pair.poisoned.queries) == 500
    assert len(pair.clean.corpus) == 6119
    assert len(pair.poisoned.corpus) == 6119
    assert set(pair.clean.queries) == set(pair.poisoned.queries)
    assert set(pair.clean.answers) == set(pair.poisoned.answers)
    assert set(pair.clean.qrels) == set(pair.poisoned.qrels)
    assert set(pair.clean.corpus) == set(pair.poisoned.corpus)


def test_build_corpus_diff_records_detects_logicpoison_content_changes() -> None:
    config = LogicPoisonOfficialConfig.from_yaml(CONFIG_PATH)
    pair = load_logicpoison_pair(config, "2wikimultihopqa")

    diff_records = build_corpus_diff_records(pair)
    changed_records = [record for record in diff_records if record.changed]

    assert len(diff_records) == 6119
    assert changed_records
    assert all(record.clean_hash != record.poisoned_hash for record in changed_records)
    assert any(record.text_changed for record in changed_records)
    assert all(record.doc_id in pair.clean.corpus for record in changed_records)


def test_build_query_integrity_records_marks_changed_gold_supports() -> None:
    config = LogicPoisonOfficialConfig.from_yaml(CONFIG_PATH)
    pair = load_logicpoison_pair(config, "2wikimultihopqa")
    diff_records = build_corpus_diff_records(pair)
    changed_doc_ids = {record.doc_id for record in diff_records if record.changed}

    integrity_records = build_query_integrity_records(pair, changed_doc_ids)

    assert len(integrity_records) == 500
    assert integrity_records[0].query_id == "a457e11c0bdb11eba7f7acde48001122"
    assert integrity_records[0].support_doc_ids == ["639", "638"]
    assert any(record.changed_support_doc_ids for record in integrity_records)
    assert all(
        set(record.changed_support_doc_ids) <= set(record.support_doc_ids)
        for record in integrity_records
    )


def test_summarize_logicpoison_pair_reports_changed_doc_and_answer_surface_loss() -> None:
    config = LogicPoisonOfficialConfig.from_yaml(CONFIG_PATH)
    pair = load_logicpoison_pair(config, "2wikimultihopqa")
    diff_records = build_corpus_diff_records(pair)
    changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
    integrity_records = build_query_integrity_records(pair, changed_doc_ids)

    summary = summarize_logicpoison_pair(pair, diff_records, integrity_records)

    assert summary.dataset == "2wikimultihopqa"
    assert summary.clean_docs == 6119
    assert summary.poisoned_docs == 6119
    assert summary.queries == 500
    assert summary.changed_doc_count > 0
    assert 0.0 < summary.changed_doc_rate <= 1.0
    assert summary.queries_with_changed_gold_support > 0
    assert summary.answer_surface_loss_count >= 0


def test_run_from_config_writes_stage0_metadata_artifacts(tmp_path: Path) -> None:
    config = LogicPoisonOfficialConfig(
        clean_data_root=LOCAL_DATA_ROOT / "clean",
        poisoned_data_root=LOCAL_DATA_ROOT / "poisoned",
        output_root=tmp_path / "attacks" / "logicpoison_official",
        report_path=tmp_path / "reports" / "LogicPoison污染语料可用性验证报告.md",
        datasets=["2wikimultihopqa"],
    )

    summaries = run_from_config(config)
    dataset_output = config.output_root / "2wikimultihopqa"

    assert len(summaries) == 1
    assert summaries[0].dataset == "2wikimultihopqa"
    assert (dataset_output / "changed_docs.jsonl").is_file()
    assert (dataset_output / "query_integrity.jsonl").is_file()
    assert config.report_path.is_file()
