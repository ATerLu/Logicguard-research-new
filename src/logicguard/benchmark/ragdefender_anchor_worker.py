"""Execute the pinned RAGDefender model anchor in its isolated runtime."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import time
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_functions(path: Path, names: set[str], namespace: dict[str, Any]) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    found = {node.name for node in selected}
    if found != names:
        raise RuntimeError(f"missing functions in {path}: {sorted(names - found)}")
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102


def _artifact_removed_indices(
    docs: list[str], model: Any, *, task_type: str, functions: dict[str, Any]
) -> tuple[int, list[int]]:
    if task_type == "multi_hop":
        n_adv = int(functions["find_num_adv"](docs, model))
    else:
        n_adv = int(functions["find_num_adv_agg"](docs, model))
    pair_count = max(1, int(n_adv * (n_adv - 1) / 2))
    pairs = functions["top_similar_pairs"](docs, model, pair_count)
    scores: Counter[int] = Counter()
    for left, right, similarity in pairs:
        scores[left] += math.copysign(similarity * similarity, similarity)
        scores[right] += math.copysign(similarity * similarity, similarity)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:n_adv]
    return n_adv, sorted(index for index, _ in ranked)


def _classification_metrics(
    removed: list[int], poisoned: list[int]
) -> dict[str, float | int]:
    removed_set = set(removed)
    poisoned_set = set(poisoned)
    tp = len(removed_set & poisoned_set)
    fp = len(removed_set - poisoned_set)
    fn = len(poisoned_set - removed_set)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def run(config_path: Path, output_path: Path) -> dict[str, Any]:
    import pandas as pd
    import sklearn.feature_extraction.text as text
    import torch
    from huggingface_hub import snapshot_download
    from ragdefender import RAGDefender
    from sentence_transformers import SentenceTransformer, util
    from sklearn.cluster import AgglomerativeClustering

    config = json.loads(config_path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    model = SentenceTransformer(
        config["model_id"],
        revision=config["model_revision"],
        device="cpu",
        trust_remote_code=bool(config.get("trust_remote_code", False)),
        local_files_only=bool(config.get("local_files_only", False)),
    )
    snapshot = Path(
        snapshot_download(
            repo_id=config["model_id"],
            revision=config["model_revision"],
            local_files_only=True,
        )
    )

    functions: dict[str, Any] = {
        "torch": torch,
        "util": util,
        "text": text,
        "pd": pd,
        "math": math,
        "AgglomerativeClustering": AgglomerativeClustering,
        "sentence_transformers_util": util,
    }
    _load_functions(
        Path(config["artifact_main"]),
        {"find_num_adv", "find_num_adv_tfidf", "find_num_adv_agg"},
        functions,
    )
    _load_functions(Path(config["artifact_utils"]), {"top_similar_pairs"}, functions)

    rows = []
    for fixture_spec in config["fixtures"]:
        fixture_path = Path(fixture_spec["path"])
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        docs = [str(item) for item in fixture["docs"]]
        poisoned = [int(item) for item in fixture["ground_truth_adversarial_indices"]]
        task_type = str(fixture_spec["task_type"])
        defender = RAGDefender(
            embedder=model,
            task_type=task_type,
            device="cpu",
            p=int(config["p"]),
            m=int(config["m"]),
        )
        _, package_removed = defender.defend(
            str(fixture["query"]), docs, return_indices=True
        )
        artifact_n_adv, artifact_removed = _artifact_removed_indices(
            docs, model, task_type=task_type, functions=functions
        )

        reversed_docs = list(reversed(docs))
        _, reversed_removed = defender.defend(
            str(fixture["query"]), reversed_docs, return_indices=True
        )
        reversed_removed_docs = {reversed_docs[index] for index in reversed_removed}
        original_removed_docs = {docs[index] for index in package_removed}
        passage_order_equivariant = reversed_removed_docs == original_removed_docs
        rows.append(
            {
                "fixture": fixture_path.name,
                "fixture_sha256": _sha256(fixture_path),
                "task_type": task_type,
                "query": fixture["query"],
                "document_count": len(docs),
                "ground_truth_adversarial_indices": poisoned,
                "artifact_n_adv": artifact_n_adv,
                "artifact_removed_indices": artifact_removed,
                "package_removed_indices": package_removed,
                "artifact_package_exact_match": artifact_removed == package_removed,
                "passage_order_equivariant_by_text": passage_order_equivariant,
                "reversed_package_removed_indices": reversed_removed,
                "original_removed_text_sha256": sorted(
                    hashlib.sha256(text.encode("utf-8")).hexdigest()
                    for text in original_removed_docs
                ),
                "reversed_removed_text_sha256": sorted(
                    hashlib.sha256(text.encode("utf-8")).hexdigest()
                    for text in reversed_removed_docs
                ),
                "metrics": _classification_metrics(package_removed, poisoned),
            }
        )

    weight_files = sorted(snapshot.rglob("*.safetensors"))
    success_status = str(
        config.get(
            "success_status", "RAGDEFENDER_PUBLISHED_ARTIFACT_MODEL_ANCHOR_PASSED"
        )
    )
    payload = {
        "schema_version": 1,
        "status": success_status,
        "evidence_scope": "model_level_filter_execution_not_answer_effect",
        "implementation": {
            "published_artifact_ast_executed": True,
            "package_public_api_executed": True,
            "artifact_package_exact_match": all(
                row["artifact_package_exact_match"] for row in rows
            ),
            "paper_text_formula_faithful": False,
            "paper_text_formula_caveat": (
                "published multi-hop artifact uses OR/shifted-median/result-flip, "
                "while the paper text describes AND/median"
            ),
        },
        "model": {
            "id": config["model_id"],
            "revision": config["model_revision"],
            "role": str(
                config.get("model_role", "explicit model in pinned artifacts/main.py")
            ),
            "embedding_dimension": int(model.get_sentence_embedding_dimension()),
            "weight_files": [
                {
                    "relative_path": path.relative_to(snapshot).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in weight_files
            ],
        },
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "sentence_transformers": importlib.metadata.version(
                "sentence-transformers"
            ),
            "transformers": importlib.metadata.version("transformers"),
            "ragdefender": importlib.metadata.version("ragdefender"),
            "device": "cpu",
        },
        "fixtures": rows,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "provider_calls_made": 0,
        "actual_cost_cny": 0.0,
    }
    if not payload["implementation"]["artifact_package_exact_match"]:
        payload["status"] = "RAGDEFENDER_ARTIFACT_PACKAGE_MISMATCH"
    elif not all(row["passage_order_equivariant_by_text"] for row in rows):
        payload["status"] = success_status + "_WITH_ORDER_SENSITIVITY"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.config, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
