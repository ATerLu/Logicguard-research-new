"""Command-line entry point for NaiveRAG retrieval experiments.

The runner mirrors `logicguard.graph.run_baseline` so the two retrieval
families can be launched with the same mental model:

1. read a YAML config,
2. load normalized samples and the full raw corpus,
3. run one retrieval mode,
4. write trace JSONL plus a Chinese Markdown report.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.schemas import CorpusDocument
from logicguard.data.loader import DatasetPaths, load_raw_dataset
from logicguard.data.prepare import load_normalized_samples
from logicguard.naive_rag.baseline import (
    NaiveRagMode,
    NaiveRagOutputPaths,
    load_sentence_transformer_encoder,
    run_naive_rag_baseline,
)


@dataclass(frozen=True, slots=True)
class NaiveRagConfig:
    """Configuration for one NaiveRAG baseline run."""

    dataset: str
    raw_data_root: Path
    sample_path: Path
    corpus_path: Path | None
    output_root: Path
    report_root: Path
    run_name: str
    mode: NaiveRagMode
    top_k: int
    bm25_weight: float = 0.5
    dense_weight: float = 0.5
    encoder_model: str | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "NaiveRagConfig":
        """Load config with paths relative to the LogicGuard project root."""

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
        mode = str(payload.get("mode", "bm25")).lower()
        if mode not in {"bm25", "dense", "hybrid"}:
            raise ValueError(f"Unsupported NaiveRAG mode in {path}: {mode}")

        return cls(
            dataset=str(payload["dataset"]),
            raw_data_root=resolve_project_path(payload["raw_data_root"]),
            sample_path=sample_path,
            corpus_path=(
                resolve_project_path(str(payload["corpus_path"]))
                if payload.get("corpus_path")
                else None
            ),
            output_root=resolve_project_path(payload["output_root"]),
            report_root=resolve_project_path(payload["report_root"]),
            run_name=str(payload.get("run_name", sample_path.stem)),
            mode=cast(NaiveRagMode, mode),
            top_k=int(payload.get("top_k", 10)),
            bm25_weight=float(payload.get("bm25_weight", 0.5)),
            dense_weight=float(payload.get("dense_weight", 0.5)),
            encoder_model=payload.get("encoder_model"),
        )

    def output_paths(self) -> NaiveRagOutputPaths:
        """Derive mode-specific output locations from the run configuration."""

        report_run_name = f"{self.mode}_{self.dataset}_{self.run_name}"
        return NaiveRagOutputPaths(
            trace_path=self.output_root
            / self.mode
            / self.dataset
            / f"{self.run_name}_traces.jsonl",
            report_path=self.report_root / f"naive_rag_{report_run_name}.md",
        )


def run_from_config(config: NaiveRagConfig) -> dict[str, object]:
    """Run one NaiveRAG experiment and print a compact console summary."""

    samples = load_normalized_samples(config.sample_path)
    if config.corpus_path:
        corpus_documents = _load_corpus_documents(config.corpus_path)
    else:
        raw_dataset = load_raw_dataset(
            DatasetPaths.from_root(config.raw_data_root, config.dataset)
        )
        corpus_documents = list(raw_dataset.corpus.values())
    encoder = None
    if config.mode in {"dense", "hybrid"}:
        encoder = (
            load_sentence_transformer_encoder(config.encoder_model)
            if config.encoder_model
            else load_sentence_transformer_encoder()
        )

    summary = run_naive_rag_baseline(
        dataset_name=config.dataset,
        samples=samples,
        corpus_documents=corpus_documents,
        outputs=config.output_paths(),
        mode=config.mode,
        top_k=config.top_k,
        encoder=encoder,
        bm25_weight=config.bm25_weight,
        dense_weight=config.dense_weight,
    )
    print(
        f"{summary['dataset']}: mode={summary['mode']}, "
        f"queries={summary['query_count']}, "
        f"hit@{summary['top_k']}={summary['hit_at_k']:.4f}, "
        f"gold_recall@{summary['top_k']}={summary['gold_recall_at_k']:.4f}"
    )
    return summary


def _load_corpus_documents(path: Path) -> list[CorpusDocument]:
    """Load a clean or poisoned corpus JSONL file.

    LogicPoison raw corpora and our generated poisoned corpora use `_id`,
    `title`, and `text`. The fallback `doc_id` key keeps this helper compatible
    with any future project-native corpus export.
    """

    documents: list[CorpusDocument] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            doc_id = payload.get("_id", payload.get("doc_id"))
            if doc_id is None:
                raise ValueError(f"Missing document id in {path} at line {line_number}")
            documents.append(
                CorpusDocument(
                    doc_id=str(doc_id),
                    title=str(payload.get("title", "")),
                    text=str(payload["text"]),
                )
            )
    if not documents:
        raise ValueError(f"Corpus file is empty: {path}")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a NaiveRAG retrieval baseline.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/naive_rag_bm25_2wiki_full_500.yaml"),
        help="Path to the NaiveRAG YAML config.",
    )
    args = parser.parse_args()
    run_from_config(NaiveRagConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
