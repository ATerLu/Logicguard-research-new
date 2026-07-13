"""Command-line runner for the first offline LogicGuard defense evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.attack.schemas import PoisonedEvidenceExposure
from logicguard.defense.reranker import build_guarded_trace, build_recovered_trace, rerank_trace
from logicguard.defense.schemas import RerankedTrace
from logicguard.graph.schemas import EntityMention, PathCandidate, RetrievalTrace


@dataclass(frozen=True, slots=True)
class LogicGuardRunConfig:
    """Configuration for one LogicGuard MVP evaluation run."""

    dataset: str
    reference_corpus_path: Path
    clean_corpus_path: Path
    clean_trace_path: Path
    clean_corpus_entity_path: Path
    entity_swap_corpus_path: Path
    entity_swap_trace_path: Path
    entity_swap_corpus_entity_path: Path
    entity_swap_attack_metadata_path: Path
    bridge_corpus_path: Path
    bridge_trace_path: Path
    bridge_corpus_entity_path: Path
    bridge_attack_metadata_path: Path
    reference_corpus_entity_path: Path
    output_root: Path
    report_path: Path
    top_k: int
    risk_penalty: float
    risk_threshold: float

    @classmethod
    def from_yaml(cls, path: Path) -> "LogicGuardRunConfig":
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
            reference_corpus_path=resolve_project_path(payload["reference_corpus_path"]),
            clean_corpus_path=resolve_project_path(payload["clean_corpus_path"]),
            clean_trace_path=resolve_project_path(payload["clean_trace_path"]),
            clean_corpus_entity_path=resolve_project_path(payload["clean_corpus_entity_path"]),
            entity_swap_corpus_path=resolve_project_path(payload["entity_swap_corpus_path"]),
            entity_swap_trace_path=resolve_project_path(payload["entity_swap_trace_path"]),
            entity_swap_corpus_entity_path=resolve_project_path(payload["entity_swap_corpus_entity_path"]),
            entity_swap_attack_metadata_path=resolve_project_path(payload["entity_swap_attack_metadata_path"]),
            bridge_corpus_path=resolve_project_path(payload["bridge_corpus_path"]),
            bridge_trace_path=resolve_project_path(payload["bridge_trace_path"]),
            bridge_corpus_entity_path=resolve_project_path(payload["bridge_corpus_entity_path"]),
            bridge_attack_metadata_path=resolve_project_path(payload["bridge_attack_metadata_path"]),
            reference_corpus_entity_path=resolve_project_path(payload["reference_corpus_entity_path"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            top_k=int(payload.get("top_k", 10)),
            risk_penalty=float(payload.get("risk_penalty", 0.75)),
            risk_threshold=float(payload.get("risk_threshold", 0.90)),
        )

    def output_dir(self) -> Path:
        return self.output_root / self.dataset


@dataclass(frozen=True, slots=True)
class DefenseRunMetrics:
    """Before/after metrics for one trace collection."""

    name: str
    query_count: int
    before_hit_at_k: float
    before_gold_recall_at_k: float
    reranked_hit_at_k: float
    reranked_gold_recall_at_k: float
    guarded_hit_at_k: float
    guarded_gold_recall_at_k: float
    before_trusted_hit_at_k: float
    before_trusted_gold_recall_at_k: float
    guarded_trusted_hit_at_k: float
    guarded_trusted_gold_recall_at_k: float
    queries_with_trusted_gold: int
    corrupted_gold_doc_count: int
    before_exposure_at_k: float | None
    reranked_exposure_at_k: float | None
    guarded_exposure_at_k: float | None
    average_risk: float
    guarded_avg_candidates: float
    suppressed_candidates: int
    suppressed_gold_candidates: int
    suppressed_poisoned_candidates: int
    suppressed_changed_candidates: int


def run_from_config(config: LogicGuardRunConfig) -> None:
    clean_traces = load_traces_jsonl(config.clean_trace_path)
    entity_traces = load_traces_jsonl(config.entity_swap_trace_path)
    bridge_traces = load_traces_jsonl(config.bridge_trace_path)
    reference_doc_ids = load_reference_doc_ids(config.reference_corpus_entity_path)
    clean_global_support = load_global_entity_support_counts(config.clean_corpus_entity_path)
    entity_global_support = load_global_entity_support_counts(config.entity_swap_corpus_entity_path)
    bridge_global_support = load_global_entity_support_counts(config.bridge_corpus_entity_path)
    reference_fingerprints = load_document_fingerprints(config.reference_corpus_path)
    clean_changed_doc_ids = find_changed_doc_ids(reference_fingerprints, load_document_fingerprints(config.clean_corpus_path))
    entity_changed_doc_ids = find_changed_doc_ids(
        reference_fingerprints,
        load_document_fingerprints(config.entity_swap_corpus_path),
    )
    bridge_changed_doc_ids = find_changed_doc_ids(
        reference_fingerprints,
        load_document_fingerprints(config.bridge_corpus_path),
    )

    entity_poisoned_docs = load_poisoned_doc_ids_by_query(config.entity_swap_attack_metadata_path)
    bridge_poisoned_docs = load_poisoned_doc_ids_by_query(config.bridge_attack_metadata_path)

    clean_reranked = [
        rerank_trace(
            trace,
            risk_penalty=config.risk_penalty,
            global_entity_support_counts=clean_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=clean_changed_doc_ids,
        )
        for trace in clean_traces
    ]
    entity_reranked = [
        rerank_trace(
            trace,
            risk_penalty=config.risk_penalty,
            global_entity_support_counts=entity_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=entity_changed_doc_ids,
        )
        for trace in entity_traces
    ]
    bridge_reranked = [
        rerank_trace(
            trace,
            risk_penalty=config.risk_penalty,
            global_entity_support_counts=bridge_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=bridge_changed_doc_ids,
        )
        for trace in bridge_traces
    ]
    clean_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=config.risk_penalty,
            risk_threshold=config.risk_threshold,
            global_entity_support_counts=clean_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=clean_changed_doc_ids,
        )
        for trace in clean_traces
    ]
    entity_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=config.risk_penalty,
            risk_threshold=config.risk_threshold,
            global_entity_support_counts=entity_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=entity_changed_doc_ids,
        )
        for trace in entity_traces
    ]
    bridge_guarded = [
        build_guarded_trace(
            trace,
            risk_penalty=config.risk_penalty,
            risk_threshold=config.risk_threshold,
            global_entity_support_counts=bridge_global_support,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=bridge_changed_doc_ids,
        )
        for trace in bridge_traces
    ]
    clean_reference_by_query = {trace.query_id: trace for trace in clean_traces}
    clean_recovered = build_recovered_trace_collection(clean_guarded, clean_reference_by_query, top_k=config.top_k)
    entity_recovered = build_recovered_trace_collection(entity_guarded, clean_reference_by_query, top_k=config.top_k)
    bridge_recovered = build_recovered_trace_collection(bridge_guarded, clean_reference_by_query, top_k=config.top_k)

    output_dir = config.output_dir()
    write_reranked_traces_jsonl(output_dir / "clean_reranked_traces.jsonl", clean_reranked)
    write_reranked_traces_jsonl(output_dir / "entity_swap_reranked_traces.jsonl", entity_reranked)
    write_reranked_traces_jsonl(output_dir / "bridge_injection_reranked_traces.jsonl", bridge_reranked)
    write_reranked_traces_jsonl(output_dir / "clean_guarded_traces.jsonl", clean_guarded)
    write_reranked_traces_jsonl(output_dir / "entity_swap_guarded_traces.jsonl", entity_guarded)
    write_reranked_traces_jsonl(output_dir / "bridge_injection_guarded_traces.jsonl", bridge_guarded)
    write_reranked_traces_jsonl(output_dir / "clean_recovered_traces.jsonl", clean_recovered)
    write_reranked_traces_jsonl(output_dir / "entity_swap_recovered_traces.jsonl", entity_recovered)
    write_reranked_traces_jsonl(output_dir / "bridge_injection_recovered_traces.jsonl", bridge_recovered)

    clean_metrics = summarize_defense_run(
        name="Clean GraphRAG baseline",
        before_traces=clean_traces,
        reranked_traces=clean_reranked,
        guarded_traces=clean_guarded,
        poisoned_doc_ids_by_query={},
        changed_doc_ids=clean_changed_doc_ids,
        top_k=config.top_k,
    )
    entity_metrics = summarize_defense_run(
        name="Entity Swap",
        before_traces=entity_traces,
        reranked_traces=entity_reranked,
        guarded_traces=entity_guarded,
        poisoned_doc_ids_by_query=entity_poisoned_docs,
        changed_doc_ids=entity_changed_doc_ids,
        top_k=config.top_k,
    )
    bridge_metrics = summarize_defense_run(
        name="Bridge Injection",
        before_traces=bridge_traces,
        reranked_traces=bridge_reranked,
        guarded_traces=bridge_guarded,
        poisoned_doc_ids_by_query=bridge_poisoned_docs,
        changed_doc_ids=bridge_changed_doc_ids,
        top_k=config.top_k,
    )

    write_defense_report(
        config.report_path,
        dataset=config.dataset,
        top_k=config.top_k,
        risk_penalty=config.risk_penalty,
        risk_threshold=config.risk_threshold,
        metrics=[clean_metrics, entity_metrics, bridge_metrics],
        entity_examples=collect_top_risk_examples(entity_reranked, entity_poisoned_docs, limit=5),
        bridge_examples=collect_top_risk_examples(bridge_reranked, bridge_poisoned_docs, limit=5),
    )

    print(
        f"{config.dataset}: "
        f"entity_exposure@{config.top_k} {entity_metrics.before_exposure_at_k:.4f}"
        f"->{entity_metrics.guarded_exposure_at_k:.4f}, "
        f"bridge_exposure@{config.top_k} {bridge_metrics.before_exposure_at_k:.4f}"
        f"->{bridge_metrics.guarded_exposure_at_k:.4f}"
    )


def load_traces_jsonl(path: Path) -> list[RetrievalTrace]:
    """Load retrieval trace JSONL emitted by the lightweight GraphRAG baseline."""

    traces: list[RetrievalTrace] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            traces.append(
                RetrievalTrace(
                    query_id=payload["query_id"],
                    query=payload["query"],
                    answer=payload["answer"],
                    gold_doc_ids=list(payload["gold_doc_ids"]),
                    query_entities=[
                        EntityMention(
                            text=item["text"],
                            normalized=item["normalized"],
                            label=item.get("label", "RULE"),
                        )
                        for item in payload["query_entities"]
                    ],
                    candidates=[
                        PathCandidate(
                            doc_id=item["doc_id"],
                            title=item["title"],
                            score=float(item["score"]),
                            path_nodes=list(item["path_nodes"]),
                            matched_query_entities=list(item["matched_query_entities"]),
                            bridge_entities=list(item["bridge_entities"]),
                        )
                        for item in payload["candidates"]
                    ],
                )
            )
    return traces


def build_recovered_trace_collection(
    guarded_traces: list[RerankedTrace],
    reference_traces_by_query: dict[str, RetrievalTrace],
    top_k: int,
) -> list[RerankedTrace]:
    """Build recovered traces by backfilling from clean reference traces."""

    recovered: list[RerankedTrace] = []
    for guarded in guarded_traces:
        reference_trace = reference_traces_by_query.get(guarded.query_id)
        if reference_trace is None:
            recovered.append(guarded)
            continue
        recovered.append(build_recovered_trace(guarded, reference_trace, top_k=top_k))
    return recovered


def load_poisoned_doc_ids_by_query(path: Path) -> dict[str, set[str]]:
    """Load attack metadata into a query-to-poisoned-doc lookup."""

    poisoned_by_query: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            poisoned_by_query[payload["query_id"]] = set(payload["poisoned_doc_ids"])
    return poisoned_by_query


def load_reference_doc_ids(path: Path) -> set[str]:
    """Load source documents considered present in the trusted reference index."""

    doc_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_ids.add(str(payload["doc_id"]))
    return doc_ids


def load_global_entity_support_counts(path: Path) -> dict[str, int]:
    """Count how many corpus documents mention each normalized entity."""

    entity_to_docs: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_id = str(payload["doc_id"])
            for entity in payload["entities"]:
                normalized = str(entity["normalized"])
                entity_to_docs.setdefault(normalized, set()).add(doc_id)
    return {entity: len(doc_ids) for entity, doc_ids in entity_to_docs.items()}


def load_document_fingerprints(path: Path) -> dict[str, str]:
    """Load stable content fingerprints for corpus documents.

    The loader accepts BEIR-style JSONL records that use `_id`, `title`, and
    `text`. A known document whose fingerprint differs from the reference index
    is treated as a content-integrity risk.
    """

    fingerprints: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_id = str(payload.get("_id", payload.get("doc_id")))
            title = str(payload.get("title", ""))
            text = str(payload.get("text", ""))
            fingerprints[doc_id] = _document_fingerprint(title, text)
    return fingerprints


def find_changed_doc_ids(
    reference_fingerprints: dict[str, str],
    current_fingerprints: dict[str, str],
) -> set[str]:
    """Return known source documents whose current content differs."""

    changed: set[str] = set()
    for doc_id, current_fingerprint in current_fingerprints.items():
        reference_fingerprint = reference_fingerprints.get(doc_id)
        if reference_fingerprint is None:
            continue
        if current_fingerprint != reference_fingerprint:
            changed.add(doc_id)
    return changed


def _document_fingerprint(title: str, text: str) -> str:
    normalized = "\n".join([" ".join(title.split()), " ".join(text.split())])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def calculate_poison_exposure_from_doc_ids(
    traces: list[RetrievalTrace] | list[RerankedTrace],
    poisoned_doc_ids_by_query: dict[str, set[str]],
    top_k: int,
) -> PoisonedEvidenceExposure:
    """Measure whether known poisoned documents appear in targeted top-k."""

    targeted = 0
    exposed = 0
    for trace in traces:
        poisoned_doc_ids = poisoned_doc_ids_by_query.get(trace.query_id)
        if not poisoned_doc_ids:
            continue
        targeted += 1
        retrieved_doc_ids = {candidate.doc_id for candidate in trace.candidates[:top_k]}
        if retrieved_doc_ids.intersection(poisoned_doc_ids):
            exposed += 1
    return PoisonedEvidenceExposure(
        targeted_queries=targeted,
        exposed_queries=exposed,
        exposure_rate=exposed / targeted if targeted else 0.0,
        top_k=top_k,
    )


def summarize_defense_run(
    name: str,
    before_traces: list[RetrievalTrace],
    reranked_traces: list[RerankedTrace],
    guarded_traces: list[RerankedTrace],
    poisoned_doc_ids_by_query: dict[str, set[str]],
    changed_doc_ids: set[str],
    top_k: int,
) -> DefenseRunMetrics:
    before_retrieval = calculate_retrieval_metrics_from_doc_ids(before_traces, top_k=top_k)
    reranked_retrieval = calculate_retrieval_metrics_from_doc_ids(reranked_traces, top_k=top_k)
    guarded_retrieval = calculate_retrieval_metrics_from_doc_ids(guarded_traces, top_k=top_k)
    before_trusted = calculate_trusted_retrieval_metrics_from_doc_ids(
        before_traces,
        top_k=top_k,
        untrusted_doc_ids=changed_doc_ids,
    )
    guarded_trusted = calculate_trusted_retrieval_metrics_from_doc_ids(
        guarded_traces,
        top_k=top_k,
        untrusted_doc_ids=changed_doc_ids,
    )
    before_exposure = (
        calculate_poison_exposure_from_doc_ids(before_traces, poisoned_doc_ids_by_query, top_k=top_k)
        if poisoned_doc_ids_by_query
        else None
    )
    reranked_exposure = (
        calculate_poison_exposure_from_doc_ids(reranked_traces, poisoned_doc_ids_by_query, top_k=top_k)
        if poisoned_doc_ids_by_query
        else None
    )
    guarded_exposure = (
        calculate_poison_exposure_from_doc_ids(guarded_traces, poisoned_doc_ids_by_query, top_k=top_k)
        if poisoned_doc_ids_by_query
        else None
    )
    suppression = calculate_suppression_stats(
        reranked_traces,
        guarded_traces,
        poisoned_doc_ids_by_query,
        changed_doc_ids=changed_doc_ids,
    )
    return DefenseRunMetrics(
        name=name,
        query_count=len(before_traces),
        before_hit_at_k=before_retrieval["hit_at_k"],
        before_gold_recall_at_k=before_retrieval["gold_recall_at_k"],
        reranked_hit_at_k=reranked_retrieval["hit_at_k"],
        reranked_gold_recall_at_k=reranked_retrieval["gold_recall_at_k"],
        guarded_hit_at_k=guarded_retrieval["hit_at_k"],
        guarded_gold_recall_at_k=guarded_retrieval["gold_recall_at_k"],
        before_trusted_hit_at_k=before_trusted["trusted_hit_at_k"],
        before_trusted_gold_recall_at_k=before_trusted["trusted_gold_recall_at_k"],
        guarded_trusted_hit_at_k=guarded_trusted["trusted_hit_at_k"],
        guarded_trusted_gold_recall_at_k=guarded_trusted["trusted_gold_recall_at_k"],
        queries_with_trusted_gold=int(guarded_trusted["queries_with_trusted_gold"]),
        corrupted_gold_doc_count=int(guarded_trusted["corrupted_gold_doc_count"]),
        before_exposure_at_k=before_exposure.exposure_rate if before_exposure else None,
        reranked_exposure_at_k=reranked_exposure.exposure_rate if reranked_exposure else None,
        guarded_exposure_at_k=guarded_exposure.exposure_rate if guarded_exposure else None,
        average_risk=calculate_average_risk(reranked_traces),
        guarded_avg_candidates=guarded_retrieval["avg_candidates"],
        suppressed_candidates=suppression["suppressed_candidates"],
        suppressed_gold_candidates=suppression["suppressed_gold_candidates"],
        suppressed_poisoned_candidates=suppression["suppressed_poisoned_candidates"],
        suppressed_changed_candidates=suppression["suppressed_changed_candidates"],
    )


def calculate_retrieval_metrics_from_doc_ids(
    traces: list[RetrievalTrace] | list[RerankedTrace],
    top_k: int,
) -> dict[str, float]:
    """Calculate retrieval quality from any trace object with doc-id candidates."""

    if not traces:
        return {"hit_at_k": 0.0, "gold_recall_at_k": 0.0, "avg_candidates": 0.0}

    hit_count = 0
    recall_values: list[float] = []
    candidate_counts: list[int] = []
    for trace in traces:
        retrieved_doc_ids = [candidate.doc_id for candidate in trace.candidates[:top_k]]
        gold_doc_ids = set(trace.gold_doc_ids)
        overlap = gold_doc_ids.intersection(retrieved_doc_ids)
        if overlap:
            hit_count += 1
        recall_values.append(len(overlap) / len(gold_doc_ids) if gold_doc_ids else 0.0)
        candidate_counts.append(len(trace.candidates))

    return {
        "hit_at_k": hit_count / len(traces),
        "gold_recall_at_k": sum(recall_values) / len(traces),
        "avg_candidates": sum(candidate_counts) / len(traces),
    }


def calculate_trusted_retrieval_metrics_from_doc_ids(
    traces: list[RetrievalTrace] | list[RerankedTrace],
    top_k: int,
    untrusted_doc_ids: set[str],
) -> dict[str, float]:
    """Calculate recall over gold evidence that remains trusted.

    Changed or otherwise untrusted gold documents are excluded from the recall
    denominator. Queries whose gold set is entirely untrusted are not averaged
    into trusted recall because there is no trusted target evidence to recover.
    """

    trusted_hit_count = 0
    recall_values: list[float] = []
    corrupted_gold_doc_count = 0
    for trace in traces:
        gold_doc_ids = set(trace.gold_doc_ids)
        corrupted_gold_doc_count += len(gold_doc_ids.intersection(untrusted_doc_ids))
        trusted_gold_doc_ids = gold_doc_ids.difference(untrusted_doc_ids)
        if not trusted_gold_doc_ids:
            continue
        retrieved_doc_ids = {candidate.doc_id for candidate in trace.candidates[:top_k]}
        overlap = trusted_gold_doc_ids.intersection(retrieved_doc_ids)
        if overlap:
            trusted_hit_count += 1
        recall_values.append(len(overlap) / len(trusted_gold_doc_ids))

    query_count = len(recall_values)
    return {
        "trusted_hit_at_k": trusted_hit_count / query_count if query_count else 0.0,
        "trusted_gold_recall_at_k": sum(recall_values) / query_count if query_count else 0.0,
        "queries_with_trusted_gold": float(query_count),
        "corrupted_gold_doc_count": float(corrupted_gold_doc_count),
    }


def calculate_average_risk(traces: list[RerankedTrace]) -> float:
    """Average risk over all reranked candidates in a trace collection."""

    risks = [candidate.risk_score for trace in traces for candidate in trace.candidates]
    return sum(risks) / len(risks) if risks else 0.0


def calculate_suppression_stats(
    reranked_traces: list[RerankedTrace],
    guarded_traces: list[RerankedTrace],
    poisoned_doc_ids_by_query: dict[str, set[str]],
    changed_doc_ids: set[str] | None = None,
) -> dict[str, int]:
    """Count which candidates the guarded context removed."""

    guarded_by_query = {trace.query_id: trace for trace in guarded_traces}
    suppressed_candidates = 0
    suppressed_gold_candidates = 0
    suppressed_poisoned_candidates = 0
    suppressed_changed_candidates = 0
    changed_doc_ids = changed_doc_ids or set()

    for reranked in reranked_traces:
        guarded = guarded_by_query.get(reranked.query_id)
        guarded_doc_ids = {candidate.doc_id for candidate in guarded.candidates} if guarded else set()
        gold_doc_ids = set(reranked.gold_doc_ids)
        poisoned_doc_ids = poisoned_doc_ids_by_query.get(reranked.query_id, set())

        for candidate in reranked.candidates:
            if candidate.doc_id in guarded_doc_ids:
                continue
            suppressed_candidates += 1
            if candidate.doc_id in gold_doc_ids:
                suppressed_gold_candidates += 1
            if candidate.doc_id in poisoned_doc_ids:
                suppressed_poisoned_candidates += 1
            if candidate.doc_id in changed_doc_ids:
                suppressed_changed_candidates += 1

    return {
        "suppressed_candidates": suppressed_candidates,
        "suppressed_gold_candidates": suppressed_gold_candidates,
        "suppressed_poisoned_candidates": suppressed_poisoned_candidates,
        "suppressed_changed_candidates": suppressed_changed_candidates,
    }


def write_reranked_traces_jsonl(path: Path, traces: list[RerankedTrace]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace.to_json_dict(), ensure_ascii=False) + "\n")


def collect_top_risk_examples(
    traces: list[RerankedTrace],
    poisoned_doc_ids_by_query: dict[str, set[str]],
    limit: int,
) -> list[dict[str, object]]:
    """Collect compact examples showing how poisoned bridge docs moved."""

    examples: list[dict[str, object]] = []
    for trace in traces:
        poisoned_doc_ids = poisoned_doc_ids_by_query.get(trace.query_id, set())
        for candidate in trace.candidates:
            if candidate.doc_id not in poisoned_doc_ids:
                continue
            examples.append(
                {
                    "query_id": trace.query_id,
                    "doc_id": candidate.doc_id,
                    "original_rank": candidate.original_rank,
                    "new_rank": candidate.new_rank,
                    "base_score": candidate.base_score,
                    "risk_score": candidate.risk_score,
                    "adjusted_score": candidate.adjusted_score,
                    "risk_reasons": candidate.risk_reasons,
                }
            )
    return sorted(examples, key=lambda item: (item["new_rank"], item["query_id"]))[:limit]


def _format_example_rows(examples: list[dict[str, object]]) -> list[str]:
    rows = [
        "| query_id | doc_id | original_rank | new_rank | base | risk | adjusted | reasons |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for example in examples:
        rows.append(
            "| "
            + " | ".join(
                [
                    str(example["query_id"]),
                    str(example["doc_id"]),
                    str(example["original_rank"]),
                    str(example["new_rank"]),
                    f"{float(example['base_score']):.4f}",
                    f"{float(example['risk_score']):.4f}",
                    f"{float(example['adjusted_score']):.4f}",
                    ", ".join(str(reason) for reason in example["risk_reasons"]),
                ]
            )
            + " |"
        )
    return rows


def write_defense_report(
    path: Path,
    dataset: str,
    top_k: int,
    risk_penalty: float,
    risk_threshold: float,
    metrics: list[DefenseRunMetrics],
    entity_examples: list[dict[str, object]],
    bridge_examples: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metric_rows = [
        "| run | exposure before | exposure reranked | exposure guarded | hit before | hit guarded | recall before | recall guarded | trusted recall before | trusted recall guarded | corrupted gold | suppressed | suppressed gold | suppressed poisoned | suppressed changed | guarded avg candidates |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in metrics:
        metric_rows.append(
            "| "
            + " | ".join(
                [
                    item.name,
                    _format_optional_float(item.before_exposure_at_k),
                    _format_optional_float(item.reranked_exposure_at_k),
                    _format_optional_float(item.guarded_exposure_at_k),
                    f"{item.before_hit_at_k:.4f}",
                    f"{item.guarded_hit_at_k:.4f}",
                    f"{item.before_gold_recall_at_k:.4f}",
                    f"{item.guarded_gold_recall_at_k:.4f}",
                    f"{item.before_trusted_gold_recall_at_k:.4f}",
                    f"{item.guarded_trusted_gold_recall_at_k:.4f}",
                    str(item.corrupted_gold_doc_count),
                    str(item.suppressed_candidates),
                    str(item.suppressed_gold_candidates),
                    str(item.suppressed_poisoned_candidates),
                    str(item.suppressed_changed_candidates),
                    f"{item.guarded_avg_candidates:.2f}",
                ]
            )
            + " |"
        )

    entity_example_rows = _format_example_rows(entity_examples)
    bridge_example_rows = _format_example_rows(bridge_examples)

    content = "\n".join(
        [
            f"# LogicGuard MVP Report: {dataset}",
            "",
            "## Run Configuration",
            "",
            f"- Top-k: `{top_k}`",
            f"- Risk penalty: `{risk_penalty:.2f}`",
            f"- Guarded risk threshold: `{risk_threshold:.2f}`",
            "",
            "## Before/After Metrics",
            "",
            *metric_rows,
            "",
            "## Entity Swap Poisoned Examples",
            "",
            *entity_example_rows,
            "",
            "## Bridge Injection Poisoned Examples",
            "",
            *bridge_example_rows,
            "",
            "## Interpretation",
            "",
            "This MVP first reranks retrieved candidates with a transparent path-risk penalty, then builds "
            "a guarded context by suppressing candidates whose risk reaches the configured threshold. It is "
            "offline, so it does not change graph construction or the original GraphRAG baseline.",
            "",
            "The current BridgeRisk signal no longer depends on local doc-id shape such as a `poison_` prefix "
            "or a non-numeric id. It compares candidates against a reference corpus entity cache and marks "
            "documents absent from that reference index as unseen source documents.",
            "",
            "The Entity Swap signal compares current known-source document fingerprints against a reference "
            "corpus snapshot. A known document whose content changed is marked as `reference_content_mismatch` "
            "and withheld from the guarded context. When a poisoned document is also a benchmark gold support "
            "document, nominal gold recall can decrease even though the removed evidence is corrupted.",
            "",
            "`trusted recall` excludes changed/corrupted gold support documents from the recall denominator. "
            "`corrupted gold` counts gold evidence occurrences across queries, not unique document ids.",
            "",
            "The reranked exposure column measures rank-only movement inside the retrieved candidate list. "
            "The guarded exposure column measures the final context after high-risk candidates are withheld. "
            "Suppressed poisoned counts only attack-metadata target documents; suppressed can be larger when "
            "injected bridge documents also appear for non-target queries.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _format_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LogicGuard MVP reranking evaluation.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicguard_mvp.yaml"),
        help="Path to the LogicGuard MVP YAML config.",
    )
    args = parser.parse_args()
    run_from_config(LogicGuardRunConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
