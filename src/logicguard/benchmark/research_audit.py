"""Read-only history inspection and a separate v1.2 research amendment inventory.

An artifact proves that a record exists, not that a researcher inspected it or
tuned on it. No prior split, attack, answer, or readiness artifact is rewritten.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

import yaml

from logicguard.core.config import find_project_root
from logicguard.core.io import atomic_write_json, load_jsonl, sha256_file, write_jsonl


def normalize_question(value: str) -> str:
    return " ".join(value.casefold().split())


def objects(value: Any, pointer: str = "$") -> Iterator[tuple[str, dict[str, Any]]]:
    """Find query-bearing objects, never interpret source/doc IDs as query IDs."""
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                yield from objects(child, f"{pointer}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from objects(child, f"{pointer}[{index}]")


def records(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for line, row in enumerate(csv.DictReader(handle), 2):
                yield f"line:{line}", row
    elif path.suffix == ".jsonl":
        with path.open(encoding="utf-8-sig") as handle:
            for line, text in enumerate(handle, 1):
                if text.strip():
                    yield from objects(json.loads(text), f"line:{line}")
    else:
        yield from objects(json.loads(path.read_text(encoding="utf-8-sig")))


def evidence_class(path: str) -> str:
    name = Path(path).name.lower()
    if "fixtures" in Path(path).parts:
        return "fixture_available"
    if any(word in name for word in ("request_plan", "manifest", "preflight")):
        return "prepared_or_listed"
    if any(
        word in name for word in ("analysis", "taxonomy", "example", "judged", "judge")
    ):
        return "analysis_or_judgment_artifact"
    if "attack_records" in name or "attack_results" in name:
        return "attack_attempt_artifact"
    if any(word in name for word in ("answer", "generation_result", "generation_case")):
        return "answer_artifact"
    if any(word in name for word in ("trace", "context", "query_entities", "metric")):
        return "retrieval_or_evaluation_artifact"
    return "usage_uncertain"


EXECUTION_CLASSES = {
    "analysis_or_judgment_artifact",
    "attack_attempt_artifact",
    "answer_artifact",
    "retrieval_or_evaluation_artifact",
}


def match_query(
    row: dict[str, Any],
    path: str,
    by_id: dict[str, set[tuple[str, str]]],
    by_question: dict[str, set[tuple[str, str]]],
) -> tuple[set[tuple[str, str]], str]:
    query_id = row.get("query_id", row.get("qid", row.get("question_id")))
    question = row.get("question", row.get("query"))
    if query_id is None and isinstance(question, str):
        query_id = row.get("id", row.get("_id"))
    candidates = by_id.get(str(query_id), set()) if query_id is not None else set()
    method = "query_id"
    if not candidates and isinstance(question, str):
        candidates = by_question.get(normalize_question(question), set())
        method = "normalized_question"
    if not candidates:
        return set(), "unmatched"
    dataset = row.get("dataset")
    if dataset:
        return {key for key in candidates if key[0] == dataset}, method
    path_datasets = {key[0] for key in candidates if key[0] in path.lower()}
    if len(path_datasets) == 1:
        return {key for key in candidates if key[0] in path_datasets}, method
    if len({key[0] for key in candidates}) == 1:
        return candidates, method
    return set(), "ambiguous_dataset"


def select_development(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Round-robin existing development strata, never rank by experimental outcome."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["split"] == "development":
            groups[row["stratum"]].append(row)
    for group in groups.values():
        group.sort(key=lambda row: (row["order_key"], row["query_id"]))
    selected: list[dict[str, Any]] = []
    while len(selected) < count:
        progress = False
        for key in sorted(groups):
            if groups[key] and len(selected) < count:
                selected.append(groups[key].pop(0))
                progress = True
        if not progress:
            raise ValueError("insufficient existing development queries")
    return selected


def run(config_path: Path) -> dict[str, Any]:
    root = find_project_root(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output = root / config["output_root"]
    queries: list[dict[str, Any]] = []
    protected = [root / value for value in config["protected_artifacts"]]
    for dataset in config["datasets"]:
        path = root / config["split_root"] / f"{dataset}_attacker_safe.jsonl"
        protected.append(path)
        protected.append(path.parent / "evaluator_only" / f"{dataset}.jsonl")
        queries.extend(load_jsonl(path))
    before = {str(path.relative_to(root)): sha256_file(path) for path in protected}
    by_id: dict[str, set[tuple[str, str]]] = defaultdict(set)
    by_question: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in queries:
        key = (row["dataset"], row["query_id"])
        by_id[key[1]].add(key)
        by_question[normalize_question(row["question"])].add(key)

    paths = {root / value for value in config["history_files"]}
    for value in config["history_roots"]:
        paths.update((root / value).rglob("*"))
    evidence: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    evidence_paths: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in sorted(paths):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".csv"}:
            continue
        relative = path.relative_to(root).as_posix()
        reason = None
        if set(path.relative_to(root).parts) & set(config["excluded_directory_names"]):
            reason = "excluded_runtime_directory"
        elif any(value in path.name for value in config["excluded_filename_fragments"]):
            reason = "document_inventory_not_query_usage"
        elif path.suffix == ".json" and path.stat().st_size > config["max_json_bytes"]:
            reason = "json_size_limit"
        if reason:
            files.append({"path": relative, "status": "excluded", "reason": reason})
            continue
        kind = evidence_class(relative)
        file_keys: set[tuple[str, str]] = set()
        ambiguity_count = 0
        status = "scanned"
        error = None
        try:
            for pointer, row in records(path):
                matches, method = match_query(row, relative, by_id, by_question)
                ambiguity_count += int(method == "ambiguous_dataset")
                for key in sorted(matches - file_keys):
                    file_keys.add(key)
                    seen[key].add(kind)
                    evidence_paths[key].add(relative)
                    evidence.append(
                        {
                            "dataset": key[0],
                            "query_id": key[1],
                            "path": relative,
                            "first_record_pointer": pointer,
                            "match_method": method,
                            "evidence_class": kind,
                            "human_inspection_or_tuning": "not_inferable_from_artifact",
                        }
                    )
        except (ValueError, UnicodeError, csv.Error) as exc:
            status, error = "parse_error", type(exc).__name__
        files.append(
            {
                "path": relative,
                "status": status,
                "error_type": error,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "matched_queries": len(file_keys),
                "ambiguous_records": ambiguity_count,
                "evidence_class": kind,
            }
        )

    membership: list[dict[str, Any]] = []
    for row in queries:
        key = (row["dataset"], row["query_id"])
        classes = seen[key]
        executed = bool(classes & EXECUTION_CLASSES)
        membership.append(
            {
                "dataset": key[0],
                "query_id": key[1],
                "existing_split": row["split"],
                "stratum": row["stratum"],
                "evidence_classes": sorted(classes),
                "has_execution_or_analysis_artifact": executed,
                "history_file_count": len(evidence_paths[key]),
                "freshness_status": (
                    "previous_execution_or_analysis_record"
                    if executed
                    else "prior_listing_or_uncertain_usage"
                    if classes
                    else "no_record_in_scanned_scope"
                ),
                "confirmatory_independence_certified": False,
            }
        )
    summary_rows = []
    for dataset in config["datasets"]:
        for split in ("development", "validation", "locked_test"):
            selected = [
                r
                for r in membership
                if r["dataset"] == dataset and r["existing_split"] == split
            ]
            summary_rows.append(
                {
                    "dataset": dataset,
                    "split": split,
                    "query_count": len(selected),
                    "execution_or_analysis_overlap": sum(
                        r["has_execution_or_analysis_artifact"] for r in selected
                    ),
                    "any_artifact_overlap": sum(
                        r["history_file_count"] > 0 for r in selected
                    ),
                    "no_record_in_scanned_scope": sum(
                        r["history_file_count"] == 0 for r in selected
                    ),
                }
            )
    pilot = []
    for dataset in config["datasets"]:
        selected = select_development(
            [r for r in queries if r["dataset"] == dataset],
            config["development_queries_per_dataset"],
        )
        pilot.extend(
            {
                "dataset": dataset,
                "query_id": row["query_id"],
                "question": row["question"],
                "stratum": row["stratum"],
                "split": "development",
                "purpose": "WP2_mechanism_and_fairness_pilot_not_confirmatory",
            }
            for row in selected
        )

    # Only these new derivative files may change.
    write_jsonl(output / "history_evidence.jsonl", evidence)
    write_jsonl(output / "history_files.jsonl", files)
    write_jsonl(output / "query_history_membership.jsonl", membership)
    write_jsonl(output / "wp2_development_queries.jsonl", pilot)
    after = {str(path.relative_to(root)): sha256_file(path) for path in protected}
    if before != after:
        raise RuntimeError("protected historical artifacts changed during audit")
    payload = {
        "schema_version": 1,
        "benchmark_version": config["benchmark_version"],
        "audit_date": config["audit_date"],
        "audit_config_sha256": sha256_file(config_path),
        "audit_implementation_sha256": sha256_file(Path(__file__)),
        "status": "HISTORY_AUDITED__INDEPENDENCE_NOT_CERTIFIED",
        "query_count": len(membership),
        "datasets_and_splits": summary_rows,
        "file_status_counts": dict(
            sorted(Counter(item["status"] for item in files).items())
        ),
        "evidence_rows": len(evidence),
        "development_pilot_queries": len(pilot),
        "protected_artifacts_unchanged": before == after,
        "protected_sha256": before,
        "reviewed_source_sha256": {
            value: sha256_file(root / value) for value in config["reviewed_sources"]
        },
        "limits": [
            "Artifact presence does not establish human inspection, tuning, or causality.",
            "Absence in scanned scope does not prove a query was never used elsewhere.",
            "Document-level/topic leakage and external experiment history need separate review.",
            "Classification is filename-based; per-file evidence and exceptions are retained.",
        ],
        "new_provider_calls": 0,
        "new_attack_generations": 0,
        "new_indexes": 0,
    }
    atomic_write_json(output / "history_summary.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config.resolve()), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
