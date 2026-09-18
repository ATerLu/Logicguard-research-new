import shutil
from pathlib import Path
from uuid import uuid4

import yaml

from logicguard.benchmark.real_trace_contract_runner import run_from_config

ROOT = Path(__file__).parents[1]


def test_real_trace_contract_anchor_runs_and_replays_without_provider() -> None:
    source = yaml.safe_load(
        (
            ROOT / "configs/benchmark/comparison_v1_2_real_trace_contract_anchor.yaml"
        ).read_text(encoding="utf-8")
    )
    output = (
        ROOT
        / "artifacts/benchmark/research_revision_v1_2/wp2/test_real_trace_contract"
        / uuid4().hex
    )
    source["output_root"] = str(output.relative_to(ROOT))
    temporary = ROOT / "tmp/real_trace_contract_tests" / uuid4().hex
    temporary.mkdir(parents=True)
    config_path = temporary / "config.yaml"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    try:
        first = run_from_config(config_path)
        second = run_from_config(config_path)

        assert first == second
        assert first["status"] == "REAL_TRACE_ZERO_COVERAGE_CONTRACT_ANCHOR_PASSED"
        assert first["source_hits"] == {
            "S1_microsoft_graphrag": 42,
            "S2_lightrag": 6,
        }
        assert first["clean_exact_matches"] == first["source_hits"]
        assert first["context_rows"] == 4
        assert first["audit_failures"] == 0
        assert first["trusted_pool_retrieval_executed"] is False
        assert first["provider_calls_made"] == 0
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
