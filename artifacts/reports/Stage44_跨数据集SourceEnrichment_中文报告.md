# Stage44 跨数据集 Source Enrichment

更新日期：2026-07-12

## 实验定位

Stage44 以 Stage43 的 HotpotQA/MuSiQue risk-non-oracle recovered contexts 为固定输入，复用 Stage35 的 source enrichment 消融。目标是从可信 clean candidate pool 中追加 query 相关的候选 source，补回 Stage42 检索和 Stage43 恢复之后仍缺失的支持证据。

运行时的 `query_bm25_append` 只使用 query、candidate 标题与正文 BM25，不使用 gold answer 或 support doc_id。`oracle_support_append` 仅作为离线可达上界。本阶段未调用回答 LLM，也没有接入先前 answer audit，因此 `answer surface` 与 `clean answerable` 均只是 source/context-level proxy。

## 设置

- 数据集：HotpotQA、MuSiQue，各 20 条 query。
- 输入：Stage43 `risk_non_oracle_title_entity_bm25` recovered source contexts。
- 候选库：各自 clean official GraphRAG `text_units`。
- 比较：`stage33_title_overlap`、`query_bm25_append`、`query_bm25_rerank` 与 `oracle_support_append`；top-8/12/16。
- 后续导出策略：`query_bm25_append + top-12`。top-16 在两个数据集都没有提高 answer surface，且平均增加约 500 prompt tokens。

## 关键结果

| 数据集 | 策略 | answer surface | support answer surface | clean answerable | support hit | full support | unsafe context | 平均 tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | title-overlap top-8 | 0.6000 | 0.6000 | 0.6000 | 0.8500 | 0.7500 | 0.0000 | 1042.45 |
| HotpotQA | BM25 append top-12 | 0.8500 | 0.8000 | 0.8500 | 1.0000 | 0.9500 | 0.0000 | 1517.05 |
| HotpotQA | BM25 rerank top-12 | 0.3500 | 0.1500 | 0.3500 | 0.2000 | 0.1000 | 0.0000 | 1518.80 |
| HotpotQA | oracle append top-12 | 0.8500 | 0.8500 | 0.8500 | 1.0000 | 1.0000 | 0.0000 | 1087.80 |
| MuSiQue | title-overlap top-8 | 0.3500 | 0.3000 | 0.3500 | 0.9500 | 0.3000 | 0.0000 | 1089.05 |
| MuSiQue | BM25 append top-12 | 0.4000 | 0.4000 | 0.4000 | 1.0000 | 0.6000 | 0.0000 | 1594.05 |
| MuSiQue | BM25 rerank top-12 | 0.1000 | 0.1000 | 0.1000 | 0.5500 | 0.0000 | 0.0000 | 1591.20 |
| MuSiQue | oracle append top-12 | 0.4500 | 0.4500 | 0.4500 | 1.0000 | 1.0000 | 0.0000 | 1204.60 |

## 结论

1. `query_bm25_append` 在两个数据集都优于简单扩大已有 source，也显著优于对全部候选重新排序。后者会挤掉 Stage43 已恢复的证据：HotpotQA full support 从 0.75 降至 0.10，MuSiQue 从 0.30 降至 0。

2. HotpotQA 的 non-oracle append 基本接近上界：full support `0.75 -> 0.95`，support answer surface `0.60 -> 0.80`。四条 query 新获得 support answer surface，其中 `DeskMate`、`Larnelle Harris`、`1943` 和 `Morning glory` 都由新增 clean support source 支撑。唯一仍不完整的 `Paul Avery` query 只补回部分 support，说明它需要后续链路补证。

3. MuSiQue 的非 oracle append 也带来改善，但 candidate ranking 缺口更大：full support `0.30 -> 0.60`，而 oracle 上界为 `1.00`；support answer surface 仅从 `0.30 -> 0.40`。这说明 MuSiQue 的多跳链更长、query BM25 对中间桥接实体的定位不足，不能用简单扩大 top-k 代替链路诊断。

4. 选定 top-12 context 的 480 个 source 实例均为 `clean_reference`，两个数据集的 `unsafe_context_rate` 都为 0。这确认 source enrichment 没有把 Stage43 已消除的未恢复污染 source 再带回上下文。

## 边界与下一步

本阶段仍依赖可信 clean candidate pool，且没有真实 LLM answer、judge 或 adaptive attack；因此不能将 `clean_answerable_rate` 解释为最终回答正确率。Stage40 readiness 审计已将 HotpotQA/MuSiQue 的下一动作推进为 `run_stage38_chain_completeness`。

下一阶段应以选定的 top-12 contexts 为输入，复用 Stage38 做跨数据集的 chain-completeness 与 targeted second-hop append：优先分析 HotpotQA 的 `Paul Avery` 和 MuSiQue 剩余 8 条不完整 support 链，再决定是否进入 answer-level 复验。

## 主要产物

- HotpotQA selected contexts：[stage40_hotpotqa_poisoned20_query_bm25_append_top12_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_bm25_append_top12_contexts.jsonl)
- HotpotQA summary：[stage40_hotpotqa_poisoned20_source_enrichment_summary.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_source_enrichment_summary.csv)
- MuSiQue selected contexts：[stage40_musique_poisoned20_query_bm25_append_top12_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_query_bm25_append_top12_contexts.jsonl)
- MuSiQue summary：[stage40_musique_poisoned20_source_enrichment_summary.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_source_enrichment_summary.csv)
- 最新 readiness：[stage40_cross_dataset_readiness_summary.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv)
