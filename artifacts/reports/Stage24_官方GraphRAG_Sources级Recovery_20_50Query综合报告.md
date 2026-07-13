# Microsoft GraphRAG Stage24 Sources级Recovery 20/50 Query综合报告

## 实验目的

Stage24 将 Stage23 的 official `context_data.sources` 级 recovery 从 5 query 扩展到 20 query 和 50 query。实验复用 `stage10_debug50_poisoned_query_ready` workspace，不重新索引 Microsoft GraphRAG，不调用回答模型，只评估 official context sources 层的证据召回、污染暴露和替换效果。

## 实验流程

1. 使用 `query_layer_seeding` 为前 20/50 个 query 生成不含 gold 字段的 `full_query_guard` seed plan。
2. 使用 Microsoft GraphRAG 隔离环境调用 official `LocalSearchMixedContext` context builder，导出 `full_query_guard` sources。
3. 使用 `source_recovery` 生成三种 source-level 变体：`full_query_guard`、`guarded_sources`、`recovered_sources_by_doc_id`。
4. 离线计算 `gold recall`、`changed exposure`、`trusted recall`、`empty context`、`avg sources` 和 `avg recovered`。

## 20 Query结果

| method | queries | gold recall | changed exposure | trusted recall | empty context | avg sources | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 20 | 0.7750 | 0.7750 | 0.0500 | 0.0000 | 25.40 | 0.00 |
| guarded_sources | 20 | 0.0250 | 0.0000 | 0.0500 | 0.0000 | 23.65 | 0.00 |
| recovered_sources_by_doc_id | 20 | 0.7750 | 0.0000 | 0.0500 | 0.0000 | 25.40 | 1.75 |

## 50 Query结果

| method | queries | gold recall | changed exposure | trusted recall | empty context | avg sources | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 50 | 0.7850 | 0.7833 | 0.0900 | 0.0000 | 26.96 | 0.00 |
| guarded_sources | 50 | 0.0400 | 0.0000 | 0.0900 | 0.0000 | 25.24 | 0.00 |
| recovered_sources_by_doc_id | 50 | 0.7850 | 0.0000 | 0.0900 | 0.0000 | 26.96 | 1.72 |

## 结论

- 扩展到 20/50 query 后，`full_query_guard` 仍表现为高召回与高污染暴露并存：50-query 下 `gold recall=0.7850`，`changed exposure=0.7833`。
- `guarded_sources` 可以稳定清除未恢复污染暴露，但会显著牺牲 gold recall：50-query 下只剩 `0.0400`。
- `recovered_sources_by_doc_id` 保持 `full_query_guard` 的 gold recall，同时将未恢复 changed exposure 降为 0：50-query 下 `gold recall=0.7850`，`changed exposure=0.0000`。
- 该结果支持 Stage23 的主要判断在 50-query official context-only 设置下仍成立：sources 级 recovery 是把 query-layer 召回增强转化为可用防御结果的关键步骤。

## 边界

- `recovered_sources_by_doc_id` 仍是 oracle clean-reference recovery，上界意义强，不能直接代表无干净库真实部署。
- 本阶段只替换 `context_data.sources`，未重写 entities、relationships、reports 或 claims。
- 本阶段不包含 LLM answer-level 指标；最终回答正确率、拒答率和攻击成功率需要后续小规模回答实验验证。
- 20/50-query seed plan 的 anomaly excludes 仍复用 Stage22 5-query baseline context 中的重复实体诊断，后续可补齐 20/50-query baseline context 以增强 seed 审计。

## 产物路径

- 20-query seed plan：`outputs/ms_graphrag_query/stage24_poisoned20_query_seed_plan.jsonl`
- 20-query official context：`outputs/ms_graphrag_query/stage24_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- 20-query sources recovery summary：`outputs/ms_graphrag_query/stage24_poisoned20_sources_recovery_summary.csv`
- 20-query report：`outputs/reports/Stage24_官方GraphRAG_Sources级Recovery_20Query实验报告.md`
- 50-query seed plan：`outputs/ms_graphrag_query/stage24_poisoned50_query_seed_plan.jsonl`
- 50-query official context：`outputs/ms_graphrag_query/stage24_poisoned50_query_guard_contexts_full_query_guard.jsonl`
- 50-query sources recovery summary：`outputs/ms_graphrag_query/stage24_poisoned50_sources_recovery_summary.csv`
- 50-query report：`outputs/reports/Stage24_官方GraphRAG_Sources级Recovery_50Query实验报告.md`
