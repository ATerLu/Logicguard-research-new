"""Idempotently append the post-Stage21 milestones to the experiment registry."""

from __future__ import annotations

import csv
from pathlib import Path

REGISTRY_PATH = Path("docs/实验注册表.csv")

MILESTONES = [
    {
        "experiment_id": "LG-H04",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage22-25",
        "name": "official source context与non-oracle recovery",
        "category": "microsoft_graphrag_official",
        "status": "completed",
        "datasets": "2wikimultihopqa",
        "query_count": "50",
        "retriever": "official GraphRAG local context",
        "attack": "LogicPoison indexed corpus",
        "defense": "source filtering + oracle/non-oracle recovery",
        "models": "none",
        "metric_version": "source-recovery-v2",
        "cost_class": "local",
        "config_paths": "configs/ms_graphrag_stage25_non_oracle_sources_poisoned50.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage24_50_query_guard_contexts.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage25_non_oracle_sources_poisoned50_results.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "non-oracle recovery在不读取gold doc_id时恢复可信source，并保留oracle上界用于比较。",
        "limitations": "仍依赖可信clean candidate pool，且属于post-retrieval source处理。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.defense.non_oracle_recovery --config configs/ms_graphrag_stage25_non_oracle_sources_poisoned50.yaml",
    },
    {
        "experiment_id": "LG-H05",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage26-28",
        "name": "answer proxy、真实LLM与risk-aware recovery",
        "category": "microsoft_graphrag_official",
        "status": "completed",
        "datasets": "2wikimultihopqa",
        "query_count": "20",
        "retriever": "official GraphRAG source contexts",
        "attack": "LogicPoison indexed corpus",
        "defense": "risk-aware non-oracle recovery",
        "models": "qwen3.7-plus",
        "metric_version": "answer-eval-v2",
        "cost_class": "api-medium",
        "config_paths": "configs/ms_graphrag_stage28_risk_non_oracle_answer_llm_poisoned20.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage28_risk_non_oracle_contexts_poisoned20.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage28_risk_non_oracle_answer_llm_results_poisoned20.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "将source安全指标推进到真实回答验证，并移除changed-support风险oracle。",
        "limitations": "20-query单模型验证；评估仍受检索可答性影响。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.evaluation.answer_generation --config configs/ms_graphrag_stage28_risk_non_oracle_answer_llm_poisoned20.yaml",
    },
    {
        "experiment_id": "LG-H06",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage29-34",
        "name": "回答审计、可答性消融与judge复核",
        "category": "answer_evaluation",
        "status": "completed",
        "datasets": "2wikimultihopqa",
        "query_count": "20",
        "retriever": "frozen official source contexts",
        "attack": "LogicPoison indexed corpus",
        "defense": "rendering ablation + normalized audit",
        "models": "qwen3.7-plus;LLM judge",
        "metric_version": "judge-audit-v1",
        "cost_class": "api-medium",
        "config_paths": "configs/ms_graphrag_stage34_answer_judge_audit_poisoned20.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage33_answer_llm_results_poisoned20.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage34_answer_judge_audit_results_poisoned20.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "区分严格匹配低估、拒答、普通错误与污染攻击成功。",
        "limitations": "judge只复核不确定样本，不能替代独立人工标注。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.evaluation.judge_audit --config configs/ms_graphrag_stage34_answer_judge_audit_poisoned20.yaml",
    },
    {
        "experiment_id": "LG-H07",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage35-39",
        "name": "source enrichment与二跳链路补证",
        "category": "defense_ablation",
        "status": "completed",
        "datasets": "2wikimultihopqa",
        "query_count": "20",
        "retriever": "frozen official source contexts",
        "attack": "LogicPoison indexed corpus",
        "defense": "candidate enrichment + conditional second-hop append",
        "models": "qwen3.7-plus;LLM judge",
        "metric_version": "chain-completeness-v1",
        "cost_class": "api-medium",
        "config_paths": "configs/ms_graphrag_stage38_chain_completeness_poisoned20.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage35_source_enrichment_rows_poisoned20.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage38_chain_completeness_rows_poisoned20.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "确认答案表面存在不等于多跳证据完整，条件式补证优于无差别扩容。",
        "limitations": "补证候选仍来自可信clean池，规模为20 query。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.defense.chain_completion --config configs/ms_graphrag_stage38_chain_completeness_poisoned20.yaml",
    },
    {
        "experiment_id": "LG-H08",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage40-42",
        "name": "HotpotQA与MuSiQue跨数据集接入",
        "category": "cross_dataset",
        "status": "completed",
        "datasets": "hotpotqa;musique",
        "query_count": "25",
        "retriever": "official GraphRAG local context",
        "attack": "none (readiness baseline)",
        "defense": "query guard context export",
        "models": "text-embedding-v4",
        "metric_version": "cross-dataset-readiness-v1",
        "cost_class": "api-low",
        "config_paths": "configs/ms_graphrag_stage40_hotpotqa.yaml;configs/ms_graphrag_stage40_musique.yaml",
        "input_paths": "data/processed/hotpotqa;data/processed/musique",
        "output_paths": "outputs/ms_graphrag_query/stage42_hotpotqa_query_guard_contexts.jsonl;outputs/ms_graphrag_query/stage42_musique_query_guard_contexts.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "补齐两个外部多跳数据集的官方索引、上下文与query-guard诊断。",
        "limitations": "两个数据集的样本数不同，跨数据集结果需配对解释。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.evaluation.cross_dataset_audit --config configs/ms_graphrag_stage40_hotpotqa.yaml",
    },
    {
        "experiment_id": "LG-H09",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage43-46",
        "name": "跨数据集recovery、enrichment与真实回答",
        "category": "cross_dataset",
        "status": "completed",
        "datasets": "hotpotqa;musique",
        "query_count": "40",
        "retriever": "official GraphRAG source contexts",
        "attack": "frozen source-risk benchmark",
        "defense": "risk recovery + top12 enrichment + top14 chain completion",
        "models": "qwen3.7-plus;LLM judge",
        "metric_version": "paired-answer-v1",
        "cost_class": "api-high",
        "config_paths": "configs/ms_graphrag_stage46_hotpotqa_answer_preflight.yaml;configs/ms_graphrag_stage46_musique_answer_preflight.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage43_hotpotqa_risk_non_oracle_contexts.jsonl;outputs/ms_graphrag_query/stage43_musique_risk_non_oracle_contexts.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage46_hotpotqa_answer_judge_results.jsonl;outputs/ms_graphrag_query/stage46_musique_answer_judge_results.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "形成四策略配对回答矩阵，分离恢复、扩容和链路补证的增量效果。",
        "limitations": "依赖冻结上下文且未执行端到端在线攻击。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.evaluation.cross_dataset_analysis --config configs/ms_graphrag_stage46_cross_dataset_answer_analysis.yaml",
    },
    {
        "experiment_id": "LG-H10",
        "main_stage": "H",
        "legacy_stage": "Microsoft GraphRAG Stage47",
        "name": "三类自适应source攻击与防御验证",
        "category": "adaptive_attack",
        "status": "completed",
        "datasets": "hotpotqa;musique",
        "query_count": "25",
        "retriever": "frozen clean official GraphRAG contexts",
        "attack": "low drift + candidate collision + natural bridge",
        "defense": "Stage43 recovery + Stage44 enrichment + Stage45 chain completion",
        "models": "qwen3.7-plus;LLM judge",
        "metric_version": "targeted-asr-v1",
        "cost_class": "api-high",
        "config_paths": "configs/experiments/stage47/hotpotqa/attack.yaml;configs/experiments/stage47/musique/attack.yaml;configs/experiments/stage47/analysis.yaml",
        "input_paths": "outputs/ms_graphrag_query/stage47_hotpotqa_clean_contexts.jsonl;outputs/ms_graphrag_query/stage47_musique_clean_contexts.jsonl",
        "output_paths": "outputs/ms_graphrag_query/stage47_adaptive_attack_analysis_rows.jsonl",
        "report_paths": "docs/results.md",
        "key_result": "candidate collision可被检测但恢复正确性仍需约束；natural bridge是当前最明确的防御缺口。",
        "limitations": "攻击发生于clean检索后的source层，不代表已完成重新索引的端到端自适应攻击。",
        "reproduction_command": ".venv\\Scripts\\python.exe -m logicguard.evaluation.adaptive_attack_analysis --config configs/experiments/stage47/analysis.yaml",
    },
]


def main() -> None:
    with REGISTRY_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if fieldnames is None:
        raise RuntimeError(f"Missing CSV header in {REGISTRY_PATH}")

    by_id = {row["experiment_id"]: row for row in rows}
    for milestone in MILESTONES:
        by_id[milestone["experiment_id"]] = milestone

    ordered = sorted(by_id.values(), key=lambda row: row["experiment_id"])
    with REGISTRY_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ordered)
    print(f"Registry now contains {len(ordered)} experiments through LG-H10")


if __name__ == "__main__":
    main()
