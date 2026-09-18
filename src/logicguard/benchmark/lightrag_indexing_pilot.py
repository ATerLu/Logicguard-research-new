"""Run one tightly bounded LightRAG indexing cost pilot in its isolated runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import tiktoken
import yaml
from lightrag import LightRAG
from lightrag.llm.openai import AsyncOpenAI
from lightrag.utils import EmbeddingFunc


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _load_documents(path: Path, index: int, count: int) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for current, line in enumerate(handle):
            if current < index or not line.strip():
                continue
            row = json.loads(line)
            documents.append(
                {
                    "doc_id": str(row.get("_id", row.get("doc_id", ""))),
                    "title": str(row.get("title", "")),
                    "text": str(row["text"]),
                }
            )
            if len(documents) == count:
                return documents
    raise ValueError(f"{count} documents from index {index} are unavailable in {path}")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class BoundedProvider:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        key = os.environ.get(str(config["api_key_env"]), "").strip()
        if not key:
            raise RuntimeError(f"missing {config['api_key_env']}")
        base_url = os.environ.get(str(config["base_url_env"]), "").strip()
        if not base_url:
            base_url = str(config["default_base_url"])
        self.client = AsyncOpenAI(
            api_key=key,
            base_url=base_url,
            max_retries=0,
            timeout=float(config.get("timeout_seconds", 120)),
        )
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.lock = asyncio.Lock()
        self.llm_calls = 0
        self.embedding_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.embedding_tokens = 0

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for item in history_messages or []:
            messages.append(
                {"role": str(item["role"]), "content": str(item["content"])}
            )
        messages.append({"role": "user", "content": prompt})
        estimated_input = sum(
            len(self.encoding.encode(message["content"])) for message in messages
        )
        if estimated_input > int(self.config["llm_input_tokens_per_call_cap"]):
            raise RuntimeError("LightRAG pilot LLM input cap exceeded before dispatch")
        async with self.lock:
            if self.llm_calls >= int(self.config["llm_call_cap"]):
                raise RuntimeError("LightRAG pilot LLM call cap exhausted")
            self.llm_calls += 1
        response = await self.client.chat.completions.create(
            model=str(self.config["completion_model"]),
            messages=messages,  # type: ignore[arg-type]
            temperature=0.0,
            max_completion_tokens=int(self.config["llm_output_tokens_per_call_cap"]),
            extra_body={"enable_thinking": False},
        )
        usage = response.usage
        if usage:
            self.prompt_tokens += int(usage.prompt_tokens or 0)
            self.completion_tokens += int(usage.completion_tokens or 0)
            details = usage.completion_tokens_details
            self.reasoning_tokens += int(getattr(details, "reasoning_tokens", 0) or 0)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LightRAG pilot received an empty completion")
        return content

    async def embed(self, texts: list[str]) -> np.ndarray:
        token_count = sum(len(self.encoding.encode(text)) for text in texts)
        async with self.lock:
            if self.embedding_tokens + token_count > int(
                self.config["embedding_input_tokens_total_cap"]
            ):
                raise RuntimeError("LightRAG pilot embedding token cap exhausted")
            self.embedding_calls += 1
            self.embedding_tokens += token_count
        response = await self.client.embeddings.create(
            model=str(self.config["embedding_model"]),
            input=texts,
            dimensions=int(self.config["embedding_dimension"]),
            encoding_format="float",
        )
        if response.usage:
            self.embedding_tokens = max(
                self.embedding_tokens, int(response.usage.prompt_tokens or 0)
            )
        ordered = sorted(response.data, key=lambda item: item.index)
        return np.asarray([item.embedding for item in ordered], dtype=np.float32)

    async def close(self) -> None:
        await self.client.close()

    def usage(self) -> dict[str, int]:
        return {
            "llm_calls": self.llm_calls,
            "embedding_calls": self.embedding_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "embedding_tokens": self.embedding_tokens,
        }


_ACTIVE_PROVIDER: BoundedProvider | None = None


async def _bounded_complete(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    if _ACTIVE_PROVIDER is None:
        raise RuntimeError("LightRAG pilot provider is not initialized")
    return await _ACTIVE_PROVIDER.complete(
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        **kwargs,
    )


async def _bounded_embed(texts: list[str]) -> np.ndarray:
    if _ACTIVE_PROVIDER is None:
        raise RuntimeError("LightRAG pilot provider is not initialized")
    return await _ACTIVE_PROVIDER.embed(texts)


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


async def _run(config_path: Path) -> dict[str, Any]:
    global _ACTIVE_PROVIDER
    root = config_path.resolve().parents[2]
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output = _resolve(root, config["output_summary"])
    working_dir = _resolve(root, config["working_dir"])
    if output.exists() or working_dir.exists():
        raise FileExistsError("refusing to rerun an existing LightRAG pilot namespace")
    planned_cap = _planned_cap(config)
    hard_cap = float(config["pricing"]["hard_cost_cap_cny"])
    if planned_cap > hard_cap + 1e-12:
        raise RuntimeError("LightRAG planned cap exceeds configured hard cap")

    documents = _load_documents(
        _resolve(root, config["corpus_path"]),
        int(config["document_index"]),
        int(config.get("document_count", 1)),
    )
    document_texts = [
        f"Title: {document['title']}\n\n{document['text']}" for document in documents
    ]
    provider = BoundedProvider(config)
    _ACTIVE_PROVIDER = provider
    rag: LightRAG | None = None
    started = time.perf_counter()
    error: str | None = None
    try:
        rag = LightRAG(
            working_dir=str(working_dir),
            llm_model_func=_bounded_complete,
            embedding_func=EmbeddingFunc(
                embedding_dim=int(config["embedding_dimension"]),
                max_token_size=int(config["embedding_max_tokens_per_text"]),
                func=_bounded_embed,
            ),
            llm_model_name=str(config["completion_model"]),
            llm_model_max_async=1,
            embedding_func_max_async=1,
            entity_extract_max_gleaning=0,
            entity_extract_max_records=int(config["entity_extract_max_records"]),
            entity_extract_max_entities=int(config["entity_extract_max_entities"]),
            summary_max_tokens=int(config["summary_max_tokens"]),
            summary_length_recommended=int(config["summary_length_recommended"]),
            max_parallel_insert=1,
            enable_llm_cache=False,
            enable_llm_cache_for_entity_extract=False,
        )
        await rag.initialize_storages()
        await rag.ainsert(
            document_texts,
            ids=[document["doc_id"] for document in documents],
            file_paths=[f"{document['doc_id']}.txt" for document in documents],
        )
    except Exception as exc:  # failure is a frozen experimental outcome
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if rag is not None:
            try:
                await rag.finalize_storages()
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"
        await provider.close()
        _ACTIVE_PROVIDER = None

    usage = provider.usage()
    actual_cost = (
        usage["prompt_tokens"] * float(config["pricing"]["chat_input_per_million_cny"])
        + usage["completion_tokens"]
        * float(config["pricing"]["chat_output_per_million_cny"])
        + usage["embedding_tokens"]
        * float(config["pricing"]["embedding_input_per_million_cny"])
    ) / 1_000_000
    output_files = list(working_dir.rglob("*")) if working_dir.exists() else []
    passed = error is None and actual_cost <= hard_cap + 1e-12
    payload: dict[str, Any] = {
        "schema_version": 1,
        "backend": "lightrag",
        "backend_version": "1.5.7",
        "status": "PASSED" if passed else "FAILED",
        "document_ids": [document["doc_id"] for document in documents],
        "document_count": len(documents),
        "document_chars": sum(len(text) for text in document_texts),
        "usage": usage,
        "generation_controls": {
            "enable_thinking": False,
            "output_limit_parameter": "max_completion_tokens",
            "provider_retries": 0,
        },
        "planned_catalog_cost_cap_cny": round(planned_cap, 6),
        "hard_cost_cap_cny": hard_cap,
        "actual_catalog_cost_cny": round(actual_cost, 6),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "output_file_count": sum(path.is_file() for path in output_files),
        "error": error,
    }
    _atomic_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args.config)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
