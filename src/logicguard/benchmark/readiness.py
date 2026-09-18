"""Build the deterministic E0 asset/split/contract readiness package.

This command is intentionally offline with respect to model providers: it reads
already-pinned public assets, writes manifests, and never generates attacks,
indexes a corpus, or calls an answer model.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping

from logicguard.benchmark.contracts import (
    ATTACK_CONTRACTS,
    BACKEND_CONTRACTS,
    DEFENSE_CONTRACTS,
)
from logicguard.benchmark.adapters import (
    BadRAGReimplementationAdapter,
    GRAGPoisonAdapter,
    LogicPoisonPairAdapter,
    PoisonedRAGOfficialAdapter,
    normalize_context_trace,
    normalize_defense_trace,
)
from logicguard.benchmark.schemas import BenchmarkQuery
from logicguard.core.config import find_project_root, load_yaml, resolve_project_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json


FORBIDDEN_ATTACKER_FIELDS = frozenset(
    {
        "answer",
        "gold_answer",
        "answer_aliases",
        "support_doc_ids",
        "support_ids",
        "changed_labels",
    }
)


def _read_qrels(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            result[row["query-id"]].append(row["corpus-id"])
    return dict(result)


def _answer_map(path: Path) -> dict[str, str]:
    return {str(row["id"]): str(row["answer"]) for row in load_jsonl(path)}


def _stratum(dataset: str, query_id: str, support_count: int) -> str:
    if dataset == "hotpotqa":
        return "2hop"
    if dataset == "musique":
        match = re.match(r"^(\d+)hop", query_id)
        return f"{match.group(1)}hop" if match else f"support_{support_count}"
    if dataset == "2wikimultihopqa":
        return f"support_{support_count}"
    return f"support_{support_count}"


def _quota(group_sizes: Mapping[str, int], target: int) -> dict[str, int]:
    total = sum(group_sizes.values())
    raw = {key: size * target / total for key, size in group_sizes.items()}
    quota = {key: int(value) for key, value in raw.items()}
    remainder = target - sum(quota.values())
    order = sorted(group_sizes, key=lambda key: (-(raw[key] - quota[key]), key))
    for key in order[:remainder]:
        quota[key] += 1
    return quota


def _build_split_rows(
    *, dataset: str, directory: Path, namespace: str, sizes: Mapping[str, int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    queries = load_jsonl(directory / "queries.jsonl")
    answers = _answer_map(directory / "answers.jsonl")
    qrels = _read_qrels(directory / "qrels" / "test.tsv")
    if len(queries) != sum(sizes.values()):
        raise ValueError(
            f"{dataset}: expected {sum(sizes.values())} queries, got {len(queries)}"
        )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in queries:
        query_id = str(row["_id"])
        if query_id not in answers or query_id not in qrels:
            raise ValueError(f"{dataset}: query lacks evaluator labels: {query_id}")
        stratum = _stratum(dataset, query_id, len(qrels[query_id]))
        groups[stratum].append(
            {
                "query_id": query_id,
                "question": str(row["text"]),
                "stratum": stratum,
                "order_key": fingerprint_json(
                    {"version": namespace, "dataset": dataset, "query_id": query_id}
                ),
            }
        )
    for rows in groups.values():
        rows.sort(key=lambda row: (row["order_key"], row["query_id"]))

    group_sizes = {key: len(value) for key, value in groups.items()}
    development_quota = _quota(group_sizes, sizes["development"])
    validation_quota = _quota(group_sizes, sizes["validation"])
    public_rows: list[dict[str, Any]] = []
    evaluator_rows: list[dict[str, Any]] = []
    distribution: dict[str, Counter[str]] = defaultdict(Counter)
    for stratum, rows in sorted(groups.items()):
        d_end = development_quota[stratum]
        v_end = d_end + validation_quota[stratum]
        for position, row in enumerate(rows):
            split = (
                "development"
                if position < d_end
                else "validation"
                if position < v_end
                else "locked_test"
            )
            query = BenchmarkQuery(
                dataset=dataset,
                query_id=row["query_id"],
                question=row["question"],
                split=split,
                stratum=stratum,
            )
            public = query.to_json_dict() | {"order_key": row["order_key"]}
            if FORBIDDEN_ATTACKER_FIELDS.intersection(public):
                raise AssertionError(
                    "attacker-safe split contains evaluator-only fields"
                )
            public_rows.append(public)
            evaluator_rows.append(
                public
                | {
                    "gold_answer": answers[row["query_id"]],
                    "support_doc_ids": qrels[row["query_id"]],
                }
            )
            distribution[split][stratum] += 1

    public_rows.sort(key=lambda row: (row["split"], row["order_key"], row["query_id"]))
    evaluator_rows.sort(
        key=lambda row: (row["split"], row["order_key"], row["query_id"])
    )
    split_sets = {
        split: {row["query_id"] for row in public_rows if row["split"] == split}
        for split in sizes
    }
    overlap = {
        "development_validation": len(
            split_sets["development"] & split_sets["validation"]
        ),
        "development_locked_test": len(
            split_sets["development"] & split_sets["locked_test"]
        ),
        "validation_locked_test": len(
            split_sets["validation"] & split_sets["locked_test"]
        ),
    }
    counts = Counter(row["split"] for row in public_rows)
    audit = {
        "dataset": dataset,
        "query_count": len(public_rows),
        "counts": dict(counts),
        "stratum_distribution": {
            key: dict(value) for key, value in distribution.items()
        },
        "overlap": overlap,
        "public_forbidden_field_count": sum(
            bool(FORBIDDEN_ATTACKER_FIELDS.intersection(row)) for row in public_rows
        ),
        "passed": dict(counts) == dict(sizes) and not any(overlap.values()),
    }
    return public_rows, evaluator_rows, audit


def _asset_manifest(project_root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    required_failures: list[str] = []
    for configured in config["assets"]:
        entry = dict(configured)
        raw_local_path = entry.get("local_path")
        path = project_root / raw_local_path if raw_local_path else None
        hashes: list[dict[str, Any]] = []
        if path is None:
            status = "not_materialized"
        elif not path.exists():
            status = "missing"
        else:
            status = "materialized"
            for relative in entry.get("hash_files", []):
                file_path = path / relative
                if not file_path.is_file():
                    status = "incomplete"
                    hashes.append({"path": relative, "status": "missing"})
                else:
                    hashes.append(
                        {
                            "path": relative,
                            "size_bytes": file_path.stat().st_size,
                            "sha256": sha256_file(file_path),
                        }
                    )
        if entry.get("required") and status != "materialized":
            required_failures.append(entry["id"])
        entry["materialization_status"] = status
        entry["file_hashes"] = hashes
        entries.append(entry)
    payload = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.1",
        "assets": entries,
        "required_failures": required_failures,
        "passed": not required_failures,
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _poisonedrag_overlap(
    path: Path, query_ids: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for query_id in sorted(set(payload) & query_ids):
        item = payload[query_id]
        rows.append(
            {
                "schema_version": "comparison-v1.1",
                "asset": "A1_poisonedrag",
                "dataset": "hotpotqa",
                "query_id": query_id,
                "question": item["question"],
                "target_answer": item["incorrect answer"],
                "gold_answer_present_evaluator_only": bool(item.get("correct answer")),
                "malicious_document_count": len(item.get("adv_texts", [])),
                "malicious_texts_sha256": fingerprint_json(item.get("adv_texts", [])),
                "fidelity": "paper_native_golden_contract",
            }
        )
    return rows, {
        "official_instance_count": len(payload),
        "common_query_overlap_count": len(rows),
        "expected_overlap_count": 6,
        "passed": len(rows) == 6
        and all(row["malicious_document_count"] == 5 for row in rows),
    }


def _gragpoison_overlap(
    path: Path, query_ids: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = [
        question for group in payload for question in group.get("questions", [])
    ]
    rows = []
    for item in sorted(questions, key=lambda row: str(row["id"])):
        query_id = str(item["id"])
        if query_id not in query_ids:
            continue
        rows.append(
            {
                "schema_version": "comparison-v1.1",
                "asset": "A3_gragpoison",
                "dataset": "musique",
                "query_id": query_id,
                "question": item["question"],
                "hop_count": len(item.get("question_decomposition", [])),
                "paragraph_count": len(item.get("paragraphs", [])),
                "fidelity": "paper_native_golden_contract",
            }
        )
    return rows, {
        "official_question_count": len(questions),
        "common_query_overlap_count": len(rows),
        "expected_overlap_count": 14,
        "passed": len(rows) == 14 and all(row["hop_count"] >= 2 for row in rows),
    }


def _audit_legacy_logicpoison(
    project_root: Path, output_root: Path, datasets: Iterable[str]
) -> dict[str, Any]:
    """Reconstruct changed-document lineage without inventing run provenance."""

    summaries: list[dict[str, Any]] = []
    for dataset in datasets:
        clean_directory = (
            project_root / "data" / "logicpoison_official" / "clean" / dataset
        )
        poisoned_directory = (
            project_root / "data" / "logicpoison_official" / "poisoned" / dataset
        )
        clean_rows = {
            str(row["_id"]): row for row in load_jsonl(clean_directory / "corpus.jsonl")
        }
        poisoned_rows = {
            str(row["_id"]): row
            for row in load_jsonl(poisoned_directory / "corpus.jsonl")
        }
        changed_rows: list[dict[str, Any]] = []
        for document_id in sorted(set(clean_rows) & set(poisoned_rows)):
            clean = clean_rows[document_id]
            poisoned = poisoned_rows[document_id]
            if clean == poisoned:
                continue
            changed_rows.append(
                {
                    "schema_version": "comparison-v1.1",
                    "dataset": dataset,
                    "document_id": document_id,
                    "changed_fields": [
                        field
                        for field in ("title", "text")
                        if clean.get(field) != poisoned.get(field)
                    ],
                    "clean_document_sha256": fingerprint_json(clean),
                    "poisoned_document_sha256": fingerprint_json(poisoned),
                }
            )
        write_jsonl(
            output_root / "legacy_logicpoison" / f"{dataset}_changed_documents.jsonl",
            changed_rows,
        )
        integrity = {
            filename: sha256_file(clean_directory / filename)
            == sha256_file(poisoned_directory / filename)
            for filename in ("queries.jsonl", "answers.jsonl", "qrels/test.tsv")
        }
        stats_path = poisoned_directory / f"poison_stats_{dataset}.json"
        summaries.append(
            {
                "dataset": dataset,
                "classification": "legacy_adapted",
                "paper_faithful": False,
                "clean_document_count": len(clean_rows),
                "poisoned_document_count": len(poisoned_rows),
                "document_id_sets_equal": set(clean_rows) == set(poisoned_rows),
                "changed_document_count": len(changed_rows),
                "changed_document_fraction": len(changed_rows) / len(clean_rows),
                "immutable_evaluator_files_equal": integrity,
                "clean_corpus_sha256": sha256_file(clean_directory / "corpus.jsonl"),
                "poisoned_corpus_sha256": sha256_file(
                    poisoned_directory / "corpus.jsonl"
                ),
                "poison_stats_sha256": sha256_file(stats_path)
                if stats_path.is_file()
                else None,
                "generation_run_manifest_available": False,
                "known_local_generator_difference": (
                    "en_core_web_lg replaced pinned en_core_web_trf"
                ),
                "eligible_for_paper_native_anchor": False,
                "eligible_as_legacy_adapted_sensitivity": True,
            }
        )
    payload = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.1",
        "datasets": summaries,
        "audit_passed": all(
            row["document_id_sets_equal"]
            and all(row["immutable_evaluator_files_equal"].values())
            and row["changed_document_count"] > 0
            for row in summaries
        ),
        "paper_faithful_anchor_available": False,
        "decision": (
            "exclude_from_paper_native_anchor_and_retain_as_legacy_adapted_sensitivity"
        ),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _runtime_smoke(project_root: Path) -> dict[str, Any]:
    """Import frozen backends in isolation without indexing or model calls."""

    checks = {
        "microsoft_graphrag": {
            "python": project_root
            / "tools"
            / "ms_graphrag"
            / ".venv"
            / "Scripts"
            / "python.exe",
            "code": (
                "import importlib.metadata as m, json; import graphrag; "
                "print(json.dumps({'package': m.version('graphrag'), "
                "'module': graphrag.__name__}))"
            ),
            "expected_version": "3.1.0",
        },
        "lightrag": {
            "python": project_root
            / "tools"
            / "lightrag"
            / ".venv"
            / "Scripts"
            / "python.exe",
            "code": (
                "import importlib.metadata as m, json; "
                "from lightrag import LightRAG, QueryParam; "
                "q=QueryParam(mode='hybrid', only_need_context=True); "
                "print(json.dumps({'package': m.version('lightrag-hku'), "
                "'class': LightRAG.__name__, 'mode': q.mode, "
                "'only_need_context': q.only_need_context}))"
            ),
            "expected_version": "1.5.7",
        },
    }
    results: dict[str, Any] = {}
    for backend, check in checks.items():
        python = check["python"]
        if not python.is_file():
            results[backend] = {"passed": False, "error": "isolated_python_missing"}
            continue
        completed = subprocess.run(
            [str(python), "-c", str(check["code"])],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        try:
            details = (
                json.loads(completed.stdout.strip())
                if completed.returncode == 0
                else {}
            )
        except json.JSONDecodeError:
            details = {}
        results[backend] = {
            "passed": completed.returncode == 0
            and details.get("package") == check["expected_version"],
            "returncode": completed.returncode,
            "details": details,
            "stderr_tail": completed.stderr[-500:],
        }
    payload = {
        "schema_version": 1,
        "checks": results,
        "passed": all(result["passed"] for result in results.values()),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _defense_source_smoke(project_root: Path) -> dict[str, Any]:
    """Check pinned external-defense entry points without loading model weights."""

    python = project_root / ".venv" / "Scripts" / "python.exe"
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    ragdefender_root = project_root / "vendor" / "upstream" / "RAGDefender"
    rag_environment = environment | {"PYTHONPATH": str(ragdefender_root)}
    rag = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import ragdefender; from ragdefender import RAGDefender; "
                "print(getattr(ragdefender, '__version__', 'unknown'), "
                "RAGDefender.__name__)"
            ),
        ],
        cwd=project_root,
        env=rag_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    hog_files = [
        project_root
        / "vendor"
        / "upstream"
        / "HoG-GRAG"
        / "Baselines"
        / "Query_Paraphrasing.py",
        project_root
        / "vendor"
        / "upstream"
        / "HoG-GRAG"
        / "Baselines"
        / "Perplexity_based.py",
        project_root / "vendor" / "upstream" / "HoG-GRAG" / "Src" / "evaluation.py",
    ]
    hog_code = (
        "from pathlib import Path; import sys; "
        "[compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in sys.argv[1:]]; "
        "print(len(sys.argv)-1)"
    )
    hog = subprocess.run(
        [str(python), "-c", hog_code, *[str(path) for path in hog_files]],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    payload = {
        "schema_version": 1,
        "ragdefender": {
            "passed": rag.returncode == 0 and "0.2.0 RAGDefender" in rag.stdout,
            "stdout": rag.stdout.strip(),
            "stderr_tail": rag.stderr[-500:],
            "paper_embedder_weights_loaded": False,
            "paper_execution_deferred_to_anchor": True,
        },
        "hog_grag": {
            "passed": hog.returncode == 0 and hog.stdout.strip() == str(len(hog_files)),
            "compiled_source_files": [
                path.relative_to(project_root).as_posix() for path in hog_files
            ],
            "stderr_tail": hog.stderr[-500:],
            "provider_calls": 0,
            "paper_execution_deferred_to_anchor": True,
        },
    }
    payload["passed"] = (
        payload["ragdefender"]["passed"] and payload["hog_grag"]["passed"]
    )
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _adapter_fidelity_smoke(
    *,
    poisonedrag_path: Path,
    poisonedrag_query_ids: set[str],
    gragpoison_path: Path,
    gragpoison_query_ids: set[str],
) -> dict[str, Any]:
    """Normalize official/synthetic fixtures through every E0 adapter boundary."""

    poisonedrag_payload = json.loads(poisonedrag_path.read_text(encoding="utf-8"))
    poisonedrag_adapted = [
        PoisonedRAGOfficialAdapter.adapt("hotpotqa", poisonedrag_payload[query_id])
        for query_id in sorted(poisonedrag_query_ids)
    ]
    if any(
        FORBIDDEN_ATTACKER_FIELDS.intersection(item.instance.to_json_dict())
        for item in poisonedrag_adapted
    ):
        raise AssertionError("PoisonedRAG attacker instance leaked evaluator gold")

    grag_payload = json.loads(gragpoison_path.read_text(encoding="utf-8"))
    grag_questions = {
        str(question["id"]): question
        for group in grag_payload
        for question in group.get("questions", [])
    }
    for query_id in gragpoison_query_ids:
        GRAGPoisonAdapter.validate_official_question(grag_questions[query_id])

    logicpoison = LogicPoisonPairAdapter.adapt(
        dataset="hotpotqa",
        query_id="fixture-query",
        clean_document={"_id": "doc-1", "title": "A", "text": "A supports B."},
        poisoned_document={
            "_id": "doc-1",
            "title": "A",
            "text": "A supports adversarial C.",
        },
    )
    gragpoison = GRAGPoisonAdapter.adapt_generated(
        {
            "dataset": "musique",
            "query_id": "fixture-query",
            "attack_mode": "targeted",
            "target_answer": "adversarial target",
            "target_relation": ["A", "supports", "C"],
            "malicious_texts": ["A supports adversarial C."],
            "fidelity": "paper_native",
        }
    )
    badrag = BadRAGReimplementationAdapter.adapt(
        {
            "dataset": "hotpotqa",
            "query_id": "fixture-query",
            "trigger": "semantic trigger",
            "payload": "fixed payload",
            "malicious_text": "Trigger-bearing fixture passage.",
        }
    )
    attack_instances = [
        poisonedrag_adapted[0].instance,
        logicpoison.instance,
        gragpoison.instance,
        badrag.instance,
    ]
    base_document_ids = attack_instances[0].malicious_document_ids
    backend_traces = [
        normalize_context_trace(
            backend_id=backend_id,
            instance_id=attack_instances[0].instance_id,
            defense_id="D0_no_defense",
            corpus_modified=True,
            index_included=True,
            graph_surfaced=True,
            retrieved_document_ids=base_document_ids,
            prompt_document_ids=base_document_ids[:1],
            rendered_prompt="offline E0 fixture",
            metadata={"mode": mode},
        )
        for backend_id, mode in (
            ("S1_microsoft_graphrag", "local"),
            ("S2_lightrag", "hybrid"),
        )
    ]
    defense_ids = [contract.adapter_id for contract in DEFENSE_CONTRACTS]
    defense_traces = [
        normalize_defense_trace(
            trace,
            defense_id=defense_id,
            kept_prompt_document_ids=trace.prompt_document_ids,
        )
        for trace in backend_traces
        for defense_id in defense_ids
    ]
    payload = {
        "schema_version": 1,
        "poisonedrag_golden_instances": len(poisonedrag_adapted),
        "poisonedrag_document_budget_values": sorted(
            {len(item.documents) for item in poisonedrag_adapted}
        ),
        "gragpoison_golden_questions": len(gragpoison_query_ids),
        "attack_endpoint_families": sorted(
            {instance.endpoint_family for instance in attack_instances}
        ),
        "backend_trace_count": len(backend_traces),
        "defense_trace_count": len(defense_traces),
        "attacker_gold_leaks": 0,
        "provider_calls": 0,
        "passed": len(poisonedrag_adapted) == 6
        and len(gragpoison_query_ids) == 14
        and len(defense_traces) == 2 * len(DEFENSE_CONTRACTS),
    }
    payload["fingerprint"] = fingerprint_json(payload)
    return payload


def _cell_matrix() -> list[dict[str, Any]]:
    datasets = ("hotpotqa", "musique", "2wikimultihopqa")
    systems = ("S1_microsoft_graphrag", "S2_lightrag")
    attacks = {item.adapter_id: item for item in ATTACK_CONTRACTS}
    defenses = {item.adapter_id: item for item in DEFENSE_CONTRACTS}
    rows: list[dict[str, Any]] = []
    for dataset in datasets:
        for system in systems:
            for attack_id, attack in attacks.items():
                fidelity = "paper_native"
                if dataset not in attack.native_datasets:
                    fidelity = (
                        "dataset_port" if attack.native_datasets else "reimplementation"
                    )
                if (
                    system.removeprefix("S1_").removeprefix("S2_")
                    not in attack.native_backends
                ):
                    if fidelity == "paper_native":
                        fidelity = "backend_port"
                    elif fidelity == "dataset_port":
                        fidelity = "dataset_and_backend_port"
                status = "ready_for_e1_implementation"
                if attack_id == "A4_badrag":
                    status = "blocked_faithful_reimplementation"
                cell = f"E1-{dataset}-{system}-{attack_id}"
                rows.append(
                    {
                        "cell_id": cell,
                        "stage": "E1",
                        "track": "backdoor"
                        if attack_id == "A4_badrag"
                        else "wrong_answer",
                        "dataset": dataset,
                        "system": system,
                        "attack": attack_id,
                        "defense": "D0_no_defense",
                        "split": "validation",
                        "attempted": 100,
                        "endpoint": attack.endpoint_family,
                        "fidelity": fidelity,
                        "status": status,
                    }
                )
                for defense_id, defense in defenses.items():
                    e2_status = "gated_by_e1"
                    if status.startswith("blocked"):
                        e2_status = status
                    if defense_id == "D6_logicguard_full":
                        e2_status = "blocked_method_incomplete"
                    elif defense_id == "D7_oracle_clean_recovery":
                        e2_status = "gated_oracle_not_ranked"
                    rows.append(
                        {
                            "cell_id": f"E2-{dataset}-{system}-{attack_id}-{defense_id}",
                            "stage": "E2",
                            "track": "backdoor"
                            if attack_id == "A4_badrag"
                            else "wrong_answer",
                            "dataset": dataset,
                            "system": system,
                            "attack": attack_id,
                            "defense": defense_id,
                            "split": "locked_test",
                            "attempted": 300,
                            "endpoint": attack.endpoint_family,
                            "fidelity": fidelity,
                            "status": e2_status,
                        }
                    )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, buffer.getvalue(), encoding="utf-8-sig")


def _report(
    readiness: Mapping[str, Any],
    split_audits: list[Mapping[str, Any]],
    overlap: Mapping[str, Any],
    legacy_audit: Mapping[str, Any],
    matrix: list[Mapping[str, Any]],
) -> str:
    matrix_status = Counter(str(row["status"]) for row in matrix)
    split_lines = "\n".join(
        f"| {audit['dataset']} | {audit['counts']['development']} | {audit['counts']['validation']} | {audit['counts']['locked_test']} | {'PASS' if audit['passed'] else 'FAIL'} |"
        for audit in split_audits
    )
    return f"""# Comparative Benchmark E0 Readiness

状态：`{readiness["overall_status"]}`  
冻结版本：`comparison-v1.1`  
冻结日期：`2026-09-03`

## E0 当前结论

E0-A 的资产、划分、schema、攻击终点和 adapter contract 已形成机器可读产物；E0-B 的后端隔离导入、外部防御 source smoke 与保存 fixture adapter smoke 也已通过。E0 至此关闭，但本文不自动授权 E1 付费攻击生成；必须先完成对应 execution adapter 与成本冻结。E2 locked-test 防御排名继续受 E1 资格门约束。

| dataset | development | validation | locked test | leakage/overlap audit |
| --- | ---: | ---: | ---: | --- |
{split_lines}

## Golden fidelity fixtures

- PoisonedRAG × HotpotQA：官方 100 条中与共同基准重合 `{overlap["poisonedrag_hotpotqa"]["common_query_overlap_count"]}` 条；仅用于字段、target 与 5-document budget contract。
- GRAGPoison × MuSiQue：官方 `{overlap["gragpoison_musique"]["official_question_count"]}` 条中重合 `{overlap["gragpoison_musique"]["common_query_overlap_count"]}` 条；仅用于字段与 hop/decomposition contract。
- 这些小样本不产生 ASR 估计，不扩写为官方 100/300 样本。

## 决策门

- E0-A asset manifest：`{"PASS" if readiness["gates"]["asset_manifest"] else "FAIL"}`
- E0-A split/leakage：`{"PASS" if readiness["gates"]["split_and_leakage"] else "FAIL"}`
- E0-A golden overlap：`{"PASS" if readiness["gates"]["golden_fixtures"] else "FAIL"}`
- E0-A schemas/contracts：`{"PASS" if readiness["gates"]["contracts"] else "FAIL"}`
- E0-B LogicPoison legacy provenance classification：`{"PASS" if readiness["gates"]["legacy_logicpoison_audit"] else "FAIL"}`（paper-faithful anchor 仍不可用）
- E0-B GraphRAG/LightRAG isolated import：`{"PASS" if readiness["gates"]["backend_runtime_imports"] else "FAIL"}`
- E0-B RAGDefender/HoG source smoke：`{"PASS" if readiness["gates"]["external_defense_source_smoke"] else "FAIL"}`
- E0-B four-attack/two-backend/eight-defense fixture adapters：`{"PASS" if readiness["gates"]["adapter_fixture_fidelity"] else "FAIL"}`
- E0 overall：`{"PASS" if readiness["e0_a_passed"] and readiness["e0_b_passed"] else "FAIL"}`

LogicPoison 旧语料已重算 changed-doc/hash：HotpotQA `{legacy_audit["datasets"][0]["changed_document_count"]}`、MuSiQue `{legacy_audit["datasets"][1]["changed_document_count"]}`、2Wiki `{legacy_audit["datasets"][2]["changed_document_count"]}` 篇文档发生变化；query/answer/qrels 保持相同。由于缺少原生成 run manifest 且生成仓库曾把 `en_core_web_trf` 改为 `en_core_web_lg`，它们被强制分类为 `legacy_adapted`，不得进入 paper-native anchor。

E0 的 fixture smoke 只证明接口语义与本地入口可重复，不等于攻击/防御论文结果复现。进入 E1 前仍要实现 A1–A3 execution paths、完成 BadRAG development smoke 并冻结付费成本；D3/D4 的 paper-native 模型级锚点和 D6 full dual-track 必须在 E2 前完成，不能把 source compile/import 当成效果证据。

## Cell 状态

机器矩阵共 `{len(matrix)}` 行：`{dict(sorted(matrix_status.items()))}`。只有状态为 `ready_for_e1_implementation` 的 validation cell 可在 E0-B 通过、成本表审核后进入 E1；所有 E2 行仍受 E1 资格门锁定。

## 禁止事项

本次没有调用付费 API、没有生成攻击、没有重建正式索引、没有运行 LightRAG batch，也没有修改 `external_repos/logicPoison` 或 `.logicguard_remote_backup`。validation/locked-test gold 与 support 只存在 evaluator-only 文件，攻击者可见 split 文件不含这些字段。
"""


def run(config_path: Path) -> dict[str, Any]:
    project_root = find_project_root(config_path)
    config = load_yaml(config_path)
    assets_config = load_yaml(
        resolve_project_path(config["assets_config"], project_root=project_root)
    )
    parameters_path = resolve_project_path(
        config["parameters_config"], project_root=project_root
    )
    parameters = load_yaml(parameters_path)
    outputs = {
        key: resolve_project_path(value, project_root=project_root)
        for key, value in config["outputs"].items()
    }

    manifest = _asset_manifest(project_root, assets_config)
    atomic_write_json(outputs["asset_manifest"], manifest)

    split_audits: list[dict[str, Any]] = []
    query_ids: dict[str, set[str]] = {}
    for dataset_config in config["datasets"]:
        dataset = str(dataset_config["id"])
        directory = resolve_project_path(
            dataset_config["directory"], project_root=project_root
        )
        public_rows, evaluator_rows, audit = _build_split_rows(
            dataset=dataset,
            directory=directory,
            namespace=str(config["split_seed_namespace"]),
            sizes=config["split_sizes"],
        )
        write_jsonl(
            outputs["root"] / "splits" / f"{dataset}_attacker_safe.jsonl", public_rows
        )
        write_jsonl(
            outputs["root"] / "splits" / "evaluator_only" / f"{dataset}.jsonl",
            evaluator_rows,
        )
        query_ids[dataset] = {row["query_id"] for row in public_rows}
        split_audits.append(audit)
    split_payload = {
        "schema_version": 1,
        "benchmark_version": str(config["benchmark_version"]),
        "seed_namespace": str(config["split_seed_namespace"]),
        "datasets": split_audits,
        "passed": all(audit["passed"] for audit in split_audits),
    }
    split_payload["fingerprint"] = fingerprint_json(split_payload)
    atomic_write_json(outputs["split_audit"], split_payload)

    poisonedrag_path = resolve_project_path(
        config["golden_assets"]["poisonedrag_hotpotqa"],
        project_root=project_root,
    )
    gragpoison_path = resolve_project_path(
        config["golden_assets"]["gragpoison_musique"],
        project_root=project_root,
    )
    poisonedrag_rows, poisonedrag_summary = _poisonedrag_overlap(
        poisonedrag_path, query_ids["hotpotqa"]
    )
    grag_rows, grag_summary = _gragpoison_overlap(gragpoison_path, query_ids["musique"])
    write_jsonl(
        outputs["root"] / "fixtures" / "poisonedrag_hotpotqa_overlap.jsonl",
        poisonedrag_rows,
    )
    write_jsonl(
        outputs["root"] / "fixtures" / "gragpoison_musique_overlap.jsonl", grag_rows
    )
    overlap = {
        "schema_version": 1,
        "poisonedrag_hotpotqa": poisonedrag_summary,
        "gragpoison_musique": grag_summary,
    }
    overlap["passed"] = poisonedrag_summary["passed"] and grag_summary["passed"]
    overlap["fingerprint"] = fingerprint_json(overlap)
    atomic_write_json(outputs["overlap_audit"], overlap)

    parameter_payload = dict(parameters)
    parameter_payload["source_sha256"] = sha256_file(parameters_path)
    parameter_payload["fingerprint"] = fingerprint_json(parameters)
    atomic_write_json(outputs["parameter_diff"], parameter_payload)

    legacy_audit = _audit_legacy_logicpoison(
        project_root,
        outputs["root"],
        [str(dataset["id"]) for dataset in config["datasets"]],
    )
    atomic_write_json(outputs["legacy_logicpoison_audit"], legacy_audit)
    runtime_smoke = _runtime_smoke(project_root)
    defense_source_smoke = _defense_source_smoke(project_root)
    adapter_smoke = _adapter_fidelity_smoke(
        poisonedrag_path=poisonedrag_path,
        poisonedrag_query_ids={row["query_id"] for row in poisonedrag_rows},
        gragpoison_path=gragpoison_path,
        gragpoison_query_ids={row["query_id"] for row in grag_rows},
    )
    fidelity_smoke = {
        "schema_version": 1,
        "backend_runtime": runtime_smoke,
        "external_defense_source": defense_source_smoke,
        "adapter_fixtures": adapter_smoke,
        "passed": runtime_smoke["passed"]
        and defense_source_smoke["passed"]
        and adapter_smoke["passed"],
    }
    fidelity_smoke["fingerprint"] = fingerprint_json(fidelity_smoke)
    atomic_write_json(outputs["fidelity_smoke"], fidelity_smoke)

    contracts = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.1",
        "attacks": [item.to_json_dict() for item in ATTACK_CONTRACTS],
        "backends": [item.to_json_dict() for item in BACKEND_CONTRACTS],
        "defenses": [item.to_json_dict() for item in DEFENSE_CONTRACTS],
        "attacker_forbidden_fields": sorted(FORBIDDEN_ATTACKER_FIELDS),
    }
    contracts["fingerprint"] = fingerprint_json(contracts)
    atomic_write_json(outputs["adapter_contracts"], contracts)

    matrix = _cell_matrix()
    _write_csv(outputs["cell_matrix"], matrix)
    e0_a_gates = {
        "asset_manifest": bool(manifest["passed"]),
        "split_and_leakage": bool(split_payload["passed"]),
        "golden_fixtures": bool(overlap["passed"]),
        "contracts": True,
        "legacy_logicpoison_audit": bool(legacy_audit["audit_passed"]),
    }
    e0_b_gates = {
        "backend_runtime_imports": bool(runtime_smoke["passed"]),
        "external_defense_source_smoke": bool(defense_source_smoke["passed"]),
        "adapter_fixture_fidelity": bool(adapter_smoke["passed"]),
    }
    gates = e0_a_gates | e0_b_gates
    e0_a_passed = all(e0_a_gates.values())
    e0_b_passed = all(e0_b_gates.values())
    readiness = {
        "schema_version": 1,
        "benchmark_version": "comparison-v1.1",
        "freeze_date": str(config["freeze_date"]),
        "gates": gates,
        "e0_a_passed": e0_a_passed,
        "e0_b_passed": e0_b_passed,
        "overall_status": "E0_PASSED__E1_IMPLEMENTATION_GATED"
        if e0_a_passed and e0_b_passed
        else "E0_BLOCKED",
        "paid_api_calls": 0,
        "attack_generations": 0,
        "formal_reindexes": 0,
        "backend_runtime_smoke": runtime_smoke,
        "blockers": [],
        "next_phase_requirements": [
            "implement_a1_a3_attack_execution_paths_before_e1",
            "run_badrag_development_reimplementation_smoke_before_its_e1_cells",
            "freeze_paid_cost_forecast_before_any_e1_call",
            "run_paper_native_d3_d4_anchors_before_e2",
            "implement_logicguard_d6_full_dual_track_before_e2",
        ],
    }
    readiness["fingerprint"] = fingerprint_json(readiness)
    atomic_write_json(outputs["readiness"], readiness)
    atomic_write_text(
        outputs["report"],
        _report(readiness, split_audits, overlap, legacy_audit, matrix),
    )
    return readiness


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    readiness = run(args.config.resolve())
    print(json.dumps(readiness, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
