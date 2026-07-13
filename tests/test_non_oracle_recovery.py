from pathlib import Path

from logicguard.data.schemas import CorpusDocument
from logicguard.defense.run_non_oracle_recovery import (
    NonOracleRecoveryConfig,
    build_non_oracle_recovered_trace,
    build_non_oracle_recovered_trace_from_index,
)
from logicguard.defense.schemas import RerankedCandidate, RerankedTrace
from logicguard.naive_rag.baseline import NaiveRagIndex


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "logicpoison_recovery_stage8.yaml"


def _guarded_trace() -> RerankedTrace:
    return RerankedTrace(
        query_id="q1",
        query="Who wrote the river biography?",
        answer="Ada River",
        gold_doc_ids=["gold"],
        candidates=[
            RerankedCandidate(
                doc_id="safe",
                title="Safe background",
                original_rank=2,
                new_rank=1,
                base_score=3.0,
                risk_score=0.0,
                adjusted_score=3.0,
                path_length=1,
                direct_query_match=True,
                source_support_count=1,
                global_support_count=None,
                known_source_document=True,
                reference_content_changed=False,
                matched_query_entities=[],
                bridge_entities=[],
                risk_reasons=["content_integrity_pass"],
            )
        ],
    )


def test_stage8_config_resolves_default_paths() -> None:
    config = NonOracleRecoveryConfig.from_yaml(CONFIG_PATH)

    assert config.clean_data_root == PROJECT_ROOT / "data" / "logicpoison_official" / "clean"
    assert config.stage3_defense_root == PROJECT_ROOT / "outputs" / "defense" / "logicpoison_official"
    assert config.output_root == PROJECT_ROOT / "outputs" / "defense" / "logicpoison_official_stage8"
    assert config.report_path == PROJECT_ROOT / "outputs" / "reports" / "LogicPoison阶段8非OracleRecovery实验报告.md"
    assert config.datasets == ["2wikimultihopqa", "hotpotqa", "musique"]
    assert config.retrievers == ["naive_bm25", "graph_surrogate"]
    assert config.top_k == 10
    assert config.recovery_mode == "trusted_bm25"


def test_non_oracle_recovery_backfills_from_clean_corpus_without_clean_trace() -> None:
    clean_documents = [
        CorpusDocument(
            doc_id="safe",
            title="Safe background",
            text="This unrelated document mentions the river.",
        ),
        CorpusDocument(
            doc_id="gold",
            title="Ada River",
            text="Ada River wrote the river biography and is the correct answer.",
        ),
        CorpusDocument(
            doc_id="other",
            title="Other note",
            text="Other text about a mountain.",
        ),
    ]

    recovered = build_non_oracle_recovered_trace(
        guarded_trace=_guarded_trace(),
        clean_documents=clean_documents,
        top_k=2,
    )

    assert [candidate.doc_id for candidate in recovered.candidates] == ["safe", "gold"]
    assert recovered.candidates[0].risk_reasons == ["content_integrity_pass"]
    assert recovered.candidates[1].risk_reasons == [
        "trusted_reference_recovery",
        "non_oracle_bm25_recovery",
    ]
    assert recovered.candidates[1].known_source_document is True
    assert recovered.candidates[1].reference_content_changed is False


def test_non_oracle_recovery_can_reuse_a_trusted_bm25_index() -> None:
    clean_documents = [
        CorpusDocument(doc_id="safe", title="Safe background", text="This unrelated document mentions the river."),
        CorpusDocument(
            doc_id="gold",
            title="Ada River",
            text="Ada River wrote the river biography and is the correct answer.",
        ),
    ]
    trusted_index = NaiveRagIndex.build(clean_documents, mode="bm25")

    recovered = build_non_oracle_recovered_trace_from_index(
        guarded_trace=_guarded_trace(),
        trusted_index=trusted_index,
        top_k=2,
    )

    assert [candidate.doc_id for candidate in recovered.candidates] == ["safe", "gold"]
