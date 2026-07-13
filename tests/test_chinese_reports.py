from logicguard.reports.chinese import localize_markdown_report


def test_localize_markdown_report_adds_chinese_metric_descriptions() -> None:
    source = "\n".join(
        [
            "# LogicGuard LLM Generation Pilot",
            "",
            "## Summary",
            "",
            "| model | attack | context | calls | correct | poisoned | abstained | errors |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            "| qwen3.7-plus | bridge_injection | guarded | 1 | 0 | 0 | 1 | 0 |",
        ]
    )

    localized = localize_markdown_report("llm_generation_test.md", source)

    assert localized.startswith("<!-- logicguard:chinese-report:v1 -->")
    assert "# 中文实验报告：真实 LLM 答案阶段实验" in localized
    assert "## 指标说明" in localized
    assert "`hit@k / hit@10`" in localized
    assert "正确答案命中次数" in localized
    assert "| 模型 | 攻击类型 | 上下文类型 | 调用次数 | 正确答案次数 | 污染答案次数 | 拒答次数 | 错误次数 |" in localized


def test_localize_markdown_report_is_idempotent() -> None:
    localized = localize_markdown_report("x.md", "# Data Validation Report")

    assert localize_markdown_report("x.md", localized) == localized
