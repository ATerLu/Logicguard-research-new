# Microsoft GraphRAG official local context 导出报告

## 实验目的

本阶段直接调用 Microsoft GraphRAG Python `api.local_search`，导出官方 local search 的 `context_data`，包括 sources、entities、relationships 和 reports。该产物用于后续把 LogicGuard 接到真正的 official local query context 上。

## 配置摘要

- 数据集：`hotpotqa`
- 样本数：`5`
- workspace：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag\hotpotqa\stage40_debug50_poisoned_query_ready`
- community_level：`2`
- response_type：`Single Sentence`
- local_search_overrides：`{'text_unit_prop': 0.8, 'community_prop': 0.0, 'top_k_entities': 60, 'top_k_relationships': 60, 'max_context_tokens': 24000}`

## 导出结果

| query_id | sources | entities | relationships | reports | response preview |
| --- | ---: | ---: | ---: | ---: | --- |
| 5abd882f55429924427fd045 | 68 | 86 | 177 | 0 | I do not know the answer based on the provided data. |
| 5a78ed6855429970f5fffdd9 | 69 | 86 | 175 | 0 | I do not know the answer. |
| 5a729cc25542991f9a20c532 | 67 | 86 | 173 | 0 | I do not know the answer, as the provided data tables do not contain information regarding the Symbionese Liberation Army or any author who wrote about a woman ... |
| 5adc7f4a5542994650320d28 | 66 | 86 | 175 | 0 | The culmination game of the United States Poker Championship was a no-limit *Texas hold 'em* (referred to as *France hold 'em* in the provided texts) tournament ... |
| 5a84e0a45542991dd0999e11 | 67 | 87 | 176 | 0 | Steel Venom is farther north, as the provided text locates it in New Jersey and Wicked Twister in Tennessee, while general knowledge corrects their actual locat ... |

## 产物路径

- JSONL：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag_query\stage40_hotpotqa_poisoned5_broad_context.jsonl`
