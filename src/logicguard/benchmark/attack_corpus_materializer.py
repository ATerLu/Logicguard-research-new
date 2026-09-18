"""Deterministically materialize bounded A1/A3 outputs into poisoned corpora."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from logicguard.benchmark.attack_qualification import calculate_need_to_keep
from logicguard.benchmark.backend_trace_adapters import comparison_token_count
from logicguard.benchmark.trust_manifest import validate_clean_documents
from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json


def materialize_a1_documents(
    result: Mapping[str, Any], *, question: str, max_documents: int, word_budget: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Materialize the exact upstream LM-targeted query-prefix form."""

    _validate_result(result, attack_id="A1_poisonedrag")
    output = result["output"]
    texts = output.get("malicious_texts")
    target = output.get("target_answer")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("A1 result has no nonempty target answer")
    if (
        not isinstance(texts, list)
        or not texts
        or len(texts) > max_documents
        or any(not isinstance(text, str) or not text.strip() for text in texts)
    ):
        raise ValueError("A1 malicious text count or content violates the budget")
    rows: list[dict[str, Any]] = []
    for occurrence, malicious in enumerate(texts, start=1):
        text = f"{question}.{malicious}"
        rows.append(
            _poison_document(
                attack_id="A1_poisonedrag",
                query_id=str(result["query_id"]),
                family="targeted_evidence",
                occurrence=occurrence,
                source_group_suffix=str(result["query_id"]),
                text=text,
                word_budget=word_budget,
            )
        )
    return rows, {
        "target_answer": target.strip(),
        "materialization_prefix": "question_plus_period_without_inserted_space",
        "paper_native_document_count": len(texts) == 5,
    }


def materialize_a3_documents(
    results: list[Mapping[str, Any]],
    *,
    questions: Mapping[str, str],
    n_alpha: int,
    n_beta: int,
    max_documents_per_query: int,
    word_budget: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the upstream adjacent relation-reuse and selection semantics."""

    documents: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    recent_relation_key: str | None = None
    occurrence = 0
    for result in results:
        _validate_result(result, attack_id="A3_gragpoison")
        query_id = str(result["query_id"])
        if query_id not in questions:
            raise ValueError(
                f"A3 result is absent from frozen development input: {query_id}"
            )
        record = result["output"].get("attack_record")
        if not isinstance(record, Mapping):
            raise ValueError("A3 result has no attack_record")
        roots = _nonempty_string_list(record.get("root_nodes"), "root_nodes")
        middle = _required_string(
            record.get("modified_middle_node"), "modified_middle_node"
        )
        target_relation = _required_string(
            record.get("target_relation"), "target_relation"
        )
        relation_payload = {
            "root_nodes": roots,
            "modified_middle_node": middle,
            "target_relation": target_relation,
        }
        relation_key = fingerprint_json(relation_payload)
        direct = _text_list(record.get("direct_adv_texts"), "direct_adv_texts")
        indirect = _text_list(record.get("indirect_adv_texts"), "indirect_adv_texts")
        enhanced = _text_list(record.get("enhanced_texts"), "enhanced_texts")
        selected: dict[str, list[str]] = {
            "direct": [],
            "indirect": indirect[:n_beta],
            "enhanced": _select_per_root(enhanced, len(roots), n_beta),
        }
        reused = relation_key == recent_relation_key
        if not reused:
            selected["direct"] = _select_per_root(direct, len(roots), n_alpha)
            recent_relation_key = relation_key
        selected_count = sum(len(values) for values in selected.values())
        if selected_count > max_documents_per_query:
            raise ValueError("A3 selected document count exceeds the per-query budget")
        for family, values in selected.items():
            for text in values:
                occurrence += 1
                suffix = relation_key if family == "direct" else query_id
                documents.append(
                    _poison_document(
                        attack_id="A3_gragpoison",
                        query_id=query_id,
                        family=family,
                        occurrence=occurrence,
                        source_group_suffix=suffix,
                        text=text,
                        word_budget=word_budget,
                    )
                )
        audits.append(
            {
                "query_id": query_id,
                "question": questions[query_id],
                "relation_key": relation_key,
                "relation_key_payload": relation_payload,
                "relation_key_basis": "root_nodes_modified_middle_node_target_relation_adaptation",
                "direct_reused_from_immediately_previous": reused,
                "generated_counts": {
                    "direct": len(direct),
                    "indirect": len(indirect),
                    "enhanced": len(enhanced),
                },
                "selected_counts": {
                    family: len(values) for family, values in selected.items()
                },
                "paper_native_count_ready": len(direct) >= n_alpha * len(roots)
                and len(indirect) >= n_beta
                and len(enhanced) >= n_beta * len(roots),
            }
        )
    return documents, audits


def run_from_config(config_path: Path) -> dict[str, Any]:
    """Run or verify the immutable common-development materialization anchor."""

    resolved = resolve_config_path(config_path)
    root = find_project_root(resolved)
    config = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if config.get("run_mode") != "local_materialization_anchor":
        raise ValueError("attack corpus materializer is local-anchor only")
    results_path = _project_input(root, config["inputs"]["attack_results"])
    development_path = _project_input(root, config["inputs"]["development_queries"])
    clean_paths = {
        dataset: _project_input(root, raw)
        for dataset, raw in config["inputs"]["clean_corpora"].items()
    }
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")
    identity = {
        "schema_version": 1,
        "protocol_version": "comparison-v1.2",
        "config_sha256": sha256_file(resolved),
        "implementation_sha256": sha256_file(Path(__file__)),
        "attack_results_sha256": sha256_file(results_path),
        "development_queries_sha256": sha256_file(development_path),
        "clean_corpus_sha256": {
            dataset: sha256_file(path) for dataset, path in sorted(clean_paths.items())
        },
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    summary_path = output / "summary.json"
    if summary_path.exists():
        return _verify_existing(summary_path, output, identity)

    development = load_jsonl(development_path)
    development_index = {
        (str(row["dataset"]), str(row["query_id"])): str(row["question"])
        for row in development
    }
    results = [row for row in load_jsonl(results_path) if row.get("generation_valid")]
    expected_attempts = int(config["expectations"]["generation_valid_attempts"])
    if len(results) != expected_attempts:
        raise ValueError("generation-valid attack result count mismatch")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for result in results:
        key = (str(result["dataset"]), str(result["attack_id"]))
        if key[0] not in clean_paths or key[1] not in {
            "A1_poisonedrag",
            "A3_gragpoison",
        }:
            raise ValueError(f"undeclared materialization cell: {key}")
        if (key[0], str(result["query_id"])) not in development_index:
            raise ValueError("attack result is absent from the frozen development set")
        grouped.setdefault(key, []).append(result)
    if len(grouped) != int(config["expectations"]["cells"]):
        raise ValueError("materialization cell count mismatch")

    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "run_identity.json", identity)
    cell_summaries: list[dict[str, Any]] = []
    for (dataset, attack_id), cell_results in sorted(grouped.items()):
        clean = validate_clean_documents(load_jsonl(clean_paths[dataset]))
        order = {
            query_id: index
            for index, ((row_dataset, query_id), _) in enumerate(
                development_index.items()
            )
            if row_dataset == dataset
        }
        cell_results.sort(key=lambda row: order[str(row["query_id"])])
        cell_dir = output / dataset / attack_id
        if attack_id == "A1_poisonedrag":
            poison: list[dict[str, Any]] = []
            audits = []
            for result in cell_results:
                question = development_index[(dataset, str(result["query_id"]))]
                materialized, audit = materialize_a1_documents(
                    result,
                    question=question,
                    max_documents=int(
                        config["budgets"][attack_id]["max_documents_per_query"]
                    ),
                    word_budget=int(
                        config["budgets"][attack_id]["max_words_per_document"]
                    ),
                )
                poison.extend(materialized)
                audits.append({"query_id": result["query_id"], **audit})
        else:
            questions = {
                str(row["query_id"]): development_index[(dataset, str(row["query_id"]))]
                for row in cell_results
            }
            poison, audits = materialize_a3_documents(
                cell_results,
                questions=questions,
                n_alpha=int(config["budgets"][attack_id]["N_alpha"]),
                n_beta=int(config["budgets"][attack_id]["N_beta"]),
                max_documents_per_query=int(
                    config["budgets"][attack_id]["max_documents_per_query"]
                ),
                word_budget=int(config["budgets"][attack_id]["max_words_per_document"]),
            )
        relative_ratio = len(poison) / len(clean)
        max_ratio = float(config["budgets"][attack_id]["max_relative_document_ratio"])
        if relative_ratio > max_ratio + 1e-12:
            raise ValueError("relative poison-document budget exceeded")
        normalized_poison = [
            {name: row[name] for name in ("_id", "title", "text", "source_group_id")}
            for row in poison
        ]
        poisoned_corpus = [*clean, *normalized_poison]
        write_jsonl(cell_dir / "poison_documents.jsonl", poison)
        write_jsonl(cell_dir / "poisoned_corpus.jsonl", poisoned_corpus)
        write_jsonl(cell_dir / "query_materialization_audit.jsonl", audits)
        family_files = _write_family_files(cell_dir, poison)
        cell_manifest = _cell_manifest(
            dataset=dataset,
            attack_id=attack_id,
            clean=clean,
            poison=poison,
            query_count=len(cell_results),
            relative_ratio=relative_ratio,
            max_ratio=max_ratio,
            cell_dir=cell_dir,
            family_files=family_files,
            paper_native_ready=all(
                row.get(
                    "paper_native_document_count",
                    row.get("paper_native_count_ready", False),
                )
                for row in audits
            ),
        )
        atomic_write_json(cell_dir / "manifest.json", cell_manifest)
        cell_summaries.append(cell_manifest)

    artifact_hashes = {
        str(path.relative_to(output)).replace("\\", "/"): sha256_file(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    summary = {
        **identity,
        "status": "COMMON_DEV_MATERIALIZATION_ANCHOR_PASSED",
        "evidence_scope": "two_existing_generation_valid_pilot_attempts_not_dev60_effect",
        "cells": cell_summaries,
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
        "artifact_hashes": artifact_hashes,
    }
    atomic_write_json(summary_path, summary)
    return summary


def _poison_document(
    *,
    attack_id: str,
    query_id: str,
    family: str,
    occurrence: int,
    source_group_suffix: str,
    text: str,
    word_budget: int,
) -> dict[str, Any]:
    words = len(text.split())
    if words > word_budget:
        raise ValueError(f"poison document exceeds {word_budget}-word budget")
    document_id = f"attack::{attack_id}::{query_id}::{family}::{occurrence:04d}"
    return {
        "_id": document_id,
        "title": f"Controlled robustness evidence {occurrence}",
        "text": text,
        "source_group_id": f"attack::{attack_id}::{family}::{source_group_suffix}",
        "attack_id": attack_id,
        "query_id": query_id,
        "attack_family": family,
        "occurrence": occurrence,
        "word_count": words,
        "comparison_token_count": comparison_token_count(text),
        "text_sha256": fingerprint_json({"text": text}),
    }


def _select_per_root(texts: list[str], root_count: int, keep: int) -> list[str]:
    per_root = len(texts) // root_count if root_count else 0
    if per_root == 0:
        return []
    indices = calculate_need_to_keep(len(texts), per_root, keep)
    return [texts[index] for index in indices if index < len(texts)]


def _write_family_files(cell_dir: Path, rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    families = sorted({str(row["attack_family"]) for row in rows})
    for family in families:
        name = f"attack_texts_{family}.txt"
        texts = [str(row["text"]) for row in rows if row["attack_family"] == family]
        atomic_write_text(cell_dir / name, "\n\n".join(texts) + "\n")
        names.append(name)
    return names


def _cell_manifest(
    *,
    dataset: str,
    attack_id: str,
    clean: list[dict[str, str]],
    poison: list[dict[str, Any]],
    query_count: int,
    relative_ratio: float,
    max_ratio: float,
    cell_dir: Path,
    family_files: list[str],
    paper_native_ready: bool,
) -> dict[str, Any]:
    families = Counter(str(row["attack_family"]) for row in poison)
    unique_texts = {str(row["text_sha256"]) for row in poison}
    return {
        "schema_version": 1,
        "dataset": dataset,
        "attack_id": attack_id,
        "status": "MATERIALIZED_WITHIN_BUDGET",
        "query_count": query_count,
        "clean_documents": len(clean),
        "poison_document_occurrences": len(poison),
        "unique_poison_texts": len(unique_texts),
        "poison_documents_by_family": dict(sorted(families.items())),
        "physical_attack_text_files": len(family_files),
        "physical_attack_text_file_names": family_files,
        "poison_to_clean_document_ratio": round(relative_ratio, 12),
        "max_relative_document_ratio": max_ratio,
        "total_poison_words": sum(int(row["word_count"]) for row in poison),
        "total_comparison_tokens": sum(
            int(row["comparison_token_count"]) for row in poison
        ),
        "max_poison_words": max(int(row["word_count"]) for row in poison),
        "paper_native_count_ready": paper_native_ready,
        "shared_runner_label": (
            "PoisonedRAG_inspired_adaptation"
            if attack_id == "A1_poisonedrag"
            else "GRAGPoison_inspired_adaptation"
        ),
        "attack_effect_measured": False,
        "hashes": {
            name: sha256_file(cell_dir / name)
            for name in [
                "poison_documents.jsonl",
                "poisoned_corpus.jsonl",
                "query_materialization_audit.jsonl",
                *family_files,
            ]
        },
    }


def _validate_result(result: Mapping[str, Any], *, attack_id: str) -> None:
    if (
        result.get("attack_id") != attack_id
        or result.get("generation_valid") is not True
    ):
        raise ValueError(f"{attack_id} result is not generation-valid")
    if not isinstance(result.get("output"), Mapping):
        raise ValueError(f"{attack_id} result has no output")


def _text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a nonempty list")
    texts = [str(item).strip() for item in value]
    if any(not text for text in texts):
        raise ValueError(f"{name} contains an empty text")
    return texts


def _nonempty_string_list(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        values = [value.strip()]
    elif isinstance(value, list):
        values = [str(item).strip() for item in value]
    else:
        raise ValueError(f"{name} must be a string or list")
    if not values or any(not item for item in values):
        raise ValueError(f"{name} must contain nonempty strings")
    return values


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _verify_existing(
    summary_path: Path, output: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("run_identity_sha256") != identity["run_identity_sha256"]:
        raise RuntimeError(
            "existing materialization namespace has a different identity"
        )
    for relative, expected in summary["artifact_hashes"].items():
        if sha256_file(output / relative) != expected:
            raise RuntimeError(f"materialized artifact hash mismatch: {relative}")
    return summary


def _project_input(root: Path, raw_path: str) -> Path:
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"input must be an existing project file: {raw_path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_from_config(args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
