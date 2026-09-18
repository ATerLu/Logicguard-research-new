"""Checkpointed global -> query -> logic -> corpus LogicPoison development port.

Fixture mode is entirely offline. Execute mode uses the existing provider client
without retries. A pending request or uncertain usage blocks subsequent dispatch.
No historical runner, corpus, label file, or readiness snapshot is overwritten.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from contextlib import contextmanager
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import yaml

from logicguard.benchmark.attack_runner import ChatClient, _chat
from logicguard.benchmark.execution_protocols import (
    build_logicpoison_query_request,
    parse_logicpoison_query_response,
)
from logicguard.benchmark.logicpoison_corpus import (
    corpus_statistics,
    replacement_plan,
    rewrite_corpus,
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


class FixtureNER:
    """Explicit synthetic NER fixture, never presented as a trained model result."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = {row["text"]: row["entities"] for row in records}

    def pipe(self, texts: Iterator[str], **_: Any) -> Iterator[Any]:
        for text in texts:
            entities = self.records[text]
            yield SimpleNamespace(
                ents=[
                    SimpleNamespace(text=e["entity"], label_=e["type"])
                    for e in entities
                ]
            )


class FixtureClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {row["question"]: row["entities"] for row in rows}

    def chat(self, **kwargs: Any) -> ChatResponse:
        question = kwargs["messages"][1]["content"].split("\nQuestion: ", 1)[1]
        return ChatResponse(json.dumps(self.rows[question]), "{}", 100, 50, 150)


@contextmanager
def exclusive_run(path: Path) -> Iterator[None]:
    """A stale lock after hard termination needs inspection, never automatic stealing."""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield
    finally:
        path.unlink()


def _positive(value: Any, name: str, *, allow_zero: bool = False) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be positive")
    return value


def _integer(value: Any, name: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    _positive(value, name, allow_zero=allow_zero)
    return value


def _ner_backend(config: dict[str, Any]) -> str:
    backend = config.get(
        "ner_backend",
        "fixture" if config["run_mode"] == "fixture" else "en_core_web_trf",
    )
    if backend not in {"fixture", "en_core_web_trf"}:
        raise ValueError("NER must use fixture or the pinned en_core_web_trf model")
    if config["run_mode"] == "execute" and backend == "fixture":
        raise ValueError("execute mode cannot use synthetic NER")
    return backend


def _runtime_identity(config: dict[str, Any]) -> dict[str, Any]:
    backend = _ner_backend(config)
    result = {"python": sys.version, "ner_backend": backend}
    if backend != "fixture":
        spec = find_spec(backend)
        if spec is None or spec.origin is None:
            raise ValueError("pinned NER model is not installed")
        if version("en-core-web-trf") != "3.8.0":
            raise ValueError("pinned NER model must be en_core_web_trf 3.8.0")
        directory = Path(spec.origin).parent
        model_hashes = {
            p.relative_to(directory).as_posix(): sha256_file(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }
        result.update(
            model_package_version=version("en-core-web-trf"),
            spacy_version=version("spacy"),
            torch_version=version("torch"),
            model_files_sha256=fingerprint_json(model_hashes),
            model_file_hashes=model_hashes,
        )
    return result


def _inputs(root: Path, config: dict[str, Any]) -> tuple[Path, list, list, dict]:
    mode = config["run_mode"]
    if mode not in {"fixture", "execute"}:
        raise ValueError("run_mode must be fixture or execute")
    if config["split"] != "development":
        raise ValueError("this runner is development-only; confirmation remains locked")
    _integer(config["expected_queries"], "expected_queries")
    _integer(config["timeout_seconds"], "timeout_seconds")
    backend = _ner_backend(config)
    paths = {name: (root / config[name]).resolve() for name in ("corpus", "queries")}
    if mode == "fixture":
        paths["query_fixture"] = (root / config["query_fixture"]).resolve()
    if backend == "fixture":
        paths["ner_fixture"] = (root / config["ner_fixture"]).resolve()
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if output == namespace or not output.is_relative_to(namespace):
        raise ValueError("output must be a dedicated child of the v1.2 WP2 namespace")
    if any(
        not path.is_relative_to(root) or path.is_relative_to(output)
        for path in paths.values()
    ):
        raise ValueError("inputs must remain in project and outside output namespace")
    corpus = load_jsonl(paths["corpus"])
    if not corpus:
        raise ValueError("empty corpus")
    for row in corpus:
        if not {"_id", "text"} <= set(row) or set(row) - {"_id", "text", "title"}:
            raise ValueError(
                "corpus requires only _id/text/optional title; no evaluator fields"
            )
        if any(not isinstance(value, str) for value in row.values()) or not row["_id"]:
            raise ValueError("corpus fields must be strings and document IDs nonempty")
    if len({row["_id"] for row in corpus}) != len(corpus):
        raise ValueError("duplicate corpus document ID")
    raw_queries = load_jsonl(paths["queries"])
    allowed = {
        "dataset",
        "query_id",
        "question",
        "stratum",
        "split",
        "purpose",
        "order_key",
    }
    if any(set(row) - allowed for row in raw_queries):
        raise ValueError(
            "query manifest contains fields outside attacker-safe allowlist"
        )
    queries = [row for row in raw_queries if row.get("dataset") == config["dataset"]]
    if len(queries) != config["expected_queries"] or not queries:
        raise ValueError("query count differs from frozen expected_queries")
    for row in queries:
        if row.get("split") != "development" or any(
            not isinstance(row.get(k), str) or not row[k].strip()
            for k in ("query_id", "question")
        ):
            raise ValueError(
                "query must have nonempty ID/question and development split"
            )
    if len({row["query_id"] for row in queries}) != len(queries):
        raise ValueError("duplicate query ID")
    ratio = _positive(config["top_ratio"], "top_ratio")
    if ratio > 1:
        raise ValueError("top_ratio exceeds 1")
    for name, value in config["poison_budget"].items():
        _positive(value, name, allow_zero=True)
    required = {
        "max_changed_documents",
        "max_changed_document_fraction",
        "max_replacement_occurrences",
        "max_poisoned_text_utf8_bytes",
    }
    if set(config["poison_budget"]) != required:
        raise ValueError("poison_budget must declare all four measured limits")
    for name in required - {"max_changed_document_fraction"}:
        _integer(config["poison_budget"][name], name, allow_zero=True)
    if config["poison_budget"]["max_changed_document_fraction"] > 1:
        raise ValueError("max_changed_document_fraction exceeds 1")
    pricing = config["pricing"]
    for name in (
        "input_per_million_tokens_cny",
        "output_per_million_tokens_cny",
        "hard_cost_cap_cny",
        "max_input_tokens",
        "max_calls",
    ):
        _positive(
            pricing[name], name, allow_zero=name in {"hard_cost_cap_cny", "max_calls"}
        )
    _integer(pricing["max_calls"], "max_calls", allow_zero=True)
    _integer(pricing["max_input_tokens"], "max_input_tokens")
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    hashes["pipeline_source"] = sha256_file(Path(__file__))
    hashes["corpus_source"] = sha256_file(
        Path(__file__).with_name("logicpoison_corpus.py")
    )
    hashes["request_source"] = sha256_file(
        Path(__file__).with_name("execution_protocols.py")
    )
    hashes["dispatch_source"] = sha256_file(
        Path(__file__).with_name("attack_runner.py")
    )
    hashes["provider_source"] = sha256_file(
        Path(__file__).parents[1] / "llm/provider.py"
    )
    return output, corpus, queries, hashes


def _summary(output: Path, state: dict, config: dict) -> dict:
    attempts = list(state["requests"].values())
    fixture = config["run_mode"] == "fixture"
    costs = [row.get("actual_cost_cny") for row in attempts]
    known = sum(cost for cost in costs if cost is not None)
    result = {
        "benchmark_version": "comparison-v1.2",
        "attack_id": "A2_logicpoison",
        "dataset": config["dataset"],
        "run_mode": config["run_mode"],
        "status": state["status"],
        "completed_stages": state["completed_stages"],
        "planned_queries": config["expected_queries"],
        "recorded_requests": len(attempts),
        "provider_calls_made": 0 if fixture else len(attempts),
        "fixture_calls_made": len(attempts) if fixture else 0,
        "known_catalog_cost_cny": 0 if fixture else known,
        "unknown_usage_requests": sum(cost is None for cost in costs),
        "reserved_or_charged_cny": sum(
            max(row["reserved_cny"], row.get("actual_cost_cny") or 0)
            if row["status"] != "complete"
            else row["actual_cost_cny"]
            for row in attempts
        ),
        "fixture_simulated_catalog_cost_cny": known if fixture else None,
        "materialized_corpus": "corpus.jsonl"
        if state["status"] == "CORPUS_MATERIALIZED"
        else None,
        "corpus_materialization_valid": state["status"] == "CORPUS_MATERIALIZED",
        "generation_valid": not fixture and state["status"] == "CORPUS_MATERIALIZED",
        "ner_backend": _ner_backend(config),
        "evaluation_valid": None,
        "attack_effect_measured": False,
        "paper_faithful_certified": False,
        "identity": state["identity"],
        "output_sha256": state["outputs"],
        "poison_metrics": state.get("poison_metrics"),
        "error_type": state.get("error_type"),
        "cost_limit_scope": "request admission under configured token/price bounds; provider deviations stop execution",
    }
    atomic_write_json(output / "summary.json", result)
    return result


def run(
    config_path: Path, *, nlp: Any = None, client: ChatClient | None = None
) -> dict:
    root = find_project_root(config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output, corpus, queries, hashes = _inputs(root, config)
    runtime = _runtime_identity(config)
    identity = fingerprint_json(
        {"config": config, "inputs_and_code": hashes, "runtime": runtime}
    )
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_run(output / "run.lock"):
        state_path = output / "checkpoint.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state["identity"] != identity:
                raise ValueError("resume identity mismatch: config/input/code changed")
            for name, digest in state["outputs"].items():
                if sha256_file(output / name) != digest:
                    raise ValueError("resume artifact hash mismatch")
            if state["status"] != "RUNNING":
                return _summary(output, state, config)
        else:
            if any(path.name != "run.lock" for path in output.iterdir()):
                raise FileExistsError("refusing nonempty namespace without checkpoint")
            state = {
                "identity": identity,
                "status": "RUNNING",
                "completed_stages": [],
                "requests": {},
                "outputs": {},
            }
            atomic_write_json(state_path, state)
            atomic_write_json(
                output / "manifest.json",
                {
                    "config": config,
                    "input_and_code_sha256": hashes,
                    "identity": identity,
                    "runtime": runtime,
                    "ner": _ner_backend(config),
                    "adaptation": "bounded JSON query stage; deterministic query order; ambiguous-type rejection; no labels copied",
                },
            )
            state["outputs"]["manifest.json"] = sha256_file(output / "manifest.json")
            atomic_write_json(state_path, state)
        if any(
            row["status"]
            in {"in_flight", "usage_unknown", "provider_error", "cost_violation"}
            for row in state["requests"].values()
        ):
            state["status"] = "STOPPED_UNCERTAIN_REQUEST"
            atomic_write_json(state_path, state)
            return _summary(output, state, config)

        def save_artifact(name: str, value: Any, *, lines: bool = False) -> None:
            (write_jsonl if lines else atomic_write_json)(output / name, value)
            state["outputs"][name] = sha256_file(output / name)

        def stop(status: str, error: str | None = None) -> dict:
            state["status"] = status
            state["error_type"] = error
            atomic_write_json(state_path, state)
            return _summary(output, state, config)

        if "global" not in state["completed_stages"]:
            if nlp is None:
                if _ner_backend(config) == "fixture":
                    nlp = FixtureNER(load_jsonl(root / config["ner_fixture"]))
                else:
                    import spacy

                    nlp = spacy.load("en_core_web_trf")
            stats = corpus_statistics(corpus, nlp)
            save_artifact("global_stats.json", stats)
            state["completed_stages"].append("global")
            atomic_write_json(state_path, state)
        else:
            stats = json.loads(
                (output / "global_stats.json").read_text(encoding="utf-8")
            )
        pricing = config["pricing"]
        for query in queries:
            key = query["query_id"]
            if key in state["requests"]:
                continue
            request = build_logicpoison_query_request(
                query_id=key, question=query["question"]
            )
            # UTF-8 bytes plus framing allowance is an admission estimate, not a
            # certified provider tokenizer. Observe actual usage and fail closed.
            input_estimate = (
                len((request.system_prompt + request.user_prompt).encode("utf-8"))
                + 1024
            )
            if input_estimate > pricing["max_input_tokens"]:
                return stop("STOPPED_INPUT_BUDGET")
            reserved = (
                pricing["max_input_tokens"] * pricing["input_per_million_tokens_cny"]
                + request.max_output_tokens * pricing["output_per_million_tokens_cny"]
            ) / 1_000_000
            committed = sum(
                row.get("actual_cost_cny", row["reserved_cny"])
                for row in state["requests"].values()
            )
            if (
                len(state["requests"]) >= pricing["max_calls"]
                or committed + reserved > pricing["hard_cost_cap_cny"] + 1e-12
            ):
                return stop("STOPPED_REQUEST_BUDGET")
            if client is None:
                if config["run_mode"] == "fixture":
                    client = FixtureClient(load_jsonl(root / config["query_fixture"]))
                else:
                    client = OpenAICompatibleChatClient(
                        base_url=str(config["base_url"]),
                        api_key=require_env(str(config["api_key_env"])),
                    )
            attempt = {
                "query_id": key,
                "status": "in_flight",
                "reserved_cny": reserved,
                "prompt_sha256": fingerprint_json(
                    {"system": request.system_prompt, "user": request.user_prompt}
                ),
            }
            state["requests"][key] = attempt
            atomic_write_json(state_path, state)  # durable reservation BEFORE call
            try:
                response = _chat(
                    client,
                    request,
                    model=config["model"],
                    timeout_seconds=config["timeout_seconds"],
                )
            except Exception as exc:
                attempt["status"] = "provider_error"
                return stop("STOPPED_UNCERTAIN_REQUEST", type(exc).__name__)
            prompt, completion = response.prompt_tokens, response.completion_tokens
            if any(
                type(value) is not int or value < 0 for value in (prompt, completion)
            ):
                attempt["status"] = "usage_unknown"
                return stop("STOPPED_UNCERTAIN_REQUEST", "MissingOrInvalidUsage")
            actual = (
                prompt * pricing["input_per_million_tokens_cny"]
                + completion * pricing["output_per_million_tokens_cny"]
            ) / 1_000_000
            attempt.update(
                actual_cost_cny=actual,
                prompt_tokens=prompt,
                completion_tokens=completion,
            )
            if (
                prompt > pricing["max_input_tokens"]
                or completion > request.max_output_tokens
                or actual > reserved + 1e-12
            ):
                attempt["status"] = "cost_violation"
                return stop("STOPPED_COST_VIOLATION")
            try:
                entities = parse_logicpoison_query_response(response.content)
                # Legacy parser coerces nonstrings; v1.2 rejects them explicitly.
                if any(
                    not isinstance(item["entity"], str)
                    or not isinstance(item["type"], str)
                    for item in json.loads(response.content)
                ):
                    raise ValueError("entity/type must be strings")
            except (ValueError, TypeError, KeyError) as exc:
                attempt["status"] = "invalid_schema"
                attempt["error_type"] = type(exc).__name__
            else:
                attempt.update(status="complete", entities=entities)
            atomic_write_json(state_path, state)
        entity_rows = [
            {
                "query_id": q["query_id"],
                "entities": state["requests"][q["query_id"]].get("entities", []),
                "status": state["requests"][q["query_id"]]["status"],
            }
            for q in queries
        ]
        save_artifact("query_entities.jsonl", entity_rows, lines=True)
        if any(row["status"] != "complete" for row in entity_rows):
            return stop("QUERY_STAGE_INVALID")
        if "query" not in state["completed_stages"]:
            state["completed_stages"].append("query")
        atomic_write_json(state_path, state)
        try:
            plan = replacement_plan(stats, entity_rows, top_ratio=config["top_ratio"])
            save_artifact("replacement_plan.json", plan)
            poisoned, provenance, metrics = rewrite_corpus(
                corpus, plan, budget=config["poison_budget"]
            )
        except ValueError as exc:
            # Only controlled local validation messages; never persist provider text.
            return stop("LOGIC_STAGE_REJECTED", str(exc))
        state["poison_metrics"] = metrics
        if not provenance:
            return stop("NO_EFFECTIVE_REPLACEMENT")
        save_artifact("changed_documents.jsonl", provenance, lines=True)
        save_artifact("corpus.jsonl", poisoned, lines=True)
        state["completed_stages"].extend(["logic", "corpus_materialization"])
        return stop("CORPUS_MATERIALIZED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "CORPUS_MATERIALIZED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
