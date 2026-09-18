"""Freeze Stage47 attacks and audit a corpus-level GraphRAG reindex dry-run."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    load_jsonl,
    sha256_file,
    write_inferred_csv,
    write_jsonl,
)
from logicguard.core.run_state import FunnelCounts, fingerprint_json
from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.defense.non_oracle_recovery import (
    load_candidate_sources,
    rank_non_oracle_candidates,
)
from logicguard.evaluation.answer_generation import (
    Stage27RenderingPolicy,
    build_stage27_answer_cases,
)
from logicguard.llm.context import build_qa_messages
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
)
from logicguard.ms_graphrag.prepare_workspace import (
    MsGraphRagWorkspaceConfig,
    prepare_ms_graphrag_workspace,
)

_METRICS_PATTERN = re.compile(
    r"Metrics for (?P<model>[^:]+):\s*(?P<payload>\{.*?\n\})", re.DOTALL
)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
_ADDITIVE_METRIC_FIELDS = (
    "attempted_request_count",
    "successful_response_count",
    "failed_response_count",
    "requests_with_retries",
    "retries",
    "compute_duration_seconds",
    "streaming_responses",
    "responses_with_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)


@dataclass(frozen=True, slots=True)
class ReindexExposureConfig:
    """Paths and frozen policies for one context-only reindex pilot."""

    dataset: str
    attack_family: str
    max_attacks: int
    sample_path: Path
    clean_corpus_path: Path
    clean_context_path: Path
    attack_records_path: Path
    attacked_context_path: Path
    preflight_rows_path: Path
    judged_results_path: Path
    stage47_attack_config_path: Path
    reference_workspace_root: Path
    selected_samples_output_path: Path
    frozen_attacks_output_path: Path
    poisoned_corpus_output_path: Path
    attack_manifest_output_path: Path
    workspace_root: Path
    context_output_path: Path
    prompt_cases_output_path: Path
    exposure_output_path: Path
    exposure_csv_output_path: Path
    index_manifest_output_path: Path
    summary_output_path: Path
    run_status_output_path: Path
    selection_policy: str = "strict_targeted_success"
    clean_corpus_scope: str = "all"
    diagnostic_auth_probe_count: int = 0
    omit_community_reports: bool = False
    context_method: str = "full_query_guard"
    max_sources: int = 12
    max_chars_per_source: int = 450
    prompt_policy: str = "evidence_compare"
    stage47_attack_config_paths: tuple[Path, ...] = ()

    @classmethod
    def from_yaml(cls, path: Path) -> "ReindexExposureConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve_path_value(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (project_root / candidate).resolve()
            )

        def resolve(key: str) -> Path:
            return resolve_path_value(payload[key])

        return cls(
            dataset=str(payload["dataset"]),
            attack_family=str(payload["attack_family"]),
            max_attacks=int(payload.get("max_attacks", 5)),
            sample_path=resolve("sample_path"),
            clean_corpus_path=resolve("clean_corpus_path"),
            clean_context_path=resolve("clean_context_path"),
            attack_records_path=resolve("attack_records_path"),
            attacked_context_path=resolve("attacked_context_path"),
            preflight_rows_path=resolve("preflight_rows_path"),
            judged_results_path=resolve("judged_results_path"),
            stage47_attack_config_path=resolve("stage47_attack_config_path"),
            reference_workspace_root=resolve("reference_workspace_root"),
            selected_samples_output_path=resolve("selected_samples_output_path"),
            frozen_attacks_output_path=resolve("frozen_attacks_output_path"),
            poisoned_corpus_output_path=resolve("poisoned_corpus_output_path"),
            attack_manifest_output_path=resolve("attack_manifest_output_path"),
            workspace_root=resolve("workspace_root"),
            context_output_path=resolve("context_output_path"),
            prompt_cases_output_path=resolve("prompt_cases_output_path"),
            exposure_output_path=resolve("exposure_output_path"),
            exposure_csv_output_path=resolve("exposure_csv_output_path"),
            index_manifest_output_path=resolve("index_manifest_output_path"),
            summary_output_path=resolve("summary_output_path"),
            run_status_output_path=resolve("run_status_output_path"),
            selection_policy=str(
                payload.get("selection_policy", "strict_targeted_success")
            ),
            clean_corpus_scope=str(payload.get("clean_corpus_scope", "all")),
            diagnostic_auth_probe_count=int(
                payload.get("diagnostic_auth_probe_count", 0)
            ),
            omit_community_reports=bool(payload.get("omit_community_reports", False)),
            context_method=str(payload.get("context_method", "full_query_guard")),
            max_sources=int(payload.get("max_sources", 12)),
            max_chars_per_source=int(payload.get("max_chars_per_source", 450)),
            prompt_policy=str(payload.get("prompt_policy", "evidence_compare")),
            stage47_attack_config_paths=tuple(
                resolve_path_value(item)
                for item in payload.get("stage47_attack_config_paths", [])
            ),
        )


def prepare_reindex_dry_run(config: ReindexExposureConfig) -> dict[str, Any]:
    """Freeze eligible attacks, build a corpus variant and prepare a workspace."""

    _require_new_workspace(config.workspace_root)
    samples = load_normalized_samples(config.sample_path)
    samples_by_id = {sample.query_id: sample for sample in samples}
    selected = select_frozen_attacks(
        dataset=config.dataset,
        attack_family=config.attack_family,
        max_attacks=config.max_attacks,
        samples_by_id=samples_by_id,
        attack_rows=load_jsonl(config.attack_records_path),
        attacked_context_rows=load_jsonl(config.attacked_context_path),
        preflight_rows=load_jsonl(config.preflight_rows_path),
        judged_rows=load_jsonl(config.judged_results_path),
        selection_policy=config.selection_policy,
    )
    _attach_exact_attacker_visible_hashes(config, selected)

    selected_ids = {str(row["query_id"]) for row in selected}
    raw_samples = [
        row
        for row in load_jsonl(config.sample_path)
        if str(row.get("query_id", "")) in selected_ids
    ]
    raw_samples.sort(key=lambda row: _selected_order(selected, str(row["query_id"])))
    write_jsonl(config.selected_samples_output_path, raw_samples)
    write_jsonl(config.frozen_attacks_output_path, selected)

    clean_base = _clean_corpus_documents(
        samples=samples,
        clean_corpus_path=config.clean_corpus_path,
        scope=config.clean_corpus_scope,
    )
    poisoned_rows, corpus_mutation = _build_poisoned_corpus_rows(
        clean_base=clean_base,
        selected=selected,
    )
    write_jsonl(config.poisoned_corpus_output_path, poisoned_rows)

    prepare_ms_graphrag_workspace(
        MsGraphRagWorkspaceConfig(
            dataset=config.dataset,
            sample_path=config.selected_samples_output_path,
            corpus_path=config.poisoned_corpus_output_path,
            workspace_root=config.workspace_root,
            doc_scope="all",
        )
    )
    shutil.copy2(
        config.reference_workspace_root / "settings.yaml",
        config.workspace_root / "settings.yaml",
    )
    shutil.copytree(
        config.reference_workspace_root / "prompts",
        config.workspace_root / "prompts",
    )
    if config.omit_community_reports:
        _omit_unused_community_report_workflow(config.workspace_root / "settings.yaml")

    clean_base_payload = [
        {"_id": doc.doc_id, "title": doc.title, "text": doc.text} for doc in clean_base
    ]
    manifest = {
        "schema_version": 1,
        "experiment": "E1:corpus_reindex_context_only_dry_run",
        "dataset": config.dataset,
        "attack_family": config.attack_family,
        "selection_policy": config.selection_policy,
        "selection_rule": _selection_rule_description(config.selection_policy),
        "selected_attack_count": len(selected),
        "selected_query_ids": [row["query_id"] for row in selected],
        "clean_full_corpus": _artifact(config.clean_corpus_path),
        "clean_corpus_scope": config.clean_corpus_scope,
        "clean_base_doc_count": len(clean_base_payload),
        "clean_base_sha256": fingerprint_json(clean_base_payload),
        "poisoned_corpus": _artifact(config.poisoned_corpus_output_path),
        "workspace_input_doc_count": len(poisoned_rows),
        "corpus_mutation": corpus_mutation,
        "stage47_attack_config": _artifact(config.stage47_attack_config_path),
        "stage47_attack_configs": [
            _artifact(path)
            for path in (
                config.stage47_attack_config_paths
                or (config.stage47_attack_config_path,)
            )
        ],
        "reference_settings": _artifact(
            config.reference_workspace_root / "settings.yaml"
        ),
        "workspace_settings": _artifact(config.workspace_root / "settings.yaml"),
        "community_reports": (
            "omitted_before_index_because_query_community_prop_zero"
            if config.omit_community_reports
            else "configured"
        ),
        "embedding_fields": (
            ["entity_description"] if config.omit_community_reports else "configured"
        ),
        "reference_prompts_sha256": _directory_fingerprint(
            config.reference_workspace_root / "prompts"
        ),
        "oracle_fields_used_for_generation": False,
        "oracle_fields_used_for_selection": True,
        "selection_oracle_boundary": (
            "Gold/judge labels select a frozen evaluation pilot only; attack text "
            "was generated earlier without gold answer or support identifiers."
        ),
        "attacks": selected,
    }
    manifest["manifest_fingerprint"] = fingerprint_json(manifest)
    atomic_write_json(config.attack_manifest_output_path, manifest)
    atomic_write_json(
        config.run_status_output_path,
        {
            "schema_version": 1,
            "experiment": manifest["experiment"],
            "status": "prepared",
            "workspace_root": str(config.workspace_root),
            "selected_attack_count": len(selected),
            "workspace_input_doc_count": len(poisoned_rows),
            "successful_provider_requests": 0,
            "reported_tokens": 0,
        },
    )
    return manifest


def _build_poisoned_corpus_rows(
    *, clean_base: list[CorpusDocument], selected: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Replace same-ID documents and append genuinely new attack documents."""

    ordered_ids = [doc.doc_id for doc in clean_base]
    if len(set(ordered_ids)) != len(ordered_ids):
        raise RuntimeError("Clean corpus contains duplicate document IDs")
    rows_by_id = {
        doc.doc_id: {"_id": doc.doc_id, "title": doc.title, "text": doc.text}
        for doc in clean_base
    }
    replaced = 0
    appended = 0
    for attack in selected:
        doc_id = str(attack["injected_doc_id"])
        replacement = {
            "_id": doc_id,
            "title": str(attack["injected_title"]),
            "text": str(attack["injected_body"]),
        }
        if doc_id in rows_by_id:
            replaced += 1
        else:
            ordered_ids.append(doc_id)
            appended += 1
        rows_by_id[doc_id] = replacement
    return [rows_by_id[doc_id] for doc_id in ordered_ids], {
        "replaced_document_count": replaced,
        "appended_document_count": appended,
        "unique_document_count": len(ordered_ids),
    }


def select_frozen_attacks(
    *,
    dataset: str,
    attack_family: str,
    max_attacks: int,
    samples_by_id: dict[str, NormalizedSample],
    attack_rows: list[dict[str, Any]],
    attacked_context_rows: list[dict[str, Any]],
    preflight_rows: list[dict[str, Any]],
    judged_rows: list[dict[str, Any]],
    selection_policy: str = "strict_targeted_success",
) -> list[dict[str, Any]]:
    """Select a deterministic, hop-stratified frozen evaluation set."""

    if selection_policy not in {"strict_targeted_success", "evaluation_valid"}:
        raise ValueError(f"Unsupported selection policy: {selection_policy}")

    method = f"stage47_{attack_family}__unprotected"
    preflight = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row
        for row in preflight_rows
    }
    judged = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row
        for row in judged_rows
    }
    attacked = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row
        for row in attacked_context_rows
    }
    eligible: list[dict[str, Any]] = []
    for attack in attack_rows:
        if attack.get("attack_family") != attack_family or not attack.get("valid"):
            continue
        query_id = str(attack.get("query_id", ""))
        if query_id not in samples_by_id:
            continue
        prompt = preflight.get((query_id, method), {})
        answer = judged.get((query_id, method), {})
        attacked_row = attacked.get((query_id, attack_family), {})
        source = _find_attack_source(attacked_row, str(attack.get("target_doc_id", "")))
        malicious = str(attack.get("malicious_answer", ""))
        gold = samples_by_id[query_id].answer
        wrong_collision_candidate = attack_family != "candidate_collision" or str(
            attack.get("collision_candidate_doc_id", "")
        ) not in {str(item) for item in samples_by_id[query_id].support_doc_ids}
        conditions = {
            "generation_valid": bool(attack.get("valid")),
            "non_oracle_generation": not any(
                bool(attack.get(key))
                for key in (
                    "attacker_used_gold_answer",
                    "attacker_used_support_ids",
                    "attacker_used_changed_labels",
                )
            ),
            "target_is_wrong": _normalize(malicious) != _normalize(gold),
            "wrong_collision_candidate": wrong_collision_candidate,
            "source_exposed_stage47": bool(prompt.get("attack_source_exposed")),
            "target_exposed_stage47": bool(prompt.get("malicious_answer_exposed")),
            "targeted_success_stage47": (
                str(answer.get("final_label", "")) == "incorrect"
                and _contains(str(answer.get("generated_answer", "")), malicious)
            ),
        }
        required_conditions = (
            (
                "generation_valid",
                "non_oracle_generation",
                "target_is_wrong",
                "wrong_collision_candidate",
                "source_exposed_stage47",
                "target_exposed_stage47",
                "targeted_success_stage47",
            )
            if selection_policy == "strict_targeted_success"
            else (
                "generation_valid",
                "non_oracle_generation",
                "target_is_wrong",
                "wrong_collision_candidate",
            )
        )
        if not all(conditions[key] for key in required_conditions) or source is None:
            continue
        source_text = str(source.get("text", ""))
        eligible.append(
            {
                "dataset": dataset,
                "query_id": query_id,
                "hop_group": query_id.split("__", maxsplit=1)[0],
                "attack_family": attack_family,
                "attack_id": str(attack.get("attack_id", "")),
                "query": samples_by_id[query_id].query,
                "gold_answer_evaluation_only": gold,
                "malicious_answer": malicious,
                "injected_doc_id": str(attack.get("target_doc_id", "")),
                "injected_title": str(attack.get("target_title", "")),
                "injected_body": _source_body(source_text),
                "injected_source_sha256": fingerprint_json(source_text),
                "attacker_visible_input_sha256": "",
                "oracle_fields_used_for_generation": False,
                "selection_policy": selection_policy,
                "eligibility": conditions,
                "stage47_generated_answer": str(answer.get("generated_answer", "")),
            }
        )

    eligible.sort(key=lambda row: _sha_order(str(row["query_id"])))
    selected: list[dict[str, Any]] = []
    for hop_prefix in ("3hop", "4hop"):
        candidate = next(
            (row for row in eligible if str(row["hop_group"]).startswith(hop_prefix)),
            None,
        )
        if candidate is not None and len(selected) < max_attacks:
            selected.append(candidate)
    for row in eligible:
        if row not in selected and len(selected) < max_attacks:
            selected.append(row)
    selected.sort(
        key=lambda row: (str(row["hop_group"]), _sha_order(str(row["query_id"])))
    )
    if len(selected) != max_attacks:
        raise RuntimeError(
            f"Only {len(selected)} eligible {attack_family} attacks; requested {max_attacks}"
        )
    return selected


def _selection_rule_description(selection_policy: str) -> str:
    if selection_policy == "strict_targeted_success":
        return (
            "strict Stage47 generation-valid, evaluation-valid, non-oracle, "
            "target-exposed, unprotected targeted-success; stratify 2/3/4-hop "
            "then SHA-256 query-id"
        )
    return (
        "Stage47 generation-valid, evaluation-valid and non-oracle; do not select "
        "on retrieval, prompt exposure or answer success; stratify 2/3/4-hop then "
        "SHA-256 query-id"
    )


def _omit_unused_community_report_workflow(settings_path: Path) -> None:
    """Freeze a local-search-only workflow without paid community summaries."""

    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    workflows = settings.get("workflows", [])
    if not isinstance(workflows, list):
        raise RuntimeError(f"GraphRAG workflows must be a list: {settings_path}")
    settings["workflows"] = [
        workflow for workflow in workflows if workflow != "create_community_reports"
    ]
    embed_text = settings.setdefault("embed_text", {})
    if not isinstance(embed_text, dict):
        raise RuntimeError(f"GraphRAG embed_text must be a mapping: {settings_path}")
    embed_text["names"] = ["entity_description"]
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def refresh_frozen_attack_manifest(config: ReindexExposureConfig) -> dict[str, Any]:
    """Refresh exact no-oracle input hashes without changing frozen attack text."""

    manifest = json.loads(
        config.attack_manifest_output_path.read_text(encoding="utf-8")
    )
    selected = load_jsonl(config.frozen_attacks_output_path)
    _attach_exact_attacker_visible_hashes(config, selected)
    write_jsonl(config.frozen_attacks_output_path, selected)
    manifest["attacks"] = selected
    manifest["workspace_settings"] = _artifact(config.workspace_root / "settings.yaml")
    manifest["community_reports"] = (
        "omitted_before_index_because_query_community_prop_zero"
        if config.omit_community_reports
        else "configured"
    )
    manifest["embedding_fields"] = (
        ["entity_description"] if config.omit_community_reports else "configured"
    )
    manifest.pop("manifest_fingerprint", None)
    manifest["manifest_fingerprint"] = fingerprint_json(manifest)
    atomic_write_json(config.attack_manifest_output_path, manifest)
    return manifest


def record_blocked_index_status(config: ReindexExposureConfig) -> dict[str, Any]:
    """Record an authentication-blocked index attempt without exposing secrets."""

    log_paths = [
        *config.workspace_root.glob("*.log"),
        *(config.workspace_root / "logs").glob("*.log"),
    ]
    log_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in log_paths
    )
    metrics = _read_graphrag_metrics(config.workspace_root)
    status = {
        "schema_version": 1,
        "experiment": "E1:corpus_reindex_context_only_dry_run",
        "status": (
            "blocked_invalid_api_key" if "invalid_api_key" in log_text else "blocked"
        ),
        "workspace_root": str(config.workspace_root),
        "index_output_present": (config.workspace_root / "output").exists(),
        "graphrag_metrics": metrics,
        "successful_provider_requests": sum(
            int(row.get("successful_response_count", 0)) for row in metrics.values()
        ),
        "failed_provider_requests": sum(
            int(row.get("failed_response_count", 0)) for row in metrics.values()
        )
        + config.diagnostic_auth_probe_count,
        "reported_tokens": sum(
            int(row.get("total_tokens", 0)) for row in metrics.values()
        ),
        "credential_values_recorded": False,
        "cost_usd": 0.0,
        "cost_basis": "No successful response and zero provider-reported tokens.",
    }
    atomic_write_json(config.run_status_output_path, status)
    return status


def audit_reindex_dry_run(config: ReindexExposureConfig) -> dict[str, Any]:
    """Audit index inclusion, retrieval rank, prompt exposure and graph effects."""

    attacks = load_jsonl(config.frozen_attacks_output_path)
    contexts = {
        str(row.get("query_id", "")): row
        for row in load_jsonl(config.context_output_path)
        if row.get("method") == config.context_method
    }
    samples = {
        sample.query_id: sample
        for sample in load_normalized_samples(config.selected_samples_output_path)
    }
    integrity = [
        {"query_id": query_id, "changed_support_doc_ids": []} for query_id in samples
    ]
    cases = build_stage27_answer_cases(
        samples=list(samples.values()),
        integrity_rows=integrity,
        context_rows=list(contexts.values()),
        dataset=config.dataset,
        methods=[config.context_method],
        max_sources=config.max_sources,
        max_chars_per_source=config.max_chars_per_source,
        rendering_policies={
            config.context_method: Stage27RenderingPolicy(
                order_policy="official_order",
                prompt_policy=config.prompt_policy,
                max_sources=config.max_sources,
                max_chars_per_source=config.max_chars_per_source,
            )
        },
    )
    cases_by_id = {case.query_id: case for case in cases}
    prompt_rows: list[dict[str, Any]] = []
    for case in cases:
        messages = build_qa_messages(
            question=case.query,
            context=case.rendered_context,
            prompt_policy=case.prompt_policy,
        )
        prompt_rows.append(
            {
                **case.to_json_dict(),
                "messages": messages,
                "prompt_text": "\n\n".join(message["content"] for message in messages),
            }
        )
    write_jsonl(config.prompt_cases_output_path, prompt_rows)

    output_dir = config.workspace_root / "output"
    community_reports_path = output_dir / "community_reports.parquet"
    frames = _read_reindex_frames(output_dir)
    clean_output = config.reference_workspace_root / "output"
    clean_counts = (
        {
            name: len(pd.read_parquet(clean_output / f"{name}.parquet"))
            for name in (
                "documents",
                "text_units",
                "entities",
                "relationships",
                "communities",
            )
        }
        if config.clean_corpus_scope == "reference_sample_support"
        else None
    )
    new_counts = {name: len(frame) for name, frame in frames.items()}

    document_surface = _frame_surface(frames["documents"])
    text_unit_surface = _frame_surface(frames["text_units"])
    graph_record_surfaces = {
        name: _record_surfaces(frames[name])
        for name in ("entities", "relationships", "community_reports")
    }
    rows: list[dict[str, Any]] = []
    for attack in attacks:
        query_id = str(attack["query_id"])
        doc_id = str(attack["injected_doc_id"])
        title = str(attack["injected_title"])
        malicious = str(attack["malicious_answer"])
        context = contexts.get(query_id, {})
        sources = _context_sources(context)
        source_ids = [_source_doc_id(source) for source in sources]
        case = cases_by_id.get(query_id)
        rendered = case.rendered_context if case is not None else ""
        row = {
            "dataset": config.dataset,
            "query_id": query_id,
            "attack_family": config.attack_family,
            "attack_id": attack["attack_id"],
            "injected_doc_id": doc_id,
            "injected_title": title,
            "malicious_answer": malicious,
            "generation_valid": True,
            "evaluation_valid": True,
            "index_document_included": _contains(document_surface, title),
            "index_text_unit_included": (
                _contains(text_unit_surface, doc_id)
                and _contains(text_unit_surface, title)
            ),
            "retrieved": doc_id in source_ids,
            "source_rank": source_ids.index(doc_id) + 1
            if doc_id in source_ids
            else None,
            "retrieved_source_count": len(source_ids),
            "prompt_source_exposed": _contains(rendered, doc_id),
            "prompt_target_exposed": _contains(rendered, malicious),
            "rendered_prompt_chars": len(rendered),
            "entity_matches": _matching_record_surfaces(
                graph_record_surfaces["entities"], [title, malicious]
            ),
            "relationship_matches": _matching_record_surfaces(
                graph_record_surfaces["relationships"], [title, malicious]
            ),
            "community_report_matches": _matching_record_surfaces(
                graph_record_surfaces["community_reports"], [title, malicious]
            ),
        }
        row["graph_surface_exposed"] = bool(
            row["entity_matches"]
            or row["relationship_matches"]
            or row["community_report_matches"]
        )
        rows.append(row)
    write_jsonl(config.exposure_output_path, rows)
    write_inferred_csv(
        config.exposure_csv_output_path,
        [_csv_exposure_row(row) for row in rows],
    )

    attempted = len(rows)
    generated_valid = sum(bool(row["generation_valid"]) for row in rows)
    evaluation_valid = sum(bool(row["evaluation_valid"]) for row in rows)
    included = sum(
        bool(row["index_document_included"] and row["index_text_unit_included"])
        for row in rows
    )
    retrieved = sum(bool(row["retrieved"]) for row in rows)
    exposed = sum(
        bool(row["prompt_source_exposed"] and row["prompt_target_exposed"])
        for row in rows
    )
    FunnelCounts(
        attempted=attempted,
        generated_valid=generated_valid,
        evaluation_valid=evaluation_valid,
        exposed=exposed,
        judged=0,
        successful=0,
    ).validate()
    metrics = _read_graphrag_metrics(config.workspace_root)
    index_manifest = {
        "schema_version": 1,
        "workspace_root": str(config.workspace_root),
        "index_scope": "official_graphrag_context_only",
        "community_reports": (
            "generated"
            if community_reports_path.exists()
            else "intentionally_omitted_query_community_prop_zero"
        ),
        "embedding_fields": ["entity_description"],
        "settings": _artifact(config.workspace_root / "settings.yaml"),
        "prompts_sha256": _directory_fingerprint(config.workspace_root / "prompts"),
        "input_sha256": _directory_fingerprint(config.workspace_root / "input"),
        "output_artifacts": [
            _artifact(path)
            for path in sorted(output_dir.glob("*.parquet"), key=lambda item: item.name)
        ],
        "output_sha256": _directory_fingerprint(output_dir),
        "graphrag_metrics": metrics,
    }
    index_manifest["manifest_fingerprint"] = fingerprint_json(index_manifest)
    atomic_write_json(config.index_manifest_output_path, index_manifest)
    summary = {
        "schema_version": 1,
        "experiment": "E1:corpus_reindex_context_only_dry_run",
        "funnel": {
            "attempted": attempted,
            "generation_valid": generated_valid,
            "evaluation_valid": evaluation_valid,
            "index_included": included,
            "retrieved": retrieved,
            "prompt_exposed": exposed,
            "answer_judged": 0,
            "attack_success": 0,
        },
        "compatible_clean_index_counts": clean_counts,
        "reindexed_counts": new_counts,
        "index_count_deltas": (
            {key: new_counts[key] - clean_counts[key] for key in clean_counts}
            if clean_counts is not None
            else None
        ),
        "index_comparison_note": (
            "Count deltas use the compatible 117-document clean reference index."
            if clean_counts is not None
            else (
                "No clean full-corpus index is available; aggregate graph count "
                "deltas are intentionally not reported. Per-attack graph surface "
                "matches remain auditable."
            )
        ),
        "graph_surface_exposed_count": sum(
            bool(row["graph_surface_exposed"]) for row in rows
        ),
        "graphrag_metrics": metrics,
        "catalog_cost_estimate_cny": _catalog_cost_estimate_cny(metrics),
        "cost_note": (
            "Estimate uses the 2026-08-12 China-Beijing undiscounted catalog: "
            "qwen3.7-plus input CNY 2/M, output CNY 8/M; text-embedding-v4 "
            "CNY 0.0005/1K input tokens. It covers GraphRAG index logs only, "
            "not standalone credential probes or five query embeddings. Actual "
            "billing can be lower due to promotions or free quota."
        ),
    }
    atomic_write_json(config.summary_output_path, summary)
    atomic_write_json(
        config.run_status_output_path,
        {
            "schema_version": 1,
            "experiment": summary["experiment"],
            "status": "completed_context_only",
            "workspace_root": str(config.workspace_root),
            "community_reports": index_manifest["community_reports"],
            "funnel": summary["funnel"],
            "graphrag_metrics": metrics,
            "successful_provider_requests": sum(
                int(row.get("successful_response_count", 0)) for row in metrics.values()
            ),
            "reported_tokens": sum(
                int(row.get("total_tokens", 0)) for row in metrics.values()
            ),
            "credential_values_recorded": False,
        },
    )
    return summary


def _clean_corpus_documents(
    *,
    samples: list[NormalizedSample],
    clean_corpus_path: Path,
    scope: str,
) -> list[CorpusDocument]:
    if scope not in {"all", "reference_sample_support"}:
        raise ValueError(f"Unsupported clean_corpus_scope: {scope}")
    corpus: dict[str, CorpusDocument] = {}
    for row in load_jsonl(clean_corpus_path):
        doc_id = str(row.get("_id", row.get("doc_id", "")))
        corpus[doc_id] = CorpusDocument(
            doc_id, str(row.get("title", "")), str(row["text"])
        )
    if scope == "all":
        documents = list(corpus.values())
        documents.sort(
            key=lambda doc: (
                (int(doc.doc_id), doc.doc_id)
                if doc.doc_id.isdigit()
                else (10**12, doc.doc_id)
            )
        )
        return documents

    support_ids = {doc_id for sample in samples for doc_id in sample.support_doc_ids}
    embedded = {doc.doc_id: doc for sample in samples for doc in sample.support_docs}
    selected = [corpus.get(doc_id, embedded.get(doc_id)) for doc_id in support_ids]
    documents = [doc for doc in selected if doc is not None]
    documents.sort(
        key=lambda doc: (
            (int(doc.doc_id), doc.doc_id)
            if doc.doc_id.isdigit()
            else (10**12, doc.doc_id)
        )
    )
    if len(documents) != len(support_ids):
        raise RuntimeError("Could not reconstruct the reference sample-support corpus")
    return documents


def _read_reindex_frames(output_dir: Path) -> dict[str, pd.DataFrame]:
    """Read required graph outputs and treat omitted reports as an empty surface."""

    frames = {
        name: pd.read_parquet(output_dir / f"{name}.parquet")
        for name in (
            "documents",
            "text_units",
            "entities",
            "relationships",
            "communities",
        )
    }
    reports_path = output_dir / "community_reports.parquet"
    frames["community_reports"] = (
        pd.read_parquet(reports_path) if reports_path.exists() else pd.DataFrame()
    )
    return frames


def _attach_exact_attacker_visible_hashes(
    config: ReindexExposureConfig, selected: list[dict[str, Any]]
) -> None:
    attack_config_paths = config.stage47_attack_config_paths or (
        config.stage47_attack_config_path,
    )
    batches: list[dict[str, Any]] = []
    for attack_config_path in attack_config_paths:
        settings = yaml.safe_load(attack_config_path.read_text(encoding="utf-8"))
        root = find_project_root(attack_config_path)

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )

        query_offset = int(settings.get("query_offset", 0))
        max_queries = int(settings.get("max_queries", 20))
        batch_samples = load_normalized_samples(resolve(settings["sample_path"]))
        query_ids = {
            sample.query_id
            for sample in batch_samples[query_offset : query_offset + max_queries]
        }
        contexts = {
            str(row.get("query_id", "")): row
            for row in load_jsonl(resolve(settings["clean_context_path"]))
            if row.get("method", "full_query_guard") == "full_query_guard"
            and str(row.get("query_id", "")) in query_ids
        }
        missing = query_ids - set(contexts)
        if missing:
            raise ValueError(
                f"Attacker-visible contexts missing {len(missing)} queries for "
                f"{attack_config_path}; first={sorted(missing)[0]}"
            )
        batches.append(
            {
                "config_path": attack_config_path,
                "query_ids": query_ids,
                "contexts": contexts,
                "source_limit": int(settings.get("source_prompt_limit", 8)),
                "candidate_limit": int(settings.get("candidate_prompt_limit", 8)),
            }
        )
    candidates = load_candidate_sources(config.reference_workspace_root / "output")
    for row in selected:
        query_id = str(row["query_id"])
        query = str(row["query"])
        matched_batches = [batch for batch in batches if query_id in batch["query_ids"]]
        if len(matched_batches) != 1:
            raise ValueError(
                f"Expected one attacker-visible batch for {query_id}; "
                f"found {len(matched_batches)}"
            )
        batch = matched_batches[0]
        context = batch["contexts"][query_id]
        source_limit = int(batch["source_limit"])
        candidate_limit = int(batch["candidate_limit"])
        visible_sources = _sources_for_hash(context)[:source_limit]
        hits = rank_non_oracle_candidates(
            query=query,
            source={"title": ""},
            candidate_sources=candidates,
            method="non_oracle_query_bm25",
            top_k=candidate_limit,
        )
        visible_candidates = [
            {
                "doc_id": hit.candidate.logicguard_doc_id,
                "title": hit.candidate.title,
                "text": hit.candidate.text,
            }
            for hit in hits
        ]
        row["attacker_visible_input_sha256"] = fingerprint_json(
            {
                "query": query,
                "retrieved_sources": visible_sources,
                "trusted_candidate_shortlist": visible_candidates,
            }
        )
        row["attacker_visible_input_scope"] = {
            "attack_config_path": str(batch["config_path"]),
            "retrieved_source_count": len(visible_sources),
            "trusted_candidate_count": len(visible_candidates),
            "gold_answer_included": False,
            "support_ids_included": False,
            "changed_labels_included": False,
        }


def _find_attack_source(
    attacked_row: dict[str, Any], doc_id: str
) -> dict[str, Any] | None:
    return next(
        (
            source
            for source in _context_sources(attacked_row)
            if _source_doc_id(source) == doc_id
        ),
        None,
    )


def _context_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    context = row.get("context_data", {})
    sources = context.get("sources", []) if isinstance(context, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(
        source.get("logicguard_doc_id")
        or parse_doc_id_from_source_text(str(source.get("text", "")))
    )


def _sources_for_hash(row: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "doc_id": _source_doc_id(source),
            "title": str(source.get("title", "")),
            "text": str(source.get("text", "")),
        }
        for source in _context_sources(row)
        if str(source.get("source_state", "")) != "stage47_adaptive_poison"
    ]


def _source_body(text: str) -> str:
    return re.sub(
        r"^Document ID:.*?\nTitle:.*?\n+", "", text, count=1, flags=re.DOTALL
    ).strip()


def _selected_order(selected: list[dict[str, Any]], query_id: str) -> int:
    return next(
        index for index, row in enumerate(selected) if row["query_id"] == query_id
    )


def _sha_order(value: str) -> str:
    return fingerprint_json(value)


def _normalize(text: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(text.lower()))


def _contains(text: str, phrase: str) -> bool:
    return bool(phrase.strip()) and _normalize(phrase) in _normalize(text)


def _frame_surface(frame: pd.DataFrame) -> str:
    return "\n".join(str(value) for value in frame.astype(str).to_numpy().ravel())


def _record_surfaces(frame: pd.DataFrame) -> tuple[str, ...]:
    return tuple(
        " ".join(str(value) for value in record.values())
        for record in frame.to_dict(orient="records")
    )


def _matching_record_surfaces(
    record_surfaces: tuple[str, ...], terms: list[str]
) -> list[str]:
    useful = [term for term in terms if not term.replace(",", "").isdigit()]
    return [
        term
        for term in useful
        if any(_contains(surface, term) for surface in record_surfaces)
    ]


def _csv_exposure_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ";".join(value) if isinstance(value, list) else value
        for key, value in row.items()
    }


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _directory_fingerprint(path: Path) -> str:
    return fingerprint_json(
        [
            {
                "path": item.relative_to(path).as_posix(),
                "size_bytes": item.stat().st_size,
                "sha256": sha256_file(item),
            }
            for item in sorted(path.rglob("*"), key=lambda item: item.as_posix())
            if item.is_file()
        ]
    )


def _read_graphrag_metrics(workspace_root: Path) -> dict[str, Any]:
    """Aggregate provider metrics across interrupted and resumed index processes."""

    metrics: dict[str, Any] = {}
    paths = [
        *workspace_root.glob("*.log"),
        *(workspace_root / "logs").glob("*.log"),
    ]
    for path in sorted(paths, key=lambda item: item.as_posix()):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _METRICS_PATTERN.finditer(text):
            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                continue
            model = match.group("model")
            aggregate = metrics.setdefault(model, {})
            for field in _ADDITIVE_METRIC_FIELDS:
                aggregate[field] = aggregate.get(field, 0) + payload.get(field, 0)
    for aggregate in metrics.values():
        attempted = int(aggregate.get("attempted_request_count", 0))
        successful = int(aggregate.get("successful_response_count", 0))
        responses_with_tokens = int(aggregate.get("responses_with_tokens", 0))
        aggregate["incomplete_response_count"] = max(
            attempted - successful - int(aggregate.get("failed_response_count", 0)),
            0,
        )
        aggregate["failure_rate"] = (
            float(aggregate.get("failed_response_count", 0)) / attempted
            if attempted
            else 0.0
        )
        aggregate["retry_rate"] = (
            float(aggregate.get("requests_with_retries", 0)) / attempted
            if attempted
            else 0.0
        )
        aggregate["compute_duration_per_response_seconds"] = (
            float(aggregate.get("compute_duration_seconds", 0)) / successful
            if successful
            else 0.0
        )
        aggregate["tokens_per_response"] = (
            float(aggregate.get("total_tokens", 0)) / responses_with_tokens
            if responses_with_tokens
            else 0.0
        )
    return metrics


def _catalog_cost_estimate_cny(metrics: dict[str, Any]) -> float:
    """Estimate logged GraphRAG cost from a frozen undiscounted price snapshot."""

    chat = metrics.get("openai/qwen3.7-plus", {})
    embedding = metrics.get("openai/text-embedding-v4", {})
    return round(
        float(chat.get("prompt_tokens", 0)) * 2.0 / 1_000_000
        + float(chat.get("completion_tokens", 0)) * 8.0 / 1_000_000
        + float(embedding.get("total_tokens", 0)) * 0.0005 / 1_000,
        6,
    )


def _require_new_workspace(path: Path) -> None:
    material = (
        [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    )
    if material:
        raise RuntimeError(f"Dry-run workspace already contains files: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("prepare", "refresh-manifest", "audit", "record-blocked"),
        required=True,
    )
    args = parser.parse_args()
    config = ReindexExposureConfig.from_yaml(args.config)
    if args.phase == "prepare":
        result = prepare_reindex_dry_run(config)
    elif args.phase == "refresh-manifest":
        result = refresh_frozen_attack_manifest(config)
    elif args.phase == "record-blocked":
        result = record_blocked_index_status(config)
    else:
        result = audit_reindex_dry_run(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
