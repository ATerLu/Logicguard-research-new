"""Run a one-document Microsoft GraphRAG indexing pilot behind a cost cap."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request

import tiktoken
import yaml


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class UsageLedger:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.chat_calls = 0
        self.embedding_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.embedding_tokens = 0

    def prepare(self, payload: dict[str, Any], path: str) -> dict[str, Any]:
        if path.endswith("/chat/completions"):
            messages = payload.get("messages", [])
            estimated = sum(
                len(self.encoding.encode(json.dumps(item, ensure_ascii=False)))
                for item in messages
            )
            with self.lock:
                if estimated > int(self.config["chat_input_tokens_per_call_cap"]):
                    raise ValueError("GraphRAG pilot chat input cap exceeded")
                if self.chat_calls >= int(self.config["chat_call_cap"]):
                    raise ValueError("GraphRAG pilot chat call cap exhausted")
                self.chat_calls += 1
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = int(
                self.config["chat_output_tokens_per_call_cap"]
            )
            payload["enable_thinking"] = False
            payload["temperature"] = 0.0
        elif path.endswith("/embeddings"):
            inputs = payload.get("input", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            estimated = sum(len(self.encoding.encode(str(item))) for item in inputs)
            with self.lock:
                if self.embedding_tokens + estimated > int(
                    self.config["embedding_input_tokens_total_cap"]
                ):
                    raise ValueError("GraphRAG pilot embedding token cap exhausted")
                self.embedding_calls += 1
                self.embedding_tokens += estimated
        else:
            raise ValueError(f"unsupported proxied endpoint: {path}")
        return payload

    def record(self, payload: dict[str, Any], path: str) -> None:
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        with self.lock:
            if path.endswith("/chat/completions"):
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                details = usage.get("completion_tokens_details")
                if isinstance(details, dict):
                    self.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
            elif path.endswith("/embeddings"):
                actual = int(
                    usage.get("prompt_tokens") or usage.get("total_tokens") or 0
                )
                if actual:
                    self.embedding_tokens = max(self.embedding_tokens, actual)

    def as_dict(self) -> dict[str, int]:
        with self.lock:
            return {
                "chat_calls": self.chat_calls,
                "embedding_calls": self.embedding_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "embedding_tokens": self.embedding_tokens,
            }


def _planned_cap(config: dict[str, Any]) -> float:
    return (
        int(config["chat_call_cap"])
        * (
            int(config["chat_input_tokens_per_call_cap"])
            * float(config["pricing"]["chat_input_per_million_cny"])
            + int(config["chat_output_tokens_per_call_cap"])
            * float(config["pricing"]["chat_output_per_million_cny"])
        )
        + int(config["embedding_input_tokens_total_cap"])
        * float(config["pricing"]["embedding_input_per_million_cny"])
    ) / 1_000_000


def _handler(
    ledger: UsageLedger, provider_base_url: str, provider_key: str, timeout: int
) -> type[BaseHTTPRequestHandler]:
    class ProxyHandler(BaseHTTPRequestHandler):
        def log_message(self, _: str, *args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            try:
                size = int(self.headers.get("Content-Length", "0"))
                incoming = json.loads(self.rfile.read(size).decode("utf-8"))
                prepared = ledger.prepare(incoming, self.path)
                suffix = self.path.removeprefix("/v1")
                upstream = request.Request(
                    url=provider_base_url.rstrip("/") + suffix,
                    data=json.dumps(prepared, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {provider_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with request.urlopen(upstream, timeout=timeout) as response:
                    body = response.read()
                    status = response.status
                    content_type = response.headers.get(
                        "Content-Type", "application/json"
                    )
                decoded = json.loads(body.decode("utf-8"))
                ledger.record(decoded, self.path)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except error.HTTPError as exc:
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps(
                    {"error": {"message": f"pilot proxy: {type(exc).__name__}: {exc}"}}
                ).encode("utf-8")
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    return ProxyHandler


def run(config_path: Path) -> dict[str, Any]:
    root = config_path.resolve().parents[2]
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    workspace = _resolve(root, config["workspace"])
    summary_path = _resolve(root, config["output_summary"])
    output_dir = workspace / "output"
    if summary_path.exists() or output_dir.exists():
        raise FileExistsError("refusing to rerun an existing GraphRAG pilot namespace")
    settings = yaml.safe_load((workspace / "settings.yaml").read_text(encoding="utf-8"))
    completion = settings["completion_models"]["default_completion_model"]
    embedding = settings["embedding_models"]["default_embedding_model"]
    if completion.get("retry") is not None or embedding.get("retry") is not None:
        raise RuntimeError("GraphRAG pilot requires retry: null")
    if settings["extract_graph"]["max_gleanings"] != 0:
        raise RuntimeError("GraphRAG pilot requires max_gleanings=0")

    planned_cap = _planned_cap(config)
    hard_cap = float(config["pricing"]["hard_cost_cap_cny"])
    if planned_cap > hard_cap + 1e-12:
        raise RuntimeError("GraphRAG planned cap exceeds configured hard cap")
    provider_key = os.environ.get(str(config["api_key_env"]), "").strip()
    provider_base = os.environ.get(str(config["base_url_env"]), "").strip()
    if not provider_key or not provider_base:
        raise RuntimeError("GraphRAG pilot provider environment is incomplete")

    ledger = UsageLedger(config)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler(
            ledger,
            provider_base,
            provider_key,
            int(config["provider_timeout_seconds"]),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    child_env = os.environ.copy()
    child_env[str(config["api_key_env"])] = "local-pilot-proxy"
    child_env[str(config["base_url_env"])] = f"http://127.0.0.1:{server.server_port}/v1"
    started = time.perf_counter()
    command = [
        str(_resolve(root, config["graphrag_executable"])),
        "index",
        "--root",
        str(workspace),
        "--no-cache",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(config["process_timeout_seconds"]),
            check=False,
        )
        returncode = completed.returncode
        stdout_tail = completed.stdout[-3000:]
        stderr_tail = completed.stderr[-3000:]
        process_error = None
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout_tail = str(exc.stdout or "")[-3000:]
        stderr_tail = str(exc.stderr or "")[-3000:]
        process_error = "TimeoutExpired"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    usage = ledger.as_dict()
    actual_cost = (
        usage["prompt_tokens"] * float(config["pricing"]["chat_input_per_million_cny"])
        + usage["completion_tokens"]
        * float(config["pricing"]["chat_output_per_million_cny"])
        + usage["embedding_tokens"]
        * float(config["pricing"]["embedding_input_per_million_cny"])
    ) / 1_000_000
    required_outputs = [
        output_dir / "documents.parquet",
        output_dir / "entities.parquet",
        output_dir / "relationships.parquet",
        output_dir / "community_reports.parquet",
    ]
    passed = (
        returncode == 0
        and all(path.is_file() for path in required_outputs)
        and usage["reasoning_tokens"] == 0
        and actual_cost <= hard_cap + 1e-12
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "backend": "microsoft_graphrag",
        "backend_version": "3.1.0",
        "status": "PASSED" if passed else "FAILED",
        "returncode": returncode,
        "usage": usage,
        "generation_controls": {
            "enable_thinking": False,
            "output_limit_parameter": "max_completion_tokens",
            "provider_retries": 0,
            "max_gleanings": 0,
            "local_capped_proxy": True,
        },
        "planned_catalog_cost_cap_cny": round(planned_cap, 6),
        "hard_cost_cap_cny": hard_cap,
        "actual_catalog_cost_cny": round(actual_cost, 6),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "required_outputs_present": {
            path.name: path.is_file() for path in required_outputs
        },
        "process_error": process_error,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }
    _atomic_json(summary_path, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
