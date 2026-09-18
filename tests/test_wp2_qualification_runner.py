import shutil
from pathlib import Path
from uuid import uuid4

import yaml

from logicguard.benchmark.wp2_qualification_runner import run_from_config

ROOT = Path(__file__).parents[1]


def test_wp2_qualification_anchor_runs_and_replays_without_provider() -> None:
    source = yaml.safe_load(
        (
            ROOT / "configs/benchmark/comparison_v1_2_a1_a3_trace_qualification.yaml"
        ).read_text(encoding="utf-8")
    )
    output = (
        ROOT
        / "artifacts/benchmark/research_revision_v1_2/wp2/test_qualification"
        / uuid4().hex
    )
    source["output_root"] = str(output.relative_to(ROOT))
    temporary = ROOT / "tmp/wp2_qualification_tests" / uuid4().hex
    temporary.mkdir(parents=True)
    config_path = temporary / "config.yaml"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    try:
        first = run_from_config(config_path)
        second = run_from_config(config_path)

        assert first == second
        assert first["status"] == "LOCAL_QUALIFICATION_PASSED_WITH_DECLARED_BOUNDARIES"
        assert first["backend_traces"]["microsoft_graphrag"]["hits"] == 1870
        assert first["backend_traces"]["lightrag"]["real_trace_rows"] == 0
        assert first["provider_calls_made"] == 0
        assert first["actual_cost_cny"] == 0.0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
