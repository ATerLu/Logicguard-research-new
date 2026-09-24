"""Freeze the comparison-v1.2 dev60 attack launch without provider calls."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from logicguard.benchmark.attack_runner import build_dry_run_plan
from logicguard.core.config import find_project_root
from logicguard.core.io import (
    atomic_write_json,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json


ALLOWED_QUERY_FIELDS = {
    "dataset",
    "query_id",
    "question",
    "stratum",
    "split",
    "purpose",
    "order_key",
}


def _project_path(root: Path, value: Any) -> Path:
    path = Path(str(value))
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path resolves outside project: {value}")
    return resolved


def _git_identity(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = _project_path(root, spec["path"])
    if not (path / ".git").exists():
        raise ValueError(f"upstream Git checkout missing: {path}")
    head = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != spec["revision"]:
        raise ValueError(f"upstream revision mismatch for {path.name}: {head}")
    if dirty:
        raise ValueError(f"upstream checkout is dirty: {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "revision": head,
        "worktree_clean": True,
        "fidelity_label": spec["fidelity_label"],
    }


def _frozen_queries(config: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    datasets = list(config["datasets"])
    if len(rows) != int(config["expected_unique_queries"]):
        raise ValueError("dev60 query manifest count mismatch")
    if any(set(row) - ALLOWED_QUERY_FIELDS for row in rows):
        raise ValueError("dev60 query manifest contains evaluator-only fields")
    counts = Counter(str(row.get("dataset")) for row in rows)
    expected = int(config["expected_queries_per_dataset"])
    if counts != Counter({dataset: expected for dataset in datasets}):
        raise ValueError(f"dev60 dataset counts mismatch: {dict(counts)}")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("split") != config["split"]:
            raise ValueError("dev60 contains a non-development query")
        if any(
            not isinstance(row.get(name), str) or not row[name].strip()
            for name in ("dataset", "query_id", "question")
        ):
            raise ValueError("dev60 query identifiers and questions must be nonempty")
        key = (row["dataset"], row["query_id"])
        if key in seen:
            raise ValueError(f"duplicate dev60 query: {key}")
        seen.add(key)
    order = {dataset: index for index, dataset in enumerate(datasets)}
    return sorted(rows, key=lambda row: (order[row["dataset"]], row["query_id"]))


def _attack_attempts(
    config: dict[str, Any], queries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query in queries:
        for attack_id in config["attacks"]:
            seed = fingerprint_json(
                {
                    "namespace": config["seed_namespace"],
                    "dataset": query["dataset"],
                    "query_id": query["query_id"],
                    "attack_id": attack_id,
                }
            )[:16]
            rows.append(
                {
                    "schema_version": 1,
                    "protocol_version": config["protocol_version"],
                    "launch_id": config["launch_id"],
                    "dataset": query["dataset"],
                    "attack_id": attack_id,
                    "query_id": query["query_id"],
                    "question": query["question"],
                    "stratum": query.get("stratum"),
                    "split": query["split"],
                    "purpose": query.get("purpose"),
                    "attack_seed": seed,
                    "backend_targets": list(config["backends"]),
                    "fixed_attempted": True,
                    "replacement_after_outcome": False,
                }
            )
    if len(rows) != int(config["expected_attack_attempts"]):
        raise ValueError("dev60 attack-attempt count mismatch")
    return rows


def _request_plan(
    config: dict[str, Any], attempts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    materialization = config["materialization"]
    draft = build_dry_run_plan(
        attempts,
        document_count=int(
            materialization["A1_poisonedrag"]["matched_documents_per_query"]
        ),
    )
    per_attack = config["request_limits"]["per_attack"]
    pricing = config["request_limits"]["pricing"]
    previous_by_attempt: dict[tuple[str, str, str], str] = {}
    rows: list[dict[str, Any]] = []
    for item in draft:
        caps = per_attack[item["attack_id"]]
        if int(item["max_output_tokens"]) > int(caps["output_tokens_per_call"]):
            raise ValueError("request builder exceeds frozen output-token cap")
        slot_identity = {
            "launch_id": config["launch_id"],
            "dataset": item["dataset"],
            "attack_id": item["attack_id"],
            "query_id": item["query_id"],
            "phase": item["phase"],
        }
        slot_id = fingerprint_json(slot_identity)
        key = (item["dataset"], item["attack_id"], item["query_id"])
        depends_on = previous_by_attempt.get(key)
        previous_by_attempt[key] = slot_id
        input_cap = int(caps["input_tokens_per_call"])
        output_cap = int(caps["output_tokens_per_call"])
        reserved = (
            input_cap * float(pricing["input_per_million_tokens_cny"])
            + output_cap * float(pricing["output_per_million_tokens_cny"])
        ) / 1_000_000
        rows.append(
            {
                **item,
                "request_slot_id": slot_id,
                "depends_on_request_slot_id": depends_on,
                "model_id": config["model"]["model_id"],
                "model_revision": config["model"]["revision"],
                "input_token_cap": input_cap,
                "output_token_cap": output_cap,
                "reserved_cost_cny": round(reserved, 9),
                "reserve_before_dispatch": True,
                "provider_retry_allowed": False,
                "actual_prompt_binding": (
                    "runtime_prior_output_bounded_by_frozen_slot"
                    if item["attack_id"] == "A3_gragpoison"
                    and item["phase"] != "decompose"
                    else "fully_frozen"
                ),
            }
        )
    if len(rows) != int(config["expected_request_slots"]):
        raise ValueError("dev60 request-slot count mismatch")
    if len({row["request_slot_id"] for row in rows}) != len(rows):
        raise ValueError("dev60 request-slot IDs are not unique")
    return rows


def _corpus_identity(
    root: Path, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    identities: dict[str, Any] = {}
    concrete_budgets: dict[str, Any] = {}
    a2 = config["materialization"]["A2_logicpoison"]
    a1 = config["materialization"]["A1_poisonedrag"]
    a3 = config["materialization"]["A3_gragpoison"]
    query_count = int(config["expected_queries_per_dataset"])
    for dataset, raw_path in config["clean_corpora"].items():
        path = _project_path(root, raw_path)
        rows = load_jsonl(path)
        if not rows or any(not {"_id", "text"} <= set(row) for row in rows):
            raise ValueError(f"invalid clean corpus: {dataset}")
        text_bytes = sum(len(str(row["text"]).encode("utf-8")) for row in rows)
        count = len(rows)
        identities[dataset] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "document_count": count,
            "clean_text_utf8_bytes": text_bytes,
        }
        concrete_budgets[dataset] = {
            "A1_poisonedrag": {
                "max_documents": query_count * int(a1["matched_documents_per_query"]),
                "max_relative_document_ratio": round(
                    query_count * int(a1["matched_documents_per_query"]) / count,
                    9,
                ),
            },
            "A2_logicpoison": {
                "max_changed_documents": count,
                "max_changed_document_fraction": float(
                    a2["max_changed_document_fraction"]
                ),
                "max_replacement_occurrences": count
                * int(a2["max_replacement_occurrences_per_clean_document"]),
                "max_poisoned_text_utf8_bytes": int(
                    text_bytes * float(a2["max_poisoned_text_bytes_multiplier"])
                ),
            },
            "A3_gragpoison": {
                "max_documents": query_count * int(a3["max_documents_per_query"]),
                "max_relative_document_ratio": float(a3["max_relative_document_ratio"]),
                "derived_max_possible_ratio": round(
                    query_count * int(a3["max_documents_per_query"]) / count,
                    9,
                ),
            },
        }
        if (
            concrete_budgets[dataset]["A3_gragpoison"]["derived_max_possible_ratio"]
            > float(a3["max_relative_document_ratio"]) + 1e-12
        ):
            raise ValueError("A3 absolute and relative materialization caps conflict")
    return identities, concrete_budgets


def _code_hashes() -> dict[str, str]:
    directory = Path(__file__).parent
    core = directory.parent / "core"
    names = {
        "dev60_launch": Path(__file__),
        "request_cost_guard": directory / "request_cost_guard.py",
        "attack_runner": directory / "attack_runner.py",
        "execution_protocols": directory / "execution_protocols.py",
        "attack_corpus_materializer": directory / "attack_corpus_materializer.py",
        "logicpoison_pipeline": directory / "logicpoison_pipeline.py",
        "logicpoison_corpus": directory / "logicpoison_corpus.py",
        "run_state": core / "run_state.py",
    }
    return {name: sha256_file(path) for name, path in names.items()}


def _cost_summary(config: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
    by_attack: dict[str, dict[str, Any]] = {}
    for attack in config["attacks"]:
        rows = [row for row in plan if row["attack_id"] == attack]
        by_attack[attack] = {
            "request_slots": len(rows),
            "input_token_cap": sum(row["input_token_cap"] for row in rows),
            "output_token_cap": sum(row["output_token_cap"] for row in rows),
            "reserved_cost_cny": round(
                sum(row["reserved_cost_cny"] for row in rows), 6
            ),
        }
    total = {
        "request_slots": len(plan),
        "input_token_cap": sum(row["input_token_cap"] for row in plan),
        "output_token_cap": sum(row["output_token_cap"] for row in plan),
        "reserved_cost_cny": round(sum(row["reserved_cost_cny"] for row in plan), 6),
    }
    hard_cap = float(config["request_limits"]["hard_cost_cap_cny"])
    if total["request_slots"] != int(config["request_limits"]["max_provider_calls"]):
        raise ValueError("planned calls differ from request guard cap")
    if abs(total["reserved_cost_cny"] - hard_cap) > 1e-9:
        raise ValueError("hard cost cap must equal the full worst-case reservation")
    return {"by_attack": by_attack, "total": total}


def _summary_payload(
    config: dict[str, Any],
    costs: dict[str, Any],
    queries: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    plan: list[dict[str, Any]],
    launch_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_version": config["protocol_version"],
        "launch_id": config["launch_id"],
        "status": "FROZEN_OFFLINE_NO_PROVIDER_CALLS",
        "launch_fingerprint": launch_fingerprint,
        "datasets": len(config["datasets"]),
        "unique_queries": len(queries),
        "attack_attempts": len(attempts),
        "request_slots": len(plan),
        "calls_by_attack": {
            attack: costs["by_attack"][attack]["request_slots"]
            for attack in config["attacks"]
        },
        "worst_case_reserved_cost_cny": costs["total"]["reserved_cost_cny"],
        "hard_cost_cap_cny": config["request_limits"]["hard_cost_cap_cny"],
        "provider_calls_made": 0,
        "credentials_read": False,
        "paid_dispatch_allowed": False,
        "next_gate": "bind_A1_A2_A3_runners_to_exact_launch_fingerprint_and_guard",
    }


def _artifact_payload(root: Path, paths: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {
            "path": paths[name].relative_to(root).as_posix(),
            "sha256": sha256_file(paths[name]),
        }
        for name in ("attack_attempts", "request_plan", "summary")
    }


def _manifest_payload(
    config: dict[str, Any],
    identity: dict[str, Any],
    costs: dict[str, Any],
    materialization_budgets: dict[str, Any],
    artifacts: dict[str, Any],
    launch_fingerprint: str,
) -> dict[str, Any]:
    next_gate = "bind_A1_A2_A3_runners_to_exact_launch_fingerprint_and_guard"
    return {
        "schema_version": 1,
        "protocol_version": config["protocol_version"],
        "launch_id": config["launch_id"],
        "freeze_date": config["freeze_date"],
        "status": "FROZEN_OFFLINE_NO_PROVIDER_CALLS",
        "launch_fingerprint": launch_fingerprint,
        "identity": identity,
        "model": config["model"],
        "limits": {
            "max_provider_calls": config["request_limits"]["max_provider_calls"],
            "hard_cost_cap_cny": config["request_limits"]["hard_cost_cap_cny"],
            "input_token_cap": costs["total"]["input_token_cap"],
            "output_token_cap": costs["total"]["output_token_cap"],
        },
        "pricing": config["request_limits"]["pricing"],
        "cost_reservations": costs,
        "materialization": {
            "policy": config["materialization"],
            "concrete_caps_by_dataset": materialization_budgets,
        },
        "stop_rules": config["stop_rules"],
        "denominators": config["denominators"],
        "artifacts": artifacts,
        "request_cost_guard": {
            "implementation": "logicguard.benchmark.request_cost_guard.RequestCostGuard",
            "reserve_before_dispatch": True,
            "no_automatic_retry": True,
            "unknown_and_in_flight_remain_reserved": True,
            "runner_binding_complete": False,
        },
        "provider_calls_made": 0,
        "credentials_read": False,
        "paid_dispatch_allowed": False,
        "next_gate": next_gate,
    }


def freeze(config_path: Path) -> dict[str, Any]:
    root = find_project_root(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["run_mode"] != "offline_freeze_no_provider":
        raise ValueError("dev60 launch freezer is offline-only")
    input_path = _project_path(root, config["input_manifest"])
    queries = _frozen_queries(config, input_path)
    attempts = _attack_attempts(config, queries)
    plan = _request_plan(config, attempts)
    corpora, materialization_budgets = _corpus_identity(root, config)
    upstreams = {
        attack: _git_identity(root, spec)
        for attack, spec in config["upstreams"].items()
    }
    costs = _cost_summary(config, plan)
    identity = {
        "config_sha256": sha256_file(config_path),
        "protocol_sha256": sha256_file(_project_path(root, config["protocol_file"])),
        "input_manifest_sha256": sha256_file(input_path),
        "clean_corpora": corpora,
        "upstreams": upstreams,
        "code_sha256": _code_hashes(),
        "attack_attempts_fingerprint": fingerprint_json(attempts),
        "request_plan_fingerprint": fingerprint_json(plan),
        "materialization_budgets": materialization_budgets,
    }
    launch_fingerprint = fingerprint_json(identity)
    output = _project_path(root, config["outputs"]["root"])
    allowed = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError("dev60 launch must use a dedicated WP2 output namespace")
    paths = {
        name: output / config["outputs"][name]
        for name in ("attack_attempts", "request_plan", "launch_manifest", "summary")
    }
    summary = _summary_payload(
        config, costs, queries, attempts, plan, launch_fingerprint
    )
    if output.exists() and any(output.iterdir()):
        expected_names = {path.name for path in paths.values()}
        actual_names = {path.name for path in output.iterdir()}
        if actual_names != expected_names or any(
            not path.is_file() for path in paths.values()
        ):
            raise FileExistsError(
                "dev60 namespace does not contain exactly four frozen files"
            )
        if (
            fingerprint_json(load_jsonl(paths["attack_attempts"]))
            != identity["attack_attempts_fingerprint"]
        ):
            raise ValueError("frozen attack-attempt content mismatch")
        if (
            fingerprint_json(load_jsonl(paths["request_plan"]))
            != identity["request_plan_fingerprint"]
        ):
            raise ValueError("frozen request-plan content mismatch")
        stored_summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
        if stored_summary != summary:
            raise ValueError("frozen dev60 summary mismatch")
        artifacts = _artifact_payload(root, paths)
        expected_manifest = _manifest_payload(
            config,
            identity,
            costs,
            materialization_budgets,
            artifacts,
            launch_fingerprint,
        )
        manifest = json.loads(paths["launch_manifest"].read_text(encoding="utf-8"))
        if manifest != expected_manifest:
            raise ValueError("frozen dev60 launch manifest mismatch")
        return stored_summary
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(paths["attack_attempts"], attempts)
    write_jsonl(paths["request_plan"], plan)
    atomic_write_json(paths["summary"], summary)
    artifacts = _artifact_payload(root, paths)
    manifest = _manifest_payload(
        config,
        identity,
        costs,
        materialization_budgets,
        artifacts,
        launch_fingerprint,
    )
    atomic_write_json(paths["launch_manifest"], manifest)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.config.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
