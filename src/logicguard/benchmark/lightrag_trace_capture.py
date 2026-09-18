"""Capture one bounded real LightRAG query_data trace from a frozen index copy."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

import yaml
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc

from logicguard.benchmark import lightrag_indexing_pilot as pilot
from logicguard.benchmark.backend_trace_adapters import normalize_lightrag_query_data
from logicguard.core.io import atomic_write_json, sha256_file, write_jsonl
from logicguard.core.run_state import fingerprint_json


def _planned_cap(config: dict[str, Any]) -> float:
    return (
        int(config["llm_call_cap"])
        * (
            int(config["llm_input_tokens_per_call_cap"])
            * float(config["pricing"]["chat_input_per_million_cny"])
            + int(config["llm_output_tokens_per_call_cap"])
            * float(config["pricing"]["chat_output_per_million_cny"])
        )
        + int(config["embedding_input_tokens_total_cap"])
        * float(config["pricing"]["embedding_input_per_million_cny"])
    ) / 1_000_000


def _directory_hashes(path: Path) -> dict[str, str]:
    return {
        str(file.relative_to(path)).replace("\\", "/"): sha256_file(file)
        for file in sorted(path.rglob("*"))
        if file.is_file()
    }


async def _run(config_path: Path) -> dict[str, Any]:
    root = config_path.resolve().parents[2]
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("run_mode") != "execute_once_existing_index_copy":
        raise ValueError("LightRAG trace capture must use execute-once mode")
    source = (root / config["source_working_dir"]).resolve()
    output = (root / config["output_root"]).resolve()
    namespace = (root / "artifacts/benchmark/research_revision_v1_2/wp2").resolve()
    if (
        not source.is_dir()
        or output == namespace
        or not output.is_relative_to(namespace)
    ):
        raise ValueError("invalid source index or output namespace")
    if output.exists():
        raise FileExistsError("refusing to rerun an existing paid trace namespace")
    planned_cap = _planned_cap(config)
    hard_cap = float(config["pricing"]["hard_cost_cap_cny"])
    if planned_cap > hard_cap + 1e-12:
        raise RuntimeError("LightRAG trace planned cap exceeds the configured hard cap")

    source_hashes_before = _directory_hashes(source)
    identity = {
        "schema_version": 1,
        "protocol_version": "comparison-v1.2",
        "config_sha256": sha256_file(config_path),
        "implementation_sha256": sha256_file(Path(__file__)),
        "source_index_sha256": fingerprint_json(source_hashes_before),
        "query_sha256": fingerprint_json({"question": config["question"]}),
    }
    identity["run_identity_sha256"] = fingerprint_json(identity)
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "run_identity.json", identity)
    atomic_write_json(
        output / "request_reservation.json",
        {
            "planned_catalog_cost_cap_cny": round(planned_cap, 6),
            "hard_cost_cap_cny": hard_cap,
            "llm_call_cap": int(config["llm_call_cap"]),
            "embedding_input_tokens_total_cap": int(
                config["embedding_input_tokens_total_cap"]
            ),
            "provider_retries": 0,
        },
    )
    working_dir = output / "index_snapshot"
    shutil.copytree(source, working_dir)

    provider = pilot.BoundedProvider(config)
    pilot._ACTIVE_PROVIDER = provider
    rag: LightRAG | None = None
    raw: dict[str, Any] | None = None
    normalized: dict[str, Any] | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        rag = LightRAG(
            working_dir=str(working_dir),
            llm_model_func=pilot._bounded_complete,
            embedding_func=EmbeddingFunc(
                embedding_dim=int(config["embedding_dimension"]),
                max_token_size=int(config["embedding_max_tokens_per_text"]),
                func=pilot._bounded_embed,
            ),
            llm_model_name=str(config["completion_model"]),
            llm_model_max_async=1,
            embedding_func_max_async=1,
            enable_llm_cache=False,
            enable_llm_cache_for_entity_extract=False,
        )
        await rag.initialize_storages()
        raw = await rag.aquery_data(
            str(config["question"]),
            QueryParam(
                mode=str(config["query_mode"]),
                top_k=int(config["top_k"]),
                chunk_top_k=int(config["chunk_top_k"]),
                max_entity_tokens=int(config["max_entity_tokens"]),
                max_relation_tokens=int(config["max_relation_tokens"]),
                max_total_tokens=int(config["max_total_tokens"]),
                enable_rerank=False,
                include_references=True,
            ),
        )
        normalized = normalize_lightrag_query_data(
            query_id=str(config["query_id"]),
            question=str(config["question"]),
            dataset=str(config["dataset"]),
            payload=raw,
        )
    except Exception as exc:  # frozen experimental outcome; never auto-retried
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if rag is not None:
            try:
                await rag.finalize_storages()
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"
        await provider.close()
        pilot._ACTIVE_PROVIDER = None

    usage = provider.usage()
    actual_cost = (
        usage["prompt_tokens"] * float(config["pricing"]["chat_input_per_million_cny"])
        + usage["completion_tokens"]
        * float(config["pricing"]["chat_output_per_million_cny"])
        + usage["embedding_tokens"]
        * float(config["pricing"]["embedding_input_per_million_cny"])
    ) / 1_000_000
    source_hashes_after = _directory_hashes(source)
    source_unchanged = source_hashes_before == source_hashes_after
    if raw is not None:
        atomic_write_json(output / "raw_query_data.json", raw)
    if normalized is not None:
        write_jsonl(output / "normalized_trace.jsonl", [normalized])
    passed = (
        error is None
        and normalized is not None
        and len(normalized["live_hits"]) > 0
        and actual_cost <= hard_cap + 1e-12
        and source_unchanged
    )
    artifact_names = [
        "run_identity.json",
        "request_reservation.json",
        *(["raw_query_data.json", "normalized_trace.jsonl"] if normalized else []),
    ]
    summary = {
        **identity,
        "status": "REAL_LIGHTRAG_TRACE_CAPTURE_PASSED" if passed else "FAILED",
        "evidence_scope": "single_existing_clean_ten_document_index_query_data_trace",
        "backend": "S2_lightrag",
        "backend_version": "1.5.7",
        "dataset": config["dataset"],
        "query_id": config["query_id"],
        "query_mode": config["query_mode"],
        "retrieved_chunks": len(normalized["live_hits"]) if normalized else 0,
        "usage": usage,
        "provider_calls_made": usage["llm_calls"] + usage["embedding_calls"],
        "planned_catalog_cost_cap_cny": round(planned_cap, 6),
        "hard_cost_cap_cny": hard_cap,
        "actual_catalog_cost_cny": round(actual_cost, 6),
        "source_index_unchanged": source_unchanged,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "generation_controls": {
            "answer_generation": False,
            "enable_thinking": False,
            "provider_retries": 0,
            "rerank": False,
        },
        "error": error,
        "artifact_hashes": {
            name: sha256_file(output / name)
            for name in artifact_names
            if (output / name).is_file()
        },
    }
    atomic_write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(_run(args.config.resolve())), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
