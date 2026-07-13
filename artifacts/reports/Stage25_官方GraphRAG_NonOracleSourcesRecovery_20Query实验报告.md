# Microsoft GraphRAG Stage25 非 oracle Sources 级 Recovery 实验报告

## 实验目的

Stage25 在 official GraphRAG local search 已导出的 `context_data.sources` 上运行。它先沿用 Stage23/24 的风险 oracle 触发，即用 changed source 标记决定哪些 source 需要替换；随后不再按 doc_id 直接取 clean source，而是从 trusted clean text unit 候选池中用 query、source title 和 GraphRAG entity evidence 排序选取替换项。

## 边界说明

- 本阶段是 doc_id-blind / gold-blind candidate recovery，不是完整无 oracle 防御。
- `changed_support_doc_ids` 只用于风险触发和离线评估，不作为候选排序特征。
- `recovered_sources_by_doc_id` 保留为 Stage23/24 oracle 上界，用于计算 oracle gap。
- `same-doc recovery` 只说明排序结果碰巧选回同一 gold doc_id，不表示使用了 doc_id lookup。
- 当前仍是 context-only 指标，回答层 ASR/EM/F1 需要后续 LLM 评估补齐。

## 方法

- `non_oracle_query_bm25`: 仅用 query BM25 和很弱的候选顺序先验。
- `non_oracle_title_entity_bm25`: 以 source title overlap 与 entity overlap 为主，query BM25 为辅。
- `non_oracle_hybrid_policy`: 综合 query BM25、title overlap、entity overlap 与弱先验。

## 汇总结果

| method | queries | gold recall | changed exposure | oracle gap | replacement hit | bad replacement | same-doc recovery | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 20 | 0.7750 | 0.7750 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| guarded_sources | 20 | 0.0250 | 0.0000 | 0.7500 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| recovered_sources_by_doc_id | 20 | 0.7750 | 0.0000 | 0.0000 | 0.7750 | 0.0000 | 0.7750 | 1.75 |
| non_oracle_query_bm25 | 20 | 0.4750 | 0.0000 | 0.3000 | 0.4750 | 0.0000 | 0.4750 | 1.75 |
| non_oracle_title_entity_bm25 | 20 | 0.5250 | 0.0000 | 0.2500 | 0.5250 | 0.0000 | 0.5250 | 1.75 |
| non_oracle_hybrid_policy | 20 | 0.5000 | 0.0000 | 0.2750 | 0.5000 | 0.0000 | 0.5000 | 1.75 |

## 主要对照

- full_query_guard: gold recall 0.7750, changed exposure 0.7750.
- guarded_sources: gold recall 0.0250, changed exposure 0.0000.
- oracle recovered_sources_by_doc_id: gold recall 0.7750, changed exposure 0.0000.
- non_oracle_hybrid_policy: gold recall 0.5000, changed exposure 0.0000, oracle gap 0.2750.

## 产物路径

- context JSONL: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage25_poisoned20_non_oracle_sources_contexts.jsonl`
- query metrics CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage25_poisoned20_non_oracle_sources_metrics.csv`
- method summary CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage25_poisoned20_non_oracle_sources_summary.csv`
