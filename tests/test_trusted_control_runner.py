import copy
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from logicguard.benchmark.trusted_control_runner import run_from_config

ROOT = Path(__file__).parents[1]


def test_trusted_control_fixture_runs_and_replays_without_provider() -> None:
    source = yaml.safe_load(
        (
            ROOT / "configs/benchmark/comparison_v1_2_trusted_controls_fixture.yaml"
        ).read_text(encoding="utf-8")
    )
    output = (
        ROOT
        / "artifacts/benchmark/research_revision_v1_2/wp2/test_trusted_controls"
        / uuid4().hex
    )
    source["output_root"] = str(output.relative_to(ROOT))
    project_temp = ROOT / "tmp/trusted_control_tests" / uuid4().hex
    project_temp.mkdir(parents=True)
    config_path = project_temp / "config.yaml"
    config_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    try:
        first = run_from_config(config_path)
        second = run_from_config(config_path)

        assert first == second
        assert first["status"] == "LOCAL_ACCEPTANCE_PASSED"
        assert first["context_rows"] == 32
        assert first["audit_rows"] == 16
        assert first["provider_calls_made"] == 0
        assert first["actual_cost_cny"] == 0.0
    finally:
        shutil.rmtree(project_temp, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)


def test_trusted_control_fixture_rejects_modified_trusted_copy() -> None:
    source_config = yaml.safe_load(
        (
            ROOT / "configs/benchmark/comparison_v1_2_trusted_controls_fixture.yaml"
        ).read_text(encoding="utf-8")
    )
    retrieval = [
        yaml.safe_load(line)
        for line in (ROOT / source_config["retrieval_fixture"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    poisoned = copy.deepcopy(retrieval)
    poisoned[0]["trusted_catalog_hits"][0]["text"] = "changed after poisoning"
    project_temp = ROOT / "tmp/trusted_control_tests" / uuid4().hex
    project_temp.mkdir(parents=True)
    retrieval_path = project_temp / "retrieval.jsonl"
    retrieval_path.write_text(
        "".join(json.dumps(row) + "\n" for row in poisoned),
        encoding="utf-8",
    )
    source_config["retrieval_fixture"] = str(retrieval_path.relative_to(ROOT))
    output = (
        ROOT
        / "artifacts/benchmark/research_revision_v1_2/wp2/test_trusted_controls"
        / uuid4().hex
    )
    source_config["output_root"] = str(output.relative_to(ROOT))
    config_path = project_temp / "rejected.yaml"
    config_path.write_text(yaml.safe_dump(source_config), encoding="utf-8")

    try:
        with pytest.raises(ValueError, match="exact pre-poison clean document"):
            run_from_config(config_path)
    finally:
        shutil.rmtree(project_temp, ignore_errors=True)
        shutil.rmtree(output, ignore_errors=True)
