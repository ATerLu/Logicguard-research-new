"""Offline adapters used to validate benchmark boundaries before E1.

The classes in this module normalize saved records only.  They never call a
model provider, generate an attack, index a corpus, or score against gold.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from logicguard.benchmark.contracts import validate_attack_instance
from logicguard.benchmark.schemas import (
    AttackInstance,
    BenchmarkDocument,
    RetrievalContextTrace,
)
from logicguard.core.run_state import fingerprint_json


@dataclass(frozen=True, slots=True)
class AdaptedAttack:
    """Attacker output plus evaluator labels kept in a separate envelope."""

    instance: AttackInstance
    documents: tuple[BenchmarkDocument, ...]
    evaluator_only: Mapping[str, Any]


class PoisonedRAGOfficialAdapter:
    adapter_id = "A1_poisonedrag"

    @staticmethod
    def adapt(dataset: str, record: Mapping[str, Any]) -> AdaptedAttack:
        required = {"id", "question", "correct answer", "incorrect answer", "adv_texts"}
        missing = required - set(record)
        if missing:
            raise ValueError(f"PoisonedRAG record missing fields: {sorted(missing)}")
        query_id = str(record["id"])
        malicious_texts = tuple(str(text) for text in record["adv_texts"])
        if len(malicious_texts) != 5 or any(
            not text.strip() for text in malicious_texts
        ):
            raise ValueError(
                "official PoisonedRAG fixture requires five non-empty texts"
            )
        instance_id = (
            "prag-"
            + fingerprint_json(
                {"dataset": dataset, "query_id": query_id, "texts": malicious_texts}
            )[:20]
        )
        document_ids = tuple(
            f"{instance_id}-document-{index}" for index in range(len(malicious_texts))
        )
        instance = AttackInstance(
            attack_id=PoisonedRAGOfficialAdapter.adapter_id,
            instance_id=instance_id,
            dataset=dataset,
            query_id=query_id,
            threat_track="wrong_answer",
            endpoint_family="targeted_wrong_answer",
            fidelity="paper_native" if dataset == "hotpotqa" else "dataset_port",
            malicious_document_ids=document_ids,
            target_answer=str(record["incorrect answer"]),
            metadata={"paper_native_document_budget": 5},
        )
        documents = tuple(
            BenchmarkDocument(
                dataset=dataset,
                document_id=document_id,
                title="",
                text=text,
                corpus_variant="poisoned",
                attack_instance_id=instance_id,
            )
            for document_id, text in zip(document_ids, malicious_texts, strict=True)
        )
        validate_attack_instance(instance)
        return AdaptedAttack(
            instance=instance,
            documents=documents,
            evaluator_only={"gold_answer": str(record["correct answer"])},
        )


class LogicPoisonPairAdapter:
    adapter_id = "A2_logicpoison"

    @staticmethod
    def adapt(
        *,
        dataset: str,
        query_id: str,
        clean_document: Mapping[str, Any],
        poisoned_document: Mapping[str, Any],
        fidelity: str = "legacy_adapted",
    ) -> AdaptedAttack:
        clean_id = str(clean_document.get("_id", ""))
        poisoned_id = str(poisoned_document.get("_id", ""))
        if not clean_id or clean_id != poisoned_id:
            raise ValueError("LogicPoison pair must preserve document identity")
        if dict(clean_document) == dict(poisoned_document):
            raise ValueError("LogicPoison pair must contain a changed document")
        instance_id = (
            "logicpoison-"
            + fingerprint_json(
                {
                    "dataset": dataset,
                    "query_id": query_id,
                    "document": poisoned_document,
                }
            )[:20]
        )
        instance = AttackInstance(
            attack_id=LogicPoisonPairAdapter.adapter_id,
            instance_id=instance_id,
            dataset=dataset,
            query_id=query_id,
            threat_track="logical",
            endpoint_family="clean_correct_attack_flip",
            fidelity=fidelity,
            malicious_document_ids=(poisoned_id,),
            metadata={"rewrite_semantics": "same_document_id"},
        )
        document = BenchmarkDocument(
            dataset=dataset,
            document_id=poisoned_id,
            title=str(poisoned_document.get("title", "")),
            text=str(poisoned_document.get("text", "")),
            corpus_variant="poisoned",
            source_document_ids=(clean_id,),
            attack_instance_id=instance_id,
        )
        validate_attack_instance(instance)
        return AdaptedAttack(
            instance=instance, documents=(document,), evaluator_only={}
        )


class GRAGPoisonAdapter:
    adapter_id = "A3_gragpoison"

    @staticmethod
    def validate_official_question(record: Mapping[str, Any]) -> None:
        required = {"id", "question", "question_decomposition", "paragraphs"}
        missing = required - set(record)
        if missing:
            raise ValueError(f"GRAGPoison question missing fields: {sorted(missing)}")
        if len(record["question_decomposition"]) < 2:
            raise ValueError("GRAGPoison golden question must be multi-hop")

    @staticmethod
    def adapt_generated(record: Mapping[str, Any]) -> AdaptedAttack:
        required = {"dataset", "query_id", "attack_mode", "malicious_texts"}
        missing = required - set(record)
        if missing:
            raise ValueError(
                f"GRAGPoison generated record missing fields: {sorted(missing)}"
            )
        texts = tuple(str(text) for text in record["malicious_texts"])
        if not texts:
            raise ValueError("GRAGPoison requires at least one malicious text")
        instance_id = "gragpoison-" + fingerprint_json(record)[:20]
        document_ids = tuple(
            f"{instance_id}-document-{index}" for index in range(len(texts))
        )
        instance = AttackInstance(
            attack_id=GRAGPoisonAdapter.adapter_id,
            instance_id=instance_id,
            dataset=str(record["dataset"]),
            query_id=str(record["query_id"]),
            threat_track="logical",
            endpoint_family="relation_targeted_or_untargeted",
            fidelity=str(record.get("fidelity", "dataset_port")),
            malicious_document_ids=document_ids,
            target_answer=record.get("target_answer"),
            metadata={
                "attack_mode": record["attack_mode"],
                "target_relation": record.get("target_relation"),
            },
        )
        documents = tuple(
            BenchmarkDocument(
                dataset=instance.dataset,
                document_id=document_id,
                title="",
                text=text,
                corpus_variant="poisoned",
                attack_instance_id=instance_id,
            )
            for document_id, text in zip(document_ids, texts, strict=True)
        )
        validate_attack_instance(instance)
        return AdaptedAttack(instance=instance, documents=documents, evaluator_only={})


class BadRAGReimplementationAdapter:
    adapter_id = "A4_badrag"

    @staticmethod
    def adapt(record: Mapping[str, Any]) -> AdaptedAttack:
        required = {"dataset", "query_id", "trigger", "payload", "malicious_text"}
        missing = required - set(record)
        if missing:
            raise ValueError(f"BadRAG record missing fields: {sorted(missing)}")
        instance_id = "badrag-" + fingerprint_json(record)[:20]
        document_id = f"{instance_id}-document-0"
        instance = AttackInstance(
            attack_id=BadRAGReimplementationAdapter.adapter_id,
            instance_id=instance_id,
            dataset=str(record["dataset"]),
            query_id=str(record["query_id"]),
            threat_track="backdoor",
            endpoint_family="trigger_payload_success",
            fidelity="reimplementation",
            malicious_document_ids=(document_id,),
            trigger=str(record["trigger"]),
            metadata={"payload": str(record["payload"])},
        )
        document = BenchmarkDocument(
            dataset=instance.dataset,
            document_id=document_id,
            title="",
            text=str(record["malicious_text"]),
            corpus_variant="poisoned",
            attack_instance_id=instance_id,
        )
        validate_attack_instance(instance)
        return AdaptedAttack(
            instance=instance, documents=(document,), evaluator_only={}
        )


def normalize_context_trace(
    *,
    backend_id: str,
    instance_id: str,
    defense_id: str,
    corpus_modified: bool,
    index_included: bool,
    graph_surfaced: bool,
    retrieved_document_ids: Sequence[str],
    prompt_document_ids: Sequence[str],
    rendered_prompt: str,
    metadata: Mapping[str, Any] | None = None,
) -> RetrievalContextTrace:
    """Normalize saved Microsoft GraphRAG or LightRAG context metadata."""

    if backend_id not in {"S1_microsoft_graphrag", "S2_lightrag"}:
        raise ValueError(f"unsupported backend adapter: {backend_id}")
    retrieved = tuple(str(item) for item in retrieved_document_ids)
    prompt = tuple(str(item) for item in prompt_document_ids)
    if not set(prompt).issubset(retrieved):
        raise ValueError("prompt documents must be a subset of retrieved documents")
    return RetrievalContextTrace(
        instance_id=instance_id,
        backend_id=backend_id,
        defense_id=defense_id,
        corpus_modified=corpus_modified,
        index_included=index_included,
        graph_surfaced=graph_surfaced,
        retrieved_document_ids=retrieved,
        prompt_document_ids=prompt,
        prompt_sha256=hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest(),
        metadata=dict(metadata or {}),
    )


def normalize_defense_trace(
    trace: RetrievalContextTrace,
    *,
    defense_id: str,
    kept_prompt_document_ids: Sequence[str],
    metadata: Mapping[str, Any] | None = None,
) -> RetrievalContextTrace:
    """Create the paired post-defense trace without changing the attacked input."""

    allowed = {
        "D0_no_defense",
        "D1_query_paraphrase",
        "D2_ppl_pti",
        "D3_ragdefender",
        "D4_hog_grag",
        "D5_logicguard_stage43_45",
        "D6_logicguard_full",
        "D7_oracle_clean_recovery",
    }
    if defense_id not in allowed:
        raise ValueError(f"unsupported defense adapter: {defense_id}")
    kept = tuple(str(item) for item in kept_prompt_document_ids)
    if defense_id != "D7_oracle_clean_recovery" and not set(kept).issubset(
        trace.retrieved_document_ids
    ):
        raise ValueError("realistic defenses cannot inject evaluator-only documents")
    return RetrievalContextTrace(
        instance_id=trace.instance_id,
        backend_id=trace.backend_id,
        defense_id=defense_id,
        corpus_modified=trace.corpus_modified,
        index_included=trace.index_included,
        graph_surfaced=trace.graph_surfaced,
        retrieved_document_ids=trace.retrieved_document_ids,
        prompt_document_ids=kept,
        prompt_sha256=trace.prompt_sha256,
        metadata={**trace.metadata, **dict(metadata or {})},
    )
