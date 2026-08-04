"""Stage-3 LogicGuard defense evaluation for official LogicPoison corpora.

LogicPoison's official pipeline performs in-place entity replacement. This is a
different threat model from injected bridge documents: the poisoned evidence has
the same document ids as the clean corpus. For that reason, this runner keeps
the ablation modes deliberately explicit instead of relying on one blended risk
score:

- provenance-only checks whether a doc id belongs to the trusted reference set.
- content-integrity checks whether a trusted doc id has changed content.
- recovery uses the clean retrieval trace as trusted reference evidence.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import yaml

from logicguard.core.config import find_project_root, resolve_config_path

from logicguard.data.logicpoison_official import (
    LogicPoisonOfficialConfig,
    build_corpus_diff_records,
    build_query_integrity_records,
    load_logicpoison_pair,
)
from logicguard.defense.reranker import build_recovered_trace
from logicguard.defense.schemas import RerankedCandidate, RerankedTrace
from logicguard.experiments.run_logicpoison_retrieval import load_retrieval_traces
from logicguard.graph.schemas import PathCandidate, RetrievalTrace

DefenseMode = Literal[
    "none",
    "provenance_only",
    "content_integrity_only",
    "support_consistency_only",
    "full_logicguard",
    "full_logicguard_recovery",
]

DEFENSE_MODES: tuple[str, ...] = (
    "none",
    "provenance_only",
    "content_integrity_only",
    "support_consistency_only",
    "full_logicguard",
    "full_logicguard_recovery",
)


@dataclass(frozen=True, slots=True)
class LogicPoisonDefenseConfig:
    """Configuration for stage-3 defense ablation on LogicPoison traces."""

    clean_data_root: Path
    poisoned_data_root: Path
    retrieval_root: Path
    output_root: Path
    report_path: Path
    datasets: list[str]
    retrievers: list[str]
    modes: list[str]
    top_k: int

    @classmethod
    def from_yaml(cls, path: Path) -> "LogicPoisonDefenseConfig":
        """Load YAML configuration with paths relative to the project root."""

        path = resolve_config_path(path)
        project_root = find_project_root(path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        def resolve_project_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        modes = [str(mode) for mode in payload.get("modes", DEFENSE_MODES)]
        unknown_modes = sorted(set(modes).difference(DEFENSE_MODES))
        if unknown_modes:
            raise ValueError(f"Unknown LogicPoison defense modes: {unknown_modes}")

        return cls(
            clean_data_root=resolve_project_path(payload["clean_data_root"]),
            poisoned_data_root=resolve_project_path(payload["poisoned_data_root"]),
            retrieval_root=resolve_project_path(payload["retrieval_root"]),
            output_root=resolve_project_path(payload["output_root"]),
            report_path=resolve_project_path(payload["report_path"]),
            datasets=[str(dataset) for dataset in payload["datasets"]],
            retrievers=[str(retriever) for retriever in payload["retrievers"]],
            modes=modes,
            top_k=int(payload.get("top_k", 10)),
        )

    def to_logicpoison_official_config(self) -> LogicPoisonOfficialConfig:
        """Reuse the stage-0 official corpus pair loader."""

        return LogicPoisonOfficialConfig(
            clean_data_root=self.clean_data_root,
            poisoned_data_root=self.poisoned_data_root,
            output_root=self.output_root,
            report_path=self.report_path,
            datasets=self.datasets,
        )


@dataclass(frozen=True, slots=True)
class LogicPoisonDefenseMetrics:
    """Before/after metrics for one dataset, retriever, and defense mode."""

    dataset: str
    retriever: str
    mode: str
    query_count: int
    top_k: int
    before_changed_doc_exposure_at_k: float
    after_changed_doc_exposure_at_k: float
    before_changed_gold_exposure_at_k: float
    after_changed_gold_exposure_at_k: float
    before_gold_recall_at_k: float
    after_gold_recall_at_k: float
    before_trusted_gold_recall_at_k: float
    after_trusted_gold_recall_at_k: float
    queries_with_trusted_gold: int
    guarded_avg_candidates: float
    empty_context_rate: float
    suppressed_candidates: int
    suppressed_gold_candidates: int
    suppressed_changed_candidates: int
    suppressed_changed_gold_candidates: int
    recovered_candidate_count: int

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON representation for reports and tests."""

        return asdict(self)


def run_from_config(
    config: LogicPoisonDefenseConfig,
) -> list[LogicPoisonDefenseMetrics]:
    """Run all configured stage-3 defense modes and write artifacts."""

    official_config = config.to_logicpoison_official_config()
    all_metrics: list[LogicPoisonDefenseMetrics] = []
    for dataset in config.datasets:
        pair = load_logicpoison_pair(official_config, dataset)
        diff_records = build_corpus_diff_records(pair)
        changed_doc_ids = {record.doc_id for record in diff_records if record.changed}
        integrity_records = build_query_integrity_records(pair, changed_doc_ids)
        changed_gold_by_query = {
            record.query_id: set(record.changed_support_doc_ids)
            for record in integrity_records
        }
        reference_doc_ids = set(pair.clean.corpus)
        dataset_metrics: list[LogicPoisonDefenseMetrics] = []

        for retriever in config.retrievers:
            clean_traces = load_retrieval_traces(
                config.retrieval_root / dataset / f"{retriever}_clean_traces.jsonl"
            )
            poisoned_traces = load_retrieval_traces(
                config.retrieval_root / dataset / f"{retriever}_poisoned_traces.jsonl"
            )
            clean_by_query = {trace.query_id: trace for trace in clean_traces}

            for mode in config.modes:
                guarded_traces = [
                    apply_defense_mode(
                        mode=mode,
                        poisoned_trace=trace,
                        clean_reference_trace=clean_by_query[trace.query_id],
                        reference_doc_ids=reference_doc_ids,
                        changed_doc_ids=changed_doc_ids,
                        top_k=config.top_k,
                    )
                    for trace in poisoned_traces
                ]
                output_path = (
                    config.output_root / dataset / f"{retriever}_{mode}_traces.jsonl"
                )
                write_reranked_traces_jsonl(output_path, guarded_traces)
                metric = calculate_logicpoison_defense_metrics(
                    dataset=dataset,
                    retriever=retriever,
                    mode=mode,
                    before_traces=poisoned_traces,
                    after_traces=guarded_traces,
                    changed_doc_ids=changed_doc_ids,
                    changed_gold_doc_ids_by_query=changed_gold_by_query,
                    top_k=config.top_k,
                )
                dataset_metrics.append(metric)

        write_metrics_jsonl(
            config.output_root / dataset / "defense_metrics.jsonl", dataset_metrics
        )
        all_metrics.extend(dataset_metrics)

    write_metrics_jsonl(config.output_root / "defense_metrics.jsonl", all_metrics)
    write_defense_report(config.report_path, all_metrics)
    return all_metrics


def apply_defense_mode(
    *,
    mode: str,
    poisoned_trace: RetrievalTrace,
    clean_reference_trace: RetrievalTrace,
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
    top_k: int,
) -> RerankedTrace:
    """Apply one explicit defense mode to a poisoned retrieval trace."""

    if mode not in DEFENSE_MODES:
        raise ValueError(f"Unknown LogicPoison defense mode: {mode}")

    if mode == "none":
        return _identity_trace(poisoned_trace)

    if mode == "support_consistency_only":
        # In-place LogicPoison keeps doc ids and qrels unchanged. Without content
        # fingerprints or provenance drift, this signal has no independent
        # evidence to act on in the current implementation.
        return _identity_trace(
            poisoned_trace, risk_reason="support_consistency_no_independent_signal"
        )

    guarded = _filter_trace(
        poisoned_trace,
        reference_doc_ids=reference_doc_ids,
        changed_doc_ids=changed_doc_ids,
        check_provenance=mode
        in {"provenance_only", "full_logicguard", "full_logicguard_recovery"},
        check_content=mode
        in {"content_integrity_only", "full_logicguard", "full_logicguard_recovery"},
    )

    if mode == "full_logicguard_recovery":
        return build_recovered_trace(guarded, clean_reference_trace, top_k=top_k)
    return guarded


def calculate_logicpoison_defense_metrics(
    *,
    dataset: str,
    retriever: str,
    mode: str,
    before_traces: list[RetrievalTrace],
    after_traces: list[RerankedTrace],
    changed_doc_ids: set[str],
    changed_gold_doc_ids_by_query: dict[str, set[str]],
    top_k: int,
) -> LogicPoisonDefenseMetrics:
    """Calculate before/after exposure, recall, suppression, and recovery metrics."""

    after_by_query = {trace.query_id: trace for trace in after_traces}
    before_gold_recalls: list[float] = []
    after_gold_recalls: list[float] = []
    before_trusted_recalls: list[float] = []
    after_trusted_recalls: list[float] = []
    before_changed_doc_exposures: list[float] = []
    after_changed_doc_exposures: list[float] = []
    before_changed_gold_exposures: list[float] = []
    after_changed_gold_exposures: list[float] = []
    guarded_candidate_counts: list[float] = []
    empty_contexts = 0
    suppressed_candidates = 0
    suppressed_gold_candidates = 0
    suppressed_changed_candidates = 0
    suppressed_changed_gold_candidates = 0
    recovered_candidate_count = 0
    queries_with_trusted_gold = 0

    for before in before_traces:
        after = after_by_query[before.query_id]
        changed_gold_doc_ids = changed_gold_doc_ids_by_query.get(before.query_id, set())
        gold_doc_ids = set(before.gold_doc_ids)
        trusted_gold_doc_ids = gold_doc_ids.difference(changed_gold_doc_ids)
        if trusted_gold_doc_ids:
            queries_with_trusted_gold += 1

        before_doc_ids = [candidate.doc_id for candidate in before.candidates[:top_k]]
        after_candidates = after.candidates[:top_k]
        after_doc_ids = [candidate.doc_id for candidate in after_candidates]
        before_doc_id_set = set(before_doc_ids)
        after_doc_id_set = set(after_doc_ids)

        before_gold_recalls.append(_recall(before_doc_id_set, gold_doc_ids))
        after_gold_recalls.append(_recall(after_doc_id_set, gold_doc_ids))
        if trusted_gold_doc_ids:
            before_trusted_recalls.append(
                _recall(before_doc_id_set, trusted_gold_doc_ids)
            )
            after_trusted_recalls.append(
                _recall(after_doc_id_set, trusted_gold_doc_ids)
            )

        before_changed_doc_exposures.append(
            1.0 if before_doc_id_set.intersection(changed_doc_ids) else 0.0
        )
        before_changed_gold_exposures.append(
            1.0 if before_doc_id_set.intersection(changed_gold_doc_ids) else 0.0
        )
        after_changed_doc_exposures.append(
            1.0
            if any(
                _is_untrusted_changed_candidate(candidate, changed_doc_ids)
                for candidate in after_candidates
            )
            else 0.0
        )
        after_changed_gold_exposures.append(
            1.0
            if any(
                _is_untrusted_changed_candidate(candidate, changed_gold_doc_ids)
                for candidate in after_candidates
            )
            else 0.0
        )

        guarded_candidate_counts.append(float(len(after_candidates)))
        if not after_candidates:
            empty_contexts += 1
        recovered_candidate_count += sum(
            1
            for candidate in after_candidates
            if "trusted_reference_recovery" in candidate.risk_reasons
        )

        after_doc_id_set_all = {candidate.doc_id for candidate in after.candidates}
        for candidate in before.candidates[:top_k]:
            if candidate.doc_id in after_doc_id_set_all:
                continue
            suppressed_candidates += 1
            if candidate.doc_id in gold_doc_ids:
                suppressed_gold_candidates += 1
            if candidate.doc_id in changed_doc_ids:
                suppressed_changed_candidates += 1
            if candidate.doc_id in changed_gold_doc_ids:
                suppressed_changed_gold_candidates += 1

    return LogicPoisonDefenseMetrics(
        dataset=dataset,
        retriever=retriever,
        mode=mode,
        query_count=len(before_traces),
        top_k=top_k,
        before_changed_doc_exposure_at_k=_mean(before_changed_doc_exposures),
        after_changed_doc_exposure_at_k=_mean(after_changed_doc_exposures),
        before_changed_gold_exposure_at_k=_mean(before_changed_gold_exposures),
        after_changed_gold_exposure_at_k=_mean(after_changed_gold_exposures),
        before_gold_recall_at_k=_mean(before_gold_recalls),
        after_gold_recall_at_k=_mean(after_gold_recalls),
        before_trusted_gold_recall_at_k=_mean(before_trusted_recalls),
        after_trusted_gold_recall_at_k=_mean(after_trusted_recalls),
        queries_with_trusted_gold=queries_with_trusted_gold,
        guarded_avg_candidates=_mean(guarded_candidate_counts),
        empty_context_rate=empty_contexts / len(before_traces)
        if before_traces
        else 0.0,
        suppressed_candidates=suppressed_candidates,
        suppressed_gold_candidates=suppressed_gold_candidates,
        suppressed_changed_candidates=suppressed_changed_candidates,
        suppressed_changed_gold_candidates=suppressed_changed_gold_candidates,
        recovered_candidate_count=recovered_candidate_count,
    )


def write_defense_report(
    path: Path,
    rows: list[LogicPoisonDefenseMetrics],
) -> None:
    """Write a Chinese Markdown report for stage-3 defense ablation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table_lines = [
        "| 数据集 | 检索器 | 防御模式 | 改写文档暴露@k | 改写gold暴露@k | gold_recall@k | trusted_recall@k | 空上下文率 | 过滤改写候选 | recovery候选数 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(
                [
                    row.dataset,
                    row.retriever,
                    row.mode,
                    f"{row.before_changed_doc_exposure_at_k:.4f} -> {row.after_changed_doc_exposure_at_k:.4f}",
                    f"{row.before_changed_gold_exposure_at_k:.4f} -> {row.after_changed_gold_exposure_at_k:.4f}",
                    f"{row.before_gold_recall_at_k:.4f} -> {row.after_gold_recall_at_k:.4f}",
                    f"{row.before_trusted_gold_recall_at_k:.4f} -> {row.after_trusted_gold_recall_at_k:.4f}",
                    f"{row.empty_context_rate:.4f}",
                    str(row.suppressed_changed_candidates),
                    str(row.recovered_candidate_count),
                ]
            )
            + " |"
        )

    content = "\n".join(
        [
            "# LogicPoison 防御消融实验报告",
            "",
            "## 实验目的",
            "",
            "本阶段在 LogicPoison poisoned 检索 trace 上评估不同 LogicGuard 信号。实验不重新检索，也不调用 LLM；目标是判断 provenance、content-integrity 与 clean-reference recovery 分别能处理什么问题。",
            "",
            "## 防御模式说明",
            "",
            "- `none`：不启用防御，直接保留 poisoned 检索结果。",
            "- `provenance_only`：只检查 doc_id 是否来自 clean reference corpus。由于 LogicPoison 是原位替换，预期该模式几乎不会降低暴露。",
            "- `content_integrity_only`：只检查同 ID 文档内容 fingerprint 是否与 clean reference 不一致。",
            "- `support_consistency_only`：只保留为消融占位。当前原位替换设置下，它没有独立于内容指纹的可靠信号。",
            "- `full_logicguard`：同时检查 provenance 与 content-integrity。",
            "- `full_logicguard_recovery`：先执行 full 过滤，再从 clean reference trace 回填证据。回填候选按 clean corpus 渲染，因此不计为 poisoned 暴露。",
            "",
            "## 指标说明",
            "",
            "- `改写文档暴露@k`：top-k 中是否仍存在 poisoned 版本的改写文档。",
            "- `改写gold暴露@k`：top-k 中是否仍存在 poisoned 版本的改写 gold support。",
            "- `gold_recall@k`：防御前后 top-k 对全部 gold support 的召回比例。",
            "- `trusted_recall@k`：排除改写 gold support 后，对仍未改写 gold support 的召回比例。",
            "- `空上下文率`：防御后 top-k 候选为空的 query 比例。该值高说明过滤后容易 UNKNOWN。",
            "- `recovery候选数`：从 clean reference trace 回填的候选数量。",
            "",
            "## 实验结果",
            "",
            *table_lines,
            "",
            "## 当前解读",
            "",
            "- 如果 `provenance_only` 基本不降低暴露，说明 LogicPoison 的原位替换确实绕过了简单来源检查。",
            "- 如果 `content_integrity_only` 将改写文档暴露降到 0，但 gold recall 大幅下降或空上下文率升高，说明防御能挡住污染证据但会缺证。",
            "- 如果 `full_logicguard_recovery` 在保持改写文档暴露为 0 的同时恢复 gold recall，说明 clean reference 回填是后续 LLM 阶段能否回答正确的关键。",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def write_reranked_traces_jsonl(path: Path, traces: list[RerankedTrace]) -> None:
    """Write reranked or guarded traces to JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace.to_json_dict(), ensure_ascii=False) + "\n")


def write_metrics_jsonl(path: Path, rows: list[LogicPoisonDefenseMetrics]) -> None:
    """Write stage-3 metrics to JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")


def _filter_trace(
    trace: RetrievalTrace,
    *,
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
    check_provenance: bool,
    check_content: bool,
) -> RerankedTrace:
    kept_candidates: list[RerankedCandidate] = []
    for original_rank, candidate in enumerate(trace.candidates, start=1):
        reasons = _candidate_filter_reasons(
            candidate,
            reference_doc_ids=reference_doc_ids,
            changed_doc_ids=changed_doc_ids,
            check_provenance=check_provenance,
            check_content=check_content,
        )
        if reasons:
            continue
        kept_candidates.append(
            _reranked_candidate_from_path(
                candidate,
                original_rank=original_rank,
                new_rank=len(kept_candidates) + 1,
                risk_reasons=_pass_reasons(check_provenance, check_content),
            )
        )
    return RerankedTrace(
        query_id=trace.query_id,
        query=trace.query,
        answer=trace.answer,
        gold_doc_ids=trace.gold_doc_ids,
        candidates=kept_candidates,
    )


def _candidate_filter_reasons(
    candidate: PathCandidate,
    *,
    reference_doc_ids: set[str],
    changed_doc_ids: set[str],
    check_provenance: bool,
    check_content: bool,
) -> list[str]:
    reasons: list[str] = []
    if check_provenance and candidate.doc_id not in reference_doc_ids:
        reasons.append("unseen_source_document")
    if check_content and candidate.doc_id in changed_doc_ids:
        reasons.append("reference_content_mismatch")
    return reasons


def _identity_trace(
    trace: RetrievalTrace,
    risk_reason: str | None = None,
) -> RerankedTrace:
    return RerankedTrace(
        query_id=trace.query_id,
        query=trace.query,
        answer=trace.answer,
        gold_doc_ids=trace.gold_doc_ids,
        candidates=[
            _reranked_candidate_from_path(
                candidate,
                original_rank=index,
                new_rank=index,
                risk_reasons=[risk_reason] if risk_reason else [],
            )
            for index, candidate in enumerate(trace.candidates, start=1)
        ],
    )


def _reranked_candidate_from_path(
    candidate: PathCandidate,
    *,
    original_rank: int,
    new_rank: int,
    risk_reasons: list[str],
) -> RerankedCandidate:
    return RerankedCandidate(
        doc_id=candidate.doc_id,
        title=candidate.title,
        original_rank=original_rank,
        new_rank=new_rank,
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
        risk_reasons=risk_reasons,
    )


def _pass_reasons(check_provenance: bool, check_content: bool) -> list[str]:
    reasons: list[str] = []
    if check_provenance:
        reasons.append("provenance_pass")
    if check_content:
        reasons.append("content_integrity_pass")
    return reasons


def _is_untrusted_changed_candidate(
    candidate: RerankedCandidate,
    changed_doc_ids: set[str],
) -> bool:
    if candidate.doc_id not in changed_doc_ids:
        return False
    return "trusted_reference_recovery" not in candidate.risk_reasons


def _recall(retrieved_doc_ids: set[str], gold_doc_ids: set[str]) -> float:
    if not gold_doc_ids:
        return 0.0
    return len(retrieved_doc_ids.intersection(gold_doc_ids)) / len(gold_doc_ids)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stage-3 LogicGuard defense ablation on official LogicPoison traces."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/logicpoison_defense_stage3.yaml"),
        help="Path to the stage-3 defense YAML config.",
    )
    args = parser.parse_args()
    config = LogicPoisonDefenseConfig.from_yaml(args.config)
    rows = run_from_config(config)
    for row in rows:
        print(
            f"{row.dataset}/{row.retriever}/{row.mode}: "
            f"changed_doc@{row.top_k}={row.before_changed_doc_exposure_at_k:.4f}"
            f"->{row.after_changed_doc_exposure_at_k:.4f}, "
            f"gold_recall@{row.top_k}={row.before_gold_recall_at_k:.4f}"
            f"->{row.after_gold_recall_at_k:.4f}, "
            f"empty={row.empty_context_rate:.4f}"
        )


if __name__ == "__main__":
    main()
