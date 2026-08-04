from pathlib import Path

import yaml

from logicguard.ms_graphrag.official_local_context import write_official_context_rows
from logicguard.ms_graphrag.official_query_pipeline import (
    OfficialQueryPipelineConfig,
    build_context_export_command,
    run_from_config,
    write_context_export_config,
)
from logicguard.ms_graphrag.query_time_defense import QueryTimeDefenseResult


def test_pipeline_config_builds_official_context_and_defense_configs(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_config(tmp_path)

    config = OfficialQueryPipelineConfig.from_yaml(config_path)
    context_config = config.to_official_context_config()
    defense_config = config.to_defense_config()

    assert context_config.dataset == "toy"
    assert context_config.output_path == tmp_path / "outputs" / "contexts.jsonl"
    assert context_config.report_path == tmp_path / "outputs" / "context_report.md"
    assert context_config.community_level == 2
    assert defense_config.evidence_source == "official_local_context"
    assert defense_config.official_context_path == context_config.output_path
    assert defense_config.output_path == tmp_path / "outputs" / "defense.jsonl"
    assert defense_config.models == ["deepseek-v4-flash"]


def test_write_context_export_config_and_command_are_reproducible(
    tmp_path: Path,
) -> None:
    config = OfficialQueryPipelineConfig.from_yaml(_write_pipeline_config(tmp_path))
    context_config = config.to_official_context_config()
    export_config_path = tmp_path / "outputs" / "derived_context_config.yaml"

    write_context_export_config(context_config, export_config_path)
    command = build_context_export_command(config, export_config_path)

    saved = yaml.safe_load(export_config_path.read_text(encoding="utf-8"))
    assert saved["dataset"] == "toy"
    assert saved["output_path"] == str(context_config.output_path)
    assert command == [
        str(config.graphrag_python_path),
        "-m",
        "logicguard.ms_graphrag.official_local_context",
        "--config",
        str(export_config_path),
    ]


def test_run_from_config_exports_context_before_defense(tmp_path: Path) -> None:
    config = OfficialQueryPipelineConfig.from_yaml(_write_pipeline_config(tmp_path))
    calls: list[str] = []
    seen_official_context_path: Path | None = None

    def fake_context_exporter(context_config):
        calls.append("export")
        write_official_context_rows(
            context_config.output_path,
            [
                {
                    "dataset": "toy",
                    "query_id": "q1",
                    "query": "Who?",
                    "expected_answer": "Alice",
                    "response": "polluted answer",
                    "context_data": {
                        "sources": [
                            {
                                "id": "0",
                                "logicguard_doc_id": "d1",
                                "text": "Document ID: d1\nTitle: T",
                            }
                        ],
                        "entities": [{"id": "e1"}],
                        "relationships": [],
                        "reports": [],
                    },
                }
            ],
        )

    def fake_defense_runner(defense_config, client=None):  # noqa: ANN001
        nonlocal seen_official_context_path
        calls.append("defense")
        seen_official_context_path = defense_config.official_context_path
        return [
            QueryTimeDefenseResult(
                dataset="toy",
                model="deepseek-v4-flash",
                query_id="q1",
                query="Who?",
                expected_answer="Alice",
                variant="recovered",
                generated_answer="Alice",
                is_correct=True,
                is_abstained=False,
                is_incorrect=False,
                changed_doc_count=0,
                recovered_doc_count=1,
                evidence_doc_ids=["d1"],
                evidence_text_unit_ids=["u1"],
                latency_seconds=0.01,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                error=None,
            )
        ]

    summary = run_from_config(
        config,
        context_exporter=fake_context_exporter,
        defense_runner=fake_defense_runner,
    )

    assert calls == ["export", "defense"]
    assert seen_official_context_path == tmp_path / "outputs" / "contexts.jsonl"
    assert summary.context_row_count == 1
    assert summary.defense_result_count == 1
    assert summary.correct_count == 1
    assert (tmp_path / "outputs" / "pipeline_report.md").exists()


def _write_pipeline_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "pipeline.yaml"
    payload = {
        "dataset": "toy",
        "sample_path": "data/sample.jsonl",
        "poisoned_workspace_root": "outputs/poisoned_workspace",
        "clean_reference_workspace_root": "outputs/clean_workspace",
        "query_integrity_path": "outputs/query_integrity.jsonl",
        "official_context_output_path": "outputs/contexts.jsonl",
        "official_context_report_path": "outputs/context_report.md",
        "context_export_config_path": "outputs/derived_context_config.yaml",
        "defense_output_path": "outputs/defense.jsonl",
        "defense_report_path": "outputs/defense_report.md",
        "pipeline_report_path": "outputs/pipeline_report.md",
        "graphrag_python_path": "tools/ms_graphrag/.venv/Scripts/python.exe",
        "models": ["deepseek-v4-flash"],
        "community_level": 2,
        "response_type": "Single Sentence",
        "max_queries": 1,
        "top_k": 4,
        "max_units": 4,
        "max_chars_per_unit": 900,
        "temperature": 0.0,
        "max_tokens": 64,
        "timeout_seconds": 90,
    }
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return config_path
