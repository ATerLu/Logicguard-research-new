"""Chinese report localization helpers.

Experiment runners keep their raw metrics simple and machine-readable. This
module turns generated Markdown reports into Chinese-facing research notes with
consistent metric explanations and compact interpretation prompts.
"""

from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "<!-- logicguard:chinese-report:v1 -->"

METRIC_NOTES = [
    ("`hit@k / hit@10`", "检索 top-k 中是否至少命中一个 gold 支持文档；越高表示检索能找到相关证据。"),
    ("`gold_recall@k / gold_recall@10`", "检索 top-k 覆盖 gold 支持文档的平均比例；越高表示支持证据覆盖更完整。"),
    ("`average candidates/query`", "每个问题平均返回的候选证据数，用于观察检索是否过窄或过宽。"),
    ("`exposure@k`", "攻击目标文档进入 top-k 或最终上下文的比例；越低表示防御越能阻断污染证据。"),
    ("`targeted queries`", "本轮攻击实际覆盖的目标问题数量。"),
    ("`exposed queries`", "目标问题中检索到污染证据的问题数量。"),
    ("`exposed@rank1`", "污染证据排在第 1 位的目标问题数量；越高表示污染证据越支配排序。"),
    ("`average first poisoned rank`", "污染证据首次出现的平均排名；越小表示攻击证据越靠前。"),
    ("`clean recall`", "干净语料下的 gold recall，用于衡量原始检索质量。"),
    ("`trusted recall`", "排除已篡改或不可信 gold 文档后的 recall，更适合安全评估。"),
    ("`corrupted gold`", "被标记为内容篡改的 gold 支持证据出现次数。"),
    ("`suppressed`", "guarded context 中被过滤掉的候选证据总数。"),
    ("`suppressed gold`", "被过滤掉的 gold 候选数；需要结合是否 corrupted 来解释。"),
    ("`suppressed poisoned`", "被过滤掉的攻击元数据标记污染文档数；越高通常表示防御命中污染证据。"),
    ("`suppressed changed`", "被过滤掉的内容指纹不一致文档数。"),
    ("`guarded avg candidates`", "guarded context 中每个问题保留的平均候选数，反映防御后证据量。"),
    ("`correct`", "正确答案命中次数，即 LLM 输出包含 gold answer 的次数。"),
    ("`poisoned`", "LLM 输出包含 attacker replacement answer 的次数。"),
    ("`abstained`", "LLM 输出 UNKNOWN 或信息不足类拒答的次数。"),
    ("`errors`", "API 调用或生成过程中失败的次数。"),
    ("`total tokens`", "本组 LLM 调用消耗的总 token 数，用于估算成本。"),
]

TITLE_BY_PATTERN = [
    ("llm_generation", "真实 LLM 答案阶段实验"),
    ("logicguard_ablation", "LogicGuard 消融实验"),
    ("logicguard_multidataset", "多数据集防御汇总实验"),
    ("logicguard_threshold_scan", "LogicGuard 阈值扫描实验"),
    ("logicguard", "LogicGuard 防御实验"),
    ("bridge_injection", "Bridge Injection 攻击暴露实验"),
    ("entity_swap", "Entity Swap 攻击暴露实验"),
    ("graphrag_baseline", "GraphRAG 检索基线实验"),
    ("data_validation", "数据集可用性验证"),
    ("preliminary_attack_comparison", "初步攻击对比实验"),
]

LINE_REPLACEMENTS = {
    "| model | attack | context | calls | correct | poisoned | abstained | errors | total tokens |": "| 模型 | 攻击类型 | 上下文类型 | 调用次数 | 正确答案次数 | 污染答案次数 | 拒答次数 | 错误次数 | 总 token 数 |",
    "| model | attack | context | calls | correct | poisoned | abstained | errors |": "| 模型 | 攻击类型 | 上下文类型 | 调用次数 | 正确答案次数 | 污染答案次数 | 拒答次数 | 错误次数 |",
    "## Output Files": "## 输出文件",
    "## Setup": "## 实验设置",
    "## Summary": "## 结果汇总",
    "## Notes": "## 备注",
    "## Run Configuration": "## 运行配置",
    "## Graph Statistics": "## 图统计",
    "## Retrieval Metrics": "## 检索指标",
    "## Top Bridge Entities": "## 高频桥接实体",
    "## Attack Setup": "## 攻击设置",
    "## Exposure Metrics": "## 暴露指标",
    "## Bridge Rank Details": "## Bridge 排名细节",
    "## Retrieval Context": "## 检索上下文",
    "## Exposed Examples": "## 暴露样例",
    "## Before/After Metrics": "## 防御前后指标",
    "## Entity Swap Poisoned Examples": "## Entity Swap 污染样例",
    "## Bridge Injection Poisoned Examples": "## Bridge Injection 污染样例",
    "## Interpretation": "## 结果解释",
    "## Best Row": "## 最优阈值行",
    "## Grid Results": "## 网格扫描结果",
    "## Metric Notes": "## 指标补充说明",
    "## Modes": "## 消融模式",
    "## Results": "## 实验结果",
    "## Best Threshold Rows": "## 各数据集最优阈值",
    "## Experiment Setting": "## 实验设置",
    "## Overall Retrieval Metrics": "## 整体检索指标",
    "## Target Query Metrics": "## 目标问题指标",
    "## Bridge Injection Impact": "## Bridge Injection 影响",
    "## Current Limitations": "## 当前局限",
    "## Next Experiment Step": "## 下一步实验",
    "Metric": "指标",
    "Value": "取值",
    "run": "实验组",
    "exposure before": "防御前暴露率",
    "exposure reranked": "重排后暴露率",
    "exposure guarded": "guarded 后暴露率",
    "hit before": "防御前 hit",
    "hit guarded": "guarded 后 hit",
    "recall before": "防御前 recall",
    "recall guarded": "guarded 后 recall",
    "trusted recall before": "防御前可信 recall",
    "trusted recall guarded": "guarded 后可信 recall",
    "corrupted gold": "篡改 gold 数",
    "suppressed": "过滤候选数",
    "suppressed gold": "过滤 gold 数",
    "suppressed poisoned": "过滤污染数",
    "suppressed changed": "过滤篡改数",
    "guarded avg candidates": "guarded 平均候选数",
    "dataset": "数据集",
    "threshold": "阈值",
    "clean recall": "干净 recall",
    "entity exposure": "Entity 暴露率",
    "entity trusted recall": "Entity 可信 recall",
    "entity corrupted gold": "Entity 篡改 gold",
    "bridge exposure": "Bridge 暴露率",
    "bridge trusted recall": "Bridge 可信 recall",
    "mode": "模式",
    "entity suppressed changed": "Entity 过滤篡改数",
    "bridge suppressed poisoned": "Bridge 过滤污染数",
    "Run": "实验组",
    "attack exposure@10": "攻击暴露率@10",
    "average candidates/query": "平均候选数/问题",
    "Target set": "目标集合",
    "target queries": "目标问题数",
    "first_rank": "首次排名",
    "query_entity": "查询实体",
    "replacement_answer": "替换答案",
    "score": "分数",
}


def localize_markdown_report(filename: str, content: str) -> str:
    """Return a Chinese-facing Markdown report with metric descriptions."""

    if content.startswith(MARKER):
        return content
    title = _title_for_filename(filename)
    structured_content = _translate_structured_content(content)
    return "\n".join(
        [
            MARKER,
            f"# 中文实验报告：{title}",
            "",
            "## 报告来源",
            "",
            f"- 原始文件名：`{filename}`",
            "- 说明：本文件已统一改写为中文实验记录；表格中的专有指标名保留为可复现实验字段。",
            "",
            "## 实验目的",
            "",
            _purpose_for_filename(filename),
            "",
            "## 指标说明",
            "",
            *[f"- {name}：{description}" for name, description in METRIC_NOTES],
            "",
            "## 实验结果摘录",
            "",
            structured_content,
            "",
            "## 快速阅读提示",
            "",
            "- 先看暴露率是否下降，再看正确答案次数是否恢复。",
            "- 如果 guarded 后污染答案为 0 但拒答增多，说明防御更偏向安全拒答。",
            "- 如果 recovered 后正确答案次数接近 clean，说明可信参考证据回填对答案恢复有帮助。",
            "",
        ]
    )


def localize_reports_dir(report_dir: Path) -> int:
    """Localize every Markdown report under a directory in place."""

    updated = 0
    for path in sorted(report_dir.glob("*.md")):
        original = path.read_text(encoding="utf-8")
        localized = localize_markdown_report(path.name, original)
        if localized == original:
            continue
        path.write_text(localized, encoding="utf-8")
        updated += 1
    return updated


def _title_for_filename(filename: str) -> str:
    for pattern, title in TITLE_BY_PATTERN:
        if pattern in filename:
            return title
    return "LogicGuard 实验记录"


def _purpose_for_filename(filename: str) -> str:
    if "llm_generation" in filename:
        return "评估 clean、poisoned、guarded、recovered 不同上下文下，真实 LLM 是否输出正确答案、污染答案或 UNKNOWN。"
    if "ablation" in filename:
        return "比较不同防御信号组合的作用，判断 provenance 和 content integrity 分别贡献了哪些防御效果。"
    if "threshold_scan" in filename:
        return "扫描风险惩罚和风险阈值，寻找污染暴露率与检索质量之间的折中点。"
    if "multidataset" in filename:
        return "比较多个数据集上的防御趋势，检查方法是否只对单一数据集有效。"
    if "logicguard" in filename:
        return "比较防御前、重排后和 guarded context 后的污染暴露率与检索质量。"
    if "bridge_injection" in filename:
        return "评估注入桥接文档是否进入目标问题 top-k 检索结果，以及排名是否靠前。"
    if "entity_swap" in filename:
        return "评估篡改已有文档内容后，污染证据是否进入目标问题 top-k 检索结果。"
    if "graphrag_baseline" in filename:
        return "评估轻量 GraphRAG-style 检索基线在干净或污染语料上的基础检索质量。"
    if "data_validation" in filename:
        return "验证数据集样本、答案、语料和 qrels 是否齐全，确认后续实验可以使用。"
    return "记录本阶段实验设置、结果数值和后续分析所需的核心指标。"


def _translate_structured_content(content: str) -> str:
    lines = []
    for line in content.splitlines():
        translated = _translate_line(line)
        if _is_long_english_paragraph(translated):
            continue
        lines.append(translated)
    return "\n".join(lines).strip()


def _translate_line(line: str) -> str:
    translated = line
    if translated.startswith("# "):
        translated = translated.replace("# ", "### 原始标题：", 1)
    for source, target in LINE_REPLACEMENTS.items():
        translated = translated.replace(source, target)
    translated = translated.replace("n/a", "不适用")
    translated = translated.replace("PASS", "通过")
    translated = translated.replace("UNKNOWN", "UNKNOWN")
    return translated


def _is_long_english_paragraph(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "-", "|", "`", "<", ">")):
        return False
    if len(stripped.split()) < 12:
        return False
    ascii_letters = sum(character.isascii() and character.isalpha() for character in stripped)
    return ascii_letters / max(len(stripped), 1) > 0.55


def main() -> None:
    parser = argparse.ArgumentParser(description="Localize LogicGuard Markdown reports into Chinese.")
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("outputs/reports"),
        help="Directory containing Markdown reports.",
    )
    args = parser.parse_args()
    updated = localize_reports_dir(args.report_dir)
    print(f"localized_reports={updated}")


if __name__ == "__main__":
    main()
