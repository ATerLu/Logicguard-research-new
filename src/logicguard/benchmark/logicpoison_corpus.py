"""Deterministic LogicPoison global/logic stages, with explicit adaptation guards.

Mechanism reference: vendor/upstream/LogicPoison/src/{global,logic}_poison.py.
No evaluator labels, provider clients, or network access belong in this module.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from logicguard.core.run_state import fingerprint_json


def corpus_statistics(corpus: list[dict[str, Any]], nlp: Any) -> dict[str, list]:
    """Match upstream text-only NER, parenthesis spacing and frequency tie order."""
    counts: dict[str, Counter] = defaultdict(Counter)
    texts = (row["text"].replace("(", " ( ").replace(")", " ) ") for row in corpus)
    processed = 0
    for doc in nlp.pipe(texts, batch_size=32, n_process=1):
        processed += 1
        for entity in doc.ents:
            if not isinstance(entity.text, str) or not entity.text.strip():
                raise ValueError("NER returned invalid entity text")
            if not isinstance(entity.label_, str) or not entity.label_:
                raise ValueError("NER returned invalid entity type")
            counts[entity.label_][entity.text] += 1
    if processed != len(corpus):
        raise ValueError("NER did not return one result per corpus document")
    return {
        label: [[entity, count] for entity, count in counter.most_common()]
        for label, counter in counts.items()
    }


def replacement_plan(
    stats: dict[str, list], queries: list[dict[str, Any]], *, top_ratio: float
) -> dict[str, Any]:
    """Top-frequency + query-order pool, followed by a reverse circular mapping.

    Reject ambiguous entity surfaces across types instead of upstream's silent
    last-label-wins overwrite. Replacement remains surface-based, not contextual NER.
    """
    if not 0 < top_ratio <= 1:
        raise ValueError("top_ratio must be in (0, 1]")
    all_sets = {label: {entity for entity, _ in rows} for label, rows in stats.items()}
    selected: dict[str, list[str]] = defaultdict(list)
    origins: dict[tuple[str, str], list[str]] = defaultdict(list)
    excluded = []
    for query in queries:
        for entity in query["entities"]:
            label, surface = entity["type"], entity["entity"].strip()
            if surface not in all_sets.get(label, set()):
                excluded.append(
                    {"query_id": query["query_id"], "entity": surface, "type": label}
                )
                continue
            if surface not in selected[label]:
                selected[label].append(surface)
            key = (label, surface)
            if query["query_id"] not in origins[key]:
                origins[key].append(query["query_id"])
    surface_types: dict[str, set[str]] = defaultdict(set)
    for label, surfaces in all_sets.items():
        for surface in surfaces:
            surface_types[surface].add(label)
    mapping: dict[str, str] = {}
    details = []
    for label, entities in selected.items():
        frequent = [
            e for e, _ in stats[label][: max(1, int(len(stats[label]) * top_ratio))]
        ]
        pool = list(dict.fromkeys([*frequent, *entities]))
        if len(pool) < 2:
            continue
        for index, source in enumerate(pool):
            target = pool[index - 1]
            if len(surface_types[source]) != 1 or len(surface_types[target]) != 1:
                raise ValueError(
                    "ambiguous cross-type entity surface in replacement pool"
                )
            mapping[source] = target
            details.append(
                {
                    "source": source,
                    "target": target,
                    "type": label,
                    "source_query_ids": origins.get((label, source), []),
                    "source_in_frequency_pool": source in frequent,
                }
            )
    return {"mapping": mapping, "typed_mapping": details, "excluded_entities": excluded}


def rewrite_corpus(
    corpus: list[dict[str, Any]], plan: dict[str, Any], *, budget: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Single-pass longest-first boundary substitution; validate before publication."""
    mapping = plan["mapping"]
    keys = sorted(mapping, key=len, reverse=True)
    regex = (
        re.compile(r"(?<!\w)(" + "|".join(map(re.escape, keys)) + r")(?!\w)")
        if keys
        else None
    )
    typed = {row["source"]: row for row in plan["typed_mapping"]}
    poisoned, provenance = [], []
    total_replacements = 0
    for row in corpus:
        changes = []

        def replace(match: re.Match) -> str:
            source = match.group(1)
            changes.append(
                {
                    **typed[source],
                    "start_original": match.start(),
                    "end_original": match.end(),
                }
            )
            return mapping[source]

        text = regex.sub(replace, row["text"]) if regex else row["text"]
        new = {**row, "text": text}
        poisoned.append(new)
        if text != row["text"]:
            total_replacements += len(changes)
            provenance.append(
                {
                    "doc_id": row["_id"],
                    "clean_record_sha256": fingerprint_json(row),
                    "poisoned_record_sha256": fingerprint_json(new),
                    "replacements": changes,
                }
            )
    metrics = {
        "documents": len(corpus),
        "changed_documents": len(provenance),
        "changed_document_fraction": len(provenance) / len(corpus) if corpus else 0,
        "replacement_occurrences": total_replacements,
        "clean_text_utf8_bytes": sum(
            len(row["text"].encode("utf-8")) for row in corpus
        ),
        "poisoned_text_utf8_bytes": sum(
            len(row["text"].encode("utf-8")) for row in poisoned
        ),
    }
    exceeded = [
        name
        for name in (
            "changed_documents",
            "changed_document_fraction",
            "replacement_occurrences",
            "poisoned_text_utf8_bytes",
        )
        if metrics[name] > budget[f"max_{name}"]
    ]
    if exceeded:
        raise ValueError("poison budget exceeded: " + ",".join(exceeded))
    return poisoned, provenance, metrics
