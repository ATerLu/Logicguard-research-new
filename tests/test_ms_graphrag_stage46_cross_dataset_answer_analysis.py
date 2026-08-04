from logicguard.evaluation.cross_dataset_analysis import (
    build_stage46_final_summaries,
    build_stage46_pairwise_rows,
    summarize_stage46_pairwise_rows,
)


def test_stage46_pairwise_analysis_requires_matched_queries_and_tracks_asr_removal() -> (
    None
):
    rows = [
        _row("full_query_guard", "q1", "incorrect", True, "wrong"),
        _row("full_query_guard", "q2", "abstained", False, "UNKNOWN"),
        _row("stage35_query_bm25_append_top12", "q1", "correct", False, "right"),
        _row("stage35_query_bm25_append_top12", "q2", "correct", False, "right"),
    ]
    summaries = build_stage46_final_summaries(
        judged_rows=rows,
        dataset="toy",
        exposure_by_method={
            "full_query_guard": 1.0,
            "stage35_query_bm25_append_top12": 0.0,
        },
    )
    baseline = next(row for row in summaries if row.method == "full_query_guard")
    assert baseline.final_attack_success_rate == 0.5
    assert baseline.actual_unrecovered_changed_exposure_rate == 1.0

    paired = build_stage46_pairwise_rows(judged_rows=rows, dataset="toy")
    paired_summary = summarize_stage46_pairwise_rows(paired)[0]
    assert paired_summary.baseline_attack_success_rate == 0.5
    assert paired_summary.treatment_attack_success_rate == 0.0
    assert paired_summary.attack_neutralized_rate == 0.5
    assert paired_summary.utility_gain_rate == 1.0


def test_stage46_pairwise_analysis_rejects_mismatched_query_ids() -> None:
    rows = [
        _row("full_query_guard", "q1", "incorrect", True, "wrong"),
        _row("stage35_query_bm25_append_top12", "q2", "correct", False, "right"),
    ]
    try:
        build_stage46_pairwise_rows(judged_rows=rows, dataset="toy")
    except ValueError as exc:
        assert "differ" in str(exc)
    else:
        raise AssertionError("mismatched query ids should fail")


def _row(
    method: str,
    query_id: str,
    final_label: str,
    attack_success: bool,
    answer: str,
) -> dict[str, object]:
    return {
        "dataset": "toy",
        "model": "toy-model",
        "method": method,
        "query_id": query_id,
        "query": "Question?",
        "gold_answer": "right",
        "generated_answer": answer,
        "final_label": final_label,
        "final_attack_success": attack_success,
        "judge_called": final_label == "incorrect",
        "judge_error": None,
        "unrecovered_changed_doc_ids": ["d1"] if attack_success else [],
        "source_summaries": [],
    }
