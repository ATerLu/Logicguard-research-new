# Microsoft GraphRAG official local context 导出报告

## 实验目的

本阶段直接调用 Microsoft GraphRAG Python `api.local_search`，导出官方 local search 的 `context_data`，包括 sources、entities、relationships 和 reports。该产物用于后续把 LogicGuard 接到真正的 official local query context 上。

## 配置摘要

- 数据集：`musique`
- 样本数：`5`
- workspace：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag\musique\stage40_debug50_poisoned_query_ready`
- community_level：`2`
- response_type：`Single Sentence`
- local_search_overrides：`{}`

## 导出结果

| query_id | sources | entities | relationships | reports | response preview |
| --- | ---: | ---: | ---: | ---: | --- |
| 3hop1__593288_720914_27537 | 33 | 19 | 130 | 9 | I do not know. |
| 2hop__21104_16334 | 32 | 19 | 153 | 8 | I don't know, as the provided data does not contain information about a 2010 study or the genetic relationships of the group representing at least 70% of Jews w ... |
| 2hop__126306_396277 | 32 | 18 | 139 | 9 | I do not know the answer, as the provided data does not contain information about the illustrator of *Sylvester and the Magic Pebble* or their other works. |
| 3hop1__9285_5188_86687 | 30 | 18 | 136 | 7 | I don't know the answer. |
| 2hop__53147_7298 | 31 | 17 | 115 | 7 | Based on the provided data, I do not know which notable pop artist started out his career on adult contemporary radio alongside the subject of Katy Perry's "The ... |

## 产物路径

- JSONL：`F:\LogicGuard_project\logicguard\outputs\ms_graphrag_query\stage40_musique_poisoned5_official_local_context.jsonl`
