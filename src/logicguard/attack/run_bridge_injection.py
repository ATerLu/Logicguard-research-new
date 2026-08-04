"""Command-line runner for controlled Bridge Injection experiments."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.attack.bridge_injection import (
    apply_bridge_injection_attacks,
    calculate_bridge_injection_exposure,
    collect_bridge_injection_hit_details,
    select_bridge_injection_attacks,
    write_bridge_attacks_jsonl,
    write_bridge_corpus_jsonl,
)
from logicguard.attack.schemas import BridgeInjectionHitDetail, PoisonedEvidenceExposure
from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import load_normalized_samples
from logicguard.graph.baseline import (
    BaselineOutputPaths,
    BaselineRunSummary,
    run_graphrag_baseline,
)
from logicguard.graph.entities import RuleBasedEntityExtractor
from logicguard.graph.schemas import RetrievalTrace


@dataclass(frozen=True, slots=True)
class BridgeInjectionRunConfig:
    """Configuration for one controlled Bridge Injection run."""

    dataset: str
    raw_data_root: Path
    sample_path: Path
    output_root: Path
    report_root: Path
    run_name: str
    max_attacks: int
    top_k: int
    max_depth: int

    @classmethod
    def from_yaml(cls, path: Path) -> "BridgeInjectionRunConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        sample_path = resolve_project_path(payload["sample_path"])
        return cls(
            dataset=str(payload["dataset"]),
            raw_data_root=resolve_project_path(payload["raw_data_root"]),
            sample_path=sample_path,
            output_root=resolve_project_path(payload["output_root"]),
            report_root=resolve_project_path(payload["report_root"]),
            run_name=str(payload.get("run_name", sample_path.stem)),
            max_attacks=int(payload.get("max_attacks", 20)),
            top_k=int(payload.get("top_k", 10)),
            max_depth=int(payload.get("max_depth", 3)),
        )

    def metadata_path(self) -> Path:
        return self.output_root / self.dataset / "bridge_injection_metadata.jsonl"

    def poisoned_corpus_path(self) -> Path:
        return self.output_root / self.dataset / "bridge_poisoned_corpus.jsonl"

    def baseline_outputs(self) -> BaselineOutputPaths:
        base = self.output_root / self.dataset
        return BaselineOutputPaths(
            trace_path=base / f"bridge_poisoned_{self.run_name}_traces.jsonl",
            corpus_entity_cache_path=base / "bridge_poisoned_corpus_entities.jsonl",
            query_entity_cache_path=base
            / f"bridge_poisoned_{self.run_name}_query_entities.jsonl",
            report_path=self.report_root
            / f"bridge_injection_baseline_{self.dataset}_{self.run_name}.md",
        )

    def exposure_report_path(self) -> Path:
        return (
            self.report_root
            / f"bridge_injection_exposure_{self.dataset}_{self.run_name}.md"
        )


def run_from_config(config: BridgeInjectionRunConfig) -> None:
    raw_dataset = load_raw_dataset(
        DatasetPaths.from_root(config.raw_data_root, config.dataset)
    )
    samples = load_normalized_samples(config.sample_path)
    extractor = RuleBasedEntityExtractor()
    attacks = select_bridge_injection_attacks(
        samples, extractor, max_attacks=config.max_attacks
    )
    poisoned_corpus = apply_bridge_injection_attacks(
        list(raw_dataset.corpus.values()), attacks
    )

    write_bridge_attacks_jsonl(config.metadata_path(), attacks)
    write_bridge_corpus_jsonl(config.poisoned_corpus_path(), poisoned_corpus)

    summary = run_graphrag_baseline(
        dataset_name=config.dataset,
        samples=samples,
        corpus_documents=poisoned_corpus,
        outputs=config.baseline_outputs(),
        top_k=config.top_k,
        max_depth=config.max_depth,
    )
    traces = _load_traces(config.baseline_outputs().trace_path)
    exposure = calculate_bridge_injection_exposure(traces, attacks, top_k=config.top_k)
    hit_details = collect_bridge_injection_hit_details(
        traces, attacks, top_k=config.top_k
    )
    _write_exposure_report(
        config.exposure_report_path(),
        summary,
        exposure,
        attack_count=len(attacks),
        hit_details=hit_details,
    )

    print(
        f"{config.dataset}: bridge_attacks={len(attacks)}, "
        f"bridge_exposure@{config.top_k}={exposure.exposure_rate:.4f}, "
        f"hit@{config.top_k}={summary.hit_at_k:.4f}"
    )


def _load_traces(path: Path) -> list[RetrievalTrace]:
    """Load trace JSONL into RetrievalTrace objects for exposure metrics."""

    from logicguard.graph.schemas import EntityMention, PathCandidate

    traces: list[RetrievalTrace] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
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


def _write_exposure_report(
    path: Path,
    summary: BaselineRunSummary,
    exposure: PoisonedEvidenceExposure,
    attack_count: int,
    hit_details: list[BridgeInjectionHitDetail],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exposed_details = [
        detail
        for detail in hit_details
        if detail.exposed and detail.first_rank is not None
    ]
    rank_counts = Counter(detail.first_rank for detail in exposed_details)
    avg_rank = (
        sum(
            detail.first_rank
            for detail in exposed_details
            if detail.first_rank is not None
        )
        / len(exposed_details)
        if exposed_details
        else 0.0
    )
    rank_distribution = ", ".join(
        f"rank {rank}: {count}"
        for rank, count in sorted(rank_counts.items())
        if rank is not None
    )
    if not rank_distribution:
        rank_distribution = "none"

    content = "\n".join(
        [
            f"# Bridge Injection Exposure Report: {summary.dataset}",
            "",
            "## Attack Setup",
            "",
            "- Attack type: `Bridge Injection`",
            f"- Attack metadata rows: `{attack_count}`",
            f"- Top-k evaluated: `{exposure.top_k}`",
            "",
            "## Exposure Metrics",
            "",
            f"- Targeted queries: `{exposure.targeted_queries}`",
            f"- Exposed queries: `{exposure.exposed_queries}`",
            f"- bridge_poisoned_exposure@{exposure.top_k}: `{exposure.exposure_rate:.4f}`",
            "",
            "## Bridge Rank Details",
            "",
            f"- exposed@rank1: `{rank_counts.get(1, 0)}`",
            f"- average first poisoned rank: `{avg_rank:.2f}`",
            f"- first-rank distribution: `{rank_distribution}`",
            "",
            "## Retrieval Context",
            "",
            f"- hit@{summary.top_k}: `{summary.hit_at_k:.4f}`",
            f"- gold_recall@{summary.top_k}: `{summary.gold_recall_at_k:.4f}`",
            f"- average candidates/query: `{summary.avg_candidates:.2f}`",
            "",
            "## Exposed Examples",
            "",
            *_format_hit_examples(exposed_details, limit=5),
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def _format_hit_examples(
    details: list[BridgeInjectionHitDetail], limit: int
) -> list[str]:
    """Render a compact markdown table with the strongest exposed examples."""

    if not details:
        return [
            "No injected bridge documents were retrieved in the evaluated top-k window."
        ]

    rows = [
        "| attack_id | query_id | bridge_doc | first_rank | query_entity | replacement_answer | score |",
        "| --- | --- | --- | ---: | --- | --- | ---: |",
    ]
    for detail in sorted(
        details, key=lambda item: (item.first_rank or 9999, item.attack_id)
    )[:limit]:
        score = detail.retrieved_score if detail.retrieved_score is not None else 0.0
        rows.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(detail.attack_id),
                    _markdown_cell(detail.query_id),
                    _markdown_cell(detail.poisoned_doc_id),
                    str(detail.first_rank),
                    _markdown_cell(detail.query_entity),
                    _markdown_cell(detail.replacement_answer),
                    f"{score:.4f}",
                ]
            )
            + " |"
        )
    return rows


def _markdown_cell(value: str) -> str:
    """Keep generated markdown tables valid when dataset text contains pipes."""

    return value.replace("|", "\\|")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run controlled Bridge Injection poisoning."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/bridge_injection_attack.yaml"),
        help="Path to the Bridge Injection YAML config.",
    )
    args = parser.parse_args()
    run_from_config(BridgeInjectionRunConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
