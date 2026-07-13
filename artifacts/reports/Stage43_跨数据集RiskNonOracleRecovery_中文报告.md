# Stage43 跨数据集 Risk-Non-Oracle Source Recovery

更新日期：2026-07-12

## 实验定位

Stage43 将 2WikiMultihopQA 已验证的 Stage28 source-level 防御迁移至 HotpotQA 与 MuSiQue。输入是 Stage42 在 poisoned official GraphRAG workspace 导出的 20-query `full_query_guard` source contexts；防御在运行时只使用 query、source 文本/标题/实体和 clean GraphRAG candidate pool，不读取 `changed_support_doc_ids`、gold answer 或 support doc_id。后者只用于离线评估。

本阶段只验证 source-level risk detection 与 recovery，不调用回答 LLM，因此不产生 utility、最终正确率或 attack success 结论。

## 固定设置

- 数据集：HotpotQA、MuSiQue，各 20 条 query。
- 候选库：各数据集的 clean official GraphRAG `text_units`。
- 风险阈值：标题重合度 `0.80`，实体漂移 `0.10`，沿用 Stage28 设置，不按本轮结果重新调参。
- 策略：`full_query_guard`、仅过滤的 `risk_non_oracle_guarded_sources`、恢复的 `risk_non_oracle_title_entity_bm25`。

## 汇总结果

| 数据集 | 方法 | gold support recall | changed exposure | risk recall | risk precision | risk FP rate | empty context | 平均 source | 平均恢复 source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | `full_query_guard` | 0.8750 | 0.8750 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 33.10 | 0.00 |
| HotpotQA | `risk_non_oracle_guarded_sources` | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 0.00 | 0.00 |
| HotpotQA | `risk_non_oracle_title_entity_bm25` | 0.8750 | 0.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 33.10 | 33.10 |
| MuSiQue | `full_query_guard` | 0.7375 | 0.7375 | 0.9950 | 1.0000 | 0.0000 | 0.0000 | 31.65 | 0.00 |
| MuSiQue | `risk_non_oracle_guarded_sources` | 0.0250 | 0.0000 | 0.9950 | 1.0000 | 0.0000 | 0.8500 | 0.20 | 0.00 |
| MuSiQue | `risk_non_oracle_title_entity_bm25` | 0.7375 | 0.0000 | 0.9950 | 1.0000 | 0.0000 | 0.0000 | 31.65 | 31.45 |

## 结果解读

1. 两个数据集均复现了“只过滤不具可用性、恢复才能同时保留证据”的结构性结论。HotpotQA 仅过滤后 20 条 context 全为空；MuSiQue 的空 context 比例为 0.85。相反，恢复策略保留了与 `full_query_guard` 相同的 gold support recall，并将未恢复的 changed support exposure 降为 0。

2. HotpotQA 的 2 条 Stage42 检索失败仍然无法被 recovery 修复：其 gold support recall 为 0，因为 support 在防御前就未进入 source context。另有 1 条 query 仅命中一半 support。因此 recovery 解决的是“已检索到的污染证据如何替换”，不是“完全漏检的证据如何找回”。

3. 本轮恢复几乎全部是同一文档、同一标题的 clean-version 替换：HotpotQA 为 `662/662`，MuSiQue 为 `629/629`。这说明跨数据集结果稳健地验证了 clean-reference consistency recovery，但尚未充分考验无标题精确匹配时的 title/entity/BM25 候选排序能力。

4. 风险检测在 HotpotQA 将全部 662 个 source 实例标为风险，在 MuSiQue 标记 629/633 个实例。该现象符合当前 poisoned workspace 与 clean candidate pool 的整体版本差异，但也说明本设置中检测器选择性仍弱，不能据此宣称其能在 clean/poisoned 混合生产语料中精准地只拦截少数恶意 source。

5. MuSiQue 有 4 个未判风险 source 实例；代表文档 `11334`（`A Dog's Purpose (film)`）的标题重合度为 1.0、实体漂移为 0.0、文本 Jaccard 为 0.8947，因此未跨过实体漂移阈值。它给出了后续低实体漂移自适应攻击的明确测试靶点。

## 结论与边界

Stage43 已把 LogicGuard 的核心 source-level 结论从单一 2Wiki 数据集扩展到 HotpotQA 和 MuSiQue：在受控 LogicPoison 语料、可信 clean candidate pool 和 official GraphRAG source context 条件下，risk-non-oracle recovery 可以保持 Stage42 的 support recall，同时把 changed support exposure 降为 0。

这不是 no-clean 部署结论，也不是最终 answer-level 安全结论。风险 precision/recall 依赖当前 query-integrity 中可用的全局 changed support 标注做离线核验；当前还没有在两个新数据集上运行 source enrichment、链路补证、真实 LLM 回答和 judge 审计。

## 当前资产状态与下一步

Stage40 readiness 审计现在将 HotpotQA 与 MuSiQue 的下一动作统一更新为 `run_stage35_source_enrichment`。下一阶段应先复用 Stage35 的 `query_bm25_append` 完成跨数据集 source enrichment，再判断是否需要二跳补证，并最终接入 answer-level 验证。并行研究线是构造低实体漂移、候选碰撞和证据拆分的自适应攻击，检验本阶段暴露出的选择性短板。

## 主要产物

- HotpotQA contexts：[stage40_hotpotqa_poisoned20_risk_non_oracle_sources_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_risk_non_oracle_sources_contexts.jsonl)
- HotpotQA metrics：[stage40_hotpotqa_poisoned20_risk_non_oracle_sources_metrics.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_risk_non_oracle_sources_metrics.csv)
- MuSiQue contexts：[stage40_musique_poisoned20_risk_non_oracle_sources_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_contexts.jsonl)
- MuSiQue metrics：[stage40_musique_poisoned20_risk_non_oracle_sources_metrics.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_metrics.csv)
- Stage40 最新 readiness：[stage40_cross_dataset_readiness_summary.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv)
