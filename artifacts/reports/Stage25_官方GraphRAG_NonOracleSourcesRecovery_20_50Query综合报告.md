# Stage25 官方 GraphRAG Non-oracle Sources Recovery 20/50 Query 综合报告

## 实验目的

Stage25 在 Stage24 已完成的 official `context_data.sources` 级 oracle recovery 基础上，进一步降低 doc_id 直接对齐假设。实验仍保留 `recovered_sources_by_doc_id` 作为 oracle 上界，但新增三类 doc_id-blind / gold-blind 候选排序策略，从 trusted clean text unit candidate pool 中恢复被 changed source 占据的位置。

本阶段仍属于 `risk_oracle + recovery_non_oracle` 设置：`changed_support_doc_ids` 只用于风险触发和离线评估，不用于候选排序。候选排序仅使用 query、source title、GraphRAG entities、candidate title/text 和弱排序先验。

## 方法设置

| 方法 | 含义 |
| --- | --- |
| `full_query_guard` | Stage24 query-layer guard 导出的 official sources，不做 source 后处理 |
| `guarded_sources` | 删除 changed support source，不做补回 |
| `recovered_sources_by_doc_id` | Stage23/24 oracle clean-reference doc_id recovery，上界对照 |
| `non_oracle_query_bm25` | 只用 query BM25 与弱候选顺序先验排序 |
| `non_oracle_title_entity_bm25` | 主要用 source title overlap 与 entity overlap，辅以 query BM25 |
| `non_oracle_hybrid_policy` | 综合 query BM25、title overlap、entity overlap 与弱先验 |

## 20-query 结果

| 方法 | gold recall | changed exposure | oracle gap | replacement hit | bad replacement | same-doc recovery | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_query_guard` | 0.7750 | 0.7750 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| `guarded_sources` | 0.0250 | 0.0000 | 0.7500 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| `recovered_sources_by_doc_id` | 0.7750 | 0.0000 | 0.0000 | 0.7750 | 0.0000 | 0.7750 | 1.75 |
| `non_oracle_query_bm25` | 0.4750 | 0.0000 | 0.3000 | 0.4750 | 0.0000 | 0.4750 | 1.75 |
| `non_oracle_title_entity_bm25` | 0.5250 | 0.0000 | 0.2500 | 0.5250 | 0.0000 | 0.5250 | 1.75 |
| `non_oracle_hybrid_policy` | 0.5000 | 0.0000 | 0.2750 | 0.5000 | 0.0000 | 0.5000 | 1.75 |

## 50-query 结果

| 方法 | gold recall | changed exposure | oracle gap | replacement hit | bad replacement | same-doc recovery | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_query_guard` | 0.7850 | 0.7833 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| `guarded_sources` | 0.0400 | 0.0000 | 0.7450 | 0.0000 | 0.0000 | 0.0000 | 0.00 |
| `recovered_sources_by_doc_id` | 0.7850 | 0.0000 | 0.0000 | 0.7833 | 0.0000 | 0.7833 | 1.72 |
| `non_oracle_query_bm25` | 0.4700 | 0.0000 | 0.3150 | 0.4583 | 0.0000 | 0.4583 | 1.72 |
| `non_oracle_title_entity_bm25` | 0.5450 | 0.0000 | 0.2400 | 0.5333 | 0.0000 | 0.5333 | 1.72 |
| `non_oracle_hybrid_policy` | 0.4950 | 0.0000 | 0.2900 | 0.4833 | 0.0000 | 0.4833 | 1.72 |

## 主要结论

1. Stage25 证明 non-oracle candidate recovery 已经明显优于只删除 changed source：50-query 下 `non_oracle_title_entity_bm25` 将 `gold recall` 从 `guarded_sources` 的 `0.0400` 提升到 `0.5450`，同时保持 `changed exposure=0.0000`。
2. 最强 non-oracle 方法约达到 oracle 上界 `0.7850` 的 69.4%，对应 `oracle gap=0.2400`。这说明 sources 级 recovery 不完全依赖 doc_id oracle，但仍存在明显提升空间。
3. `title/entity` 信号在当前 official GraphRAG sources 设置下比纯 query BM25 更稳定：50-query 下 `0.5450` 高于纯 BM25 的 `0.4700`。
4. `same-doc recovery` 不表示使用 doc_id lookup，只表示 doc_id-blind 排序结果选回了与 changed support 相同的 clean doc_id。该指标可用于衡量非 oracle 排序离 oracle 上界的接近程度。
5. 本阶段仍不是完整无 oracle 防御。风险触发仍依赖 changed support 标注，候选池仍来自 trusted clean/reference artifacts，且没有调用回答模型。

## 产物路径

- 代码：`src/logicguard/ms_graphrag/non_oracle_source_recovery.py`
- 测试：`tests/test_ms_graphrag_non_oracle_source_recovery.py`
- 20-query 配置：`configs/ms_graphrag_stage25_non_oracle_sources_poisoned20.yaml`
- 50-query 配置：`configs/ms_graphrag_stage25_non_oracle_sources_poisoned50.yaml`
- 20-query summary：`outputs/ms_graphrag_query/stage25_poisoned20_non_oracle_sources_summary.csv`
- 50-query summary：`outputs/ms_graphrag_query/stage25_poisoned50_non_oracle_sources_summary.csv`
- 20-query 单项报告：`outputs/reports/Stage25_官方GraphRAG_NonOracleSourcesRecovery_20Query实验报告.md`
- 50-query 单项报告：`outputs/reports/Stage25_官方GraphRAG_NonOracleSourcesRecovery_50Query实验报告.md`

## 下一步

Stage26 应优先做 answer-level 小规模验证。建议冻结 Stage25 三种 recovery policy，选取 5/20 query，对 `full_query_guard`、`guarded_sources`、`recovered_sources_by_doc_id`、`non_oracle_title_entity_bm25` 进行回答生成和 correct / partial / wrong / abstained / attack-success 评价。自适应攻击应在 answer-level 验证和参数冻结之后再启动。
