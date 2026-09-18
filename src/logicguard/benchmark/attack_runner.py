"""Bounded A1/A3 comparative attack runner with an offline dry-run mode."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Protocol

import yaml

from logicguard.benchmark.execution_protocols import (
    BoundedAttackRequest,
    build_gragpoison_blackbox_request,
    build_logicpoison_query_request,
    build_poisonedrag_request,
    parse_logicpoison_query_response,
    parse_poisonedrag_response,
    validate_gragpoison_phase,
)
from logicguard.core.config import find_project_root
from logicguard.core.io import (
    atomic_write_json,
    load_jsonl,
    require_env,
    sha256_file,
    write_jsonl,
)
from logicguard.core.run_state import fingerprint_json
from logicguard.llm.provider import ChatResponse, OpenAICompatibleChatClient


class ChatClient(Protocol):
    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
        enable_thinking: bool | None = None,
        max_completion_tokens: int | None = None,
    ) -> ChatResponse: ...


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _unique_attack_inputs(config: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    allowed_attacks = set(config["attacks"])
    allowed_datasets = set(config["datasets"])
    for row in load_jsonl(path):
        if (
            row["attack_id"] not in allowed_attacks
            or row["dataset"] not in allowed_datasets
        ):
            continue
        if row["split"] != config["split"]:
            continue
        key = (str(row["dataset"]), str(row["attack_id"]), str(row["query_id"]))
        selected.setdefault(key, row)
    return [selected[key] for key in sorted(selected)]


def _request_row(
    input_row: dict[str, Any], request: BoundedAttackRequest, *, phase: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset": input_row["dataset"],
        "attack_id": request.attack_id,
        "query_id": request.query_id,
        "attack_seed": input_row["attack_seed"],
        "phase": phase,
        "max_calls": request.max_calls,
        "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature,
        "system_prompt": request.system_prompt,
        "user_prompt": request.user_prompt,
        "prompt_fingerprint": fingerprint_json(
            {"system": request.system_prompt, "user": request.user_prompt}
        ),
    }


def build_dry_run_plan(
    rows: list[dict[str, Any]], *, document_count: int
) -> list[dict[str, Any]]:
    """Materialize every paid request slot without contacting a provider."""

    plan: list[dict[str, Any]] = []
    placeholder: dict[str, Any] = {"placeholder": "prior_phase_output"}
    for row in rows:
        if row["attack_id"] == "A1_poisonedrag":
            request = build_poisonedrag_request(
                query_id=str(row["query_id"]),
                question=str(row["question"]),
                document_count=document_count,
            )
            plan.append(_request_row(row, request, phase="generate"))
        elif row["attack_id"] == "A2_logicpoison":
            request = build_logicpoison_query_request(
                query_id=str(row["query_id"]), question=str(row["question"])
            )
            plan.append(_request_row(row, request, phase="extract_query_entities"))
        elif row["attack_id"] == "A3_gragpoison":
            for phase in ("decompose", "select_relation", "generate_evidence"):
                request = build_gragpoison_blackbox_request(
                    query_id=str(row["query_id"]),
                    question=str(row["question"]),
                    phase=phase,
                    prior_output=None if phase == "decompose" else placeholder,
                )
                plan.append(_request_row(row, request, phase=phase))
        else:
            raise ValueError(f"unsupported attack runner input: {row['attack_id']}")
    return plan


def _chat(
    client: ChatClient,
    request: BoundedAttackRequest,
    *,
    model: str,
    timeout_seconds: int,
) -> ChatResponse:
    return client.chat(
        model=model,
        messages=[
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ],
        temperature=request.temperature,
        max_tokens=request.max_output_tokens,
        timeout_seconds=timeout_seconds,
        enable_thinking=False,
        max_completion_tokens=request.max_output_tokens,
    )


def execute_attempt(
    row: dict[str, Any],
    *,
    client: ChatClient,
    model: str,
    timeout_seconds: int,
    document_count: int = 1,
) -> dict[str, Any]:
    """Execute one attack attempt; any error is recorded and never retried."""

    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    calls_made = 0
    phases_completed = 0

    def call(request: BoundedAttackRequest) -> ChatResponse:
        nonlocal calls_made
        calls_made += 1
        response = _chat(client, request, model=model, timeout_seconds=timeout_seconds)
        usage["prompt_tokens"] += response.prompt_tokens or 0
        usage["completion_tokens"] += response.completion_tokens or 0
        usage["reasoning_tokens"] += response.reasoning_tokens or 0
        usage["total_tokens"] += response.total_tokens or 0
        return response

    try:
        if row["attack_id"] == "A1_poisonedrag":
            request = build_poisonedrag_request(
                query_id=str(row["query_id"]),
                question=str(row["question"]),
                document_count=document_count,
            )
            parsed = parse_poisonedrag_response(
                call(request).content, expected_document_count=document_count
            )
            output: dict[str, Any] = parsed
            phases_completed = 1
        elif row["attack_id"] == "A2_logicpoison":
            request = build_logicpoison_query_request(
                query_id=str(row["query_id"]), question=str(row["question"])
            )
            output = {
                "entities": parse_logicpoison_query_response(call(request).content)
            }
            phases_completed = 1
        elif row["attack_id"] == "A3_gragpoison":
            prior: dict[str, Any] = {}
            phases: dict[str, Any] = {}
            for phase in ("decompose", "select_relation", "generate_evidence"):
                request = build_gragpoison_blackbox_request(
                    query_id=str(row["query_id"]),
                    question=str(row["question"]),
                    phase=phase,
                    prior_output=prior or None,
                )
                parsed = dict(
                    validate_gragpoison_phase(call(request).content, phase=phase)
                )
                phases[phase] = parsed
                prior = {**prior, **parsed}
                phases_completed += 1
            output = {"phases": phases, "attack_record": prior}
        else:
            raise ValueError(f"unsupported attack runner input: {row['attack_id']}")
        return {
            "schema_version": 1,
            "dataset": row["dataset"],
            "attack_id": row["attack_id"],
            "query_id": row["query_id"],
            "attack_seed": row["attack_seed"],
            "generation_valid": True,
            "provider_calls_made": calls_made,
            "phases_completed": phases_completed,
            "output": output,
            "token_usage": usage,
            "error": None,
        }
    except Exception as exc:  # provider and schema failures are experimental outcomes
        return {
            "schema_version": 1,
            "dataset": row["dataset"],
            "attack_id": row["attack_id"],
            "query_id": row["query_id"],
            "attack_seed": row["attack_seed"],
            "generation_valid": False,
            "provider_calls_made": calls_made,
            "phases_completed": phases_completed,
            "output": None,
            "token_usage": usage,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _planned_cost_cap(plan: list[dict[str, Any]], config: dict[str, Any]) -> float:
    pricing = config["pricing"]
    total = 0.0
    for row in plan:
        caps = pricing["per_attack_token_caps"][row["attack_id"]]
        total += (
            int(caps["input_per_call"]) * float(pricing["input_per_million_tokens_cny"])
            + int(caps["output_per_call"])
            * float(pricing["output_per_million_tokens_cny"])
        ) / 1_000_000
    return total


def run(config_path: Path, *, client: ChatClient | None = None) -> dict[str, Any]:
    root = find_project_root(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    rows = _unique_attack_inputs(config, _resolve(root, config["input_manifest"]))
    output_paths = {
        key: _resolve(root, value) for key, value in config["outputs"].items()
    }
    plan = build_dry_run_plan(
        rows, document_count=int(config["matched_documents_per_target"])
    )
    input_manifest_sha256 = sha256_file(_resolve(root, config["input_manifest"]))
    mode = str(config["run_mode"])
    if mode == "execute":
        result_path = output_paths.get("results")
        summary_path = output_paths.get("summary")
        if result_path is None or summary_path is None:
            raise ValueError(
                "execute mode requires outputs.results and outputs.summary"
            )
        if result_path.exists() or summary_path.exists():
            raise FileExistsError(
                "refusing to rerun a paid namespace with existing result/summary artifacts"
            )
        planned_cost_cap = _planned_cost_cap(plan, config)
        hard_cost_cap = float(config["pricing"]["hard_cost_cap_cny"])
        if planned_cost_cap > hard_cost_cap + 1e-12:
            raise RuntimeError(
                f"planned catalog cap {planned_cost_cap:.6f} exceeds hard cap "
                f"{hard_cost_cap:.6f} CNY"
            )
    write_jsonl(output_paths["request_plan"], plan)
    request_plan_sha256 = sha256_file(output_paths["request_plan"])
    if mode == "dry_run":
        summary = {
            "schema_version": 1,
            "benchmark_version": config["benchmark_version"],
            "run_mode": mode,
            "unique_attack_attempts": len(rows),
            "planned_provider_calls": len(plan),
            "calls_by_attack": {
                attack: sum(item["attack_id"] == attack for item in plan)
                for attack in config["attacks"]
            },
            "all_requests_single_call": all(item["max_calls"] == 1 for item in plan),
            "input_manifest_sha256": input_manifest_sha256,
            "request_plan_sha256": request_plan_sha256,
            "provider_calls_made": 0,
            "credentials_read": False,
            "generation_controls": {
                "enable_thinking": False,
                "output_limit_parameter": "max_completion_tokens",
            },
            "status": "DRY_RUN_PASSED",
        }
    elif mode == "execute":
        assert result_path is not None
        assert summary_path is not None
        if client is None:
            key = require_env(str(config["api_key_env"]))
            base_url = os.environ.get(str(config["base_url_env"]), "").strip() or str(
                config["default_base_url"]
            )
            client = OpenAICompatibleChatClient(base_url=base_url, api_key=key)
        results = [
            execute_attempt(
                row,
                client=client,
                model=str(config["model"]),
                timeout_seconds=int(config["timeout_seconds"]),
                document_count=int(config["matched_documents_per_target"]),
            )
            for row in rows
        ]
        write_jsonl(result_path, results)
        prompt_tokens = sum(row["token_usage"]["prompt_tokens"] for row in results)
        completion_tokens = sum(
            row["token_usage"]["completion_tokens"] for row in results
        )
        catalog_cost = (
            prompt_tokens * float(config["pricing"]["input_per_million_tokens_cny"])
            + completion_tokens
            * float(config["pricing"]["output_per_million_tokens_cny"])
        ) / 1_000_000
        summary = {
            "schema_version": 1,
            "benchmark_version": config["benchmark_version"],
            "run_mode": mode,
            "unique_attack_attempts": len(rows),
            "planned_provider_calls": len(plan),
            "generation_valid": sum(row["generation_valid"] for row in results),
            "input_manifest_sha256": input_manifest_sha256,
            "request_plan_sha256": request_plan_sha256,
            "provider_calls_made": sum(row["provider_calls_made"] for row in results),
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "reasoning_tokens": sum(
                    row["token_usage"].get("reasoning_tokens", 0) for row in results
                ),
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "planned_catalog_cost_cap_cny": round(planned_cost_cap, 6),
            "hard_cost_cap_cny": hard_cost_cap,
            "actual_catalog_cost_cny": round(catalog_cost, 6),
            "credentials_read": True,
            "generation_controls": {
                "enable_thinking": False,
                "output_limit_parameter": "max_completion_tokens",
            },
            "status": (
                "EXECUTION_COMPLETE"
                if catalog_cost <= hard_cost_cap + 1e-12
                else "EXECUTION_COST_CAP_VIOLATION"
            ),
        }
    else:
        raise ValueError(f"unsupported run_mode: {mode}")
    summary["fingerprint"] = fingerprint_json(summary)
    summary_path = output_paths.get("summary", output_paths.get("dry_run_summary"))
    if summary_path is None:
        raise ValueError("outputs.summary or outputs.dry_run_summary is required")
    atomic_write_json(summary_path, summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    print(json.dumps(run(args.config.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
