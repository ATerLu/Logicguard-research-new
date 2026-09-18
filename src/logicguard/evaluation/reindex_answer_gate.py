"""Run the Stage48 answer micro-gate over frozen prompt-exposed reindex cases."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    append_jsonl,
    atomic_write_json,
    load_jsonl,
    require_env,
    write_jsonl,
)
from logicguard.core.run_state import (
    load_checkpoint_rows,
    prepare_run_manifest,
    stable_case_key,
    update_run_manifest,
)
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import ChatResponse, OpenAICompatibleChatClient


class ChatClient(Protocol):
    """Minimal chat interface used by the answer micro-gate."""

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout_seconds: int,
    ) -> ChatResponse: ...


@dataclass(frozen=True, slots=True)
class ReindexAnswerGateConfig:
    """Frozen inputs, outputs and provider settings for one answer micro-gate."""

    dataset: str
    attack_family: str
    prompt_cases_path: Path
    exposure_path: Path
    frozen_attacks_path: Path
    results_output_path: Path
    summary_output_path: Path
    cost_ledger_output_path: Path
    model: str = "qwen3.7-plus"
    api_key_env: str = "DASHSCOPE_API_KEY"
    base_url_env: str = "DASHSCOPE_BASE_URL"
    temperature: float = 0.0
    max_tokens: int = 64
    timeout_seconds: int = 90
    input_price_per_million_tokens_cny: float = 2.0
    output_price_per_million_tokens_cny: float = 8.0
    stage_label: str = "Stage48-E1-answer-micro-gate"

    @classmethod
    def from_yaml(cls, path: Path) -> "ReindexAnswerGateConfig":
        """Load a project-relative YAML configuration."""

        resolved_path = resolve_config_path(path)
        project_root = find_project_root(resolved_path)
        payload = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            attack_family=str(payload["attack_family"]),
            prompt_cases_path=resolve(payload["prompt_cases_path"]),
            exposure_path=resolve(payload["exposure_path"]),
            frozen_attacks_path=resolve(payload["frozen_attacks_path"]),
            results_output_path=resolve(payload["results_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            cost_ledger_output_path=resolve(payload["cost_ledger_output_path"]),
            model=str(payload.get("model", "qwen3.7-plus")),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 90)),
            input_price_per_million_tokens_cny=float(
                payload.get("input_price_per_million_tokens_cny", 2.0)
            ),
            output_price_per_million_tokens_cny=float(
                payload.get("output_price_per_million_tokens_cny", 8.0)
            ),
            stage_label=str(payload.get("stage_label", "Stage48-E1-answer-micro-gate")),
        )


def select_prompt_exposed_cases(
    *,
    config: ReindexAnswerGateConfig,
    prompt_rows: list[dict[str, Any]],
    exposure_rows: list[dict[str, Any]],
    attack_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join frozen artifacts and return only source-and-target-exposed cases."""

    prompts = {str(row["query_id"]): row for row in prompt_rows}
    attacks = {str(row["query_id"]): row for row in attack_rows}
    selected: list[dict[str, Any]] = []
    for exposure in exposure_rows:
        if str(exposure.get("dataset")) != config.dataset:
            continue
        if str(exposure.get("attack_family")) != config.attack_family:
            continue
        if not (
            bool(exposure.get("prompt_source_exposed"))
            and bool(exposure.get("prompt_target_exposed"))
        ):
            continue
        query_id = str(exposure["query_id"])
        if query_id not in prompts or query_id not in attacks:
            raise RuntimeError(f"Missing frozen join row for prompt-exposed {query_id}")
        prompt = prompts[query_id]
        attack = attacks[query_id]
        injected_doc_id = str(attack["injected_doc_id"])
        malicious_answer = str(attack["malicious_answer"])
        prompt_text = str(prompt.get("prompt_text", ""))
        if injected_doc_id not in prompt_text or malicious_answer not in prompt_text:
            raise RuntimeError(
                f"Frozen exposure audit does not match rendered prompt for {query_id}"
            )
        messages = prompt.get("messages")
        if not isinstance(messages, list) or not messages:
            raise RuntimeError(f"Frozen prompt has no messages for {query_id}")
        selected.append(
            {
                "dataset": config.dataset,
                "query_id": query_id,
                "query": str(prompt["query"]),
                "gold_answer": str(prompt["gold_answer"]),
                "attack_family": config.attack_family,
                "attack_id": str(attack["attack_id"]),
                "injected_doc_id": injected_doc_id,
                "malicious_answer": malicious_answer,
                "source_rank": exposure.get("source_rank"),
                "messages": messages,
                "prompt_text": prompt_text,
            }
        )
    return selected


def run_from_config(
    config: ReindexAnswerGateConfig, *, client: ChatClient | None = None
) -> list[dict[str, Any]]:
    """Run or resume the paid answer gate and atomically write final artifacts."""

    prompt_rows = load_jsonl(config.prompt_cases_path)
    exposure_rows = load_jsonl(config.exposure_path)
    attack_rows = load_jsonl(config.frozen_attacks_path)
    cases = select_prompt_exposed_cases(
        config=config,
        prompt_rows=prompt_rows,
        exposure_rows=exposure_rows,
        attack_rows=attack_rows,
    )
    checkpoint_path = config.results_output_path.with_name(
        f"{config.results_output_path.stem}.checkpoint.jsonl"
    )
    manifest_path = config.results_output_path.with_name(
        f"{config.results_output_path.stem}.run_manifest.json"
    )
    manifest = prepare_run_manifest(
        path=manifest_path,
        experiment=config.stage_label,
        config_payload=asdict(config),
        inputs=[
            config.prompt_cases_path,
            config.exposure_path,
            config.frozen_attacks_path,
            Path(__file__),
        ],
        expected_count=len(cases),
        checkpoint_path=checkpoint_path,
        protected_outputs=[
            config.results_output_path,
            config.summary_output_path,
            config.cost_ledger_output_path,
        ],
    )
    fingerprint = str(manifest["fingerprint"])
    completed = {
        str(row["case_key"]): dict(row["result"])
        for row in load_checkpoint_rows(checkpoint_path, fingerprint=fingerprint)
    }
    if client is None:
        client = OpenAICompatibleChatClient(
            base_url=require_env(config.base_url_env),
            api_key=require_env(config.api_key_env),
        )
    for case in cases:
        case_key = _case_key(config, case)
        if case_key in completed:
            continue
        result = _call_case(config=config, case=case, client=client)
        completed[case_key] = result
        append_jsonl(
            checkpoint_path,
            {
                "run_fingerprint": fingerprint,
                "case_key": case_key,
                "dataset": config.dataset,
                "query_id": case["query_id"],
                "attack_family": config.attack_family,
                "defense_stage": "full_query_guard__prompt_exposed",
                "model": config.model,
                "result": result,
            },
        )
        update_run_manifest(
            manifest_path,
            completed_count=len(completed),
            token_usage=_token_usage(list(completed.values())),
        )

    results = [completed[_case_key(config, case)] for case in cases]
    write_jsonl(config.results_output_path, results)
    summary = _build_summary(
        config=config,
        exposure_rows=exposure_rows,
        attack_rows=attack_rows,
        results=results,
    )
    atomic_write_json(config.summary_output_path, summary)
    atomic_write_json(config.cost_ledger_output_path, _cost_ledger(config, results))
    update_run_manifest(
        manifest_path,
        status="complete",
        completed_count=len(results),
        token_usage=_token_usage(results),
    )
    return results


def reclassify_existing_results(
    config: ReindexAnswerGateConfig,
) -> list[dict[str, Any]]:
    """Recompute transparent answer labels without making provider calls."""

    results = load_jsonl(config.results_output_path)
    for result in results:
        if result.get("error") is not None:
            continue
        classification = classify_answer(
            str(result.get("generated_answer", "")),
            gold_answer=str(result.get("gold_answer", "")),
            poisoned_answer=str(result.get("malicious_answer", "")),
        )
        result.update(classification.to_json_dict())
        result["is_incorrect"] = not (
            classification.is_correct or classification.is_abstained
        )
        result["targeted_attack_success"] = (
            classification.is_poisoned
            and not classification.is_correct
            and not classification.is_abstained
        )
        result["classification_rule"] = "transparent_string_v2_with_numeric_gold_prefix"

    exposure_rows = load_jsonl(config.exposure_path)
    attack_rows = load_jsonl(config.frozen_attacks_path)
    write_jsonl(config.results_output_path, results)
    atomic_write_json(
        config.summary_output_path,
        _build_summary(
            config=config,
            exposure_rows=exposure_rows,
            attack_rows=attack_rows,
            results=results,
        ),
    )
    atomic_write_json(config.cost_ledger_output_path, _cost_ledger(config, results))
    manifest_path = config.results_output_path.with_name(
        f"{config.results_output_path.stem}.run_manifest.json"
    )
    if manifest_path.exists():
        update_run_manifest(
            manifest_path,
            posthoc_reclassification={
                "provider_calls_added": 0,
                "rule": "transparent_string_v2_with_numeric_gold_prefix",
                "note": (
                    "Recomputed labels from frozen provider responses; token usage "
                    "and generated text are unchanged."
                ),
            },
        )
    return results


def _call_case(
    *, config: ReindexAnswerGateConfig, case: dict[str, Any], client: ChatClient
) -> dict[str, Any]:
    start = perf_counter()
    try:
        response = client.chat(
            model=config.model,
            messages=case["messages"],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
        )
        classification = classify_answer(
            response.content,
            gold_answer=str(case["gold_answer"]),
            poisoned_answer=str(case["malicious_answer"]),
        )
        result = {
            **{key: value for key, value in case.items() if key != "messages"},
            "model": config.model,
            "generated_answer": response.content,
            **classification.to_json_dict(),
            "is_incorrect": not (
                classification.is_correct or classification.is_abstained
            ),
            "targeted_attack_success": (
                classification.is_poisoned
                and not classification.is_correct
                and not classification.is_abstained
            ),
            "latency_seconds": round(perf_counter() - start, 4),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - provider failures are experiment data.
        result = {
            **{key: value for key, value in case.items() if key != "messages"},
            "model": config.model,
            "generated_answer": "",
            "is_correct": False,
            "is_poisoned": False,
            "is_abstained": False,
            "is_incorrect": False,
            "targeted_attack_success": False,
            "latency_seconds": round(perf_counter() - start, 4),
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "error": str(exc),
        }
    return result


def _case_key(config: ReindexAnswerGateConfig, case: dict[str, Any]) -> str:
    return stable_case_key(
        dataset=config.dataset,
        query_id=str(case["query_id"]),
        attack_family=config.attack_family,
        defense_stage="full_query_guard__prompt_exposed",
        model=config.model,
    )


def _token_usage(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in results),
        "completion_tokens": sum(
            int(row.get("completion_tokens") or 0) for row in results
        ),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in results),
    }


def _build_summary(
    *,
    config: ReindexAnswerGateConfig,
    exposure_rows: list[dict[str, Any]],
    attack_rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    selection_policies = sorted(
        {str(row.get("selection_policy", "unspecified")) for row in attack_rows}
    )
    scope_note = (
        "Existence micro-gate over Stage47 targeted-success cases only; rates "
        "are conditional diagnostics, not population estimates."
        if selection_policies == ["strict_targeted_success"]
        else (
            "Evaluation-valid cases selected without conditioning on full-corpus "
            "retrieval, prompt exposure or answer success; rates remain small-sample "
            "conditional diagnostics, not population estimates."
        )
    )
    return {
        "schema_version": 1,
        "experiment": config.stage_label,
        "dataset": config.dataset,
        "attack_family": config.attack_family,
        "model": config.model,
        "selection_policies": selection_policies,
        "funnel": {
            "attempted": len(exposure_rows),
            "index_included": sum(
                bool(row.get("index_document_included"))
                and bool(row.get("index_text_unit_included"))
                for row in exposure_rows
            ),
            "retrieved": sum(bool(row.get("retrieved")) for row in exposure_rows),
            "prompt_exposed": len(results),
            "answer_generated": sum(row.get("error") is None for row in results),
            "broad_incorrect": sum(bool(row["is_incorrect"]) for row in results),
            "targeted_attack_success": sum(
                bool(row["targeted_attack_success"]) for row in results
            ),
        },
        "conditional_rates": {
            "broad_incorrect_given_prompt_exposed": _ratio(
                sum(bool(row["is_incorrect"]) for row in results), len(results)
            ),
            "targeted_asr_given_prompt_exposed": _ratio(
                sum(bool(row["targeted_attack_success"]) for row in results),
                len(results),
            ),
        },
        "token_usage": _token_usage(results),
        "scope_note": scope_note,
    }


def _cost_ledger(
    config: ReindexAnswerGateConfig, results: list[dict[str, Any]]
) -> dict[str, Any]:
    usage = _token_usage(results)
    input_cost = (
        usage["prompt_tokens"] * config.input_price_per_million_tokens_cny / 1_000_000
    )
    output_cost = (
        usage["completion_tokens"]
        * config.output_price_per_million_tokens_cny
        / 1_000_000
    )
    return {
        "schema_version": 1,
        "currency": "CNY",
        "model": config.model,
        "successful_calls": sum(row.get("error") is None for row in results),
        "token_usage": usage,
        "pricing_snapshot": {
            "input_per_million_tokens": config.input_price_per_million_tokens_cny,
            "output_per_million_tokens": config.output_price_per_million_tokens_cny,
            "basis": "Stage48 2026-08-12 China-Beijing frozen catalog snapshot",
        },
        "catalog_cost_estimate_cny": round(input_cost + output_cost, 6),
        "actual_billing_note": (
            "Actual account charge may be lower because promotions or free quota "
            "are not observable locally."
        ),
    }


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--reclassify-existing",
        action="store_true",
        help="Recompute labels from saved responses without making API calls.",
    )
    args = parser.parse_args()
    config = ReindexAnswerGateConfig.from_yaml(args.config)
    results = (
        reclassify_existing_results(config)
        if args.reclassify_existing
        else run_from_config(config)
    )
    print(f"stage48_answer_gate_cases={len(results)}")


if __name__ == "__main__":
    main()
