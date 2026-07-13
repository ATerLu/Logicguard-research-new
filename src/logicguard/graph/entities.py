"""Entity extraction for the first lightweight GraphRAG baseline.

The first baseline deliberately uses deterministic rule-based extraction. It is
weaker than a trained NER model, but it has two advantages for early research:

1. It works offline without downloading a large spaCy model.
2. It makes retrieval errors reproducible, which is useful while building trace
   logging, poisoning hooks, and LogicGuard risk features.

Later phases can add a spaCy/LLM extractor behind the same `extract()` method.
"""

from __future__ import annotations

import re

from logicguard.graph.schemas import EntityMention


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CAPITALIZED_PHRASE_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,})(?:\s+(?:[A-Z][A-Za-z0-9]+|[A-Z]{2,}))*\b"
)
_PAREN_CONTENT_RE = re.compile(r"\(([^)]+)\)")
_YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")

_STOP_NORMALIZED = {
    "a",
    "an",
    "and",
    "april",
    "american",
    "are",
    "august",
    "british",
    "by",
    "december",
    "did",
    "do",
    "does",
    "february",
    "french",
    "from",
    "german",
    "he",
    "her",
    "his",
    "film",
    "in",
    "is",
    "it",
    "its",
    "january",
    "july",
    "june",
    "march",
    "may",
    "november",
    "october",
    "of",
    "september",
    "she",
    "their",
    "them",
    "the",
    "they",
    "this",
    "was",
    "when",
    "where",
    "were",
    "what",
    "which",
    "who",
    "why",
}


def normalize_entity(text: str) -> str:
    """Normalize an entity surface form into a stable graph key."""

    collapsed = _NON_ALNUM_RE.sub(" ", text.lower()).strip()
    return " ".join(collapsed.split())


class RuleBasedEntityExtractor:
    """Deterministic extractor for titles, named entities, and years.

    The extractor favors recall over precision. Extra entity nodes are acceptable
    in this baseline because LogicGuard will later inspect noisy paths; missing
    bridge entities are more damaging than carrying a few harmless phrase nodes.
    """

    def extract(self, text: str) -> list[EntityMention]:
        seen: set[str] = set()
        mentions: list[EntityMention] = []

        for surface in self._candidate_surfaces(text):
            normalized = normalize_entity(surface)
            if not normalized or normalized in seen or normalized in _STOP_NORMALIZED:
                continue
            seen.add(normalized)
            mentions.append(EntityMention(text=surface.strip(), normalized=normalized))

        return mentions

    def _candidate_surfaces(self, text: str) -> list[str]:
        """Return candidate entity-like strings in document order."""

        candidates: list[tuple[int, str]] = []
        for match in _CAPITALIZED_PHRASE_RE.finditer(text):
            candidates.append((match.start(), match.group(0)))
        for match in _PAREN_CONTENT_RE.finditer(text):
            candidates.append((match.start(), match.group(1)))
        for match in _YEAR_RE.finditer(text):
            candidates.append((match.start(), match.group(0)))

        candidates.sort(key=lambda item: item[0])
        return [surface for _, surface in candidates]
