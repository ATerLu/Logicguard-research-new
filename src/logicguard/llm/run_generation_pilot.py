"""Run a small LLM answer-generation pilot on LogicGuard debug traces.

This runner is intentionally conservative: it samples a small number of attack
cases where poisoned evidence was actually retrieved, sends clean/poisoned/
guarded contexts to configured models, and records answer-stage outcomes. It is
not a full paper-scale LLM experiment yet; it is the first real-API validation
loop for prompts, provider connectivity, and answer metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import yaml

from logicguard.data.loader import _load_corpus
from logicguard.data.schemas import CorpusDocument
from logicguard.llm.context import build_context_blocks, build_qa_messages
from logicguard.llm.evaluation import classify_answer
from logicguard.llm.provider import OpenAICompatibleChatClient


@dataclass(frozen=True, slots=True)
class GenerationPilotConfig:
    """Configuration for one debug-size LLM generation pilot."""

    dataset: str
    run_name: str
    api_key_env: str
    base_url_env: str
    models: list[str]
    clean_corpus_path: Path
    entity_swap_corpus_path: Path
    bridge_corpus_path: Path
    clean_trace_path: Path
    entity_swap_trace_path: Path
    bridge_trace_path: Path
    entity_guarded_trace_path: Path
    bridge_guarded_trace_path: Path
    entity_recovered_trace_path: Path | None
    bridge_recovered_trace_path: Path | None
    entity_swap_metadata_path: Path
    bridge_metadata_path: Path
    output_root: Path
    report_path: Path
    include_recovered_context: bool
    top_k: int
    max_cases_per_attack: int
    max_docs: int
    max_chars_per_doc: int
    temperature: float
    max_tokens: int
    timeout_seconds: int

    @classmethod
    def from_yaml(cls, path: Path) -> "GenerationPilotConfig":
        """Load config with paths relative to the project root."""

        project_root = path.resolve().parents[1]
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            run_name=str(payload.get("run_name", "debug_50")),
            api_key_env=str(payload.get("api_key_env", "DASHSCOPE_API_KEY")),
            base_url_env=str(payload.get("base_url_env", "DASHSCOPE_BASE_URL")),
            models=[str(model) for model in payload["models"]],
            clean_corpus_path=resolve_project_path(payload["clean_corpus_path"]),
            entity_swap_corpus_path=resolve_project_path(payload["entity_swap_corpus_path"]),
            bridge_corpus_path=resolve_project_path(payload["bridge_corpus_path"]),
            clean_trace_path=resolve_project_path(payload["clean_trace_path"]),
            entity_swap_trace_path=resolve_project_path(payload["entity_swap_trace_path"]),
            bridge_trace_path=resolve_project_path(payload["bridge_trace_path"]),
            entity_guarded_trace_path=resolve_project_path(payload["entity_guarded_trace_path"]),
            bridge_guarded_trace_path=resolve_project_path(payload["bridge_guarded_trace_path"]),
            entity_recovered_trace_path=(
                resolve_project_path(payload["entity_recovered_trace_path"])
                if payload.get("entity_recovered_trace_path")
                else None
            ),
            bridge_recovered_trace_path=(
                resolve_project_path(payload["bridge_recovered_trace_path"])
                if payload.get("bridge_recovered_trace_path")
                else None
            ),
            entity_swap_metadata_path=resolve_project_path(payload["entity_swap_metadata_path"]),
            bridge_metadata_path=resolve_project_path(payload["bridge_metadata_path"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            include_recovered_context=bool(payload.get("include_recovered_context", False)),
            top_k=int(payload.get("top_k", 10)),
            max_cases_per_attack=int(payload.get("max_cases_per_attack", 1)),
            max_docs=int(payload.get("max_docs", 5)),
            max_chars_per_doc=int(payload.get("max_chars_per_doc", 700)),
            temperature=float(payload.get("temperature", 0.0)),
            max_tokens=int(payload.get("max_tokens", 64)),
            timeout_seconds=int(payload.get("timeout_seconds", 60)),
        )

    def output_dir(self) -> Path:
        return self.output_root / self.dataset / self.run_name


@dataclass(frozen=True, slots=True)
class GenerationCase:
    """One attack case selected for LLM answer-stage evaluation."""

    attack_type: str
    query_id: str
    question: str
    gold_answer: str
    poisoned_answer: str
    poisoned_doc_ids: list[str]
    clean_doc_ids: list[str]
    poisoned_doc_ids_in_context: list[str]
    guarded_doc_ids: list[str]
    recovered_doc_ids: list[str]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """One model answer for one case/context variant."""

    model: str
    attack_type: str
    context_variant: str
    query_id: str
    gold_answer: str
    poisoned_answer: str
    generated_answer: str
    is_correct: bool
    is_poisoned: bool
    is_abstained: bool
    latency_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error: str | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def run_from_config(config: GenerationPilotConfig) -> list[GenerationResult]:
    """Run the configured generation pilot and write result artifacts."""

    api_key = _read_required_env(config.api_key_env)
    base_url = _read_required_env(config.base_url_env)
    client = OpenAICompatibleChatClient(base_url=base_url, api_key=api_key)

    corpora = {
        "clean": _load_corpus(config.clean_corpus_path),
        "entity_swap": _load_corpus(config.entity_swap_corpus_path),
        "bridge_injection": _load_corpus(config.bridge_corpus_path),
    }
    traces = {
        "clean": _load_trace_records(config.clean_trace_path),
        "entity_swap": _load_trace_records(config.entity_swap_trace_path),
        "bridge_injection": _load_trace_records(config.bridge_trace_path),
        "entity_guarded": _load_trace_records(config.entity_guarded_trace_path),
        "bridge_guarded": _load_trace_records(config.bridge_guarded_trace_path),
    }
    if config.include_recovered_context:
        if config.entity_recovered_trace_path is None or config.bridge_recovered_trace_path is None:
            raise ValueError("Recovered context is enabled but recovered trace paths are missing.")
        traces["entity_recovered"] = _load_trace_records(config.entity_recovered_trace_path)
        traces["bridge_recovered"] = _load_trace_records(config.bridge_recovered_trace_path)
    cases = _select_generation_cases(
        traces=traces,
        entity_metadata=_load_metadata_records(config.entity_swap_metadata_path),
        bridge_metadata=_load_metadata_records(config.bridge_metadata_path),
        entity_corpus=corpora["entity_swap"],
        bridge_corpus=corpora["bridge_injection"],
        top_k=config.top_k,
        max_cases_per_attack=config.max_cases_per_attack,
    )
    results: list[GenerationResult] = []
    for model in config.models:
        for case in cases:
            results.extend(_run_case_for_model(config, client, model, case, corpora))

    write_generation_outputs(config, cases, results)
    print(
        f"{config.dataset}: generation_cases={len(cases)}, "
        f"models={len(config.models)}, calls={len(results)}"
    )
    return results


def _run_case_for_model(
    config: GenerationPilotConfig,
    client: OpenAICompatibleChatClient,
    model: str,
    case: GenerationCase,
    corpora: dict[str, dict[str, CorpusDocument]],
) -> list[GenerationResult]:
    """Run clean, poisoned, and guarded context variants for one case/model."""

    variants = [
        (
            variant_name,
            doc_ids,
            corpora[corpus_key],
        )
        for variant_name, doc_ids, corpus_key in _context_variants_for_case(
            case,
            include_recovered_context=config.include_recovered_context,
        )
    ]
    return [
        _call_model_for_variant(config, client, model, case, variant_name, doc_ids, documents)
        for variant_name, doc_ids, documents in variants
    ]


def _call_model_for_variant(
    config: GenerationPilotConfig,
    client: OpenAICompatibleChatClient,
    model: str,
    case: GenerationCase,
    context_variant: str,
    doc_ids: list[str],
    documents: dict[str, CorpusDocument],
) -> GenerationResult:
    context = build_context_blocks(
        doc_ids,
        documents,
        max_docs=config.max_docs,
        max_chars_per_doc=config.max_chars_per_doc,
    )
    messages = build_qa_messages(question=case.question, context=context)
    start = perf_counter()
    try:
        response = client.chat(
            model=model,
            messages=messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
        )
        elapsed = perf_counter() - start
        classification = classify_answer(
            response.content,
            gold_answer=case.gold_answer,
            poisoned_answer=case.poisoned_answer,
        )
        return GenerationResult(
            model=model,
            attack_type=case.attack_type,
            context_variant=context_variant,
            query_id=case.query_id,
            gold_answer=case.gold_answer,
            poisoned_answer=case.poisoned_answer,
            generated_answer=response.content,
            is_correct=classification.is_correct,
            is_poisoned=classification.is_poisoned,
            is_abstained=classification.is_abstained,
            latency_seconds=round(elapsed, 4),
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - experiment records provider failures as data.
        elapsed = perf_counter() - start
        return GenerationResult(
            model=model,
            attack_type=case.attack_type,
            context_variant=context_variant,
            query_id=case.query_id,
            gold_answer=case.gold_answer,
            poisoned_answer=case.poisoned_answer,
            generated_answer="",
            is_correct=False,
            is_poisoned=False,
            is_abstained=False,
            latency_seconds=round(elapsed, 4),
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            error=str(exc),
        )


def _select_generation_cases(
    *,
    traces: dict[str, dict[str, dict[str, object]]],
    entity_metadata: list[dict[str, object]],
    bridge_metadata: list[dict[str, object]],
    entity_corpus: dict[str, CorpusDocument],
    bridge_corpus: dict[str, CorpusDocument],
    top_k: int,
    max_cases_per_attack: int,
) -> list[GenerationCase]:
    cases: list[GenerationCase] = []
    cases.extend(
        _select_cases_for_attack(
            attack_type="entity_swap",
            metadata_records=entity_metadata,
            poisoned_corpus=entity_corpus,
            clean_traces=traces["clean"],
            poisoned_traces=traces["entity_swap"],
            guarded_traces=traces["entity_guarded"],
            recovered_traces=traces.get("entity_recovered"),
            top_k=top_k,
            max_cases=max_cases_per_attack,
        )
    )
    cases.extend(
        _select_cases_for_attack(
            attack_type="bridge_injection",
            metadata_records=bridge_metadata,
            poisoned_corpus=bridge_corpus,
            clean_traces=traces["clean"],
            poisoned_traces=traces["bridge_injection"],
            guarded_traces=traces["bridge_guarded"],
            recovered_traces=traces.get("bridge_recovered"),
            top_k=top_k,
            max_cases=max_cases_per_attack,
        )
    )
    return cases


def _select_cases_for_attack(
    *,
    attack_type: str,
    metadata_records: list[dict[str, object]],
    poisoned_corpus: dict[str, CorpusDocument],
    clean_traces: dict[str, dict[str, object]],
    poisoned_traces: dict[str, dict[str, object]],
    guarded_traces: dict[str, dict[str, object]],
    recovered_traces: dict[str, dict[str, object]] | None = None,
    top_k: int,
    max_cases: int,
) -> list[GenerationCase]:
    selected: list[GenerationCase] = []
    for metadata in metadata_records:
        query_id = str(metadata["query_id"])
        clean_trace = clean_traces.get(query_id)
        poisoned_trace = poisoned_traces.get(query_id)
        guarded_trace = guarded_traces.get(query_id)
        recovered_trace = recovered_traces.get(query_id) if recovered_traces is not None else None
        if clean_trace is None or poisoned_trace is None or guarded_trace is None:
            continue
        poisoned_doc_ids = [str(doc_id) for doc_id in metadata["poisoned_doc_ids"]]
        poisoned_top_doc_ids = _top_doc_ids(poisoned_trace, top_k=top_k)
        if not set(poisoned_doc_ids).intersection(poisoned_top_doc_ids):
            continue
        poisoned_document_texts = [
            poisoned_corpus[doc_id].text
            for doc_id in poisoned_doc_ids
            if doc_id in poisoned_corpus
        ]
        if not is_answer_stage_candidate(
            gold_answer=str(metadata["original_answer"]),
            poisoned_answer=str(metadata["replacement_answer"]),
            poisoned_document_texts=poisoned_document_texts,
        ):
            continue
        selected.append(
            GenerationCase(
                attack_type=attack_type,
                query_id=query_id,
                question=str(poisoned_trace["query"]),
                gold_answer=str(metadata["original_answer"]),
                poisoned_answer=str(metadata["replacement_answer"]),
                poisoned_doc_ids=poisoned_doc_ids,
                clean_doc_ids=_top_doc_ids(clean_trace, top_k=top_k),
                poisoned_doc_ids_in_context=poisoned_top_doc_ids,
                guarded_doc_ids=_top_doc_ids(guarded_trace, top_k=top_k),
                recovered_doc_ids=_top_doc_ids(recovered_trace or guarded_trace, top_k=top_k),
            )
        )
        if len(selected) >= max_cases:
            break
    return selected


def _context_variants_for_case(
    case: GenerationCase,
    *,
    include_recovered_context: bool,
) -> list[tuple[str, list[str], str]]:
    """Choose context variants and the corpus each variant should render from."""

    poisoned_corpus_key = "entity_swap" if case.attack_type == "entity_swap" else "bridge_injection"
    variants = [
        ("clean", case.clean_doc_ids, "clean"),
        ("poisoned", case.poisoned_doc_ids_in_context, poisoned_corpus_key),
        ("guarded", case.guarded_doc_ids, poisoned_corpus_key),
    ]
    if include_recovered_context:
        variants.append(("recovered", case.recovered_doc_ids, "clean"))
    return variants


def is_answer_stage_candidate(
    *,
    gold_answer: str,
    poisoned_answer: str,
    poisoned_document_texts: list[str],
) -> bool:
    """Return true when a retrieval attack case is suitable for answer-stage pilot.

    Very short yes/no answers are useful for retrieval metrics but brittle for
    answer-stage string matching. We also require the replacement answer to
    appear in the poisoned document text; otherwise the LLM has no explicit
    poisoned answer to copy.
    """

    if gold_answer.strip().lower() in {"yes", "no"}:
        return False
    normalized_poisoned = poisoned_answer.strip().lower()
    if not normalized_poisoned:
        return False
    return any(normalized_poisoned in text.lower() for text in poisoned_document_texts)


def _top_doc_ids(trace: dict[str, object], *, top_k: int) -> list[str]:
    candidates = trace.get("candidates")
    if not isinstance(candidates, list):
        return []
    doc_ids: list[str] = []
    for candidate in candidates[:top_k]:
        if isinstance(candidate, dict) and "doc_id" in candidate:
            doc_ids.append(str(candidate["doc_id"]))
    return doc_ids


def _load_trace_records(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for payload in _load_jsonl(path):
        records[str(payload["query_id"])] = payload
    return records


def _load_metadata_records(path: Path) -> list[dict[str, object]]:
    return list(_load_jsonl(path))


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            records.append(payload)
    return records


def write_generation_outputs(
    config: GenerationPilotConfig,
    cases: list[GenerationCase],
    results: list[GenerationResult],
) -> None:
    output_dir = config.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / "generation_cases.jsonl"
    jsonl_path = output_dir / "generation_results.jsonl"
    csv_path = output_dir / "generation_results.csv"

    with cases_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_json_dict(), ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].to_json_dict()))
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_json_dict())

    _write_generation_report(config.report_path, cases, results, cases_path, jsonl_path, csv_path)


def _write_generation_report(
    path: Path,
    cases: list[GenerationCase],
    results: list[GenerationResult],
    cases_path: Path,
    jsonl_path: Path,
    csv_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped = _summarize_results(results)
    context_variants = ", ".join(f"`{variant}`" for variant in sorted({result.context_variant for result in results}))
    table_lines = [
        "| model | attack | context | calls | correct | poisoned | abstained | errors | total tokens |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, metrics in sorted(grouped.items()):
        model, attack_type, context_variant = key
        table_lines.append(
            "| "
            + " | ".join(
                [
                    model,
                    attack_type,
                    context_variant,
                    str(metrics["calls"]),
                    str(metrics["correct"]),
                    str(metrics["poisoned"]),
                    str(metrics["abstained"]),
                    str(metrics["errors"]),
                    str(metrics["total_tokens"]),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicGuard LLM Generation Pilot",
            "",
            "## Output Files",
            "",
            f"- Cases: `{cases_path}`",
            f"- JSONL results: `{jsonl_path}`",
            f"- CSV results: `{csv_path}`",
            "",
            "## Setup",
            "",
            f"- Cases selected: `{len(cases)}`",
            f"- Context variants: {context_variants}",
            "- Answer classification: string match against gold and poisoned answers.",
            "",
            "## Summary",
            "",
            *table_lines,
            "",
            "## Notes",
            "",
            "This is a low-cost pilot for API connectivity and answer-stage signal. "
            "It should not yet be treated as a paper-scale LLM evaluation.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _summarize_results(results: list[GenerationResult]) -> dict[tuple[str, str, str], dict[str, int]]:
    grouped: dict[tuple[str, str, str], dict[str, int]] = {}
    for result in results:
        key = (result.model, result.attack_type, result.context_variant)
        metrics = grouped.setdefault(
            key,
            {"calls": 0, "correct": 0, "poisoned": 0, "abstained": 0, "errors": 0, "total_tokens": 0},
        )
        metrics["calls"] += 1
        metrics["correct"] += int(result.is_correct)
        metrics["poisoned"] += int(result.is_poisoned)
        metrics["abstained"] += int(result.is_abstained)
        metrics["errors"] += int(result.error is not None)
        metrics["total_tokens"] += result.total_tokens or 0
    return grouped


def _read_required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    # On Windows, this lets a newly-set user variable work even if the current
    # process environment was not refreshed. It is harmless on other platforms.
    try:
        import subprocess

        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"[Environment]::GetEnvironmentVariable('{name}', 'User')",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = completed.stdout.strip()
        if value:
            return value
    except Exception:
        pass
    raise RuntimeError(f"Missing required environment variable: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LogicGuard LLM generation pilot.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/llm_generation_pilot_debug.yaml"),
        help="Path to the generation pilot YAML config.",
    )
    args = parser.parse_args()
    run_from_config(GenerationPilotConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
