# Microsoft GraphRAG Stage24 sources级Recovery实验报告

## 实验目的

Stage24 直接读取 official GraphRAG local search 导出的 `context_data.sources`，在官方上下文已经生成之后，对 source 行执行污染标注、过滤与 clean-reference doc_id 替换。该阶段不修改 Microsoft GraphRAG 源码，也不调用回答模型。

## 重要边界

- 本阶段是 context-only 评估，回答层正确率和攻击成功率需要后续 LLM 实验验证。
- `recovered_sources_by_doc_id` 是 oracle clean-reference recovery，上界意义强，不能等同于无干净库真实部署。
- 当前只替换 `sources`，不重写 official context 中的 entities、relationships、reports 或 claims。
- gold support 只在 context 构建完成后用于指标计算，不参与 Stage24 的 source 替换决策。

## 指标说明

- gold recall：sources 中覆盖 gold support doc_id 的比例，越高越可答。
- changed exposure：未恢复的 changed support source 进入 sources 的比例，越低越安全。
- trusted recall：未改写 support 的召回比例；若样本 support 全部被改写，该项分母为空并记为 0。
- empty context：source 过滤或恢复后 sources 是否为空。
- avg recovered：每个 query 平均由 clean reference 替换回来的 source 数。
- avg filtered：每个 query 平均被过滤且未替换的 source doc_id 数。

## 汇总结果

| method | queries | gold recall | changed exposure | trusted recall | empty context | avg sources | avg source rows | avg recovered | avg filtered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 20 | 0.7750 | 0.7750 | 0.0500 | 0.0000 | 25.40 | 25.40 | 0.00 | 0.00 |
| guarded_sources | 20 | 0.0250 | 0.0000 | 0.0500 | 0.0000 | 23.65 | 23.65 | 0.00 | 1.75 |
| recovered_sources_by_doc_id | 20 | 0.7750 | 0.0000 | 0.0500 | 0.0000 | 25.40 | 25.40 | 1.75 | 0.00 |

## 主对照变化

- sources guard 后 changed exposure：0.7750 -> 0.0000。
- sources guard 后 gold recall：0.7750 -> 0.0250。
- sources recovery 后 changed exposure：0.7750 -> 0.0000。
- sources recovery 后 gold recall：0.7750 -> 0.7750。
- sources recovery 平均替换 source 数：1.75。

## 产物路径

- context JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage24_poisoned20_sources_recovery_contexts.jsonl`
- query 指标 CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage24_poisoned20_sources_recovery_metrics.csv`
- method 汇总 CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage24_poisoned20_sources_recovery_summary.csv`
