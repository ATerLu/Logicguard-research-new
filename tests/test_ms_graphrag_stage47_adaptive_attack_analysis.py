from logicguard.evaluation.adaptive_attack_analysis import (
    summarize_stage47_pairwise,
    summarize_stage47_results,
)


def test_stage47_analysis_separates_broad_and_targeted_asr() -> None:
    rows = [
        _row(
            stage="unprotected",
            final_label="incorrect",
            generated_answer="The answer is Rome.",
            exposed=True,
        ),
        _row(
            stage="stage43_recovery",
            final_label="correct",
            generated_answer="The answer is London.",
            exposed=False,
        ),
        _row(
            stage="stage44_top12",
            final_label="correct",
            generated_answer="London",
            exposed=False,
        ),
        _row(
            stage="stage45_top14",
            final_label="incorrect",
            generated_answer="Unknown City",
            exposed=True,
        ),
    ]
    summaries = summarize_stage47_results(rows)
    baseline = next(row for row in summaries if row.defense_stage == "unprotected")
    stage45 = next(row for row in summaries if row.defense_stage == "stage45_top14")
    assert baseline.broad_asr_exposure_conditioned == 1.0
    assert baseline.targeted_asr_exposure_conditioned == 1.0
    assert stage45.broad_asr_exposure_conditioned == 1.0
    assert stage45.targeted_asr_exposure_conditioned == 0.0

    pairwise = summarize_stage47_pairwise(rows)
    stage43 = next(row for row in pairwise if row.treatment_stage == "stage43_recovery")
    assert stage43.targeted_asr_delta == -1.0
    assert stage43.utility_delta == 1.0
    assert stage43.newly_correct_count == 1


def _row(
    *,
    stage: str,
    final_label: str,
    generated_answer: str,
    exposed: bool,
) -> dict[str, object]:
    return {
        "dataset": "toy",
        "attack_family": "natural_bridge",
        "defense_stage": stage,
        "method": f"stage47_natural_bridge__{stage}",
        "query_id": "q1",
        "attack_valid": True,
        "attack_exposed": exposed,
        "target_exposed": exposed,
        "malicious_answer": "Rome",
        "generated_answer": generated_answer,
        "final_label": final_label,
        "targeted_attack_success": exposed and "rome" in generated_answer.lower(),
        "broad_attack_success": exposed and final_label == "incorrect",
        "risk_detected": stage != "unprotected",
        "candidate_collision_recovered": False,
        "wrong_candidate_recovered": False,
        "judge_error": None,
    }
