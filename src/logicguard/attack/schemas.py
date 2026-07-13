"""Attack metadata contracts.

These objects describe controlled benchmark perturbations. They are not meant
to be a reusable real-world attack toolkit; they make local defensive evaluation
auditable by recording exactly which documents were modified and why.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class EntitySwapAttack:
    """Metadata for one controlled entity-swap poisoning operation."""

    attack_id: str
    query_id: str
    original_answer: str
    replacement_answer: str
    poisoned_doc_ids: list[str]
    strategy: str = "answer_entity_swap"

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BridgeInjectionAttack:
    """Metadata for one synthetic bridge-document injection."""

    attack_id: str
    query_id: str
    query_entity: str
    query_entity_surface: str
    original_answer: str
    replacement_answer: str
    poisoned_doc_ids: list[str]
    question: str = ""
    strategy: str = "bridge_injection"

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BridgeInjectionHitDetail:
    """Per-query retrieval detail for one bridge-injection attack."""

    attack_id: str
    query_id: str
    query_entity: str
    replacement_answer: str
    poisoned_doc_id: str
    first_rank: int | None
    retrieved_score: float | None
    exposed: bool

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PoisonedEvidenceExposure:
    """How often poisoned evidence appears in targeted query retrieval results."""

    targeted_queries: int
    exposed_queries: int
    exposure_rate: float
    top_k: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)
