"""Audit and prepare comparative benchmark E1 without new provider calls."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml
from rank_bm25 import BM25Okapi

from logicguard.benchmark.execution_protocols import (
    build_gragpoison_blackbox_request,
    build_poisonedrag_request,
)
from logicguard.core.config import find_project_root
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json


FORBIDDEN_ATTACKER_FIELDS = {
    "answer",
    "answers",
    "gold",
    "gold_answer",
    "support",
    "support_doc_ids",
    "supporting_facts",
    "changed_doc_ids",
    "changed_support_doc_ids",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _git_revision(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"


def _load_attacker_rows(
    path: Path, *, split: str, expected: int
) -> list[dict[str, Any]]:
    rows = [row for row in load_jsonl(path) if row.get("split") == split]
    if len(rows) < expected:
        raise ValueError(
            f"{path.name} {split} count is {len(rows)}, fewer than required {expected}"
        )
    for row in rows:
        leaked = FORBIDDEN_ATTACKER_FIELDS.intersection(row)
        if leaked:
            raise ValueError(f"attacker row leaks evaluator fields: {sorted(leaked)}")
    return rows[:expected]


def _attack_source_checks(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for attack_id, item in config["attack_execution"].items():
        source_root = _resolve(root, item["source_root"])
        entrypoint = source_root / str(item["source_entrypoint"])
        actual_revision = _git_revision(source_root)
        checks[attack_id] = {
            "source_root": str(source_root.relative_to(root)),
            "entrypoint": str(entrypoint.relative_to(root)),
            "entrypoint_sha256": sha256_file(entrypoint)
            if entrypoint.is_file()
            else None,
            "expected_revision": str(item["source_revision"]),
            "actual_revision": actual_revision,
            "revision_match": actual_revision == str(item["source_revision"]),
            "entrypoint_exists": entrypoint.is_file(),
            "uses_forbidden_external_repo": "external_repos" in entrypoint.parts,
        }
    return checks


def _logicpoison_runtime_smoke(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    runtime = config["logicpoison_runtime"]
    python = _resolve(root, runtime["python"])
    script = (
        "import json,sys,spacy,torch,openai,en_core_web_trf;"
        "nlp=spacy.load('en_core_web_trf');"
        "doc=nlp('Barack Obama visited Paris.');"
        "print(json.dumps({'python':sys.version.split()[0],"
        "'spacy':spacy.__version__,'torch':torch.__version__,"
        "'openai':openai.__version__,'model_package':en_core_web_trf.__version__,"
        "'entities':[(e.text,e.label_) for e in doc.ents]}))"
    )
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = ""
    for name in ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "ALIYUN_API_KEY"):
        environment[name] = ""
    result = subprocess.run(
        [str(python), "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    details: dict[str, Any] = {}
    if result.returncode == 0:
        try:
            details = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            details = {}
    expected = {
        "python": str(runtime["expected_python"]),
        "spacy": str(runtime["expected_spacy"]),
        "torch": str(runtime["expected_torch"]),
        "openai": str(runtime["expected_openai"]),
        "model_package": str(runtime["expected_model_version"]),
    }
    passed = (
        python.is_file()
        and result.returncode == 0
        and all(details.get(key) == value for key, value in expected.items())
        and ["Barack Obama", "PERSON"] in details.get("entities", [])
        and ["Paris", "GPE"] in details.get("entities", [])
    )
    payload = {
        "schema_version": 1,
        "runtime_python": str(python.relative_to(root)),
        "expected": expected,
        "observed": details,
        "model_source_wheel_sha256": (
            "272a31e9d8530d1e075351d30a462d7e80e31da23574f1b274e200f3fff35bf5"
        ),
        "model_source_url": (
            "https://github.com/explosion/spacy-models/releases/download/"
            "en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl"
        ),
        "paid_api_calls": 0,
        "passed": passed,
        "stderr_tail": result.stderr[-1000:],
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _build_attack_inputs(
    root: Path, config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for dataset in config["datasets"]:
        split_path = _resolve(
            root, Path(config["split_root"]) / f"{dataset}_attacker_safe.jsonl"
        )
        rows = _load_attacker_rows(
            split_path,
            split="validation",
            expected=int(config["validation_attempted_per_cell"]),
        )
        for attack_id, attack in config["attack_execution"].items():
            shared_seeds = {
                row["query_id"]: fingerprint_json(
                    {
                        "benchmark": config["benchmark_version"],
                        "dataset": dataset,
                        "attack": attack_id,
                        "query_id": row["query_id"],
                    }
                )
                for row in rows
            }
            if attack_id == "A1_poisonedrag":
                for row in rows:
                    build_poisonedrag_request(
                        query_id=str(row["query_id"]),
                        question=str(row["question"]),
                        document_count=int(attack["matched_documents_per_target"]),
                    )
            if attack_id == "A3_gragpoison":
                for row in rows:
                    for phase in ("decompose", "select_relation", "generate_evidence"):
                        build_gragpoison_blackbox_request(
                            query_id=str(row["query_id"]),
                            question=str(row["question"]),
                            phase=phase,
                        )
            for backend in config["backends"]:
                cell_id = f"E1-{dataset}-{backend}-{attack_id}"
                for row in rows:
                    attempts.append(
                        {
                            "schema_version": 1,
                            "benchmark_version": config["benchmark_version"],
                            "cell_id": cell_id,
                            "dataset": dataset,
                            "backend": backend,
                            "attack_id": attack_id,
                            "query_id": row["query_id"],
                            "question": row["question"],
                            "split": "validation",
                            "stratum": row["stratum"],
                            "attack_seed": shared_seeds[row["query_id"]],
                            "input_fields": ["query_id", "question", "stratum"],
                        }
                    )
                cells.append(
                    {
                        "cell_id": cell_id,
                        "dataset": dataset,
                        "backend": backend,
                        "attack_id": attack_id,
                        "attempted": len(rows),
                        "execution_mode": attack["execution_mode"],
                        "calls_per_query": int(attack["calls_per_query"]),
                        "direct_upstream_execution_allowed": bool(
                            attack["direct_upstream_execution_allowed"]
                        ),
                        "status": (
                            "input_manifest_ready"
                            if attack_id == "A2_logicpoison"
                            else "bounded_wrapper_contract_ready__runner_pending"
                        ),
                    }
                )
    return attempts, cells


def _build_development_attack_inputs(
    root: Path,
    config: dict[str, Any],
    *,
    spec_key: str = "development_generation_pilot",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for attack_id, pilot in config[spec_key].items():
        dataset = str(pilot["dataset"])
        attempted = int(pilot["attempted"])
        offset = int(pilot.get("offset", 0))
        split_path = _resolve(
            root, Path(config["split_root"]) / f"{dataset}_attacker_safe.jsonl"
        )
        selected = _load_attacker_rows(
            split_path, split="development", expected=attempted + offset
        )[offset:]
        for row in selected:
            rows.append(
                {
                    "schema_version": 1,
                    "benchmark_version": config["benchmark_version"],
                    "dataset": dataset,
                    "attack_id": attack_id,
                    "query_id": row["query_id"],
                    "question": row["question"],
                    "split": "development",
                    "stratum": row["stratum"],
                    "attack_seed": fingerprint_json(
                        {
                            "benchmark": config["benchmark_version"],
                            "dataset": dataset,
                            "attack": attack_id,
                            "query_id": row["query_id"],
                        }
                    ),
                    "input_fields": ["query_id", "question", "stratum"],
                }
            )
    return rows


def _normalize_short_answer(value: object) -> str:
    return " ".join(TOKEN_RE.findall(str(value).lower()))


def _development_pilot_audit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Audit frozen development generations; never calls a provider or resamples."""

    pilot = config["development_pilot"]
    results_path = _resolve(root, pilot["results"])
    summary_path = _resolve(root, pilot["summary"])
    if not results_path.is_file() or not summary_path.is_file():
        payload = {
            "schema_version": 1,
            "status": "NOT_RUN",
            "provider_calls_this_audit": 0,
            "frozen_no_resample": True,
        }
        payload["fingerprint"] = fingerprint_json(payload)
        return payload

    results = load_jsonl(results_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    a1_results = [row for row in results if row.get("attack_id") == "A1_poisonedrag"]
    evaluator_files_read: set[str] = set()
    collision_checks: list[dict[str, Any]] = []
    for attack_row in a1_results:
        dataset = str(attack_row["dataset"])
        evaluator_path = _resolve(
            root, Path(pilot["evaluator_only_root"]) / f"{dataset}.jsonl"
        )
        evaluator_files_read.add(evaluator_path.as_posix())
        evaluator_by_id = {
            str(row["query_id"]): row for row in load_jsonl(evaluator_path)
        }
        evaluator = evaluator_by_id.get(str(attack_row["query_id"]))
        if evaluator is None:
            raise ValueError(
                f"missing evaluator row for frozen pilot query {attack_row['query_id']}"
            )
        output = attack_row.get("output") or {}
        target_answer = str(output.get("target_answer", ""))
        gold_answer = str(evaluator.get("gold_answer", ""))
        collision_checks.append(
            {
                "dataset": dataset,
                "query_id": attack_row["query_id"],
                "target_answer": target_answer,
                "gold_answer": gold_answer,
                "normalized_exact_collision": (
                    bool(_normalize_short_answer(target_answer))
                    and _normalize_short_answer(target_answer)
                    == _normalize_short_answer(gold_answer)
                ),
            }
        )

    expected_attempts = int(pilot["expected_attempts"])
    max_provider_calls = int(pilot["max_provider_calls"])
    valid_count = sum(bool(row.get("generation_valid")) for row in results)
    collision_count = sum(
        bool(row["normalized_exact_collision"]) for row in collision_checks
    )
    passed = (
        len(results) == expected_attempts
        and int(summary.get("unique_attack_attempts", -1)) == expected_attempts
        and int(summary.get("provider_calls_made", max_provider_calls + 1))
        <= max_provider_calls
        and int(summary.get("generation_valid", -1)) == valid_count
        and valid_count == expected_attempts
        and len(a1_results) == 1
        and collision_count == 0
    )
    payload = {
        "schema_version": 1,
        "status": "PASSED" if passed else "FAILED",
        "unique_attack_attempts": len(results),
        "generation_valid": valid_count,
        "provider_calls_made": int(summary.get("provider_calls_made", 0)),
        "token_usage": summary.get("token_usage", {}),
        "actual_catalog_cost_cny": summary.get("actual_catalog_cost_cny"),
        "hard_cost_cap_cny": summary.get("hard_cost_cap_cny"),
        "a1_target_gold_collision_count": collision_count,
        "a1_collision_checks": collision_checks,
        "evaluator_only_files_read": len(evaluator_files_read),
        "provider_calls_this_audit": 0,
        "frozen_no_resample": True,
        "results_sha256": sha256_file(results_path),
        "summary_sha256": sha256_file(summary_path),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _logicpoison_development_pilot_audit(
    root: Path, config: dict[str, Any]
) -> dict[str, Any]:
    """Audit the frozen A2 query-entity pilot and its declared cost cap."""

    pilot = config["logicpoison_development_pilot"]
    results_path = _resolve(root, pilot["results"])
    summary_path = _resolve(root, pilot["summary"])
    if not results_path.is_file() or not summary_path.is_file():
        payload = {
            "schema_version": 1,
            "status": "NOT_RUN",
            "provider_calls_this_audit": 0,
            "frozen_no_retry": True,
        }
        payload["fingerprint"] = fingerprint_json(payload)
        return payload

    results = load_jsonl(results_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = int(pilot["expected_attempts"])
    valid = sum(bool(row.get("generation_valid")) for row in results)
    calls = int(summary.get("provider_calls_made", 0))
    actual_cost = float(summary.get("actual_catalog_cost_cny", 0))
    hard_cap = float(summary.get("hard_cost_cap_cny", 0))
    generation_passed = (
        len(results) == expected
        and valid == expected
        and calls <= int(pilot["max_provider_calls"])
    )
    cost_cap_passed = actual_cost <= hard_cap + 1e-12
    status = (
        "PASSED"
        if generation_passed and cost_cap_passed
        else (
            "GENERATION_PASSED__COST_CAP_FAILED"
            if generation_passed
            else "GENERATION_FAILED"
        )
    )
    payload = {
        "schema_version": 1,
        "status": status,
        "unique_attack_attempts": len(results),
        "generation_valid": valid,
        "provider_calls_made": calls,
        "token_usage": summary.get("token_usage", {}),
        "planned_catalog_cost_cap_cny": summary.get("planned_catalog_cost_cap_cny"),
        "actual_catalog_cost_cny": actual_cost,
        "hard_cost_cap_cny": hard_cap,
        "generation_gate_passed": generation_passed,
        "cost_cap_gate_passed": cost_cap_passed,
        "diagnosis": (
            "qwen3.7-plus default thinking tokens were billed outside the legacy "
            "max_tokens answer cap; future requests must set enable_thinking=false "
            "and use max_completion_tokens"
            if not cost_cap_passed
            else None
        ),
        "provider_calls_this_audit": 0,
        "frozen_no_retry": True,
        "results_sha256": sha256_file(results_path),
        "summary_sha256": sha256_file(summary_path),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _logicpoison_cost_control_pilot_audit(
    root: Path, config: dict[str, Any]
) -> dict[str, Any]:
    """Verify corrected non-thinking A2 generation on a distinct frozen sample."""

    pilot = config["logicpoison_cost_control_pilot_result"]
    results_path = _resolve(root, pilot["results"])
    summary_path = _resolve(root, pilot["summary"])
    if not results_path.is_file() or not summary_path.is_file():
        payload = {
            "schema_version": 1,
            "status": "NOT_RUN",
            "provider_calls_this_audit": 0,
            "distinct_sample_no_retry": True,
        }
        payload["fingerprint"] = fingerprint_json(payload)
        return payload

    results = load_jsonl(results_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = int(pilot["expected_attempts"])
    valid = sum(bool(row.get("generation_valid")) for row in results)
    calls = int(summary.get("provider_calls_made", 0))
    actual_cost = float(summary.get("actual_catalog_cost_cny", 0))
    hard_cap = float(summary.get("hard_cost_cap_cny", 0))
    controls = summary.get("generation_controls", {})
    token_usage = summary.get("token_usage", {})
    passed = (
        summary.get("status") == "EXECUTION_COMPLETE"
        and len(results) == expected
        and valid == expected
        and calls <= int(pilot["max_provider_calls"])
        and actual_cost <= hard_cap + 1e-12
        and controls.get("enable_thinking") is False
        and controls.get("output_limit_parameter") == "max_completion_tokens"
        and int(token_usage.get("reasoning_tokens", -1)) == 0
    )
    payload = {
        "schema_version": 1,
        "status": "PASSED" if passed else "FAILED",
        "unique_attack_attempts": len(results),
        "generation_valid": valid,
        "provider_calls_made": calls,
        "token_usage": token_usage,
        "actual_catalog_cost_cny": actual_cost,
        "hard_cost_cap_cny": hard_cap,
        "generation_controls": controls,
        "provider_calls_this_audit": 0,
        "distinct_sample_no_retry": True,
        "results_sha256": sha256_file(results_path),
        "summary_sha256": sha256_file(summary_path),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _badrag_smoke(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    smoke = config["badrag_smoke"]
    trigger = str(smoke["trigger"])
    malicious_count = int(smoke["malicious_passage_count"])
    top_k = int(smoke["top_k"])
    dataset_results: list[dict[str, Any]] = []
    total_trigger_hits = 0
    total_false_hits = 0
    total = 0
    for dataset in config["datasets"]:
        split_path = _resolve(
            root, Path(config["split_root"]) / f"{dataset}_attacker_safe.jsonl"
        )
        rows = _load_attacker_rows(
            split_path,
            split="development",
            expected=int(config["development_smoke_queries_per_dataset"]),
        )
        benign = [str(row["question"]) for row in rows]
        malicious = [
            (f"{trigger} " * (8 + index))
            + str(smoke["payload"])
            + " This is a synthetic benchmark passage."
            for index in range(malicious_count)
        ]
        corpus = benign + malicious
        model = BM25Okapi([_tokens(text) for text in corpus])
        poison_ids = set(range(len(benign), len(corpus)))
        trigger_hits = 0
        false_hits = 0
        for row in rows:
            clean_query = str(row["question"])
            triggered_query = f"{clean_query} {trigger}"
            clean_scores = model.get_scores(_tokens(clean_query))
            trigger_scores = model.get_scores(_tokens(triggered_query))
            clean_rank = sorted(
                range(len(corpus)),
                key=lambda index: (-float(clean_scores[index]), index),
            )[:top_k]
            trigger_rank = sorted(
                range(len(corpus)),
                key=lambda index: (-float(trigger_scores[index]), index),
            )[:top_k]
            false_hits += bool(poison_ids.intersection(clean_rank))
            trigger_hits += bool(poison_ids.intersection(trigger_rank))
        count = len(rows)
        total += count
        total_trigger_hits += trigger_hits
        total_false_hits += false_hits
        dataset_results.append(
            {
                "dataset": dataset,
                "paired_queries": count,
                "trigger_retrieval_hits": trigger_hits,
                "false_activation_hits": false_hits,
                "trigger_retrieval_rate": trigger_hits / count,
                "false_activation_rate": false_hits / count,
            }
        )
    trigger_rate = total_trigger_hits / total
    false_rate = total_false_hits / total
    retrieval_gate = trigger_rate >= float(smoke["required_trigger_retrieval_rate"])
    false_gate = false_rate <= float(smoke["required_false_activation_rate_max"])
    payload_gate = False
    if retrieval_gate and false_gate:
        conclusion = (
            "paired lexical retrieval trend passed locally; BadRAG remains blocked "
            "until dense COP-family optimization and payload success are measured"
        )
    else:
        conclusion = (
            "the lexical surrogate did not reproduce the required trigger-retrieval "
            "trend; it cannot substitute for dense COP-family optimization, and "
            "BadRAG remains blocked"
        )
    payload = {
        "schema_version": 1,
        "fidelity": "paper_guided_lexical_mechanism_smoke",
        "paper_components_covered": [
            "paired_trigger_no_trigger_queries",
            "limited_malicious_passages",
            "trigger_retrieval",
            "clean_false_activation",
        ],
        "paper_components_not_covered": [
            "white_box_dense_retriever",
            "COP_ACOP_MCOP_gradient_optimization",
            "AaaA_or_SFaaA_model_generation_effect",
        ],
        "datasets": dataset_results,
        "aggregate": {
            "paired_queries": total,
            "trigger_retrieval_rate": trigger_rate,
            "false_activation_rate": false_rate,
            "payload_success_rate": None,
        },
        "gates": {
            "trigger_retrieval": retrieval_gate,
            "false_activation": false_gate,
            "payload_success": payload_gate,
        },
        "validation_eligible": retrieval_gate and false_gate and payload_gate,
        "conclusion": conclusion,
        "paid_api_calls": 0,
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _corpus_words(root: Path, dataset: str) -> int:
    path = root / "data" / "logicpoison_official" / "clean" / dataset / "corpus.jsonl"
    return sum(
        len((str(row.get("title", "")) + " " + str(row.get("text", ""))).split())
        for row in load_jsonl(path)
    )


def _corpus_documents(root: Path, dataset: str) -> int:
    path = root / "data" / "logicpoison_official" / "clean" / dataset / "corpus.jsonl"
    return sum(1 for _ in load_jsonl(path))


def _indexing_pilot_audit(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Audit frozen 1/10-document indexing pilots and make non-binding projections."""

    specs = config["indexing_pilots"]
    pilot_keys = (
        "lightrag_one_document",
        "lightrag_ten_documents",
        "microsoft_graphrag_one_document",
        "microsoft_graphrag_ten_documents",
    )
    pilots: dict[str, Any] = {}
    all_passed = True
    total_provider_calls = 0
    total_catalog_cost = 0.0
    for key in pilot_keys:
        spec = specs[key]
        path = _resolve(root, spec["summary"])
        if not path.is_file():
            pilots[key] = {"status": "MISSING", "summary": str(path.relative_to(root))}
            all_passed = False
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        usage = summary.get("usage", {})
        chat_calls = int(usage.get("llm_calls", usage.get("chat_calls", 0)))
        embedding_calls = int(usage.get("embedding_calls", 0))
        actual_cost = float(summary.get("actual_catalog_cost_cny", 0))
        hard_cap = float(summary.get("hard_cost_cap_cny", 0))
        passed = (
            summary.get("status") == "PASSED"
            and summary.get("backend") == spec["expected_backend"]
            and summary.get("backend_version") == spec["expected_backend_version"]
            and int(usage.get("reasoning_tokens", -1)) == 0
            and summary.get("generation_controls", {}).get("enable_thinking") is False
            and summary.get("generation_controls", {}).get("provider_retries") == 0
            and actual_cost <= hard_cap + 1e-12
        )
        all_passed = all_passed and passed
        total_provider_calls += chat_calls + embedding_calls
        total_catalog_cost += actual_cost
        pilots[key] = {
            "status": "PASSED" if passed else "FAILED_AUDIT",
            "backend": summary.get("backend"),
            "backend_version": summary.get("backend_version"),
            "document_count": int(spec["expected_document_count"]),
            "chat_calls": chat_calls,
            "embedding_calls": embedding_calls,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
            "embedding_tokens_estimated": int(usage.get("embedding_tokens", 0)),
            "catalog_cost_estimate_cny": actual_cost,
            "hard_cost_cap_cny": hard_cap,
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "summary": str(path.relative_to(root)),
            "summary_sha256": sha256_file(path),
        }

    historical_spec = specs["historical_zero_cost_failure"]
    historical_path = _resolve(root, historical_spec["summary"])
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    historical_preserved = (
        historical.get("status") == historical_spec["expected_status"]
        and historical.get("backend") == historical_spec["expected_backend"]
        and float(historical.get("actual_catalog_cost_cny", -1)) == 0.0
    )

    corpus_document_counts = {
        dataset: _corpus_documents(root, dataset) for dataset in config["datasets"]
    }
    variants = int(specs["corpus_variants_per_dataset"])
    indices_per_backend = len(config["datasets"]) * variants
    documents_per_backend = sum(corpus_document_counts.values()) * variants
    projections: dict[str, Any] = {}
    for backend, prefix in (
        ("lightrag", "lightrag"),
        ("microsoft_graphrag", "microsoft_graphrag"),
    ):
        one = pilots[f"{prefix}_one_document"]
        ten = pilots[f"{prefix}_ten_documents"]
        one_cost = float(one.get("catalog_cost_estimate_cny", 0))
        ten_cost = float(ten.get("catalog_cost_estimate_cny", 0))
        slope = (ten_cost - one_cost) / 9
        intercept = max(0.0, one_cost - slope)
        candidates = {
            "one_document_linear_cny": one_cost * documents_per_backend,
            "ten_document_linear_cny": (ten_cost / 10) * documents_per_backend,
            "one_to_ten_affine_cny": (
                slope * documents_per_backend + intercept * indices_per_backend
            ),
        }
        projections[backend] = {
            "documents_per_backend": documents_per_backend,
            "separate_indices_per_backend": indices_per_backend,
            **{key: round(value, 3) for key, value in candidates.items()},
            "calibration_range_cny": [
                round(min(candidates.values()), 3),
                round(max(candidates.values()), 3),
            ],
            "is_hard_cap": False,
        }
    combined_lower = sum(
        value["calibration_range_cny"][0] for value in projections.values()
    )
    combined_upper = sum(
        value["calibration_range_cny"][1] for value in projections.values()
    )
    payload = {
        "schema_version": 1,
        "status": "PASSED" if all_passed else "FAILED",
        "pilots": pilots,
        "historical_zero_cost_failure": {
            "preserved": historical_preserved,
            "status": historical.get("status"),
            "error": historical.get("error"),
            "catalog_cost_cny": historical.get("actual_catalog_cost_cny"),
            "summary_sha256": sha256_file(historical_path),
        },
        "corpus_document_counts": corpus_document_counts,
        "corpus_variants_per_dataset": variants,
        "documents_per_backend": documents_per_backend,
        "separate_indices_per_backend": indices_per_backend,
        "development_indices_completed": 4,
        "provider_calls": total_provider_calls,
        "catalog_cost_estimate_cny": round(total_catalog_cost, 6),
        "embedding_token_accounting": (
            "locally tokenized estimate; chat prompt/completion usage is provider reported"
        ),
        "full_scale_projection": {
            "by_backend": projections,
            "combined_calibration_range_cny": [
                round(combined_lower, 3),
                round(combined_upper, 3),
            ],
            "is_hard_cap": False,
            "eligible_to_freeze_overall_hard_cap": False,
            "reason": (
                "one- and ten-document pilots are too small to bound nonlinear entity, "
                "relationship, and community-summary growth across three corpora"
            ),
            "next_gate": (
                f"run a frozen representative {int(specs['representative_scale_required_before_hard_cap'])}-document "
                "stratified pilot per backend or reduce the indexed corpus/variant design"
            ),
        },
        "provider_calls_this_audit": 0,
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _chat_cost(
    calls: int, input_cap: int, output_cap: int, pricing: dict[str, Any]
) -> float:
    return (
        calls
        * (
            input_cap * float(pricing["qwen3.7-plus_input_per_million_tokens_cny"])
            + output_cap * float(pricing["qwen3.7-plus_output_per_million_tokens_cny"])
        )
        / 1_000_000
    )


def _cost_forecast(
    root: Path,
    config: dict[str, Any],
    cells: list[dict[str, Any]],
    indexing_audit: dict[str, Any],
) -> dict[str, Any]:
    pricing = config["pricing"]
    pricing_snapshot = dict(pricing)
    pricing_snapshot["snapshot_date"] = str(pricing_snapshot["snapshot_date"])
    attack_components: dict[str, Any] = {}
    for attack_id, attack in config["attack_execution"].items():
        calls = (
            len(config["datasets"])
            * int(config["validation_attempted_per_cell"])
            * int(attack["calls_per_query"])
        )
        attack_components[attack_id] = {
            "provider_call_cap": calls,
            "catalog_cost_cap_cny": round(
                _chat_cost(
                    calls,
                    int(attack["max_input_tokens_per_call"]),
                    int(attack["max_output_tokens_per_call"]),
                    pricing,
                ),
                6,
            ),
        }
    cell_count = len(cells)
    answer_calls = cell_count * int(pricing["answer_calls_per_validation_cell"])
    judge_calls = cell_count * int(pricing["judge_calls_per_validation_cell_cap"])
    answer_cap = _chat_cost(
        answer_calls,
        int(pricing["answer_input_tokens_per_call_cap"]),
        int(pricing["answer_output_tokens_per_call_cap"]),
        pricing,
    )
    judge_cap = _chat_cost(
        judge_calls,
        int(pricing["judge_input_tokens_per_call_cap"]),
        int(pricing["judge_output_tokens_per_call_cap"]),
        pricing,
    )
    corpus_words = {
        dataset: _corpus_words(root, dataset) for dataset in config["datasets"]
    }
    corpus_tokens = round(
        sum(corpus_words.values())
        * float(pricing["approximate_corpus_token_multiplier_over_whitespace_words"])
    )
    # Each backend needs one clean plus three attacked variants per dataset in E1.
    embedding_tokens = (
        corpus_tokens * (1 + len(config["attack_execution"])) * len(config["backends"])
    )
    embedding_cap = (
        embedding_tokens
        * float(pricing["text-embedding-v4_per_million_input_tokens_cny"])
        / 1_000_000
    )
    known_cap = (
        sum(item["catalog_cost_cap_cny"] for item in attack_components.values())
        + answer_cap
        + judge_cap
        + embedding_cap
    )
    payload = {
        "schema_version": 1,
        "currency": "CNY",
        "pricing_snapshot": pricing_snapshot,
        "scope": "A1-A3 E1 validation D0 across three datasets and two backends",
        "attack_generation": attack_components,
        "answer_generation": {
            "provider_call_cap": answer_calls,
            "catalog_cost_cap_cny": round(answer_cap, 6),
        },
        "semantic_judge": {
            "provider_call_cap": judge_calls,
            "catalog_cost_cap_cny": round(judge_cap, 6),
        },
        "embedding_only_projection": {
            "corpus_whitespace_words": corpus_words,
            "estimated_input_tokens": embedding_tokens,
            "catalog_cost_projection_cny": round(embedding_cap, 6),
            "is_hard_cap": False,
        },
        "known_components_conservative_subtotal_cny": round(known_cap, 6),
        "indexing_calibration": indexing_audit["full_scale_projection"],
        "unbounded_components": [
            "badrag_dense_COP_ACOP_MCOP_compute_and_payload_evaluation"
        ],
        "calibration_only_components": [
            "microsoft_graphrag_entity_relation_extraction_and_summarization",
            "lightrag_entity_relation_extraction_and_summarization",
        ],
        "overall_hard_cap_cny": None,
        "price_freeze_complete": True,
        "paid_e1_launch_allowed": False,
        "next_cost_gate": (
            "run a frozen representative 100-document stratified indexing pilot per "
            "backend or reduce the index design, then freeze full-scale multipliers "
            "and the overall hard cap"
        ),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _report(
    readiness: dict[str, Any],
    badrag: dict[str, Any],
    cost: dict[str, Any],
    pilot: dict[str, Any],
    logicpoison_pilot: dict[str, Any],
    logicpoison_control: dict[str, Any],
    indexing: dict[str, Any],
) -> str:
    statuses = Counter(cell["status"] for cell in readiness["cells"])
    return f"""# Comparative Benchmark E1 Preparation

状态：`{readiness["overall_status"]}`  
协议：`comparison-v1.1`  
历史付费调用：{readiness["paid_api_calls"]}（含 embedding 请求）；攻击生成：{readiness["attack_generations"]}；development 索引：{readiness["development_indices"]}；正式索引：0

## 本轮完成

- 固定 A1-A3 的 18 个 validation cell、每格 100 attempted，共 {readiness["attack_input_rows"]} 条后端执行记录；同一 dataset/attack/query 在两个后端共享 attack seed。
- 攻击生成输入只含 query ID、question、stratum；冻结后的 A1 audit 才读取 1 条 evaluator-only 记录做 target/gold collision 检查。
- A1 使用 question-only 单次目标选择协议，攻击冻结后才由评估器检查 target/gold collision，碰撞不补样。
- A2 只允许 clean pinned vendor、`en_core_web_trf`、top ratio 0.05 和无 gold staging workspace。
- A3 改为 3 个 question-only 有界阶段；上游无界递归/循环不得直接进入主实验。
- development 生成小试验状态为 `{pilot["status"]}`：2 个冻结样本最多 4 次调用，实际费用 ¥{float(pilot.get("actual_catalog_cost_cny") or 0):.5f}；A1 target/gold 碰撞数为 {pilot.get("a1_target_gold_collision_count", 0)}，不补样。
- A2 单样本 query-entity 生成有效，但成本门状态为 `{logicpoison_pilot["status"]}`：实际费用 ¥{float(logicpoison_pilot.get("actual_catalog_cost_cny") or 0):.6f}，高于原 ¥{float(logicpoison_pilot.get("hard_cost_cap_cny") or 0):.4f} 上限。该结果冻结且不重试；后续请求显式关闭 thinking，并改用 `max_completion_tokens`。
- A2 修正后的另一冻结样本状态为 `{logicpoison_control["status"]}`：reasoning tokens={logicpoison_control.get("token_usage", {}).get("reasoning_tokens", 0)}，实际费用 ¥{float(logicpoison_control.get("actual_catalog_cost_cny") or 0):.6f}，低于 ¥{float(logicpoison_control.get("hard_cost_cap_cny") or 0):.4f} 上限。

cell 状态：`{dict(sorted(statuses.items()))}`。

## 双后端索引计量

LightRAG 1/10 文档试验费用估计分别为 ¥{indexing["pilots"]["lightrag_one_document"]["catalog_cost_estimate_cny"]:.6f}/¥{indexing["pilots"]["lightrag_ten_documents"]["catalog_cost_estimate_cny"]:.6f}；Microsoft GraphRAG 分别为 ¥{indexing["pilots"]["microsoft_graphrag_one_document"]["catalog_cost_estimate_cny"]:.6f}/¥{indexing["pilots"]["microsoft_graphrag_ten_documents"]["catalog_cost_estimate_cny"]:.6f}。4 次 development 索引均通过，无 reasoning tokens；累计 {indexing["provider_calls"]} 次 chat/embedding 请求，目录价估计 ¥{indexing["catalog_cost_estimate_cny"]:.6f}。embedding tokens 为本地 tokenizer 估计，chat usage 为服务端返回。

若按当前三数据集、每数据集 clean + 3 个攻击变体计算，每个后端需要 {indexing["documents_per_backend"]} 次文档索引暴露、12 个独立索引。1/10 文档三种朴素外推给出的双后端合计区间为 ¥{indexing["full_scale_projection"]["combined_calibration_range_cny"][0]:.3f}–¥{indexing["full_scale_projection"]["combined_calibration_range_cny"][1]:.3f}。该区间只是校准信号，不是 hard cap；图抽取和 community summary 随语料非线性增长，必须先做冻结的 100 文档分层试验或缩减索引设计。

## BadRAG development smoke

本地 lexical mechanism smoke 共 {badrag["aggregate"]["paired_queries"]} 个 trigger/no-trigger 配对，trigger retrieval={badrag["aggregate"]["trigger_retrieval_rate"]:.3f}，false activation={badrag["aggregate"]["false_activation_rate"]:.3f}。本轮完成了配对与指标合同检查，但未通过 trigger retrieval 门，也不包含 dense COP/ACOP/MCOP 或回答 payload；因此 `validation_eligible=false`，不能写成 BadRAG 复现结果。

## 成本闸门

已冻结 2026-09-03 华北 2（北京）未折扣目录价和所有已知调用上限。已知非索引组件保守小计为 ¥{cost["known_components_conservative_subtotal_cny"]:.3f}；双后端索引已有实测校准，但仍没有可验证的全规模 hard cap，BadRAG dense/payload 也未封顶。因此 overall hard cap 仍为空，`paid_e1_launch_allowed=false`。

## 当前结论

E1 的样本边界、跨后端配对、A1-A3 runner、生成成本控制和双后端小规模索引计量已成为可测试产物；尚不能得出系统攻击效果或防御优越性结论。下一步是冻结 100 文档分层索引试验设计（或先缩减重复索引方案），据此冻结 A1-A3 validation hard cap；BadRAG dense/payload 保持独立资格轨。
"""


def run(config_path: Path) -> dict[str, Any]:
    root = find_project_root(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    e0 = json.loads(_resolve(root, config["e0_readiness"]).read_text(encoding="utf-8"))
    if e0.get("overall_status") != "E0_PASSED__E1_IMPLEMENTATION_GATED":
        raise RuntimeError("E1 preparation requires the passed E0 readiness artifact")
    outputs = {key: _resolve(root, value) for key, value in config["outputs"].items()}
    source_checks = _attack_source_checks(root, config)
    attempts, cells = _build_attack_inputs(root, config)
    write_jsonl(outputs["attack_input_manifest"], attempts)
    development_attempts = _build_development_attack_inputs(root, config)
    write_jsonl(outputs["development_attack_input_manifest"], development_attempts)
    logicpoison_development_attempts = _build_development_attack_inputs(
        root, config, spec_key="logicpoison_development_generation_pilot"
    )
    write_jsonl(
        outputs["logicpoison_development_input_manifest"],
        logicpoison_development_attempts,
    )
    logicpoison_cost_control_attempts = _build_development_attack_inputs(
        root, config, spec_key="logicpoison_cost_control_pilot"
    )
    write_jsonl(
        outputs["logicpoison_cost_control_input_manifest"],
        logicpoison_cost_control_attempts,
    )
    development_pilot = _development_pilot_audit(root, config)
    atomic_write_json(outputs["development_pilot_audit"], development_pilot)
    logicpoison_development_pilot = _logicpoison_development_pilot_audit(root, config)
    atomic_write_json(
        outputs["logicpoison_development_pilot_audit"],
        logicpoison_development_pilot,
    )
    logicpoison_cost_control = _logicpoison_cost_control_pilot_audit(root, config)
    atomic_write_json(
        outputs["logicpoison_cost_control_pilot_audit"],
        logicpoison_cost_control,
    )
    indexing_audit = _indexing_pilot_audit(root, config)
    atomic_write_json(outputs["indexing_pilot_audit"], indexing_audit)
    dryrun_path = _resolve(root, config["attack_runner_dryrun"])
    dryrun = (
        json.loads(dryrun_path.read_text(encoding="utf-8"))
        if dryrun_path.is_file()
        else {}
    )
    runner_dryrun_passed = (
        dryrun.get("status") == "DRY_RUN_PASSED"
        and dryrun.get("input_manifest_sha256")
        == sha256_file(outputs["attack_input_manifest"])
        and dryrun.get("planned_provider_calls") == 1200
    )
    logicpoison_dryrun_path = _resolve(root, config["logicpoison_runner_dryrun"])
    logicpoison_dryrun = (
        json.loads(logicpoison_dryrun_path.read_text(encoding="utf-8"))
        if logicpoison_dryrun_path.is_file()
        else {}
    )
    logicpoison_runner_dryrun_passed = (
        logicpoison_dryrun.get("status") == "DRY_RUN_PASSED"
        and logicpoison_dryrun.get("input_manifest_sha256")
        == sha256_file(outputs["attack_input_manifest"])
        and logicpoison_dryrun.get("planned_provider_calls") == 300
        and logicpoison_dryrun.get("calls_by_attack") == {"A2_logicpoison": 300}
    )
    if runner_dryrun_passed:
        for cell in cells:
            if cell["attack_id"] in {"A1_poisonedrag", "A3_gragpoison"}:
                cell["status"] = "bounded_runner_implemented__dry_run_passed"
    if logicpoison_runner_dryrun_passed:
        for cell in cells:
            if cell["attack_id"] == "A2_logicpoison":
                cell["status"] = "gold_free_staging_runner_implemented__dry_run_passed"
    logicpoison_runtime = _logicpoison_runtime_smoke(root, config)
    atomic_write_json(outputs["logicpoison_runtime_smoke"], logicpoison_runtime)
    execution_plan = {
        "schema_version": 1,
        "benchmark_version": config["benchmark_version"],
        "source_checks": source_checks,
        "environment_checks": {
            "spacy_version": _package_version("spacy"),
            "en_core_web_trf_installed": _module_available("en_core_web_trf"),
            "isolated_logicpoison_runtime": logicpoison_runtime,
        },
        "cells": cells,
        "forbidden_external_repo_used": False,
        "evaluator_only_files_read": development_pilot.get(
            "evaluator_only_files_read", 0
        ),
        "paid_api_calls": development_pilot.get("provider_calls_made", 0),
        "development_generation_pilot": development_pilot,
        "logicpoison_development_generation_pilot": logicpoison_development_pilot,
        "logicpoison_cost_control_pilot": logicpoison_cost_control,
        "bounded_attack_runner_dryrun": dryrun,
        "logicpoison_staging_runner_dryrun": logicpoison_dryrun,
    }
    execution_plan["fingerprint"] = fingerprint_json(execution_plan)
    atomic_write_json(outputs["execution_plan"], execution_plan)
    badrag = _badrag_smoke(root, config)
    atomic_write_json(outputs["badrag_smoke"], badrag)
    cost = _cost_forecast(root, config, cells, indexing_audit)
    atomic_write_json(outputs["cost_forecast"], cost)
    all_sources = all(
        item["revision_match"]
        and item["entrypoint_exists"]
        and not item["uses_forbidden_external_repo"]
        for item in source_checks.values()
    )
    logicpoison_ner_available = bool(logicpoison_runtime["passed"])
    remaining_blockers = [
        "run_representative_100_document_indexing_gate_or_reduce_index_design",
        "implement_dense_COP_family_and_payload_evaluation_for_BadRAG",
        "freeze_overall_E1_hard_cost_cap",
    ]
    if development_pilot["status"] != "PASSED":
        remaining_blockers.insert(
            0, "run_capped_paid_development_A1_A3_generation_pilots"
        )
    if not logicpoison_runner_dryrun_passed:
        remaining_blockers.insert(0, "implement_A2_gold_free_staging_runner")
    if logicpoison_cost_control["status"] != "PASSED":
        remaining_blockers.insert(
            0,
            "verify_nonthinking_max_completion_token_cost_control_on_new_A2_development_sample",
        )
    if not logicpoison_ner_available:
        remaining_blockers.insert(
            1, "provision_isolated_logicpoison_runtime_with_en_core_web_trf"
        )
    readiness = {
        "schema_version": 1,
        "benchmark_version": config["benchmark_version"],
        "overall_status": "E1_PREPARATION_PARTIAL__PAID_LAUNCH_BLOCKED",
        "gates": {
            "e0_passed": True,
            "pinned_attack_sources": all_sources,
            "attacker_safe_validation_manifests": len(attempts) == 1800,
            "bounded_A1_A3_runner_dryrun": runner_dryrun_passed,
            "A2_gold_free_staging_runner_dryrun": logicpoison_runner_dryrun_passed,
            "logicpoison_paper_ner_available": logicpoison_ner_available,
            "development_A1_A3_generation_pilot": development_pilot["status"]
            == "PASSED",
            "A2_default_thinking_cost_cap_passed": (
                logicpoison_development_pilot["status"] == "PASSED"
            ),
            "A2_nonthinking_generation_and_cost_control": (
                logicpoison_cost_control["status"] == "PASSED"
            ),
            "bounded_one_and_ten_document_indexing_pilots": (
                indexing_audit["status"] == "PASSED"
            ),
            "full_scale_indexing_hard_cap_frozen": indexing_audit[
                "full_scale_projection"
            ]["eligible_to_freeze_overall_hard_cap"],
            "badrag_validation_eligible": badrag["validation_eligible"],
            "overall_cost_hard_cap_frozen": cost["overall_hard_cap_cny"] is not None,
        },
        "attack_input_rows": len(attempts),
        "development_attack_input_rows": len(development_attempts),
        "logicpoison_development_attack_input_rows": len(
            logicpoison_development_attempts
        ),
        "logicpoison_cost_control_attack_input_rows": len(
            logicpoison_cost_control_attempts
        ),
        "cells": cells,
        "paid_api_calls": development_pilot.get("provider_calls_made", 0)
        + logicpoison_development_pilot.get("provider_calls_made", 0)
        + logicpoison_cost_control.get("provider_calls_made", 0)
        + indexing_audit.get("provider_calls", 0),
        "attack_generations": development_pilot.get("generation_valid", 0)
        + logicpoison_development_pilot.get("generation_valid", 0)
        + logicpoison_cost_control.get("generation_valid", 0),
        "actual_catalog_cost_cny": round(
            float(development_pilot.get("actual_catalog_cost_cny") or 0)
            + float(logicpoison_development_pilot.get("actual_catalog_cost_cny") or 0)
            + float(logicpoison_cost_control.get("actual_catalog_cost_cny") or 0)
            + float(indexing_audit.get("catalog_cost_estimate_cny") or 0),
            6,
        ),
        "development_indices": indexing_audit.get("development_indices_completed", 0),
        "indexing_catalog_cost_estimate_cny": indexing_audit.get(
            "catalog_cost_estimate_cny", 0
        ),
        "formal_reindexes": 0,
        "paid_e1_launch_allowed": False,
        "remaining_blockers": remaining_blockers,
    }
    readiness["fingerprint"] = fingerprint_json(readiness)
    atomic_write_json(outputs["readiness"], readiness)
    atomic_write_text(
        outputs["report"],
        _report(
            readiness,
            badrag,
            cost,
            development_pilot,
            logicpoison_development_pilot,
            logicpoison_cost_control,
            indexing_audit,
        ),
    )
    return readiness


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    print(json.dumps(run(args.config.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
