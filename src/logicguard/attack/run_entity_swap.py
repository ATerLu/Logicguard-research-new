"""Command-line runner for controlled Entity Swap poisoning experiments."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.attack.entity_swap import (
    apply_entity_swap_attacks,
    calculate_poisoned_evidence_exposure,
    select_entity_swap_attacks,
    write_attacks_jsonl,
    write_poisoned_corpus_jsonl,
)
from logicguard.attack.schemas import PoisonedEvidenceExposure
from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import load_normalized_samples
from logicguard.graph.baseline import BaselineOutputPaths, BaselineRunSummary, run_graphrag_baseline
from logicguard.graph.schemas import RetrievalTrace


@dataclass(frozen=True, slots=True)
class EntitySwapRunConfig:
    """Configuration for one controlled Entity Swap run."""

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
    def from_yaml(cls, path: Path) -> "EntitySwapRunConfig":
        project_root = path.resolve().parents[1]
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
        return self.output_root / self.dataset / "entity_swap_metadata.jsonl"

    def poisoned_corpus_path(self) -> Path:
        return self.output_root / self.dataset / "poisoned_corpus.jsonl"

    def baseline_outputs(self) -> BaselineOutputPaths:
        base = self.output_root / self.dataset
        return BaselineOutputPaths(
            trace_path=base / f"poisoned_{self.run_name}_traces.jsonl",
            corpus_entity_cache_path=base / "poisoned_corpus_entities.jsonl",
            query_entity_cache_path=base / f"poisoned_{self.run_name}_query_entities.jsonl",
            report_path=self.report_root / f"entity_swap_baseline_{self.dataset}_{self.run_name}.md",
        )

    def exposure_report_path(self) -> Path:
        return self.report_root / f"entity_swap_exposure_{self.dataset}_{self.run_name}.md"


def run_from_config(config: EntitySwapRunConfig) -> None:
    raw_dataset = load_raw_dataset(DatasetPaths.from_root(config.raw_data_root, config.dataset))
    samples = load_normalized_samples(config.sample_path)
    attacks = select_entity_swap_attacks(samples, max_attacks=config.max_attacks)
    poisoned_corpus = apply_entity_swap_attacks(list(raw_dataset.corpus.values()), attacks)

    write_attacks_jsonl(config.metadata_path(), attacks)
    write_poisoned_corpus_jsonl(config.poisoned_corpus_path(), poisoned_corpus)

    summary = run_graphrag_baseline(
        dataset_name=config.dataset,
        samples=samples,
        corpus_documents=list(poisoned_corpus.values()),
        outputs=config.baseline_outputs(),
        top_k=config.top_k,
        max_depth=config.max_depth,
    )
    traces = _load_traces(config.baseline_outputs().trace_path)
    exposure = calculate_poisoned_evidence_exposure(traces, attacks, top_k=config.top_k)
    _write_exposure_report(config.exposure_report_path(), summary, exposure, attack_count=len(attacks))

    print(
        f"{config.dataset}: attacks={len(attacks)}, "
        f"poisoned_exposure@{config.top_k}={exposure.exposure_rate:.4f}, "
        f"hit@{config.top_k}={summary.hit_at_k:.4f}"
    )


def _load_traces(path: Path) -> list[RetrievalTrace]:
    """Load only fields needed by exposure evaluation.

    The trace schema is richer than this runner needs. Rehydrating the full
    dataclass keeps the exposure function tested against real trace objects.
    """

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
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"# Entity Swap Exposure Report: {summary.dataset}",
            "",
            "## Attack Setup",
            "",
            "- Attack type: `Entity Swap`",
            f"- Attack metadata rows: `{attack_count}`",
            f"- Top-k evaluated: `{exposure.top_k}`",
            "",
            "## Exposure Metrics",
            "",
            f"- Targeted queries: `{exposure.targeted_queries}`",
            f"- Exposed queries: `{exposure.exposed_queries}`",
            f"- poisoned_evidence_exposure@{exposure.top_k}: `{exposure.exposure_rate:.4f}`",
            "",
            "## Retrieval Context",
            "",
            f"- hit@{summary.top_k}: `{summary.hit_at_k:.4f}`",
            f"- gold_recall@{summary.top_k}: `{summary.gold_recall_at_k:.4f}`",
            f"- average candidates/query: `{summary.avg_candidates:.2f}`",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run controlled Entity Swap poisoning.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/entity_swap_attack.yaml"),
        help="Path to the Entity Swap YAML config.",
    )
    args = parser.parse_args()
    run_from_config(EntitySwapRunConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
