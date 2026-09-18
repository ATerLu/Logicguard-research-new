"""Versioned, attack-agnostic schemas for the v1.1 comparative benchmark.

These contracts deliberately separate attacker-visible records from evaluator-only
gold data.  Adapters exchange these objects instead of method-specific dictionaries,
which prevents a targeted-ASR implementation from silently being reused for an
untargeted logical attack or a trigger backdoor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Mapping


SCHEMA_VERSION = "comparison-v1.1"


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class BenchmarkQuery:
    """Attacker-safe query record; it contains no answer or support labels."""

    dataset: str
    query_id: str
    question: str
    split: str
    stratum: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("dataset", "query_id", "question", "split", "stratum"):
            _require_text(name, getattr(self, name))
        if self.split not in {"development", "validation", "locked_test"}:
            raise ValueError(f"unsupported split: {self.split}")

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkDocument:
    """One clean or poisoned document with explicit lineage."""

    dataset: str
    document_id: str
    title: str
    text: str
    corpus_variant: str
    source_document_ids: tuple[str, ...] = ()
    attack_instance_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("dataset", "document_id", "text", "corpus_variant"):
            _require_text(name, getattr(self, name))
        if self.corpus_variant not in {"clean", "poisoned", "recovered"}:
            raise ValueError(f"unsupported corpus_variant: {self.corpus_variant}")
        if self.corpus_variant == "poisoned" and not self.attack_instance_id:
            raise ValueError("poisoned documents require attack_instance_id")

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AttackInstance:
    """Frozen output of one attack adapter before indexing or evaluation."""

    attack_id: str
    instance_id: str
    dataset: str
    query_id: str
    threat_track: str
    endpoint_family: str
    fidelity: str
    malicious_document_ids: tuple[str, ...]
    target_answer: str | None = None
    trigger: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("attack_id", "instance_id", "dataset", "query_id"):
            _require_text(name, getattr(self, name))
        if self.threat_track not in {"wrong_answer", "logical", "backdoor"}:
            raise ValueError(f"unsupported threat_track: {self.threat_track}")
        if self.fidelity not in {
            "paper_native",
            "dataset_port",
            "backend_port",
            "reimplementation",
            "legacy_adapted",
        }:
            raise ValueError(f"unsupported fidelity: {self.fidelity}")
        if not self.malicious_document_ids:
            raise ValueError("attack instance must reference a malicious document")

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetrievalContextTrace:
    """Corpus-to-prompt trace shared by GraphRAG and LightRAG adapters."""

    instance_id: str
    backend_id: str
    defense_id: str
    corpus_modified: bool
    index_included: bool
    graph_surfaced: bool
    retrieved_document_ids: tuple[str, ...]
    prompt_document_ids: tuple[str, ...]
    prompt_sha256: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("instance_id", "backend_id", "defense_id", "prompt_sha256"):
            _require_text(name, getattr(self, name))
        if not self.corpus_modified and (self.index_included or self.graph_surfaced):
            raise ValueError("an unmodified corpus cannot include/surface poison")
        if self.graph_surfaced and not self.index_included:
            raise ValueError("graph_surfaced requires index_included")

    @property
    def retrieved(self) -> bool:
        return bool(self.retrieved_document_ids)

    @property
    def prompt_exposed(self) -> bool:
        return bool(self.prompt_document_ids)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["retrieved"] = self.retrieved
        payload["prompt_exposed"] = self.prompt_exposed
        return payload


@dataclass(frozen=True, slots=True)
class AnswerEvaluation:
    """Answer-level outcome with an explicitly named threat-native endpoint."""

    instance_id: str
    backend_id: str
    defense_id: str
    answered: bool
    exact_match: float
    token_f1: float
    threat_native_success: bool
    endpoint_family: str
    abstained: bool = False
    recovery_outcome: str = "none"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("instance_id", "backend_id", "defense_id", "endpoint_family"):
            _require_text(name, getattr(self, name))
        for name, value in (
            ("exact_match", self.exact_match),
            ("token_f1", self.token_f1),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.recovery_outcome not in {"correct", "wrong", "none", "ambiguous"}:
            raise ValueError(f"unsupported recovery_outcome: {self.recovery_outcome}")
        if self.abstained and self.answered:
            raise ValueError("an abstention cannot also be marked answered")

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FunnelCounts:
    """The only valid v1.1 corpus-to-answer funnel and its monotonic validator."""

    STAGES: ClassVar[tuple[str, ...]] = (
        "attempted",
        "generation_valid",
        "evaluation_valid",
        "corpus_modified",
        "index_included",
        "graph_surfaced",
        "retrieved",
        "prompt_exposed",
        "answered",
        "threat_native_success",
    )

    attempted: int
    generation_valid: int
    evaluation_valid: int
    corpus_modified: int
    index_included: int
    graph_surfaced: int
    retrieved: int
    prompt_exposed: int
    answered: int
    threat_native_success: int

    def __post_init__(self) -> None:
        values = [getattr(self, stage) for stage in self.STAGES]
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("all funnel counts must be non-negative integers")
        for previous, current, previous_name, current_name in zip(
            values[:-1], values[1:], self.STAGES[:-1], self.STAGES[1:], strict=True
        ):
            if current > previous:
                raise ValueError(
                    f"funnel is non-monotonic: {current_name}={current} exceeds "
                    f"{previous_name}={previous}"
                )

    @classmethod
    def from_mapping(cls, values: Mapping[str, int]) -> "FunnelCounts":
        missing = set(cls.STAGES) - set(values)
        extra = set(values) - set(cls.STAGES)
        if missing or extra:
            raise ValueError(
                f"funnel stage mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
            )
        return cls(**{stage: values[stage] for stage in cls.STAGES})

    def rate(self, numerator: str, denominator: str = "attempted") -> float:
        if numerator not in self.STAGES or denominator not in self.STAGES:
            raise KeyError("rate stages must be registered funnel stages")
        denominator_value = getattr(self, denominator)
        return (
            getattr(self, numerator) / denominator_value if denominator_value else 0.0
        )

    def to_json_dict(self) -> dict[str, int]:
        return {stage: getattr(self, stage) for stage in self.STAGES}
