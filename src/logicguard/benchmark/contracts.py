"""Adapter and metric contracts frozen for comparative benchmark v1.1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from logicguard.benchmark.schemas import AttackInstance


@dataclass(frozen=True, slots=True)
class AdapterContract:
    adapter_id: str
    kind: str
    method_name: str
    input_schema: str
    output_schema: str
    native_datasets: tuple[str, ...]
    native_backends: tuple[str, ...]
    endpoint_family: str | None
    implementation_status: str
    ranking_eligible: bool
    gold_access_allowed: bool = False
    notes: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


ATTACK_CONTRACTS: tuple[AdapterContract, ...] = (
    AdapterContract(
        "A1_poisonedrag",
        "attack",
        "PoisonedRAG black-box",
        "BenchmarkQuery",
        "AttackInstance+BenchmarkDocument[]",
        ("hotpotqa",),
        ("naive_rag",),
        "targeted_wrong_answer",
        "official_asset_contract_ready",
        True,
        notes="HotpotQA official overlap is a golden contract only; other cells are ports.",
    ),
    AdapterContract(
        "A2_logicpoison",
        "attack",
        "LogicPoison v1",
        "BenchmarkQuery+BenchmarkDocument[]",
        "AttackInstance+BenchmarkDocument[]",
        ("hotpotqa", "musique", "2wikimultihopqa"),
        ("microsoft_graphrag",),
        "clean_correct_attack_flip",
        "pinned_code_contract_ready",
        True,
        notes="Legacy local poisoned corpora remain legacy_adapted until provenance passes.",
    ),
    AdapterContract(
        "A3_gragpoison",
        "attack",
        "GraphRAG under Fire / GRAGPoison",
        "BenchmarkQuery[]",
        "AttackInstance+BenchmarkDocument[]",
        ("musique",),
        ("microsoft_graphrag", "lightrag"),
        "relation_targeted_or_untargeted",
        "official_asset_contract_ready",
        True,
        notes="The 14-query overlap is a golden contract, not an ASR estimate.",
    ),
    AdapterContract(
        "A4_badrag",
        "attack",
        "BadRAG/TrojRAG",
        "BenchmarkQuery[]+trigger_pairing",
        "AttackInstance+BenchmarkDocument[]",
        (),
        (),
        "trigger_payload_success",
        "blocked_faithful_reimplementation",
        False,
        notes="No verified official implementation/data asset; separate backdoor track.",
    ),
)


BACKEND_CONTRACTS: tuple[AdapterContract, ...] = (
    AdapterContract(
        "S1_microsoft_graphrag",
        "backend",
        "Microsoft GraphRAG official Local Search",
        "BenchmarkDocument[]+BenchmarkQuery",
        "RetrievalContextTrace",
        ("hotpotqa", "musique", "2wikimultihopqa"),
        ("microsoft_graphrag",),
        None,
        "local_runtime_contract_ready",
        True,
    ),
    AdapterContract(
        "S2_lightrag",
        "backend",
        "LightRAG official hybrid mode",
        "BenchmarkDocument[]+BenchmarkQuery",
        "RetrievalContextTrace",
        ("musique", "hotpotqa"),
        ("lightrag",),
        None,
        "local_runtime_contract_ready",
        True,
        notes="Official v1.5.7 hybrid mode in an isolated local environment.",
    ),
)


DEFENSE_CONTRACTS: tuple[AdapterContract, ...] = (
    AdapterContract(
        "D0_no_defense",
        "defense",
        "No defense",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        (),
        (),
        None,
        "contract_ready",
        True,
    ),
    AdapterContract(
        "D1_query_paraphrase",
        "defense",
        "Query paraphrasing",
        "BenchmarkQuery",
        "BenchmarkQuery",
        ("hotpotqa", "musique"),
        ("microsoft_graphrag", "lightrag"),
        None,
        "official_baseline_contract_ready",
        True,
    ),
    AdapterContract(
        "D2_ppl_pti",
        "defense",
        "PPL/PTI filtering",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        ("hotpotqa", "musique"),
        ("microsoft_graphrag", "lightrag"),
        None,
        "official_baseline_contract_ready",
        True,
    ),
    AdapterContract(
        "D3_ragdefender",
        "defense",
        "RAGDefender",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        ("hotpotqa",),
        ("naive_rag",),
        None,
        "pinned_code_contract_ready",
        True,
    ),
    AdapterContract(
        "D4_hog_grag",
        "defense",
        "HoG-GRAG",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        ("hotpotqa", "musique"),
        ("microsoft_graphrag", "lightrag"),
        None,
        "pinned_code_contract_ready",
        True,
    ),
    AdapterContract(
        "D5_logicguard_stage43_45",
        "defense",
        "LogicGuard Stage43-45 frozen",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        ("hotpotqa", "musique"),
        ("microsoft_graphrag",),
        None,
        "existing_frozen_baseline",
        True,
    ),
    AdapterContract(
        "D6_logicguard_full",
        "defense",
        "LogicGuard full dual-track",
        "RetrievalContextTrace",
        "RetrievalContextTrace",
        ("hotpotqa", "musique", "2wikimultihopqa"),
        ("microsoft_graphrag", "lightrag"),
        None,
        "interface_only_method_incomplete",
        False,
    ),
    AdapterContract(
        "D7_oracle_clean_recovery",
        "defense",
        "Oracle clean recovery",
        "RetrievalContextTrace+evaluator_gold",
        "RetrievalContextTrace",
        (),
        (),
        None,
        "contract_ready",
        False,
        True,
        "Upper bound only; excluded from realistic ranking.",
    ),
)


def validate_contract_registry(contracts: Iterable[AdapterContract]) -> None:
    """Reject duplicate/malformed contracts before a matrix is generated."""

    items = tuple(contracts)
    identifiers = [item.adapter_id for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("adapter IDs must be unique")
    for item in items:
        if item.kind not in {"attack", "backend", "defense"}:
            raise ValueError(f"unsupported adapter kind: {item.kind}")
        if not item.adapter_id or not item.method_name:
            raise ValueError("adapter ID and method name are required")
        if item.kind == "attack" and not item.endpoint_family:
            raise ValueError(f"attack {item.adapter_id} has no endpoint family")
        if item.gold_access_allowed and item.adapter_id != "D7_oracle_clean_recovery":
            raise ValueError("only the oracle contract may access evaluator gold")


def validate_attack_instance(instance: AttackInstance) -> None:
    """Validate method-specific semantics without evaluating an answer."""

    contracts = {item.adapter_id: item for item in ATTACK_CONTRACTS}
    if instance.attack_id not in contracts:
        raise ValueError(f"unregistered attack adapter: {instance.attack_id}")
    contract = contracts[instance.attack_id]
    if instance.endpoint_family != contract.endpoint_family:
        raise ValueError(
            f"endpoint mismatch for {instance.attack_id}: "
            f"{instance.endpoint_family} != {contract.endpoint_family}"
        )
    if instance.attack_id == "A1_poisonedrag" and not instance.target_answer:
        raise ValueError("PoisonedRAG requires an attacker-specified target answer")
    if instance.attack_id == "A2_logicpoison" and (
        instance.target_answer or instance.trigger
    ):
        raise ValueError("LogicPoison v1 is scored as a clean-correct attack flip")
    if instance.attack_id == "A3_gragpoison":
        mode = instance.metadata.get("attack_mode")
        if mode not in {"targeted", "untargeted"}:
            raise ValueError("GRAGPoison requires attack_mode=targeted|untargeted")
        if mode == "targeted" and not instance.target_answer:
            raise ValueError("targeted GRAGPoison requires target_answer")
    if instance.attack_id == "A4_badrag" and not instance.trigger:
        raise ValueError("BadRAG requires an explicit trigger")


for registry in (ATTACK_CONTRACTS, BACKEND_CONTRACTS, DEFENSE_CONTRACTS):
    validate_contract_registry(registry)
