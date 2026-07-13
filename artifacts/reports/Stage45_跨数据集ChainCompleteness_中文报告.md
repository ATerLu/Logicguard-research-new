# Stage45 跨数据集 Chain Completeness 与二跳补证

更新日期：2026-07-12

## 实验定位

Stage45 以 Stage44 的 `query_bm25_append + top-12` clean contexts 为输入，对 HotpotQA 与 MuSiQue 各 20 条 query 做 source/chain-level 诊断。它离线使用 support doc_id 判断支撑链是否完整；运行时二跳候选排序只使用 query、当前 source 标题、正文中抽取的实体桥接词和 clean candidate 文本，不使用 support doc_id、gold answer 或污染标签。

本阶段未调用回答 LLM，也没有历史回答审计输入。因此 CSV 中 `answer_audit_available=0`，utility 与 attack success 均为空值；`complete_but_unanswered` 只表示 source 链已经完整但尚未执行回答层验证，不能理解为模型拒答或模型错误。

## 设置

- 输入：Stage44 的 12-source clean contexts。
- 二跳策略：每条 query 保留 12 个 source，再追加至多 2 个 bridge-aware clean candidates，形成 top-14 targeted context。
- 候选库：各数据集的 clean official GraphRAG `text_units`。
- 样本：HotpotQA 20 条，MuSiQue 20 条。

## 汇总结果

| 数据集 | 基线 full support / chain complete | targeted full support / chain complete | 完整链增益 | 新增 support 率 | 平均 tokens | targeted tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | 0.9500 / 0.9500 | 0.9500 / 0.9500 | 0.0000 | 0.0000 | 1517.05 | 1761.75 |
| MuSiQue | 0.6000 / 0.6000 | 0.8000 / 0.8000 | 0.2000 | 0.2000 | 1594.05 | 1861.30 |

两个 targeted context 集合的 560 个 source 实例均为 `clean_reference`，因此二跳补证没有重新引入未恢复污染 source。

## 结果解读

1. MuSiQue 的 bridge-aware 二跳追加有效补齐了 4 条 query 的缺失 support，使完整链比例从 `0.60` 升至 `0.80`。其中 `modern-day Italians`、`Sea, Air, and Land`、`$72,641`、`Mario Andretti` 分别补入 doc `11305`、`387`、`990`、`1036`。

2. 这 4 条 MuSiQue 追加后仍没有增加 answer surface；两条从“答案表面存在但缺链”转为“链完整、待回答验证”，两条转为“链完整但 support 中尚无答案表面”。因此 Stage45 证明了证据链被补齐，尚未证明最终答案一定提高。

3. HotpotQA 的 Stage44 已有 `0.95` 完整链，剩余 `Paul Avery` query 缺少 doc `5654`。当前 bridge terms 被 `Lantern Waste`、`Mr. Tumnus` 等无关实体淹没，二跳排序追加了 `7369` 与 `4883`，未命中缺失 support。对 HotpotQA 来说，本轮无条件 top-14 追加仅增加约 245 tokens，没有链路收益。

4. 这揭示了下一步的设计要求：二跳扩展不应对全部 query 一视同仁。应在不使用 support oracle 的前提下引入“是否存在可验证桥接候选”的风险/收益门控，或只在 answer-level 审计显示证据不足时触发扩展；否则 complete query 会积累无关上下文噪声。

## 结论与后续验证

Stage45 将跨数据集防御链推进到 source/chain-level 完整性：HotpotQA 已基本由 Stage44 覆盖，MuSiQue 通过二跳桥接修复了额外 20% 的完整 support 链。该差异表明 LogicGuard 的 recovery 与 enrichment 不是单一固定 top-k 策略，而需要针对多跳链深度自适应地扩展证据。

Stage46 应进入真实 answer-level 验证，但应采用公平对照：HotpotQA 以 Stage44 top-12 作为主输入，并将 Stage45 top-14 作为“无收益扩展”的对照；MuSiQue 对比 Stage44 top-12 与 Stage45 targeted top-14，重点检查这 4 条补链 query 是否真的提高 correct/partial、是否出现新的错误回答，以及 attack success 是否仍为 0。

## 主要产物

- HotpotQA chain rows：[stage40_hotpotqa_poisoned20_chain_completeness_rows.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_chain_completeness_rows.jsonl)
- HotpotQA targeted contexts：[stage40_hotpotqa_poisoned20_second_hop_append_top14_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_second_hop_append_top14_contexts.jsonl)
- MuSiQue chain rows：[stage40_musique_poisoned20_chain_completeness_rows.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_chain_completeness_rows.jsonl)
- MuSiQue targeted contexts：[stage40_musique_poisoned20_second_hop_append_top14_contexts.jsonl](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_second_hop_append_top14_contexts.jsonl)
- 最新 readiness：[stage40_cross_dataset_readiness_summary.csv](F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv)
