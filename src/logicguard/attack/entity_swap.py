"""Controlled entity-swap poisoning for local benchmark evaluation.

The first attack is intentionally narrow: replace a target sample's gold answer
string inside its own support documents with another benchmark answer. This
creates a poisoned evidence source that is easy to audit and suitable for
testing whether downstream retrieval exposes modified documents.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from logicguard.attack.schemas import EntitySwapAttack, PoisonedEvidenceExposure
from logicguard.data.schemas import CorpusDocument, NormalizedSample
from logicguard.graph.entities import normalize_entity
from logicguard.graph.schemas import RetrievalTrace


def select_entity_swap_attacks(
    samples: list[NormalizedSample],
    max_attacks: int,
) -> list[EntitySwapAttack]:
    """Select deterministic answer-swap attacks from normalized samples.

    A sample is attackable when its exact answer string appears in at least one
    support document title or body. The replacement answer is taken from the
    next sample with a different normalized answer, which keeps the attack fully
    reproducible without LLM generation.
    """

    attacks: list[EntitySwapAttack] = []
    for index, sample in enumerate(samples):
        if len(attacks) >= max_attacks:
            break
        poisoned_doc_ids = _support_docs_containing_answer(sample)
        if not poisoned_doc_ids:
            continue
        replacement = _next_distinct_answer(samples, index, sample.answer)
        if replacement is None:
            continue
        attacks.append(
            EntitySwapAttack(
                attack_id=f"entity_swap_{len(attacks):04d}",
                query_id=sample.query_id,
                original_answer=sample.answer,
                replacement_answer=replacement,
                poisoned_doc_ids=poisoned_doc_ids,
            )
        )
    return attacks


def apply_entity_swap_attacks(
    corpus_documents: list[CorpusDocument],
    attacks: list[EntitySwapAttack],
) -> dict[str, CorpusDocument]:
    """Return a corpus lookup with target documents rewritten."""

    attack_by_doc: dict[str, list[EntitySwapAttack]] = {}
    for attack in attacks:
        for doc_id in attack.poisoned_doc_ids:
            attack_by_doc.setdefault(doc_id, []).append(attack)

    poisoned: dict[str, CorpusDocument] = {}
    for document in corpus_documents:
        title = document.title
        text = document.text
        for attack in attack_by_doc.get(document.doc_id, []):
            title = _case_insensitive_replace(title, attack.original_answer, attack.replacement_answer)
            text = _case_insensitive_replace(text, attack.original_answer, attack.replacement_answer)
        poisoned[document.doc_id] = CorpusDocument(
            doc_id=document.doc_id,
            title=title,
            text=text,
        )
    return poisoned


def calculate_poisoned_evidence_exposure(
    traces: list[RetrievalTrace],
    attacks: list[EntitySwapAttack],
    top_k: int,
) -> PoisonedEvidenceExposure:
    """Measure whether poisoned docs appear in top-k for targeted queries."""

    attack_by_query = {attack.query_id: attack for attack in attacks}
    targeted = 0
    exposed = 0
    for trace in traces:
        attack = attack_by_query.get(trace.query_id)
        if attack is None:
            continue
        targeted += 1
        retrieved_doc_ids = {candidate.doc_id for candidate in trace.candidates[:top_k]}
        if retrieved_doc_ids.intersection(attack.poisoned_doc_ids):
            exposed += 1
    exposure_rate = exposed / targeted if targeted else 0.0
    return PoisonedEvidenceExposure(
        targeted_queries=targeted,
        exposed_queries=exposed,
        exposure_rate=exposure_rate,
        top_k=top_k,
    )


def write_attacks_jsonl(path: Path, attacks: list[EntitySwapAttack]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for attack in attacks:
            handle.write(json.dumps(attack.to_json_dict(), ensure_ascii=False) + "\n")


def write_poisoned_corpus_jsonl(path: Path, poisoned_corpus: dict[str, CorpusDocument]) -> None:
    """Write a BEIR-like corpus JSONL file for inspection and reruns."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for doc_id in sorted(poisoned_corpus, key=_stable_doc_sort_key):
            document = poisoned_corpus[doc_id]
            payload = {"_id": document.doc_id, "title": document.title, "text": document.text}
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _support_docs_containing_answer(sample: NormalizedSample) -> list[str]:
    matches: list[str] = []
    for document in sample.support_docs:
        haystack = f"{document.title}\n{document.text}"
        if _contains_case_insensitive(haystack, sample.answer):
            matches.append(document.doc_id)
    return matches


def _next_distinct_answer(
    samples: list[NormalizedSample],
    start_index: int,
    original_answer: str,
) -> str | None:
    original_normalized = normalize_entity(original_answer)
    original_shape = _answer_shape(original_answer)
    fallback: str | None = None
    for offset in range(1, len(samples)):
        candidate = samples[(start_index + offset) % len(samples)].answer
        if normalize_entity(candidate) == original_normalized:
            continue
        if _answer_shape(candidate) == original_shape:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _answer_shape(answer: str) -> tuple[bool, int]:
    """Coarse type proxy used before a real entity typer exists.

    The shape is intentionally simple: whether the answer contains a digit and
    how many normalized tokens it has. This avoids the most jarring swaps, such
    as replacing a two-token person name with a three-token organization, while
    keeping the first attack generator deterministic and dependency-free.
    """

    normalized = normalize_entity(answer)
    token_count = len(normalized.split())
    has_digit = any(char.isdigit() for char in normalized)
    return (has_digit, token_count)


def _contains_case_insensitive(text: str, needle: str) -> bool:
    return re.search(re.escape(needle), text, flags=re.IGNORECASE) is not None


def _case_insensitive_replace(text: str, old: str, new: str) -> str:
    return re.sub(re.escape(old), new, text, flags=re.IGNORECASE)


def _stable_doc_sort_key(doc_id: str) -> tuple[int, int | str]:
    if doc_id.isdigit():
        return (0, int(doc_id))
    return (1, doc_id)
