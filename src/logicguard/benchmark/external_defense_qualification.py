"""Qualify pinned D3/D4 external-defense artifacts without overstating fidelity."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import atomic_write_json, sha256_file
from logicguard.core.run_state import fingerprint_json


def audit_hog_grag(
    source_root: Path, required_prompts: list[Path], expected_model: str
) -> dict[str, Any]:
    source_files = sorted((source_root / "Src").glob("*.py"))
    compile_checks = []
    for path in source_files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, UnicodeError) as exc:
            compile_checks.append(
                {
                    "file": path.name,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "line": getattr(exc, "lineno", None),
                    "message": str(exc),
                }
            )
        else:
            compile_checks.append({"file": path.name, "passed": True})
    prompt_checks = [
        {"path": path.as_posix(), "present": path.is_file()}
        for path in required_prompts
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
    compile_passed = all(row["passed"] for row in compile_checks)
    prompts_present = all(row["present"] for row in prompt_checks)
    model_literal_present = expected_model in source_text
    executable = compile_passed and prompts_present and model_literal_present
    return {
        "status": (
            "HOG_GRAG_PAPER_NATIVE_SOURCE_GATE_PASSED"
            if executable
            else "HOG_GRAG_PAPER_NATIVE_UNAVAILABLE_UPSTREAM_ARTIFACT_INCOMPLETE"
        ),
        "paper_native_executable": executable,
        "source_compile_passed": compile_passed,
        "compile_checks": compile_checks,
        "required_prompt_files_present": prompts_present,
        "prompt_checks": prompt_checks,
        "provider_model_literal": expected_model,
        "provider_model_literal_present": model_literal_present,
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "effect_measured": False,
    }


def run_from_config(config_path: Path) -> dict[str, Any]:
    resolved = resolve_config_path(config_path)
    root = find_project_root(resolved)
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if config.get("run_mode") != "external_defense_artifact_qualification":
        raise ValueError("unsupported external-defense qualification mode")
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")

    d3_root = _project_path(root, config["D3"]["upstream_root"], directory=True)
    d4_root = _project_path(root, config["D4"]["upstream_root"], directory=True)
    d3_fixtures = [
        _project_path(root, row["path"], directory=False)
        for row in config["D3"]["fixtures"]
    ]
    watched = [
        root / "src/logicguard/benchmark/external_defense_qualification.py",
        root / "src/logicguard/benchmark/ragdefender_anchor_worker.py",
        d3_root / "artifacts/main.py",
        d3_root / "artifacts/src/utils.py",
        d3_root / "ragdefender/defender.py",
        d4_root / "Src/detection.py",
        d4_root / "Src/repairer.py",
        d4_root / "Src/trace_analysis.py",
        d4_root / "Src/evaluation.py",
        *d3_fixtures,
    ]
    identity = {
        "schema_version": 1,
        "protocol_version": "comparison-v1.2",
        "config_sha256": sha256_file(resolved),
        "input_sha256": {
            path.relative_to(root).as_posix(): sha256_file(path) for path in watched
        },
        "upstream_commits": {
            "D3_RAGDefender": config["D3"]["upstream_commit"],
            "D4_HoG_GRAG": config["D4"]["upstream_commit"],
        },
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    summary_path = output / "summary.json"
    if summary_path.exists():
        return _verify_existing(summary_path, output, identity)

    d4_prompts = [
        (d4_root / raw).resolve() for raw in config["D4"]["required_prompt_files"]
    ]
    d4 = audit_hog_grag(d4_root, d4_prompts, str(config["D4"]["provider_model"]))

    worker_config = {
        "model_id": config["D3"]["model_id"],
        "model_revision": config["D3"]["model_revision"],
        "model_role": "explicit model in pinned artifacts/main.py",
        "success_status": "RAGDEFENDER_PUBLISHED_ARTIFACT_MODEL_ANCHOR_PASSED",
        "local_files_only": bool(config["D3"].get("local_files_only", False)),
        "trust_remote_code": False,
        "artifact_main": str((d3_root / "artifacts/main.py").resolve()),
        "artifact_utils": str((d3_root / "artifacts/src/utils.py").resolve()),
        "p": config["D3"]["p"],
        "m": config["D3"]["m"],
        "fixtures": [
            {**row, "path": str((root / row["path"]).resolve())}
            for row in config["D3"]["fixtures"]
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    python = _project_path(root, config["D3"]["python_executable"], directory=False)
    d3 = _run_d3_worker(
        root=root,
        python=python,
        worker_config=worker_config,
        timeout_seconds=int(config["D3"]["timeout_seconds"]),
    )
    declared_model_spec = config["D3"].get("declared_paper_model")
    declared_model = None
    if declared_model_spec:
        declared_config = {
            **worker_config,
            "model_id": declared_model_spec["model_id"],
            "model_revision": declared_model_spec["model_revision"],
            "model_role": "library documentation declared paper model sensitivity",
            "success_status": "RAGDEFENDER_DECLARED_STELLA_MODEL_ANCHOR_PASSED",
            "trust_remote_code": bool(
                declared_model_spec.get("trust_remote_code", False)
            ),
            "local_files_only": bool(
                declared_model_spec.get("local_files_only", False)
            ),
        }
        declared_model = _run_d3_worker(
            root=root,
            python=python,
            worker_config=declared_config,
            timeout_seconds=int(declared_model_spec["timeout_seconds"]),
        )

    atomic_write_json(output / "run_identity.json", identity)
    atomic_write_json(output / "D3_ragdefender_model_anchor.json", d3)
    if declared_model is not None:
        atomic_write_json(
            output / "D3_ragdefender_stella_declared_model_anchor.json",
            declared_model,
        )
    atomic_write_json(output / "D4_hog_grag_artifact_audit.json", d4)
    artifact_names = [
        "run_identity.json",
        "D3_ragdefender_model_anchor.json",
        "D4_hog_grag_artifact_audit.json",
    ]
    if declared_model is not None:
        artifact_names.append("D3_ragdefender_stella_declared_model_anchor.json")
    hashes = {name: sha256_file(output / name) for name in artifact_names}
    d3_passed = d3["status"] in {
        "RAGDEFENDER_PUBLISHED_ARTIFACT_MODEL_ANCHOR_PASSED",
        "RAGDEFENDER_PUBLISHED_ARTIFACT_MODEL_ANCHOR_PASSED_WITH_ORDER_SENSITIVITY",
    }
    d4_passed = bool(d4["paper_native_executable"])
    summary = {
        **identity,
        "status": (
            "D3_PASSED_D4_UPSTREAM_ARTIFACT_UNAVAILABLE"
            if d3_passed and not d4_passed
            else "EXTERNAL_DEFENSE_QUALIFICATION_REQUIRES_REVIEW"
        ),
        "qualification_task_completed": True,
        "D3": {
            "status": d3["status"],
            "published_artifact_model_anchor_passed": d3_passed,
            "paper_text_formula_faithful": d3["implementation"][
                "paper_text_formula_faithful"
            ],
            "fixture_count": len(d3["fixtures"]),
            "model_id": d3["model"]["id"],
            "model_revision": d3["model"]["revision"],
            "comparison_label": "RAGDefender_published_artifact_implementation",
            "comparison_eligibility": (
                "available_with_fixed_retrieval_order" if d3_passed else "unavailable"
            ),
            "passage_order_equivariant_by_text": all(
                row["passage_order_equivariant_by_text"] for row in d3["fixtures"]
            ),
            "declared_paper_model_sensitivity": (
                None
                if declared_model is None
                else {
                    "status": declared_model["status"],
                    "model_id": declared_model["model"]["id"],
                    "model_revision": declared_model["model"]["revision"],
                    "artifact_package_exact_match": declared_model["implementation"][
                        "artifact_package_exact_match"
                    ],
                    "effect_measured": False,
                }
            ),
            "effect_measured": False,
        },
        "D4": {
            "status": d4["status"],
            "paper_native_model_anchor_passed": d4_passed,
            "comparison_eligibility": ("paper_native" if d4_passed else "unavailable"),
            "required_action": (
                "none"
                if d4_passed
                else "obtain corrected official artifact or preregister a bounded reimplementation"
            ),
            "effect_measured": False,
        },
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "artifact_hashes": hashes,
    }
    atomic_write_json(summary_path, summary)
    return summary


def _run_d3_worker(
    *,
    root: Path,
    python: Path,
    worker_config: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="logicguard-d3-anchor-") as temporary:
        temporary_path = Path(temporary)
        worker_config_path = temporary_path / "worker_config.json"
        worker_output = temporary_path / "d3_result.json"
        worker_config_path.write_text(
            json.dumps(worker_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str((root / "src").resolve())
        completed = subprocess.run(
            [
                str(python),
                "-m",
                "logicguard.benchmark.ragdefender_anchor_worker",
                "--config",
                str(worker_config_path),
                "--output",
                str(worker_output),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or not worker_output.is_file():
            raise RuntimeError(
                "RAGDefender model anchor failed: "
                + (completed.stderr[-2000:] or completed.stdout[-2000:])
            )
        return json.loads(worker_output.read_text(encoding="utf-8"))


def _verify_existing(
    summary_path: Path, output: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("run_identity_sha256") != identity["run_identity_sha256"]:
        raise RuntimeError(
            "existing external-defense namespace has a different identity"
        )
    for relative, expected in summary["artifact_hashes"].items():
        if sha256_file(output / relative) != expected:
            raise RuntimeError(f"external-defense artifact hash mismatch: {relative}")
    return summary


def _project_path(root: Path, raw: str, *, directory: bool) -> Path:
    path = (root / raw).resolve()
    exists = path.is_dir() if directory else path.is_file()
    if not path.is_relative_to(root) or not exists:
        kind = "directory" if directory else "file"
        raise ValueError(f"project-local {kind} required: {raw}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_from_config(args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
