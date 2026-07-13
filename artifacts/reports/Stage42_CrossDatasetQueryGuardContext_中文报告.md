# Stage42 HotpotQA/MuSiQue query-guard source context 导出报告

## 实验目的

Stage41 已补齐 HotpotQA 与 MuSiQue 的 official GraphRAG clean/poisoned 索引，并导出 5-query baseline/broad contexts。Stage42 继续推进跨数据集验证：在 HotpotQA/MuSiQue poisoned official GraphRAG workspace 上运行 query-layer seed planning、`full_query_guard` context export 与 retrieval/safety proxy evaluation，生成后续 Stage28 risk-non-oracle recovery 所需的 20-query source contexts。

本阶段仍不调用 answer-level LLM，也不报告最终 utility 或 attack success。它回答的问题是：HotpotQA/MuSiQue 是否已经具备可进入 recovery 的 official GraphRAG source contexts，以及这些 contexts 的 support recall / changed exposure 情况如何。

## 执行内容

1. 新增 HotpotQA/MuSiQue query-layer 配置：
   - `configs/ms_graphrag_stage40_hotpotqa.yaml`
   - `configs/ms_graphrag_stage40_musique.yaml`
2. 运行 `query_layer_seeding`，生成每个数据集 20 条 non-gold seed plan。
3. 使用 GraphRAG 隔离环境运行 `query_layer_context`，导出 official `context_data.sources`。
4. 运行 `query_layer_evaluation`，计算 gold support recall、changed support exposure、trusted recall、context recall failure 等指标。
5. 重跑 Stage40 readiness audit，确认 HotpotQA/MuSiQue 的下一阻断项已推进到 `run_stage28_risk_non_oracle_recovery`。

## Seed plan 概况

| 数据集 | seed rows | avg include entities | avg exclude entities | max include | max exclude |
| --- | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | 20 | 4.30 | 21.55 | 10 | 22 |
| MuSiQue | 20 | 3.80 | 20.45 | 7 | 21 |

这些 seed 不读取 gold answer/support 字段；gold 字段只在 context 导出之后用于离线评价。

## Context 导出概况

| 数据集 | context rows | source数范围 | 平均 source数 |
| --- | ---: | ---: | ---: |
| HotpotQA | 20 | 19-44 | 33.1 |
| MuSiQue | 20 | 23-37 | 31.6 |

导出时 `community_prop=0.0`，因此 GraphRAG 打印 `No community records added when building community context` 属于预期 warning，不影响 source contexts。

## Retrieval / Safety proxy 结果

| 数据集 | 方法 | query数 | gold support recall | changed exposure | trusted recall | entity hit | context failures | avg sources |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | mixed_baseline | 5 | 0.2000 | 0.2000 | 0.0000 | 0.0000 | 3 | 28.2 |
| HotpotQA | budget_expansion | 5 | 0.4000 | 0.4000 | 0.0000 | 0.0000 | 3 | 67.4 |
| HotpotQA | full_query_guard | 20 | 0.8750 | 0.8750 | 0.0000 | 0.0250 | 2 | 33.1 |
| MuSiQue | mixed_baseline | 5 | 0.4667 | 0.4667 | 0.0000 | 0.1000 | 1 | 31.6 |
| MuSiQue | budget_expansion | 5 | 0.6000 | 0.6000 | 0.0000 | 0.1000 | 1 | 89.8 |
| MuSiQue | full_query_guard | 20 | 0.7375 | 0.7375 | 0.0500 | 0.0417 | 0 | 31.6 |

## 关键结论

- HotpotQA/MuSiQue 已经具备进入 Stage28 risk-non-oracle recovery 的 official source contexts。
- HotpotQA 的 `full_query_guard` 在 20-query 上达到 `gold_support_recall=0.8750`，明显高于 5-query baseline/broad 的 `0.2000/0.4000`；但 `changed_exposure=0.8750`，说明召回的 support 大多仍是 poisoned/changed source，必须继续做 recovery。
- MuSiQue 的 `full_query_guard` 达到 `gold_support_recall=0.7375`，且 `context_recall_failure_count=0`，说明 20 条 query 至少都有部分 support 进入 context；但 `changed_exposure=0.7375`，同样需要 Stage28 recovery 降低污染暴露。
- HotpotQA 有 2 条 `context_recall_failure`：`5a729cc25542991f9a20c532` 与 `5a774e9c55429972597f14f3`。后续 Stage28/35/38 即使能恢复已召回 sources，也要关注这类完全缺 support 的检索失败。
- 与单纯 broad expansion 相比，`full_query_guard` 用更少平均 sources 达到更高 recall：HotpotQA `67.4 -> 33.1 sources` 且 recall `0.4000 -> 0.8750`；MuSiQue `89.8 -> 31.6 sources` 且 recall `0.6000 -> 0.7375`。

## Readiness 变化

Stage42 后重新运行 Stage40 audit：

| 数据集 | source context | risk non-oracle context | 下一步 |
| --- | --- | --- | --- |
| 2WikiMultihopQA | ready | ready | `ready_for_attribute_sentence_completeness_or_adaptive_attack` |
| HotpotQA | ready | missing | `run_stage28_risk_non_oracle_recovery` |
| MuSiQue | ready | missing | `run_stage28_risk_non_oracle_recovery` |

## 主要产物

配置：
- `configs/ms_graphrag_stage40_hotpotqa.yaml`
- `configs/ms_graphrag_stage40_musique.yaml`

Seed plan：
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_seed_plan.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_seed_plan.jsonl`

Source contexts：
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_contexts.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_contexts.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_contexts_full_query_guard.jsonl`

Evaluation：
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_metrics.csv`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_summary.csv`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_metrics.csv`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_summary.csv`

Reports：
- `outputs/reports/Stage42_HotpotQA_QueryGuardSeedPlan_20Query.md`
- `outputs/reports/Stage42_HotpotQA_QueryGuardContextExport_20Query.md`
- `outputs/reports/Stage42_HotpotQA_QueryGuardEvaluation_20Query.md`
- `outputs/reports/Stage42_MuSiQue_QueryGuardSeedPlan_20Query.md`
- `outputs/reports/Stage42_MuSiQue_QueryGuardContextExport_20Query.md`
- `outputs/reports/Stage42_MuSiQue_QueryGuardEvaluation_20Query.md`

## 下一阶段

Stage43 应复用 Stage28 的 risk-non-oracle recovery 逻辑，为 HotpotQA/MuSiQue 分别生成：

- `stage40_hotpotqa_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- `stage40_hotpotqa_poisoned20_risk_non_oracle_sources_metrics.csv`
- `stage40_musique_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- `stage40_musique_poisoned20_risk_non_oracle_sources_metrics.csv`

下一阶段的核心问题是：在不使用 doc-id oracle 的前提下，能否将 Stage42 召回到 context 的 changed support sources 替换为 clean candidate sources，并在保留 support recall 的同时降低 changed exposure。
