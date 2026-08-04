"""Prepare small official Microsoft GraphRAG local-query defense corpora.

The official GraphRAG indexer is much more expensive than the lightweight
LogicGuard simulators, so this module builds a narrow but auditable pilot set:
queries where LogicPoison removed the gold answer surface from at least one
support document while another support document remains unchanged. Those cases
let us compare four conditions with clear semantics:

* clean: all gold support documents from the clean corpus;
* poisoned: all gold support documents from the poisoned corpus;
* guarded: only support documents that LogicPoison did not change;
* recovered: all gold support documents restored from the clean corpus.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.ms_graphrag.prepare_workspace import _stable_doc_sort_key


@dataclass(frozen=True, slots=True)
class LocalDefenseDataConfig:
    """Configuration for deriving official GraphRAG defense corpora."""

    dataset: str
    sample_path: Path
    clean_corpus_path: Path
    poisoned_corpus_path: Path
    query_integrity_path: Path
    output_sample_path: Path
    variant_corpus_root: Path
    manifest_path: Path
    max_queries: int = 1

    @classmethod
    def from_yaml(cls, path: Path) -> "LocalDefenseDataConfig":
        """Load YAML configuration with project-relative paths."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve_project_path(payload["sample_path"]),
            clean_corpus_path=resolve_project_path(payload["clean_corpus_path"]),
            poisoned_corpus_path=resolve_project_path(payload["poisoned_corpus_path"]),
            query_integrity_path=resolve_project_path(payload["query_integrity_path"]),
            output_sample_path=resolve_project_path(payload["output_sample_path"]),
            variant_corpus_root=resolve_project_path(payload["variant_corpus_root"]),
            manifest_path=resolve_project_path(payload["manifest_path"]),
            max_queries=int(payload.get("max_queries", 1)),
        )


def prepare_local_defense_data(config: LocalDefenseDataConfig) -> dict[str, Any]:
    """Create selected samples and four condition-specific corpus files."""

    if config.max_queries < 1:
        raise ValueError("max_queries must be positive")

    samples = load_normalized_samples(config.sample_path)
    integrity_by_query = _load_query_integrity(config.query_integrity_path)
    clean_corpus = _load_corpus_rows(config.clean_corpus_path)
    poisoned_corpus = _load_corpus_rows(config.poisoned_corpus_path)

    selected = _select_strong_samples(
        samples=samples,
        integrity_by_query=integrity_by_query,
        max_queries=config.max_queries,
    )
    if not selected:
        raise ValueError("No suitable local-defense samples found")

    support_ids = _collect_support_ids(selected)
    changed_ids = {
        str(doc_id)
        for sample in selected
        for doc_id in integrity_by_query[sample.query_id].get(
            "changed_support_doc_ids", []
        )
    }
    trusted_ids = support_ids - changed_ids

    variant_rows = {
        "clean": _collect_corpus_subset(clean_corpus, support_ids),
        "poisoned": _collect_corpus_subset(poisoned_corpus, support_ids),
        "guarded": _collect_corpus_subset(poisoned_corpus, trusted_ids),
        "recovered": _collect_corpus_subset(clean_corpus, support_ids),
    }

    _write_samples(config.output_sample_path, selected)
    corpus_paths: dict[str, str] = {}
    for variant_name, rows in variant_rows.items():
        corpus_path = config.variant_corpus_root / variant_name / "corpus.jsonl"
        _write_corpus_rows(corpus_path, rows)
        corpus_paths[variant_name] = str(corpus_path.resolve())

    manifest = {
        "dataset": config.dataset,
        "source_sample_path": str(config.sample_path.resolve()),
        "source_clean_corpus_path": str(config.clean_corpus_path.resolve()),
        "source_poisoned_corpus_path": str(config.poisoned_corpus_path.resolve()),
        "query_integrity_path": str(config.query_integrity_path.resolve()),
        "output_sample_path": str(config.output_sample_path.resolve()),
        "variant_corpus_paths": corpus_paths,
        "selected_query_count": len(selected),
        "selected_query_ids": [sample.query_id for sample in selected],
        "support_doc_count": len(support_ids),
        "changed_support_doc_count": len(changed_ids),
        "trusted_support_doc_count": len(trusted_ids),
        "support_doc_ids": sorted(support_ids, key=_stable_doc_sort_key),
        "changed_support_doc_ids": sorted(changed_ids, key=_stable_doc_sort_key),
        "trusted_support_doc_ids": sorted(trusted_ids, key=_stable_doc_sort_key),
        "selection_rule": (
            "answer_surface_loss=true, at least one changed support document, "
            "and at least one trusted support document"
        ),
        "variant_semantics": {
            "clean": "clean corpus versions of all selected gold support documents",
            "poisoned": "LogicPoison corpus versions of all selected gold support documents",
            "guarded": "LogicPoison corpus versions of only unchanged/trusted support documents",
            "recovered": "clean corpus versions of all selected gold support documents, simulating recovery",
        },
    }
    config.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    config.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _select_strong_samples(
    *,
    samples: list[NormalizedSample],
    integrity_by_query: dict[str, dict[str, Any]],
    max_queries: int,
) -> list[NormalizedSample]:
    """Select samples where guarded and recovered conditions are meaningful."""

    selected: list[NormalizedSample] = []
    for sample in samples:
        integrity = integrity_by_query.get(sample.query_id)
        if integrity is None:
            continue
        support_ids = {str(doc_id) for doc_id in sample.support_doc_ids}
        changed_ids = {
            str(doc_id) for doc_id in integrity.get("changed_support_doc_ids", [])
        }
        trusted_ids = support_ids - changed_ids
        if integrity.get("answer_surface_loss") is True and changed_ids and trusted_ids:
            selected.append(sample)
        if len(selected) >= max_queries:
            break
    return selected


def _collect_support_ids(samples: list[NormalizedSample]) -> set[str]:
    return {str(doc_id) for sample in samples for doc_id in sample.support_doc_ids}


def _load_query_integrity(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            query_id = row.get("query_id")
            if query_id is None:
                raise ValueError(f"Missing query_id in {path} at line {line_number}")
            rows[str(query_id)] = row
    return rows


def _load_corpus_rows(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            doc_id = row.get("_id", row.get("doc_id"))
            if doc_id is None:
                raise ValueError(f"Missing document id in {path} at line {line_number}")
            rows[str(doc_id)] = {
                "_id": str(doc_id),
                "title": str(row.get("title", "")),
                "text": str(row["text"]),
            }
    return rows


def _collect_corpus_subset(
    corpus: dict[str, dict[str, str]], doc_ids: set[str]
) -> list[dict[str, str]]:
    missing_ids = sorted(
        (doc_id for doc_id in doc_ids if doc_id not in corpus), key=_stable_doc_sort_key
    )
    if missing_ids:
        raise ValueError(f"Corpus is missing required documents: {missing_ids}")
    return [corpus[doc_id] for doc_id in sorted(doc_ids, key=_stable_doc_sort_key)]


def _write_samples(path: Path, samples: list[NormalizedSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_json_dict(), ensure_ascii=False) + "\n")


def _write_corpus_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare Microsoft GraphRAG local defense corpora."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_local_defense_data_stage10.yaml"),
    )
    args = parser.parse_args()
    manifest = prepare_local_defense_data(LocalDefenseDataConfig.from_yaml(args.config))
    print(
        f"{manifest['dataset']}: selected_queries={manifest['selected_query_count']}, "
        f"support_docs={manifest['support_doc_count']}, "
        f"changed={manifest['changed_support_doc_count']}, trusted={manifest['trusted_support_doc_count']}"
    )


if __name__ == "__main__":
    main()
