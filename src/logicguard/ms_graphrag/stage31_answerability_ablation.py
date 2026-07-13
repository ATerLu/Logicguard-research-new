"""Stage31 offline answerability ablation for recovered official GraphRAG sources."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import string
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from logicguard.data.prepare import load_normalized_samples
from logicguard.data.schemas import NormalizedSample
from logicguard.llm.context import build_qa_messages
from logicguard.ms_graphrag.official_local_context import (
    parse_doc_id_from_source_text,
    parse_title_from_source_text,
)

_METHOD_ORDER = {
    "full_query_guard": 1,
    "risk_non_oracle_guarded_sources": 2,
    "risk_non_oracle_title_entity_bm25": 3,
}

_ORDER_POLICY_ORDER = {
    "official_order": 1,
    "recovered_first": 2,
    "title_query_overlap": 3,
    "recovered_then_title_query_overlap": 4,
    "oracle_answer_surface_first": 9,
}

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class Stage31AnswerabilityConfig:
    """Paths and settings for Stage31 offline answerability ablation."""

    dataset: str
    sample_path: Path
    query_integrity_path: Path
    context_input_path: Path
    ablation_rows_output_path: Path
    summary_output_path: Path
    examples_output_path: Path
    report_path: Path
    methods: list[str]
    order_policies: list[str]
    top_ks: list[int]
    prompt_char_budgets: dict[str, int]
    max_queries: int = 20
    stage_label: str = "Stage31"

    @classmethod
    def from_yaml(cls, path: Path) -> "Stage31AnswerabilityConfig":
        """Load a project-relative YAML config."""

        project_root = path.resolve().parents[1]
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: object) -> Path:
            candidate = Path(str(raw))
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        prompt_budgets = {
            str(name): int(value)
            for name, value in dict(payload.get("prompt_char_budgets", {})).items()
        }
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(payload["sample_path"]),
            query_integrity_path=resolve(payload["query_integrity_path"]),
            context_input_path=resolve(payload["context_input_path"]),
            ablation_rows_output_path=resolve(payload["ablation_rows_output_path"]),
            summary_output_path=resolve(payload["summary_output_path"]),
            examples_output_path=resolve(payload["examples_output_path"]),
            report_path=resolve(payload["report_path"]),
            methods=[str(method) for method in payload.get("methods", [])],
            order_policies=[
                str(policy) for policy in payload.get("order_policies", [])
            ],
            top_ks=[int(top_k) for top_k in payload.get("top_ks", [])],
            prompt_char_budgets=prompt_budgets,
            max_queries=int(payload.get("max_queries", 20)),
            stage_label=str(payload.get("stage_label", "Stage31")),
        )


@dataclass(frozen=True, slots=True)
class Stage31AblationRow:
    """One query-method-policy row in the Stage31 offline ablation."""

    dataset: str
    query_id: str
    query: str
    method: str
    order_policy: str
    ordering_uses_oracle: bool
    top_k: int
    prompt_policy: str
    max_chars_per_source: int
    gold_answer: str
    support_doc_ids: list[str]
    changed_support_doc_ids: list[str]
    context_doc_ids: list[str]
    support_hit_doc_ids: list[str]
    full_support_hit: bool
    unrecovered_changed_doc_ids: list[str]
    recovered_support_doc_ids: list[str]
    source_count: int
    recovered_source_count: int
    context_has_gold_answer: bool
    first_gold_answer_rank: int | None
    first_support_rank: int | None
    prompt_char_count: int
    estimated_prompt_tokens: int
    answerability_label: str

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, list):
                output[key] = ";".join(str(item) for item in value)
            elif isinstance(value, bool):
                output[key] = "1" if value else "0"
            elif value is None:
                output[key] = ""
            else:
                output[key] = str(value)
        return output


@dataclass(frozen=True, slots=True)
class Stage31SummaryRow:
    """Aggregated Stage31 answerability metrics."""

    dataset: str
    method: str
    order_policy: str
    ordering_uses_oracle: bool
    top_k: int
    prompt_policy: str
    query_count: int
    answer_surface_rate: float
    clean_answerable_rate: float
    support_hit_rate: float
    full_support_hit_rate: float
    unsafe_context_rate: float
    missing_answer_rate: float
    avg_source_count: float
    avg_recovered_source_count: float
    avg_prompt_char_count: float
    avg_estimated_prompt_tokens: float
    avg_first_gold_answer_rank: float
    avg_first_support_rank: float

    def to_csv_row(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, bool):
                output[key] = "1" if value else "0"
            elif isinstance(value, float):
                output[key] = f"{value:.4f}"
            else:
                output[key] = str(value)
        return output


def run_from_config(config: Stage31AnswerabilityConfig) -> list[Stage31AblationRow]:
    """Run Stage31 offline ablation and write all artifacts."""

    samples = load_normalized_samples(config.sample_path)[: config.max_queries]
    integrity_rows = _load_jsonl(config.query_integrity_path)[: config.max_queries]
    context_rows = _load_jsonl(config.context_input_path)
    rows = build_stage31_ablation_rows(
        samples=samples,
        integrity_rows=integrity_rows,
        context_rows=context_rows,
        dataset=config.dataset,
        methods=config.methods,
        order_policies=config.order_policies,
        top_ks=config.top_ks,
        prompt_char_budgets=config.prompt_char_budgets,
    )
    summaries = summarize_stage31_rows(rows)
    write_stage31_outputs(config=config, rows=rows, summaries=summaries)
    return rows


def build_stage31_ablation_rows(
    *,
    samples: list[NormalizedSample],
    integrity_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    dataset: str,
    methods: list[str],
    order_policies: list[str],
    top_ks: list[int],
    prompt_char_budgets: dict[str, int],
) -> list[Stage31AblationRow]:
    """Build offline source-ordering/top-k/prompt-budget ablation rows."""

    samples_by_query = {sample.query_id: sample for sample in samples}
    allowed_methods = set(methods)
    integrity_by_query = {
        str(row.get("query_id", "")): row
        for row in integrity_rows
        if row.get("query_id") is not None
    }

    rows: list[Stage31AblationRow] = []
    for context_row in context_rows:
        query_id = str(context_row.get("query_id", ""))
        method = str(context_row.get("method", "unknown"))
        if query_id not in samples_by_query:
            continue
        if allowed_methods and method not in allowed_methods:
            continue
        sample = samples_by_query[query_id]
        changed_doc_ids = _string_list(
            integrity_by_query.get(query_id, {}).get("changed_support_doc_ids", [])
        )
        sources = _source_records(context_row)
        for order_policy in order_policies:
            ordered_sources = _order_sources(
                sources=sources,
                query=sample.query,
                gold_answer=sample.answer,
                order_policy=order_policy,
            )
            for top_k in top_ks:
                top_sources = ordered_sources[:top_k]
                for prompt_policy, max_chars in prompt_char_budgets.items():
                    rows.append(
                        _build_ablation_row(
                            dataset=dataset,
                            sample=sample,
                            method=method,
                            order_policy=order_policy,
                            top_k=top_k,
                            prompt_policy=prompt_policy,
                            max_chars_per_source=max_chars,
                            sources=top_sources,
                            changed_doc_ids=changed_doc_ids,
                        )
                    )
    rows.sort(
        key=lambda row: (
            row.query_id,
            _METHOD_ORDER.get(row.method, 99),
            _ORDER_POLICY_ORDER.get(row.order_policy, 99),
            row.top_k,
            row.prompt_policy,
        )
    )
    return rows


def summarize_stage31_rows(
    rows: list[Stage31AblationRow],
) -> list[Stage31SummaryRow]:
    """Aggregate Stage31 rows by method, ordering, top-k, and prompt policy."""

    grouped: dict[tuple[str, str, int, str], list[Stage31AblationRow]] = {}
    for row in rows:
        grouped.setdefault(
            (row.method, row.order_policy, row.top_k, row.prompt_policy), []
        ).append(row)

    summaries: list[Stage31SummaryRow] = []
    for (method, order_policy, top_k, prompt_policy), group in grouped.items():
        total = len(group)
        summaries.append(
            Stage31SummaryRow(
                dataset=group[0].dataset,
                method=method,
                order_policy=order_policy,
                ordering_uses_oracle=any(row.ordering_uses_oracle for row in group),
                top_k=top_k,
                prompt_policy=prompt_policy,
                query_count=total,
                answer_surface_rate=_ratio(
                    sum(1 for row in group if row.context_has_gold_answer), total
                ),
                clean_answerable_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.answerability_label == "answerable_clean"
                    ),
                    total,
                ),
                support_hit_rate=_ratio(
                    sum(1 for row in group if row.support_hit_doc_ids), total
                ),
                full_support_hit_rate=_ratio(
                    sum(1 for row in group if row.full_support_hit), total
                ),
                unsafe_context_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.answerability_label == "unsafe_context"
                    ),
                    total,
                ),
                missing_answer_rate=_ratio(
                    sum(
                        1
                        for row in group
                        if row.answerability_label
                        in {"missing_answer_surface", "support_without_answer_surface"}
                    ),
                    total,
                ),
                avg_source_count=_avg(row.source_count for row in group),
                avg_recovered_source_count=_avg(
                    row.recovered_source_count for row in group
                ),
                avg_prompt_char_count=_avg(row.prompt_char_count for row in group),
                avg_estimated_prompt_tokens=_avg(
                    row.estimated_prompt_tokens for row in group
                ),
                avg_first_gold_answer_rank=_avg(
                    row.first_gold_answer_rank
                    for row in group
                    if row.first_gold_answer_rank is not None
                ),
                avg_first_support_rank=_avg(
                    row.first_support_rank
                    for row in group
                    if row.first_support_rank is not None
                ),
            )
        )
    summaries.sort(
        key=lambda row: (
            _METHOD_ORDER.get(row.method, 99),
            _ORDER_POLICY_ORDER.get(row.order_policy, 99),
            row.top_k,
            row.prompt_policy,
        )
    )
    return summaries


def write_stage31_outputs(
    *,
    config: Stage31AnswerabilityConfig,
    rows: list[Stage31AblationRow],
    summaries: list[Stage31SummaryRow],
) -> None:
    """Write Stage31 JSONL/CSV/report artifacts."""

    config.ablation_rows_output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.ablation_rows_output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    _write_csv(
        config.summary_output_path,
        [row.to_csv_row() for row in summaries],
    )

    examples = _select_examples(rows)
    with config.examples_output_path.open("w", encoding="utf-8") as handle:
        for row in examples:
            handle.write(json.dumps(row.to_json_dict(), ensure_ascii=False) + "\n")

    _write_stage31_report(
        config=config,
        rows=rows,
        summaries=summaries,
        examples=examples,
    )


def _build_ablation_row(
    *,
    dataset: str,
    sample: NormalizedSample,
    method: str,
    order_policy: str,
    top_k: int,
    prompt_policy: str,
    max_chars_per_source: int,
    sources: list[dict[str, Any]],
    changed_doc_ids: list[str],
) -> Stage31AblationRow:
    context_doc_ids = _dedupe(_source_doc_id(source) for source in sources)
    support_doc_ids = [str(doc_id) for doc_id in sample.support_doc_ids]
    support_hits = _ordered_intersection(support_doc_ids, context_doc_ids)
    recovered_support_doc_ids = _ordered_intersection(
        support_doc_ids,
        _dedupe(
            _source_doc_id(source) for source in sources if _is_recovered_source(source)
        ),
    )
    unrecovered_changed = _dedupe(
        _source_doc_id(source)
        for source in sources
        if _source_doc_id(source) in set(changed_doc_ids)
        and not _is_recovered_source(source)
    )
    rendered_blocks = [
        _render_single_source_block(
            source,
            rank=index,
            max_chars_per_source=max_chars_per_source,
        )
        for index, source in enumerate(sources, start=1)
    ]
    rendered_context = "\n\n".join(rendered_blocks)
    context_has_gold_answer = _contains_answer_phrase(rendered_context, sample.answer)
    first_gold_answer_rank = _first_rank_with_answer(rendered_blocks, sample.answer)
    first_support_rank = _first_rank_with_doc_id(sources, set(support_doc_ids))
    prompt_char_count = _prompt_char_count(question=sample.query, context=rendered_context)

    return Stage31AblationRow(
        dataset=dataset,
        query_id=sample.query_id,
        query=sample.query,
        method=method,
        order_policy=order_policy,
        ordering_uses_oracle=_ordering_uses_oracle(order_policy),
        top_k=top_k,
        prompt_policy=prompt_policy,
        max_chars_per_source=max_chars_per_source,
        gold_answer=sample.answer,
        support_doc_ids=support_doc_ids,
        changed_support_doc_ids=changed_doc_ids,
        context_doc_ids=context_doc_ids,
        support_hit_doc_ids=support_hits,
        full_support_hit=set(support_doc_ids).issubset(set(context_doc_ids)),
        unrecovered_changed_doc_ids=unrecovered_changed,
        recovered_support_doc_ids=recovered_support_doc_ids,
        source_count=len(context_doc_ids),
        recovered_source_count=sum(1 for source in sources if _is_recovered_source(source)),
        context_has_gold_answer=context_has_gold_answer,
        first_gold_answer_rank=first_gold_answer_rank,
        first_support_rank=first_support_rank,
        prompt_char_count=prompt_char_count,
        estimated_prompt_tokens=max(1, math.ceil(prompt_char_count / 4)),
        answerability_label=_answerability_label(
            context_has_gold_answer=context_has_gold_answer,
            support_hits=support_hits,
            unrecovered_changed=unrecovered_changed,
            source_count=len(context_doc_ids),
        ),
    )


def _order_sources(
    *,
    sources: list[dict[str, Any]],
    query: str,
    gold_answer: str,
    order_policy: str,
) -> list[dict[str, Any]]:
    indexed_sources = list(enumerate(sources))
    if order_policy == "official_order":
        return list(sources)
    if order_policy == "recovered_first":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (not _is_recovered_source(item[1]), item[0]),
            )
        ]
    if order_policy == "title_query_overlap":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (
                    -_title_query_overlap(query, item[1]),
                    not _is_recovered_source(item[1]),
                    item[0],
                ),
            )
        ]
    if order_policy == "recovered_then_title_query_overlap":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (
                    not _is_recovered_source(item[1]),
                    -_title_query_overlap(query, item[1]),
                    item[0],
                ),
            )
        ]
    if order_policy == "oracle_answer_surface_first":
        return [
            source
            for _, source in sorted(
                indexed_sources,
                key=lambda item: (
                    not _source_contains_answer(item[1], gold_answer),
                    item[0],
                ),
            )
        ]
    raise ValueError(f"Unknown Stage31 order policy: {order_policy}")


def _source_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    context_data = row.get("context_data", {})
    sources = context_data.get("sources", []) if isinstance(context_data, dict) else []
    return [source for source in sources if isinstance(source, dict)]


def _source_doc_id(source: dict[str, Any]) -> str:
    return str(
        source.get("logicguard_doc_id")
        or parse_doc_id_from_source_text(str(source.get("text", "")))
    )


def _source_title(source: dict[str, Any]) -> str:
    return str(source.get("title") or parse_title_from_source_text(str(source.get("text", ""))))


def _is_recovered_source(source: dict[str, Any]) -> bool:
    return (
        bool(source.get("recovered_from_risk_non_oracle_source"))
        or bool(source.get("recovered_from_changed_doc"))
        or str(source.get("source_state")) == "clean_reference"
    )


def _render_single_source_block(
    source: dict[str, Any],
    *,
    rank: int,
    max_chars_per_source: int,
) -> str:
    doc_id = _source_doc_id(source)
    state = str(source.get("source_state", "official_poisoned_context"))
    title = _source_title(source)
    text = _truncate(str(source.get("text", "")), max_chars=max_chars_per_source)
    return "\n".join(
        [
            f"[G{rank}] doc_id={doc_id}; source_state={state}",
            f"Title: {title}",
            f"Text: {text}",
        ]
    )


def _contains_answer_phrase(text: str, answer: str) -> bool:
    normalized_text = _normalize_text(text)
    return any(
        _contains_token_phrase(normalized_text, variant)
        for variant in _answer_variants(answer)
    )


def _source_contains_answer(source: dict[str, Any], answer: str) -> bool:
    return _contains_answer_phrase(
        " ".join([_source_title(source), str(source.get("text", ""))]),
        answer,
    )


def _answer_variants(answer: str) -> list[str]:
    normalized = _normalize_text(answer)
    without_parenthetical = _normalize_text(re.sub(r"\([^)]*\)", " ", str(answer)))
    before_comma = _normalize_text(str(answer).split(",", maxsplit=1)[0])
    variants = [normalized, without_parenthetical, before_comma]
    if normalized.startswith("the "):
        variants.append(normalized[4:])
    return _dedupe(variant for variant in variants if variant)


def _contains_token_phrase(normalized_text: str, normalized_answer: str) -> bool:
    if not normalized_answer:
        return False
    pattern = r"(?<!\w)" + re.escape(normalized_answer) + r"(?!\w)"
    return re.search(pattern, normalized_text) is not None


def _normalize_text(text: str) -> str:
    lowered = str(text).lower()
    without_punctuation = lowered.translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _first_rank_with_answer(blocks: list[str], answer: str) -> int | None:
    for index, block in enumerate(blocks, start=1):
        if _contains_answer_phrase(block, answer):
            return index
    return None


def _first_rank_with_doc_id(
    sources: list[dict[str, Any]],
    target_doc_ids: set[str],
) -> int | None:
    for index, source in enumerate(sources, start=1):
        if _source_doc_id(source) in target_doc_ids:
            return index
    return None


def _title_query_overlap(query: str, source: dict[str, Any]) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(_source_title(source)))
    if not query_tokens or not title_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / math.sqrt(len(query_tokens) * len(title_tokens))


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text))
        if token and token not in {"the", "a", "an", "of", "and", "or", "was", "were"}
    ]


def _prompt_char_count(*, question: str, context: str) -> int:
    return sum(
        len(message["content"])
        for message in build_qa_messages(question=question, context=context)
    )


def _answerability_label(
    *,
    context_has_gold_answer: bool,
    support_hits: list[str],
    unrecovered_changed: list[str],
    source_count: int,
) -> str:
    if source_count == 0:
        return "empty_context"
    if unrecovered_changed:
        return "unsafe_context"
    if context_has_gold_answer:
        return "answerable_clean"
    if support_hits:
        return "support_without_answer_surface"
    return "missing_answer_surface"


def _ordering_uses_oracle(order_policy: str) -> bool:
    return order_policy.startswith("oracle_")


def _select_examples(rows: list[Stage31AblationRow]) -> list[Stage31AblationRow]:
    def priority(row: Stage31AblationRow) -> tuple[int, str, str, int, str]:
        if row.order_policy == "title_query_overlap" and row.answerability_label == "answerable_clean":
            bucket = 0
        elif row.order_policy == "oracle_answer_surface_first" and row.answerability_label == "answerable_clean":
            bucket = 1
        elif row.answerability_label == "support_without_answer_surface":
            bucket = 2
        elif row.answerability_label == "missing_answer_surface":
            bucket = 3
        else:
            bucket = 9
        return (bucket, row.query_id, row.order_policy, row.top_k, row.prompt_policy)

    selected: list[Stage31AblationRow] = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in sorted(rows, key=priority):
        key = (row.query_id, row.order_policy, row.top_k, row.prompt_policy)
        if key in seen:
            continue
        selected.append(row)
        seen.add(key)
        if len(selected) >= 12:
            break
    return selected


def _write_stage31_report(
    *,
    config: Stage31AnswerabilityConfig,
    rows: list[Stage31AblationRow],
    summaries: list[Stage31SummaryRow],
    examples: list[Stage31AblationRow],
) -> None:
    table = [
        "| 方法 | 排序策略 | oracle? | top-k | prompt budget | query数 | answer surface | clean answerable | support hit | full support | unsafe | avg tokens |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        table.append(
            f"| `{row.method}` | `{row.order_policy}` | "
            f"{int(row.ordering_uses_oracle)} | {row.top_k} | `{row.prompt_policy}` | "
            f"{row.query_count} | {row.answer_surface_rate:.4f} | "
            f"{row.clean_answerable_rate:.4f} | {row.support_hit_rate:.4f} | "
            f"{row.full_support_hit_rate:.4f} | {row.unsafe_context_rate:.4f} | "
            f"{row.avg_estimated_prompt_tokens:.2f} |"
        )

    example_lines = [
        "| query_id | 方法 | 排序 | top-k | prompt | 标签 | gold answer | support hit | first answer rank | first support rank |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in examples:
        example_lines.append(
            f"| `{row.query_id}` | `{row.method}` | `{row.order_policy}` | "
            f"{row.top_k} | `{row.prompt_policy}` | `{row.answerability_label}` | "
            f"`{_markdown_cell(row.gold_answer)}` | `{';'.join(row.support_hit_doc_ids)}` | "
            f"{row.first_gold_answer_rank or ''} | {row.first_support_rank or ''} |"
        )

    content = "\n".join(
        [
            f"# {config.stage_label} 回答可用性消融",
            "",
            "## 实验目的",
            "",
            "Stage31 复用 Stage28 的 recovered official GraphRAG sources，不重新调用外部 LLM。"
            "它离线比较 source ordering / top-k / prompt budget 对回答可用性的影响，"
            "用 gold answer surface、support hit 和 unrecovered changed exposure 作为可复现 proxy。",
            "",
            "## 重要边界",
            "",
            "- 非 oracle 排序策略只使用 query、source title、source state 和 recovery 标记。",
            "- `oracle_answer_surface_first` 只作为诊断上界，使用 gold answer 判断 source 是否含答案，不能作为部署策略。",
            "- 本阶段解释 Stage29 的低 utility 来源，不改变 Stage28/29 的真实 LLM 结果。",
            "",
            "## 实验设置",
            "",
            f"- 数据集: `{config.dataset}`",
            f"- 输入 contexts: `{config.context_input_path.as_posix()}`",
            f"- 评估行数: `{len(rows)}`",
            f"- 方法: {', '.join(f'`{method}`' for method in config.methods)}",
            f"- 排序策略: {', '.join(f'`{policy}`' for policy in config.order_policies)}",
            f"- top-k: {', '.join(str(top_k) for top_k in config.top_ks)}",
            f"- prompt budgets: {', '.join(f'`{name}`={chars}' for name, chars in config.prompt_char_budgets.items())}",
            "",
            "## 汇总结果",
            "",
            *table,
            "",
            "## 主要结论",
            "",
            _stage31_conclusion(summaries),
            "",
            "## 代表样例",
            "",
            *example_lines,
            "",
            "## 产物路径",
            "",
            f"- ablation rows JSONL: `{config.ablation_rows_output_path.as_posix()}`",
            f"- summary CSV: `{config.summary_output_path.as_posix()}`",
            f"- examples JSONL: `{config.examples_output_path.as_posix()}`",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _stage31_conclusion(summaries: list[Stage31SummaryRow]) -> str:
    non_oracle = [row for row in summaries if not row.ordering_uses_oracle]
    oracle = [row for row in summaries if row.ordering_uses_oracle]
    lines: list[str] = []
    if non_oracle:
        best = max(
            non_oracle,
            key=lambda row: (
                row.clean_answerable_rate,
                row.answer_surface_rate,
                -row.avg_estimated_prompt_tokens,
            ),
        )
        lines.append(
            f"最佳非 oracle 设置是 `{best.order_policy}` + top-{best.top_k} + "
            f"`{best.prompt_policy}`，clean answerable rate 为 "
            f"`{best.clean_answerable_rate:.4f}`，answer surface rate 为 "
            f"`{best.answer_surface_rate:.4f}`。"
        )
    baseline = next(
        (
            row
            for row in summaries
            if row.order_policy == "official_order"
            and row.top_k == 8
            and row.prompt_policy == "stage28"
        ),
        None,
    )
    if baseline is not None:
        lines.append(
            f"Stage28 默认渲染近似为 `official_order` + top-8 + `stage28`，"
            f"其 clean answerable rate 为 `{baseline.clean_answerable_rate:.4f}`。"
        )
    if oracle:
        best_oracle = max(oracle, key=lambda row: row.clean_answerable_rate)
        lines.append(
            f"oracle answer-surface 上界最高达到 "
            f"`{best_oracle.clean_answerable_rate:.4f}`，用于衡量排序和截断仍有多少可解释空间。"
        )
    return "\n\n".join(lines) if lines else "未生成 Stage31 汇总结果。"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object in {path}")
            rows.append(payload)
    return rows


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return []


def _ordered_intersection(left: Iterable[str], right: Iterable[str]) -> list[str]:
    right_set = set(right)
    return [item for item in _dedupe(left) if item in right_set]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _avg(values: Iterable[float | int | None]) -> float:
    items = [float(value) for value in values if value is not None]
    return sum(items) / len(items) if items else 0.0


def _truncate(text: str, *, max_chars: int) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + " ..."


def _markdown_cell(text: str) -> str:
    return str(text).replace("|", "/")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Stage31 回答可用性离线消融。")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_stage31_answerability_poisoned20.yaml"),
    )
    args = parser.parse_args()
    rows = run_from_config(Stage31AnswerabilityConfig.from_yaml(args.config))
    print(f"stage31_ablation_rows={len(rows)}")


if __name__ == "__main__":
    main()
