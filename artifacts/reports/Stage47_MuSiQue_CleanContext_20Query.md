# Microsoft GraphRAG Stage20 Query-layer Context导出报告

## 实验目的

通过GraphRAG 3.1.0官方LocalSearchMixedContext接口注入或排除实体，不修改官方源码，也不调用回答模型。

## 指标说明

- avg include：每个query显式前置的实体数。
- avg exclude：每个query从embedding候选中排除的异常实体数。
- fallback：没有有效include/exclude并退化为baseline的query数。

## 导出汇总

| method | rows | avg include | avg exclude | fallback |
| --- | ---: | ---: | ---: | ---: |
| full_query_guard | 20 | 3.45 | 8.70 | 0 |

- 输出：F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage47_musique_clean20_query_guard_contexts.jsonl
- 总行数：20
