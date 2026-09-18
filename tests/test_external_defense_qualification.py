from pathlib import Path

from logicguard.benchmark.external_defense_qualification import audit_hog_grag


ROOT = Path(__file__).parents[1]


def test_pinned_hog_grag_artifact_fails_closed_on_actual_core_sources() -> None:
    upstream = ROOT / "vendor/upstream/HoG-GRAG"
    result = audit_hog_grag(
        upstream,
        [upstream / "get_response.md", upstream / "prompts/response_subquestion.md"],
        "gpt-5-mini",
    )

    assert result["paper_native_executable"] is False
    assert result["source_compile_passed"] is False
    assert result["required_prompt_files_present"] is False
    assert result["provider_model_literal_present"] is True
    repair = next(
        row for row in result["compile_checks"] if row["file"] == "repairer.py"
    )
    assert repair["error_type"] == "IndentationError"
    assert repair["line"] == 304
    assert result["provider_calls_made"] == 0


def test_hog_grag_audit_can_pass_a_complete_minimal_artifact(tmp_path: Path) -> None:
    source = tmp_path / "Src"
    source.mkdir()
    (source / "detection.py").write_text('MODEL = "gpt-5-mini"\n', encoding="utf-8")
    prompt_a = tmp_path / "get_response.md"
    prompt_b = tmp_path / "prompts/response_subquestion.md"
    prompt_b.parent.mkdir()
    prompt_a.write_text("prompt", encoding="utf-8")
    prompt_b.write_text("prompt", encoding="utf-8")

    result = audit_hog_grag(tmp_path, [prompt_a, prompt_b], "gpt-5-mini")

    assert result["paper_native_executable"] is True
    assert result["status"] == "HOG_GRAG_PAPER_NATIVE_SOURCE_GATE_PASSED"
