import importlib
import json
from pathlib import Path

import pytest

from logicguard.core.config import (
    find_project_root,
    load_yaml,
    resolve_config_path,
    resolve_project_path,
)
from logicguard.core.io import (
    append_jsonl,
    load_jsonl,
    require_env,
    sha256_file,
    write_csv,
    write_inferred_csv,
    write_jsonl,
)
from logicguard.core.metrics import dedupe, dedupe_strings, mean, mean_defined, ratio
from logicguard.cli import main as cli_main


def test_find_project_root_supports_nested_config(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    config = tmp_path / "configs" / "experiments" / "stage47" / "run.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("dataset: hotpotqa\n", encoding="utf-8")

    assert find_project_root(config) == tmp_path


def test_find_project_root_rejects_unmarked_tree(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_project_root(tmp_path, strict=True)


def test_find_project_root_preserves_legacy_standalone_config_behavior(
    tmp_path: Path,
) -> None:
    config = tmp_path / "configs" / "run.yaml"
    config.parent.mkdir()
    config.touch()

    assert find_project_root(config) == tmp_path


def test_load_and_resolve_project_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("output: outputs/result.jsonl\n", encoding="utf-8")

    payload = load_yaml(config)

    assert resolve_project_path(payload["output"], project_root=tmp_path) == (
        tmp_path / "outputs" / "result.jsonl"
    )


def test_load_yaml_requires_mapping(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("- item\n", encoding="utf-8")

    with pytest.raises(TypeError):
        load_yaml(config)


def test_resolve_config_path_supports_legacy_aliases(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    alias_file = tmp_path / "configs" / "config_aliases.yaml"
    alias_file.parent.mkdir()
    alias_file.write_text(
        "aliases:\n  configs/old.yaml: configs/experiments/new.yaml\n",
        encoding="utf-8",
    )
    target = tmp_path / "configs" / "experiments" / "new.yaml"
    target.parent.mkdir()
    target.write_text("dataset: toy\n", encoding="utf-8")

    assert resolve_config_path(tmp_path / "configs" / "old.yaml") == target


def test_jsonl_csv_and_hash_helpers(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "nested" / "rows.jsonl"
    rows = [{"id": "q1", "value": 1}, {"id": "问题", "value": 2}]
    write_jsonl(jsonl_path, rows)
    append_jsonl(jsonl_path, {"id": "q3", "value": 3})

    assert load_jsonl(jsonl_path) == [*rows, {"id": "q3", "value": 3}]
    assert sha256_file(jsonl_path) == sha256_file(jsonl_path)
    assert json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[1]) == rows[1]

    csv_path = tmp_path / "nested" / "rows.csv"
    write_csv(csv_path, rows, fieldnames=("id", "value"))
    assert "id,value" in csv_path.read_text(encoding="utf-8-sig")

    inferred_path = tmp_path / "nested" / "inferred.csv"
    write_inferred_csv(inferred_path, rows)
    assert "id,value" in inferred_path.read_text(encoding="utf-8-sig")


def test_shared_metrics_are_safe_and_ordered() -> None:
    assert ratio(1, 4) == 0.25
    assert ratio(1, 0) == 0.0
    assert mean([1, 2, 3]) == 2.0
    assert mean([]) == 0.0
    assert mean_defined([1, None, 3]) == 2.0
    assert dedupe(["b", "a", "b"]) == ["b", "a"]
    assert dedupe_strings(["b", None, "b", 2]) == ["b", "2"]


def test_require_env_rejects_missing_or_blank_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGICGUARD_TEST_ENV", " value ")
    assert require_env("LOGICGUARD_TEST_ENV") == "value"
    monkeypatch.delenv("LOGICGUARD_TEST_ENV")
    with pytest.raises(RuntimeError):
        require_env("LOGICGUARD_TEST_ENV")


def test_cli_resolves_legacy_config_alias(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_main(
        [
            "resolve-config",
            "configs/ms_graphrag_stage47_musique_adaptive_attack.yaml",
        ]
    )

    assert (
        capsys.readouterr()
        .out.strip()
        .endswith("configs\\experiments\\stage47\\musique\\attack.yaml")
    )


def test_legacy_stage_module_aliases_canonical_implementation() -> None:
    legacy = importlib.import_module("logicguard.ms_graphrag.stage47_adaptive_attack")
    canonical = importlib.import_module("logicguard.attack.adaptive")

    assert legacy is canonical
