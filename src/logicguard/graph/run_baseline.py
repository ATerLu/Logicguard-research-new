"""Command-line entry point for the lightweight GraphRAG baseline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import yaml

from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import load_normalized_samples
from logicguard.graph.baseline import BaselineOutputPaths, run_graphrag_baseline


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """Configuration for one baseline run."""

    dataset: str
    raw_data_root: Path
    sample_path: Path
    output_root: Path
    report_root: Path
    run_name: str
    top_k: int
    max_depth: int

    @classmethod
    def from_yaml(cls, path: Path) -> "BaselineConfig":
        """Load baseline config with paths relative to the project root."""

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
            top_k=int(payload.get("top_k", 10)),
            max_depth=int(payload.get("max_depth", 3)),
        )

    def output_paths(self) -> BaselineOutputPaths:
        """Derive all output locations from the run configuration."""

        report_run_name = f"{self.dataset}_{self.run_name}"
        return BaselineOutputPaths(
            trace_path=self.output_root / self.dataset / f"{self.run_name}_traces.jsonl",
            corpus_entity_cache_path=self.output_root / self.dataset / "corpus_entities.jsonl",
            query_entity_cache_path=self.output_root / self.dataset / f"{self.run_name}_query_entities.jsonl",
            report_path=self.report_root / f"graphrag_baseline_{report_run_name}.md",
        )


def run_from_config(config: BaselineConfig) -> None:
    """Run baseline from config and print a compact summary."""

    raw_dataset = load_raw_dataset(DatasetPaths.from_root(config.raw_data_root, config.dataset))
    samples = load_normalized_samples(config.sample_path)
    summary = run_graphrag_baseline(
        dataset_name=config.dataset,
        samples=samples,
        corpus_documents=list(raw_dataset.corpus.values()),
        outputs=config.output_paths(),
        top_k=config.top_k,
        max_depth=config.max_depth,
    )
    print(
        f"{summary.dataset}: queries={summary.query_count}, "
        f"hit@{summary.top_k}={summary.hit_at_k:.4f}, "
        f"gold_recall@{summary.top_k}={summary.gold_recall_at_k:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the lightweight GraphRAG baseline.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/graphrag_baseline.yaml"),
        help="Path to the baseline YAML config.",
    )
    args = parser.parse_args()
    run_from_config(BaselineConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
