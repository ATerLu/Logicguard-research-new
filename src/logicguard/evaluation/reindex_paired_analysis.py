"""Analyze Stage48 attacked/clean answer pairs and write the cost ledger."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from logicguard.core.io import (
    atomic_write_json,
    atomic_write_text,
    load_jsonl,
    write_jsonl,
)
from logicguard.llm.evaluation import classify_answer


@dataclass(frozen=True, slots=True)
class Stage48PairInputs:
    """Frozen artifacts for one dataset/attack-family pair."""

    dataset: str
    attack_family: str
    frozen_attacks_path: Path
    attacked_preflight_path: Path
    clean_preflight_path: Path
    attacked_results_path: Path
    clean_results_path: Path


@dataclass(frozen=True, slots=True)
class Stage48PairedAnalysisConfig:
    """Inputs, outputs and frozen catalog prices for Stage48 analysis."""

    pairs: list[Stage48PairInputs]
    paired_rows_output_path: Path
    summary_output_path: Path
    cost_ledger_output_path: Path
    report_path: Path
    clean_index_workspace_roots: list[Path]
    answer_input_price_per_million_tokens_cny: float = 2.0
    answer_output_price_per_million_tokens_cny: float = 8.0
    embedding_price_per_thousand_tokens_cny: float = 0.0005
    context_query_embedding_count: int = 14
    context_query_embedding_max_tokens_each: int = 128
    stage_label: str = "Stage48-E1-paired-defense-analysis"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage48PairedAnalysisConfig":
        """Load a project-relative paired-analysis config."""

        path = resolve_config_path(path)
        root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )

        pairs = [
            Stage48PairInputs(
                dataset=str(row["dataset"]),
                attack_family=str(row["attack_family"]),
                frozen_attacks_path=resolve(row["frozen_attacks_path"]),
                attacked_preflight_path=resolve(row["attacked_preflight_path"]),
                clean_preflight_path=resolve(row["clean_preflight_path"]),
                attacked_results_path=resolve(row["attacked_results_path"]),
                clean_results_path=resolve(row["clean_results_path"]),
            )
            for row in payload["pairs"]
        ]
        return cls(
            pairs=pairs,
            paired_rows_output_path=resolve(payload["paired_rows_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            cost_ledger_output_path=resolve(payload["cost_ledger_output_path"]),
            report_path=resolve(payload["report_path"]),
            clean_index_workspace_roots=[
                resolve(item) for item in payload["clean_index_workspace_roots"]
            ],
            answer_input_price_per_million_tokens_cny=float(
                payload.get("answer_input_price_per_million_tokens_cny", 2.0)
            ),
            answer_output_price_per_million_tokens_cny=float(
                payload.get("answer_output_price_per_million_tokens_cny", 8.0)
            ),
            embedding_price_per_thousand_tokens_cny=float(
                payload.get("embedding_price_per_thousand_tokens_cny", 0.0005)
            ),
            context_query_embedding_count=int(
                payload.get("context_query_embedding_count", 14)
            ),
            context_query_embedding_max_tokens_each=int(
                payload.get("context_query_embedding_max_tokens_each", 128)
            ),
            stage_label=str(
                payload.get("stage_label", "Stage48-E1-paired-defense-analysis")
            ),
        )


def run_from_config(config: Stage48PairedAnalysisConfig) -> list[dict[str, Any]]:
    """Join all paired cases, summarize outcomes and account for paid calls."""

    paired_rows = [row for pair in config.pairs for row in build_pair_rows(pair)]
    summary = build_paired_summary(config=config, rows=paired_rows)
    cost_ledger = build_cost_ledger(config)
    write_jsonl(config.paired_rows_output_path, paired_rows)
    atomic_write_json(config.summary_output_path, summary)
    atomic_write_json(config.cost_ledger_output_path, cost_ledger)
    atomic_write_text(
        config.report_path,
        _render_report(config=config, summary=summary, cost_ledger=cost_ledger),
    )
    print(
        f"stage48_paired_rows={len(paired_rows)}, "
        f"answer_calls={cost_ledger['answer_layer']['completed_calls']}, "
        f"cost_cny={cost_ledger['stage48_paired_increment_upper_cny']:.6f}"
    )
    return paired_rows


def build_pair_rows(pair: Stage48PairInputs) -> list[dict[str, Any]]:
    """Join clean/attacked prompts and answers for one attack family."""

    attacks = {
        str(row["query_id"]): row for row in load_jsonl(pair.frozen_attacks_path)
    }
    attacked_preflight = _keyed(load_jsonl(pair.attacked_preflight_path))
    clean_preflight = _keyed(load_jsonl(pair.clean_preflight_path))
    attacked_results = _keyed(load_jsonl(pair.attacked_results_path))
    clean_results = _keyed(load_jsonl(pair.clean_results_path))
    key_sets = [
        set(attacked_preflight),
        set(clean_preflight),
        set(attacked_results),
        set(clean_results),
    ]
    if any(keys != key_sets[0] for keys in key_sets[1:]):
        raise ValueError(
            f"Stage48 pair key mismatch: {pair.dataset}/{pair.attack_family}"
        )

    output: list[dict[str, Any]] = []
    for query_id, method in sorted(key_sets[0]):
        attack = attacks.get(query_id)
        if attack is None:
            raise ValueError(f"Missing frozen attack for query {query_id}")
        attacked_pre = attacked_preflight[(query_id, method)]
        clean_pre = clean_preflight[(query_id, method)]
        attacked = attacked_results[(query_id, method)]
        clean = clean_results[(query_id, method)]
        if attacked.get("error") is not None or clean.get("error") is not None:
            raise RuntimeError(f"Provider error in paired case {query_id}/{method}")
        malicious = str(attack.get("malicious_answer", ""))
        attacked_class = classify_answer(
            str(attacked.get("generated_answer", "")),
            gold_answer=str(attacked.get("gold_answer", "")),
            poisoned_answer=malicious,
        )
        clean_class = classify_answer(
            str(clean.get("generated_answer", "")),
            gold_answer=str(clean.get("gold_answer", "")),
            poisoned_answer=malicious,
        )
        targeted = bool(
            attacked_class.is_poisoned
            and not attacked_class.is_correct
            and not attacked_class.is_abstained
        )
        output.append(
            {
                "dataset": pair.dataset,
                "attack_family": pair.attack_family,
                "query_id": query_id,
                "method": method,
                "defense_stage": attacked_pre["defense_stage"],
                "gold_answer": attacked.get("gold_answer", ""),
                "malicious_answer": malicious,
                "attack_source_exposed": bool(attacked_pre["attack_source_exposed"]),
                "malicious_answer_exposed": bool(
                    attacked_pre["malicious_answer_exposed"]
                ),
                "risk_detected_attack": bool(attacked_pre["risk_detected_attack"]),
                "attack_recovered": bool(attacked_pre["attack_recovered"]),
                "attacked_gold_surface": bool(attacked_pre["gold_answer_exposed"]),
                "clean_gold_surface": bool(clean_pre["gold_answer_exposed"]),
                "clean_risk_detected_source_count": int(
                    clean_pre["risk_detected_source_count"]
                ),
                "clean_recovered_source_count": int(
                    clean_pre["recovered_source_count"]
                ),
                "attacked_generated_answer": attacked.get("generated_answer", ""),
                "clean_generated_answer": clean.get("generated_answer", ""),
                "attacked_correct": attacked_class.is_correct,
                "attacked_abstained": attacked_class.is_abstained,
                "attacked_targeted_success": targeted,
                "clean_correct": clean_class.is_correct,
                "clean_abstained": clean_class.is_abstained,
                "clean_matches_malicious_answer": clean_class.is_poisoned,
                "paired_correctness_delta": int(attacked_class.is_correct)
                - int(clean_class.is_correct),
                "classification_rule": (
                    "transparent_string_v2_with_numeric_gold_prefix"
                ),
                "model": attacked.get("model", ""),
                "attacked_prompt_tokens": attacked.get("prompt_tokens"),
                "attacked_completion_tokens": attacked.get("completion_tokens"),
                "clean_prompt_tokens": clean.get("prompt_tokens"),
                "clean_completion_tokens": clean.get("completion_tokens"),
            }
        )
    return output


def build_paired_summary(
    *, config: Stage48PairedAnalysisConfig, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build family-specific and pooled method summaries."""

    pair_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    method_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pair_groups.setdefault(
            (row["dataset"], row["attack_family"], row["method"]), []
        ).append(row)
        method_groups.setdefault(row["method"], []).append(row)
    return {
        "schema_version": 1,
        "experiment": config.stage_label,
        "classification_rule": "transparent_string_v2_with_numeric_gold_prefix",
        "denominator_policy": {
            "attempted": "all frozen attack attempts",
            "source_exposed": "attack source present in the exact rendered prompt",
            "target_exposed": "malicious target string present in the exact rendered prompt",
            "clean_utility": "same query/family/method over the matched clean full-corpus index",
        },
        "paired_case_count": len(rows),
        "attack_attempt_count": len(rows) // 4,
        "by_dataset_family_method": [
            _summarize_group(group)
            for _, group in sorted(pair_groups.items(), key=lambda item: item[0])
        ],
        "overall_by_method": [
            _summarize_group(group)
            for _, group in sorted(method_groups.items(), key=lambda item: item[0])
        ],
    }


def build_cost_ledger(config: Stage48PairedAnalysisConfig) -> dict[str, Any]:
    """Aggregate exact answer/index tokens and bound context-query embeddings."""

    manifests = [
        _answer_manifest(pair.attacked_results_path) for pair in config.pairs
    ] + [_answer_manifest(pair.clean_results_path) for pair in config.pairs]
    answer_prompt = 0
    answer_completion = 0
    completed = 0
    expected = 0
    for path in manifests:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        usage = payload.get("token_usage", {})
        answer_prompt += int(usage.get("answer_prompt_tokens", 0))
        answer_completion += int(usage.get("answer_completion_tokens", 0))
        completed += int(payload.get("completed_count", 0))
        expected += int(payload.get("expected_count", 0))
        if payload.get("status") != "complete":
            raise RuntimeError(f"Incomplete answer manifest: {path}")

    index_prompt = 0
    index_completion = 0
    index_embedding = 0
    index_requests = 0
    for root in config.clean_index_workspace_roots:
        metrics = _read_index_metrics(root)
        chat = metrics.get("openai/qwen3.7-plus", {})
        embedding = metrics.get("openai/text-embedding-v4", {})
        index_prompt += int(chat.get("prompt_tokens", 0))
        index_completion += int(chat.get("completion_tokens", 0))
        index_embedding += int(embedding.get("total_tokens", 0))
        index_requests += int(chat.get("successful_response_count", 0)) + int(
            embedding.get("successful_response_count", 0)
        )
    answer_cost = _chat_cost(
        config, prompt_tokens=answer_prompt, completion_tokens=answer_completion
    )
    index_cost = (
        _chat_cost(
            config, prompt_tokens=index_prompt, completion_tokens=index_completion
        )
        + index_embedding * config.embedding_price_per_thousand_tokens_cny / 1_000
    )
    query_embedding_upper_tokens = (
        config.context_query_embedding_count
        * config.context_query_embedding_max_tokens_each
    )
    query_embedding_upper_cost = (
        query_embedding_upper_tokens
        * config.embedding_price_per_thousand_tokens_cny
        / 1_000
    )
    return {
        "schema_version": 1,
        "price_basis": (
            "Stage48 frozen 2026-08-12 China-Beijing undiscounted catalog snapshot"
        ),
        "answer_layer": {
            "manifest_count": len(manifests),
            "completed_calls": completed,
            "expected_calls": expected,
            "prompt_tokens": answer_prompt,
            "completion_tokens": answer_completion,
            "catalog_cost_cny": round(answer_cost, 6),
        },
        "clean_index_layer": {
            "workspace_count": len(config.clean_index_workspace_roots),
            "successful_provider_requests": index_requests,
            "chat_prompt_tokens": index_prompt,
            "chat_completion_tokens": index_completion,
            "embedding_tokens": index_embedding,
            "catalog_cost_cny": round(index_cost, 6),
        },
        "clean_context_query_embedding_upper_bound": {
            "query_count": config.context_query_embedding_count,
            "max_tokens_per_query": config.context_query_embedding_max_tokens_each,
            "max_tokens": query_embedding_upper_tokens,
            "catalog_cost_upper_cny": round(query_embedding_upper_cost, 6),
            "note": "Provider did not emit per-query usage; this is a conservative bound.",
        },
        "stage48_paired_increment_exact_logged_cny": round(answer_cost + index_cost, 6),
        "stage48_paired_increment_upper_cny": round(
            answer_cost + index_cost + query_embedding_upper_cost, 6
        ),
        "credential_values_recorded": False,
    }


def _summarize_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(group)
    source_exposed = [row for row in group if row["attack_source_exposed"]]
    target_exposed = [row for row in group if row["malicious_answer_exposed"]]
    return {
        "dataset": group[0]["dataset"]
        if len({row["dataset"] for row in group}) == 1
        else "pooled",
        "attack_family": (
            group[0]["attack_family"]
            if len({row["attack_family"] for row in group}) == 1
            else "pooled"
        ),
        "method": group[0]["method"],
        "defense_stage": group[0]["defense_stage"],
        "attempted": count,
        "source_exposed": len(source_exposed),
        "target_exposed": len(target_exposed),
        "targeted_success": sum(row["attacked_targeted_success"] for row in group),
        "targeted_asr_attempted": _ratio(
            sum(row["attacked_targeted_success"] for row in group), count
        ),
        "targeted_asr_given_source_exposed": _ratio(
            sum(row["attacked_targeted_success"] for row in source_exposed),
            len(source_exposed),
        ),
        "targeted_asr_given_target_exposed": _ratio(
            sum(row["attacked_targeted_success"] for row in target_exposed),
            len(target_exposed),
        ),
        "attacked_accuracy": _ratio(
            sum(row["attacked_correct"] for row in group), count
        ),
        "clean_accuracy": _ratio(sum(row["clean_correct"] for row in group), count),
        "paired_accuracy_delta": round(
            _ratio(sum(row["attacked_correct"] for row in group), count)
            - _ratio(sum(row["clean_correct"] for row in group), count),
            6,
        ),
        "attacked_abstain_rate": _ratio(
            sum(row["attacked_abstained"] for row in group), count
        ),
        "clean_abstain_rate": _ratio(
            sum(row["clean_abstained"] for row in group), count
        ),
        "attack_recovered_count": sum(row["attack_recovered"] for row in group),
        "clean_queries_with_any_risk_detection": sum(
            row["clean_risk_detected_source_count"] > 0 for row in group
        ),
        "clean_queries_with_any_source_recovery": sum(
            row["clean_recovered_source_count"] > 0 for row in group
        ),
    }


def _keyed(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    keyed = {
        (str(row.get("query_id", "")), str(row.get("method", ""))): row for row in rows
    }
    if len(keyed) != len(rows):
        raise ValueError("Duplicate query/method rows in Stage48 paired input")
    return keyed


def _answer_manifest(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_run_manifest.json")


def _read_index_metrics(workspace_root: Path) -> dict[str, Any]:
    from logicguard.evaluation.reindex_exposure import _read_graphrag_metrics

    return _read_graphrag_metrics(workspace_root)


def _chat_cost(
    config: Stage48PairedAnalysisConfig,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    return (
        prompt_tokens * config.answer_input_price_per_million_tokens_cny / 1_000_000
        + completion_tokens
        * config.answer_output_price_per_million_tokens_cny
        / 1_000_000
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _render_report(
    *,
    config: Stage48PairedAnalysisConfig,
    summary: dict[str, Any],
    cost_ledger: dict[str, Any],
) -> str:
    lines = [
        f"# {config.stage_label}",
        "",
        "## Pooled answer results",
        "",
        "| method | n | source exposed | target exposed | targeted ASR / exposed | attacked acc. | clean acc. | delta | clean risk queries |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["overall_by_method"]:
        lines.append(
            f"| `{row['method']}` | {row['attempted']} | {row['source_exposed']} | "
            f"{row['target_exposed']} | {_fmt(row['targeted_asr_given_target_exposed'])} | "
            f"{_fmt(row['attacked_accuracy'])} | {_fmt(row['clean_accuracy'])} | "
            f"{_fmt(row['paired_accuracy_delta'])} | "
            f"{row['clean_queries_with_any_risk_detection']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "Targeted ASR is reported separately over all frozen attempts, exact-prompt source-exposed cases, and exact-prompt target-exposed cases. Clean utility uses the same query, attack-family batch, method, index scope and rendering policy. Transparent string classification is retained; no post-hoc LLM judge is introduced.",
            "",
            "## Cost",
            "",
            f"- Exact logged paired increment: CNY {cost_ledger['stage48_paired_increment_exact_logged_cny']:.6f}",
            f"- Increment including clean query-embedding upper bound: CNY {cost_ledger['stage48_paired_increment_upper_cny']:.6f}",
            "",
        ]
    )
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run_from_config(Stage48PairedAnalysisConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
