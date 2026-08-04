"""Runner for answer-aware Bridge Injection v2 experiments.

This runner is for controlled, local benchmark evaluation only. It produces
synthetic documents that are more useful for answer-stage LLM experiments than
the v1 bridge docs, while keeping outputs separate from the original attack.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.attack.bridge_injection import (
    apply_answer_aware_bridge_injection_attacks,
    calculate_bridge_injection_exposure,
    collect_bridge_injection_hit_details,
    select_answer_aware_bridge_injection_attacks,
    write_bridge_attacks_jsonl,
    write_bridge_corpus_jsonl,
)
from logicguard.attack.run_bridge_injection import _load_traces, _write_exposure_report
from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import load_normalized_samples
from logicguard.graph.baseline import BaselineOutputPaths, run_graphrag_baseline
from logicguard.graph.entities import RuleBasedEntityExtractor


@dataclass(frozen=True, slots=True)
class AnswerAwareBridgeInjectionRunConfig:
    """Configuration for one answer-aware Bridge Injection v2 run."""

    dataset: str
    raw_data_root: Path
    sample_path: Path
    output_root: Path
    report_root: Path
    run_name: str
    max_attacks: int
    top_k: int
    max_depth: int
    template_style: str

    @classmethod
    def from_yaml(cls, path: Path) -> "AnswerAwareBridgeInjectionRunConfig":
        """Load v2 config with paths relative to the project root."""

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
            template_style=str(payload.get("template_style", "explicit")),
        )

    def metadata_path(self) -> Path:
        return self.output_root / self.dataset / "bridge_injection_v2_metadata.jsonl"

    def poisoned_corpus_path(self) -> Path:
        return (
            self.output_root
            / self.dataset
            / "answer_aware_bridge_poisoned_corpus.jsonl"
        )

    def baseline_outputs(self) -> BaselineOutputPaths:
        base = self.output_root / self.dataset
        return BaselineOutputPaths(
            trace_path=base
            / f"answer_aware_bridge_poisoned_{self.run_name}_traces.jsonl",
            corpus_entity_cache_path=base
            / "answer_aware_bridge_poisoned_corpus_entities.jsonl",
            query_entity_cache_path=base
            / f"answer_aware_bridge_poisoned_{self.run_name}_query_entities.jsonl",
            report_path=self.report_root
            / f"bridge_injection_v2_baseline_{self.dataset}_{self.run_name}.md",
        )

    def exposure_report_path(self) -> Path:
        style_segment = (
            "" if self.template_style == "explicit" else f"_{self.template_style}"
        )
        return (
            self.report_root
            / f"bridge_injection_v2{style_segment}_exposure_{self.dataset}_{self.run_name}.md"
        )


def run_from_config(config: AnswerAwareBridgeInjectionRunConfig) -> None:
    """Generate answer-aware bridge docs, rerun baseline, and write exposure report."""

    raw_dataset = load_raw_dataset(
        DatasetPaths.from_root(config.raw_data_root, config.dataset)
    )
    samples = load_normalized_samples(config.sample_path)
    extractor = RuleBasedEntityExtractor()
    attacks = select_answer_aware_bridge_injection_attacks(
        samples, extractor, max_attacks=config.max_attacks
    )
    poisoned_corpus = apply_answer_aware_bridge_injection_attacks(
        list(raw_dataset.corpus.values()),
        attacks,
        template_style=config.template_style,
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
        f"{config.dataset}: answer_aware_bridge_attacks={len(attacks)}, "
        f"bridge_v2_exposure@{config.top_k}={exposure.exposure_rate:.4f}, "
        f"hit@{config.top_k}={summary.hit_at_k:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run answer-aware Bridge Injection v2 poisoning."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/bridge_injection_v2_debug.yaml"),
        help="Path to the Bridge Injection v2 YAML config.",
    )
    args = parser.parse_args()
    run_from_config(AnswerAwareBridgeInjectionRunConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
