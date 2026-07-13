# Microsoft GraphRAG official local context 导出报告

## 实验目的

本阶段直接调用 Microsoft GraphRAG Python `api.local_search`，导出官方 local search 的 `context_data`，包括 sources、entities、relationships 和 reports。该产物用于后续把 LogicGuard 接到真正的 official local query context 上。

## 配置摘要

- 数据集：`hotpotqa`
- 样本数：`5`
- workspace：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag\hotpotqa\stage40_debug50_poisoned_query_ready`
- community_level：`2`
- response_type：`Single Sentence`
- local_search_overrides：`{}`

## 导出结果

| query_id | sources | entities | relationships | reports | response preview |
| --- | ---: | ---: | ---: | ---: | --- |
| 5abd882f55429924427fd045 | 28 | 13 | 52 | 9 | I do not know the answer. |
| 5a78ed6855429970f5fffdd9 | 28 | 15 | 67 | 7 | I do not know the answer, as the provided data does not contain information about Canobie Lake or the population of any town that gets its water supply from it. |
| 5a729cc25542991f9a20c532 | 31 | 16 | 60 | 14 | I do not know the answer, as the provided data does not contain any information regarding the Symbionese Liberation Army or an author who wrote about a woman ca ... |
| 5adc7f4a5542994650320d28 | 28 | 15 | 53 | 8 | I do not know the answer, as the provided data does not contain any information regarding the United States Poker Championship or its culmination game. |
| 5a84e0a45542991dd0999e11 | 26 | 16 | 55 | 9 | I do not know which is farther north, as the provided data does not contain any information regarding the location of Steel Venom. |

## 产物路径

- JSONL：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag_query\stage40_hotpotqa_poisoned5_official_local_context.jsonl`
