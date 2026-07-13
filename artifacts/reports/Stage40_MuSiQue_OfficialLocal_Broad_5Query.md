# Microsoft GraphRAG official local context 导出报告

## 实验目的

本阶段直接调用 Microsoft GraphRAG Python `api.local_search`，导出官方 local search 的 `context_data`，包括 sources、entities、relationships 和 reports。该产物用于后续把 LogicGuard 接到真正的 official local query context 上。

## 配置摘要

- 数据集：`musique`
- 样本数：`5`
- workspace：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag\musique\stage40_debug50_poisoned_query_ready`
- community_level：`2`
- response_type：`Single Sentence`
- local_search_overrides：`{'text_unit_prop': 0.8, 'community_prop': 0.0, 'top_k_entities': 60, 'top_k_relationships': 60, 'max_context_tokens': 24000}`

## 导出结果

| query_id | sources | entities | relationships | reports | response preview |
| --- | ---: | ---: | ---: | ---: | --- |
| 3hop1__593288_720914_27537 | 89 | 108 | 181 | 0 | I don't know. |
| 2hop__21104_16334 | 90 | 110 | 177 | 0 | I do not know the answer, as the provided data tables do not contain information regarding a 2010 study on the modern population most closely related to the gro ... |
| 2hop__126306_396277 | 91 | 109 | 181 | 0 | I do not know the answer, as the provided data does not contain any information about the illustrator of *Sylvester and the Magic Pebble* or their other works. |
| 3hop1__9285_5188_86687 | 90 | 111 | 176 | 0 | I don't know. |
| 2hop__53147_7298 | 89 | 111 | 176 | 0 | Although the provided data notes that Katy Perry's song "The One That Got Away" is about "Yan," I do not know which notable pop artist started his career on adu ... |

## 产物路径

- JSONL：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag_query\stage40_musique_poisoned5_broad_context.jsonl`
