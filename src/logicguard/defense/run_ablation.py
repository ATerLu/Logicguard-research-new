"""Ablation evaluation for LogicGuard defense signals.

The main threshold scan reports the full LogicGuard MVP. This module answers a
different question: which risk signal is responsible for blocking which attack?
It reuses existing full_500 traces and evaluates a small set of fixed defense
modes under the same threshold setting.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.defense.reranker import build_guarded_trace, rerank_trace
from logicguard.defense.run_logicguard import (
    find_changed_doc_ids,
    load_document_fingerprints,
    load_global_entity_support_counts,
    load_poisoned_doc_ids_by_query,
    load_reference_doc_ids,
    load_traces_jsonl,
    summarize_defense_run,
)
from logicguard.defense.schemas import RerankedCandidate, RerankedTrace
from logicguard.graph.schemas import RetrievalTrace


ABLATION_MODES = ("none", "provenance_only", "content_integrity_only", "full")


@dataclass(frozen=True, slots=True)
class AblationConfig:
    """Configuration for a fixed-threshold multi-dataset ablation run."""

    datasets: list[str]
    run_name: str
    raw_data_root: Path
    baseline_output_root: Path
    entity_swap_output_root: Path
    bridge_injection_output_root: Path
    output_root: Path
    report_path: Path
    modes: list[str]
    top_k: int
    risk_penalty: float
    risk_threshold: float

    @classmethod
    def from_yaml(cls, path: Path) -> "AblationConfig":
        """Load ablation config with project-relative paths."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        modes = [str(mode) for mode in payload.get("modes", ABLATION_MODES)]
        unknown_modes = sorted(set(modes).difference(ABLATION_MODES))
        if unknown_modes:
            raise ValueError(f"Unknown ablation modes: {unknown_modes}")

        return cls(
            datasets=[str(dataset) for dataset in payload["datasets"]],
            run_name=str(payload.get("run_name", "full_500")),
            raw_data_root=resolve_project_path(payload["raw_data_root"]),
            baseline_output_root=resolve_project_path(payload["baseline_output_root"]),
            entity_swap_output_root=resolve_project_path(
                payload["entity_swap_output_root"]
            ),
            bridge_injection_output_root=resolve_project_path(
                payload["bridge_injection_output_root"]
            ),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            modes=modes,
            top_k=int(payload.get("top_k", 10)),
            risk_penalty=float(payload["risk_penalty"]),
            risk_threshold=float(payload["risk_threshold"]),
        )

    def reference_corpus_path(self, dataset: str) -> Path:
        return self.raw_data_root / dataset / "corpus.jsonl"

    def reference_corpus_entity_path(self, dataset: str) -> Path:
        return self.baseline_output_root / dataset / "corpus_entities.jsonl"

    def clean_trace_path(self, dataset: str) -> Path:
        return self.baseline_output_root / dataset / f"{self.run_name}_traces.jsonl"

    def clean_corpus_entity_path(self, dataset: str) -> Path:
        return self.baseline_output_root / dataset / "corpus_entities.jsonl"

    def entity_swap_corpus_path(self, dataset: str) -> Path:
        return self.entity_swap_output_root / dataset / "poisoned_corpus.jsonl"

    def entity_swap_trace_path(self, dataset: str) -> Path:
        return (
            self.entity_swap_output_root
            / dataset
            / f"poisoned_{self.run_name}_traces.jsonl"
        )

    def entity_swap_corpus_entity_path(self, dataset: str) -> Path:
        return self.entity_swap_output_root / dataset / "poisoned_corpus_entities.jsonl"

    def entity_swap_metadata_path(self, dataset: str) -> Path:
        return self.entity_swap_output_root / dataset / "entity_swap_metadata.jsonl"

    def bridge_corpus_path(self, dataset: str) -> Path:
        return (
            self.bridge_injection_output_root / dataset / "bridge_poisoned_corpus.jsonl"
        )

    def bridge_trace_path(self, dataset: str) -> Path:
        return (
            self.bridge_injection_output_root
            / dataset
            / f"bridge_poisoned_{self.run_name}_traces.jsonl"
        )

    def bridge_corpus_entity_path(self, dataset: str) -> Path:
        return (
            self.bridge_injection_output_root
            / dataset
            / "bridge_poisoned_corpus_entities.jsonl"
        )

    def bridge_metadata_path(self, dataset: str) -> Path:
        return (
            self.bridge_injection_output_root
            / dataset
            / "bridge_injection_metadata.jsonl"
        )

    def output_dir(self) -> Path:
        return self.output_root / self.run_name


@dataclass(frozen=True, slots=True)
class AblationRow:
    """One dataset/mode result row."""

    dataset: str
    run_name: str
    mode: str
    risk_penalty: float
    risk_threshold: float
    clean_gold_recall_guarded: float
    clean_suppressed_gold: int
    entity_exposure_before: float
    entity_exposure_guarded: float
    entity_gold_recall_guarded: float
    entity_trusted_gold_recall_guarded: float
    entity_corrupted_gold_docs: int
    entity_suppressed_poisoned: int
    entity_suppressed_changed: int
    bridge_exposure_before: float
    bridge_exposure_guarded: float
    bridge_gold_recall_guarded: float
    bridge_trusted_gold_recall_guarded: float
    bridge_suppressed_poisoned: int
    bridge_suppressed_changed: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_ablation_mode(
    *,
    mode: str,
    dataset: str,
    run_name: str,
    risk_penalty: float,
    risk_threshold: float,
    top_k: int,
    clean_traces: list[RetrievalTrace],
    entity_traces: list[RetrievalTrace],
    bridge_traces: list[RetrievalTrace],
    reference_doc_ids: set[str],
    clean_global_support: dict[str, int],
    entity_global_support: dict[str, int],
    bridge_global_support: dict[str, int],
    entity_poisoned_doc_ids_by_query: dict[str, set[str]],
    bridge_poisoned_doc_ids_by_query: dict[str, set[str]],
    clean_changed_doc_ids: set[str],
    entity_changed_doc_ids: set[str],
    bridge_changed_doc_ids: set[str],
) -> AblationRow:
    """Evaluate one ablation mode against clean and poisoned traces."""

    clean_reranked = _rerank_traces_for_mode(
        mode,
        clean_traces,
        risk_penalty=risk_penalty,
        global_entity_support_counts=clean_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=clean_changed_doc_ids,
    )
    clean_guarded = _guard_traces_for_mode(
        mode,
        clean_traces,
        risk_penalty=risk_penalty,
        risk_threshold=risk_threshold,
        global_entity_support_counts=clean_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=clean_changed_doc_ids,
    )
    entity_reranked = _rerank_traces_for_mode(
        mode,
        entity_traces,
        risk_penalty=risk_penalty,
        global_entity_support_counts=entity_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=entity_changed_doc_ids,
    )
    entity_guarded = _guard_traces_for_mode(
        mode,
        entity_traces,
        risk_penalty=risk_penalty,
        risk_threshold=risk_threshold,
        global_entity_support_counts=entity_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=entity_changed_doc_ids,
    )
    bridge_reranked = _rerank_traces_for_mode(
        mode,
        bridge_traces,
        risk_penalty=risk_penalty,
        global_entity_support_counts=bridge_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=bridge_changed_doc_ids,
    )
    bridge_guarded = _guard_traces_for_mode(
        mode,
        bridge_traces,
        risk_penalty=risk_penalty,
        risk_threshold=risk_threshold,
        global_entity_support_counts=bridge_global_support,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=bridge_changed_doc_ids,
    )

    clean_metrics = summarize_defense_run(
        name="Clean",
        before_traces=clean_traces,
        reranked_traces=clean_reranked,
        guarded_traces=clean_guarded,
        poisoned_doc_ids_by_query={},
        changed_doc_ids=clean_changed_doc_ids,
        top_k=top_k,
    )
    entity_metrics = summarize_defense_run(
        name="Entity Swap",
        before_traces=entity_traces,
        reranked_traces=entity_reranked,
        guarded_traces=entity_guarded,
        poisoned_doc_ids_by_query=entity_poisoned_doc_ids_by_query,
        changed_doc_ids=entity_changed_doc_ids,
        top_k=top_k,
    )
    bridge_metrics = summarize_defense_run(
        name="Bridge Injection",
        before_traces=bridge_traces,
        reranked_traces=bridge_reranked,
        guarded_traces=bridge_guarded,
        poisoned_doc_ids_by_query=bridge_poisoned_doc_ids_by_query,
        changed_doc_ids=bridge_changed_doc_ids,
        top_k=top_k,
    )

    return AblationRow(
        dataset=dataset,
        run_name=run_name,
        mode=mode,
        risk_penalty=risk_penalty,
        risk_threshold=risk_threshold,
        clean_gold_recall_guarded=clean_metrics.guarded_gold_recall_at_k,
        clean_suppressed_gold=clean_metrics.suppressed_gold_candidates,
        entity_exposure_before=entity_metrics.before_exposure_at_k or 0.0,
        entity_exposure_guarded=entity_metrics.guarded_exposure_at_k or 0.0,
        entity_gold_recall_guarded=entity_metrics.guarded_gold_recall_at_k,
        entity_trusted_gold_recall_guarded=entity_metrics.guarded_trusted_gold_recall_at_k,
        entity_corrupted_gold_docs=entity_metrics.corrupted_gold_doc_count,
        entity_suppressed_poisoned=entity_metrics.suppressed_poisoned_candidates,
        entity_suppressed_changed=entity_metrics.suppressed_changed_candidates,
        bridge_exposure_before=bridge_metrics.before_exposure_at_k or 0.0,
        bridge_exposure_guarded=bridge_metrics.guarded_exposure_at_k or 0.0,
        bridge_gold_recall_guarded=bridge_metrics.guarded_gold_recall_at_k,
        bridge_trusted_gold_recall_guarded=bridge_metrics.guarded_trusted_gold_recall_at_k,
        bridge_suppressed_poisoned=bridge_metrics.suppressed_poisoned_candidates,
        bridge_suppressed_changed=bridge_metrics.suppressed_changed_candidates,
    )


def run_from_config(config: AblationConfig) -> list[AblationRow]:
    """Run ablation for all configured datasets and write reports."""

    rows: list[AblationRow] = []
    for dataset in config.datasets:
        reference_doc_ids = load_reference_doc_ids(
            config.reference_corpus_entity_path(dataset)
        )
        reference_fingerprints = load_document_fingerprints(
            config.reference_corpus_path(dataset)
        )
        clean_changed_doc_ids = find_changed_doc_ids(
            reference_fingerprints,
            load_document_fingerprints(config.reference_corpus_path(dataset)),
        )
        entity_changed_doc_ids = find_changed_doc_ids(
            reference_fingerprints,
            load_document_fingerprints(config.entity_swap_corpus_path(dataset)),
        )
        bridge_changed_doc_ids = find_changed_doc_ids(
            reference_fingerprints,
            load_document_fingerprints(config.bridge_corpus_path(dataset)),
        )

        for mode in config.modes:
            rows.append(
                evaluate_ablation_mode(
                    mode=mode,
                    dataset=dataset,
                    run_name=config.run_name,
                    risk_penalty=config.risk_penalty,
                    risk_threshold=config.risk_threshold,
                    top_k=config.top_k,
                    clean_traces=load_traces_jsonl(config.clean_trace_path(dataset)),
                    entity_traces=load_traces_jsonl(
                        config.entity_swap_trace_path(dataset)
                    ),
                    bridge_traces=load_traces_jsonl(config.bridge_trace_path(dataset)),
                    reference_doc_ids=reference_doc_ids,
                    clean_global_support=load_global_entity_support_counts(
                        config.clean_corpus_entity_path(dataset)
                    ),
                    entity_global_support=load_global_entity_support_counts(
                        config.entity_swap_corpus_entity_path(dataset)
                    ),
                    bridge_global_support=load_global_entity_support_counts(
                        config.bridge_corpus_entity_path(dataset)
                    ),
                    entity_poisoned_doc_ids_by_query=load_poisoned_doc_ids_by_query(
                        config.entity_swap_metadata_path(dataset)
                    ),
                    bridge_poisoned_doc_ids_by_query=load_poisoned_doc_ids_by_query(
                        config.bridge_metadata_path(dataset)
                    ),
                    clean_changed_doc_ids=clean_changed_doc_ids,
                    entity_changed_doc_ids=entity_changed_doc_ids,
                    bridge_changed_doc_ids=bridge_changed_doc_ids,
                )
            )
    write_ablation_outputs(config, rows)
    print(
        f"ablation: datasets={len(config.datasets)}, modes={len(config.modes)}, rows={len(rows)}"
    )
    return rows


def _rerank_traces_for_mode(
    mode: str,
    traces: list[RetrievalTrace],
    *,
    risk_penalty: float,
    global_entity_support_counts: dict[str, int],
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
) -> list[RerankedTrace]:
    if mode == "none":
        return [_identity_reranked_trace(trace) for trace in traces]

    active_reference_doc_ids, active_changed_doc_ids, active_global_support = (
        _active_signal_inputs(
            mode,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=changed_doc_ids,
            global_entity_support_counts=global_entity_support_counts,
        )
    )
    return [
        rerank_trace(
            trace,
            risk_penalty=risk_penalty,
            global_entity_support_counts=active_global_support,
            reference_doc_ids=active_reference_doc_ids,
            changed_doc_ids=active_changed_doc_ids,
        )
        for trace in traces
    ]


def _guard_traces_for_mode(
    mode: str,
    traces: list[RetrievalTrace],
    *,
    risk_penalty: float,
    risk_threshold: float,
    global_entity_support_counts: dict[str, int],
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
) -> list[RerankedTrace]:
    if mode == "none":
        return [_identity_reranked_trace(trace) for trace in traces]

    active_reference_doc_ids, active_changed_doc_ids, active_global_support = (
        _active_signal_inputs(
            mode,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=changed_doc_ids,
            global_entity_support_counts=global_entity_support_counts,
        )
    )
    return [
        build_guarded_trace(
            trace,
            risk_penalty=risk_penalty,
            risk_threshold=risk_threshold,
            global_entity_support_counts=active_global_support,
            reference_doc_ids=active_reference_doc_ids,
            changed_doc_ids=active_changed_doc_ids,
        )
        for trace in traces
    ]


def _active_signal_inputs(
    mode: str,
    *,
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
    global_entity_support_counts: dict[str, int],
) -> tuple[set[str] | None, set[str] | None, dict[str, int] | None]:
    """Return scorer inputs enabled for one ablation mode."""

    if mode == "provenance_only":
        return reference_doc_ids, set(), global_entity_support_counts
    if mode == "content_integrity_only":
        return None, changed_doc_ids, None
    if mode == "full":
        return reference_doc_ids, changed_doc_ids, global_entity_support_counts
    raise ValueError(f"Unknown ablation mode: {mode}")


def _identity_reranked_trace(trace: RetrievalTrace) -> RerankedTrace:
    """Represent the original retrieval result as a no-defense guarded trace."""

    return RerankedTrace(
        query_id=trace.query_id,
        query=trace.query,
        answer=trace.answer,
        gold_doc_ids=trace.gold_doc_ids,
        candidates=[
            RerankedCandidate(
                doc_id=candidate.doc_id,
                title=candidate.title,
                original_rank=index,
                new_rank=index,
                base_score=candidate.score,
                risk_score=0.0,
                adjusted_score=candidate.score,
                path_length=max(len(candidate.path_nodes) - 1, 0),
                direct_query_match=bool(candidate.matched_query_entities)
                and not candidate.bridge_entities,
                source_support_count=0,
                global_support_count=None,
                known_source_document=None,
                reference_content_changed=None,
                matched_query_entities=candidate.matched_query_entities,
                bridge_entities=candidate.bridge_entities,
                risk_reasons=[],
            )
            for index, candidate in enumerate(trace.candidates, start=1)
        ],
    )


def write_ablation_outputs(config: AblationConfig, rows: list[AblationRow]) -> None:
    output_dir = config.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "ablation_rows.jsonl"
    csv_path = output_dir / "ablation_rows.csv"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].to_json_dict()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_json_dict())

    _write_ablation_report(config.report_path, rows, jsonl_path, csv_path)


def _write_ablation_report(
    path: Path, rows: list[AblationRow], jsonl_path: Path, csv_path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| dataset | mode | clean recall | entity exposure | entity trusted recall | entity suppressed changed | bridge exposure | bridge suppressed poisoned |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.dataset,
                    row.mode,
                    f"{row.clean_gold_recall_guarded:.4f}",
                    f"{row.entity_exposure_before:.4f} -> {row.entity_exposure_guarded:.4f}",
                    f"{row.entity_trusted_gold_recall_guarded:.4f}",
                    str(row.entity_suppressed_changed),
                    f"{row.bridge_exposure_before:.4f} -> {row.bridge_exposure_guarded:.4f}",
                    str(row.bridge_suppressed_poisoned),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicGuard Ablation Report",
            "",
            "## Output Files",
            "",
            f"- JSONL rows: `{jsonl_path}`",
            f"- CSV rows: `{csv_path}`",
            "",
            "## Modes",
            "",
            "- `none`: no LogicGuard risk signal is applied.",
            "- `provenance_only`: enables reference-index provenance signals for unseen documents.",
            "- `content_integrity_only`: enables reference-content mismatch signals for changed known documents.",
            "- `full`: enables both provenance and content-integrity signals.",
            "",
            "## Results",
            "",
            *table_lines,
            "",
            "## Interpretation",
            "",
            "A successful ablation should show `provenance_only` reducing Bridge Injection exposure, "
            "`content_integrity_only` reducing Entity Swap exposure, and `full` reducing both.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LogicGuard ablation experiments.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicguard_ablation_full_500.yaml"),
        help="Path to the ablation YAML config.",
    )
    args = parser.parse_args()
    run_from_config(AblationConfig.from_yaml(args.config))


if __name__ == "__main__":
    main()
