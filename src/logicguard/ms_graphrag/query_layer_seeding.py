"""Build non-gold entity seed plans for Microsoft GraphRAG local search."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

from logicguard.core.config import find_project_root, resolve_config_path
from rank_bm25 import BM25Plus


_DOC_ID_PATTERN = re.compile(r"^Document ID:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_TITLE_PATTERN = re.compile(r"^Title:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "earlier",
    "film",
    "has",
    "is",
    "of",
    "or",
    "the",
    "was",
    "which",
    "who",
    "whose",
}
_FORBIDDEN_OUTPUT_KEYS = {
    "answer",
    "support_doc_ids",
    "support_docs",
    "expected_answer",
}


@dataclass(frozen=True, slots=True)
class QueryRecord:
    """The only sample fields visible to candidate generation."""

    query_id: str
    query: str

    def to_json_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QueryLayerSeedSettings:
    """Controls for BM25 seeding and repeated-cluster detection."""

    top_title_documents: int = 2
    entities_per_document: int = 4
    top_lexical_entities: int = 6
    max_include_entities: int = 10
    repeated_entity_min_queries: int = 2


@dataclass(frozen=True, slots=True)
class QueryLayerSeedingConfig:
    """Project-relative configuration for one Stage20 seed run."""

    dataset: str
    sample_path: Path
    entities_path: Path
    text_units_path: Path
    baseline_context_path: Path
    output_path: Path
    report_path: Path
    max_queries: int
    settings: QueryLayerSeedSettings
    emit_markdown_report: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> "QueryLayerSeedingConfig":
        path = resolve_config_path(path)
        project_root = find_project_root(path)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))

        def resolve(raw: str) -> Path:
            candidate = Path(raw)
            if candidate.is_absolute():
                return candidate.resolve()
            return (project_root / candidate).resolve()

        raw_settings = payload.get("seed_settings", {})
        return cls(
            dataset=str(payload["dataset"]),
            sample_path=resolve(str(payload["sample_path"])),
            entities_path=resolve(str(payload["entities_path"])),
            text_units_path=resolve(str(payload["text_units_path"])),
            baseline_context_path=resolve(str(payload["baseline_context_path"])),
            output_path=resolve(str(payload["seed_plan_output_path"])),
            report_path=resolve(str(payload["seed_plan_report_path"])),
            max_queries=int(payload.get("max_queries", 5)),
            emit_markdown_report=bool(payload.get("emit_markdown_report", True)),
            settings=QueryLayerSeedSettings(
                top_title_documents=int(raw_settings.get("top_title_documents", 2)),
                entities_per_document=int(raw_settings.get("entities_per_document", 4)),
                top_lexical_entities=int(raw_settings.get("top_lexical_entities", 6)),
                max_include_entities=int(raw_settings.get("max_include_entities", 10)),
                repeated_entity_min_queries=int(
                    raw_settings.get("repeated_entity_min_queries", 2)
                ),
            ),
        )


def load_query_records(path: Path, *, max_queries: int) -> list[QueryRecord]:
    """Discard answer and support fields before planning starts."""

    return [
        QueryRecord(query_id=str(row["query_id"]), query=str(row["query"]))
        for row in _load_jsonl(path)[:max_queries]
    ]


def build_query_seed_plans(
    *,
    query_rows: list[QueryRecord | dict[str, Any]],
    entities_frame: pd.DataFrame,
    text_units_frame: pd.DataFrame,
    baseline_context_rows: list[dict[str, Any]],
    settings: QueryLayerSeedSettings,
) -> list[dict[str, Any]]:
    """Build method-specific entity includes and excludes without gold data."""

    queries = [_as_query_record(row) for row in query_rows]
    entities = _entity_records(entities_frame)
    entity_by_id = {row["id"]: row for row in entities}
    entity_by_name = {row["title"].casefold(): row for row in entities}
    documents = _document_records(text_units_frame)
    title_ranker = _Bm25Ranker([row["title"] for row in documents])
    entity_ranker = _Bm25Ranker(
        [f"{row['title']} {row['description']}" for row in entities]
    )
    repeated = _repeated_baseline_entities(
        baseline_context_rows,
        minimum_queries=settings.repeated_entity_min_queries,
    )

    plans: list[dict[str, Any]] = []
    for query_record in queries:
        title_candidates = _rank_title_candidates(
            query_record.query,
            documents,
            title_ranker,
            settings.top_title_documents,
        )
        title_details = _map_title_entities(
            query_record.query,
            title_candidates,
            entity_by_id,
            settings.entities_per_document,
        )
        lexical_details = _rank_lexical_entities(
            query_record.query,
            entities,
            entity_ranker,
            settings.top_lexical_entities,
        )
        title_names = [row["entity"] for row in title_details]
        lexical_names = [row["entity"] for row in lexical_details]
        anomalies = _find_anomalies(
            query=query_record.query,
            repeated_entities=repeated,
            protected_entities=set(title_names),
            entity_by_name=entity_by_name,
        )
        full_include = _deduplicate(title_names + lexical_names)[
            : settings.max_include_entities
        ]
        full_exclude = [name for name in anomalies if name not in set(full_include)]
        plan = {
            "query_id": query_record.query_id,
            "query": query_record.query,
            "title_candidates": title_candidates,
            "title_seed_entities": title_names,
            "title_seed_details": title_details,
            "lexical_entity_candidates": lexical_details,
            "anomalous_entities": anomalies,
            "methods": {
                "all_entities_baseline": {
                    "include_entity_names": [],
                    "exclude_entity_names": [],
                },
                "title_seeding": {
                    "include_entity_names": title_names[
                        : settings.max_include_entities
                    ],
                    "exclude_entity_names": [],
                },
                "entity_rerank": {
                    "include_entity_names": lexical_names[
                        : settings.max_include_entities
                    ],
                    "exclude_entity_names": [],
                },
                "cluster_suppression": {
                    "include_entity_names": [],
                    "exclude_entity_names": anomalies,
                },
                "full_query_guard": {
                    "include_entity_names": full_include,
                    "exclude_entity_names": full_exclude,
                },
            },
        }
        _assert_no_gold_fields(plan)
        plans.append(plan)
    return plans


def run_from_config(config: QueryLayerSeedingConfig) -> list[dict[str, Any]]:
    """Write seed JSONL and a Chinese audit report."""

    plans = build_query_seed_plans(
        query_rows=load_query_records(
            config.sample_path, max_queries=config.max_queries
        ),
        entities_frame=pd.read_parquet(config.entities_path),
        text_units_frame=pd.read_parquet(config.text_units_path),
        baseline_context_rows=_load_jsonl(config.baseline_context_path),
        settings=config.settings,
    )
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    with config.output_path.open("w", encoding="utf-8") as handle:
        for plan in plans:
            handle.write(json.dumps(plan, ensure_ascii=False) + "\n")
    if config.emit_markdown_report:
        _write_seed_report(config, plans)
    return plans


class _Bm25Ranker:
    """Use BM25Plus so small two-document fixtures retain positive IDF."""

    def __init__(self, texts: list[str]) -> None:
        tokenized = [_tokenize(text) for text in texts]
        self._size = len(tokenized)
        self._ranker = BM25Plus(tokenized) if tokenized else None

    def scores(self, query: str) -> list[float]:
        if self._ranker is None:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return [0.0] * self._size
        return [float(score) for score in self._ranker.get_scores(tokens)]


def _document_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        text = str(row.get("text", ""))
        title = _metadata_value(_TITLE_PATTERN, text)
        doc_id = _metadata_value(_DOC_ID_PATTERN, text)
        if title and doc_id:
            records.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "text_unit_id": str(row.get("id", "")),
                    "entity_ids": [
                        str(value) for value in _as_list(row.get("entity_ids"))
                    ],
                }
            )
    return records


def _entity_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        title = str(row.get("title", "")).strip()
        if title:
            records.append(
                {
                    "id": str(row.get("id", "")),
                    "title": title,
                    "description": str(row.get("description", "")),
                    "degree": int(row.get("degree", 0) or 0),
                }
            )
    return records


def _rank_title_candidates(
    query: str,
    documents: list[dict[str, Any]],
    ranker: _Bm25Ranker,
    limit: int,
) -> list[dict[str, Any]]:
    query_tokens = set(_tokenize(query))
    ranked: list[tuple[int, float, dict[str, Any]]] = []
    for document, score in zip(documents, ranker.scores(query), strict=True):
        overlap = len(query_tokens.intersection(_tokenize(document["title"])))
        if overlap:
            ranked.append((overlap, score, document))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]["title"].casefold()))
    return [
        {
            **item[2],
            "bm25_score": round(item[1], 6),
            "token_overlap": item[0],
        }
        for item in ranked[:limit]
    ]


def _map_title_entities(
    query: str,
    candidates: list[dict[str, Any]],
    entity_by_id: dict[str, dict[str, Any]],
    per_document: int,
) -> list[dict[str, Any]]:
    query_tokens = set(_tokenize(query))
    normalized_query = _normalize_text(query)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        mapped = [
            entity_by_id[entity_id]
            for entity_id in candidate["entity_ids"]
            if entity_id in entity_by_id
        ]
        mapped.sort(
            key=lambda entity: (
                -int(_normalize_text(entity["title"]) in normalized_query),
                -len(query_tokens.intersection(_tokenize(entity["title"]))),
                -entity["degree"],
                entity["title"].casefold(),
            )
        )
        for entity in mapped[:per_document]:
            if entity["title"] in seen:
                continue
            seen.add(entity["title"])
            selected.append(
                {
                    "entity": entity["title"],
                    "source_doc_id": candidate["doc_id"],
                    "source_title": candidate["title"],
                    "lexical_overlap": len(
                        query_tokens.intersection(_tokenize(entity["title"]))
                    ),
                    "degree": entity["degree"],
                    "reason": "title_document_entity",
                }
            )
    return selected


def _rank_lexical_entities(
    query: str,
    entities: list[dict[str, Any]],
    ranker: _Bm25Ranker,
    limit: int,
) -> list[dict[str, Any]]:
    query_tokens = set(_tokenize(query))
    ranked: list[tuple[int, float, int, dict[str, Any]]] = []
    for entity, score in zip(entities, ranker.scores(query), strict=True):
        overlap = len(query_tokens.intersection(_tokenize(entity["title"])))
        if overlap:
            ranked.append((overlap, score, entity["degree"], entity))
    ranked.sort(
        key=lambda item: (-item[0], -item[1], -item[2], item[3]["title"].casefold())
    )
    return [
        {
            "entity": item[3]["title"],
            "bm25_score": round(item[1], 6),
            "lexical_overlap": item[0],
            "degree": item[2],
            "reason": "entity_lexical_match",
        }
        for item in ranked[:limit]
    ]


def _repeated_baseline_entities(
    rows: list[dict[str, Any]],
    *,
    minimum_queries: int,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        context = row.get("context_data", {})
        entity_rows = context.get("entities", []) if isinstance(context, dict) else []
        names = {
            str(entity.get("entity") or entity.get("title") or "").strip()
            for entity in entity_rows
            if isinstance(entity, dict)
        }
        counts.update(name for name in names if name)
    return {name: count for name, count in counts.items() if count >= minimum_queries}


def _find_anomalies(
    *,
    query: str,
    repeated_entities: dict[str, int],
    protected_entities: set[str],
    entity_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    query_tokens = set(_tokenize(query))
    anomalies: list[tuple[int, str]] = []
    for name, count in repeated_entities.items():
        entity = entity_by_name.get(name.casefold())
        canonical_name = entity["title"] if entity else name
        if canonical_name in protected_entities:
            continue
        if query_tokens.intersection(_tokenize(canonical_name)):
            continue
        anomalies.append((count, canonical_name))
    anomalies.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [name for _, name in anomalies]


def _write_seed_report(
    config: QueryLayerSeedingConfig, plans: list[dict[str, Any]]
) -> None:
    table = [
        "| query_id | 标题候选 | title seeds | lexical seeds | anomaly excludes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for plan in plans:
        table.append(
            "| "
            + " | ".join(
                [
                    str(plan["query_id"]),
                    ", ".join(row["title"] for row in plan["title_candidates"]),
                    ", ".join(plan["title_seed_entities"]),
                    ", ".join(
                        row["entity"] for row in plan["lexical_entity_candidates"]
                    ),
                    ", ".join(plan["anomalous_entities"]),
                ]
            )
            + " |"
        )
    content = "\n".join(
        [
            "# Microsoft GraphRAG Stage20 Query Seed审计报告",
            "",
            "## 目的",
            "",
            "只使用query文本和poisoned mixed graph索引元数据生成实体计划，禁止读取gold答案和support标注。",
            "",
            "## 指标说明",
            "",
            "- 标题候选：标题BM25命中的text unit文档。",
            "- title seeds：由标题候选的entity_ids映射得到的实体。",
            "- lexical seeds：实体标题与query存在词面重叠的候选。",
            "- anomaly excludes：跨query重复且与当前query词面无关的baseline实体。",
            "",
            "## Query级计划",
            "",
            *table,
            "",
            "## 产物",
            "",
            f"- seed plan：{config.output_path.as_posix()}",
            f"- query数：{len(plans)}",
            "- gold字段审计：通过；输出不含answer/support_doc字段。",
            "",
        ]
    )
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(content, encoding="utf-8")


def _assert_no_gold_fields(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_OUTPUT_KEYS.intersection(value)
        if forbidden:
            raise ValueError(
                f"Seed plan contains forbidden gold fields: {sorted(forbidden)}"
            )
        for nested in value.values():
            _assert_no_gold_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_gold_fields(nested)


def _as_query_record(value: QueryRecord | dict[str, Any]) -> QueryRecord:
    if isinstance(value, QueryRecord):
        return value
    return QueryRecord(query_id=str(value["query_id"]), query=str(value["query"]))


def _metadata_value(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group("value").strip() if match else ""


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in (raw.casefold() for raw in _TOKEN_PATTERN.findall(value))
        if token not in _STOPWORDS and len(token) > 1
    ]


def _normalize_text(value: str) -> str:
    """Normalize text without stopword removal for exact phrase checks."""

    return " ".join(raw.casefold() for raw in _TOKEN_PATTERN.findall(value))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _deduplicate(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected JSON object in {path}")
                rows.append(payload)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Stage20 non-gold entity seed plans."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/ms_graphrag_query_layer_stage20.yaml"),
    )
    args = parser.parse_args()
    plans = run_from_config(QueryLayerSeedingConfig.from_yaml(args.config))
    print(f"stage20_seed_plans={len(plans)}")


if __name__ == "__main__":
    main()
