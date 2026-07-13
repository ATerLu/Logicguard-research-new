# Stage40 跨数据集 official GraphRAG readiness 审计

## 实验目的

Stage40 的目标不是重新调用 GraphRAG 或 LLM，而是把 2WikiMultihopQA、HotpotQA、MuSiQue 是否具备 official GraphRAG source-level recovery 和 chain-level 复核条件审计清楚。

本阶段坚持一个原则：不能把缺索引的数据集计入防御效果结论。

## 资产审计汇总

| 数据集 | samples | integrity | clean idx | poisoned idx | baseline | broad | query context | recovery | enrichment | chain | judge | 下一步 |
| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `2wikimultihopqa` | 50 | 500 | ready | ready | ready | ready | ready | ready | ready | ready | ready | `ready_for_attribute_sentence_completeness_or_adaptive_attack` |
| `hotpotqa` | 50 | 500 | ready | ready | ready | ready | ready | ready | ready | ready | ready | `ready_for_attribute_sentence_completeness_or_adaptive_attack` |
| `musique` | 50 | 500 | ready | ready | ready | ready | ready | ready | ready | ready | ready | `ready_for_attribute_sentence_completeness_or_adaptive_attack` |

## 当前结论

- 已具备完整 Stage28/35/38/answer-judge 复核资产的数据集：`2wikimultihopqa`, `hotpotqa`, `musique`。
- 尚不能进入跨数据集防御效果比较的数据集：无。
- 因此 Stage40 的科学结论是 readiness/gap 结论，而不是新的 attack success 或 utility 结果。

## 阻断项与补齐动作

| 数据集 | 阻断动作 | 原因 |
| --- | --- | --- |
| 全部 | 无 | 当前配置的数据集均已具备后续验证资产。 |

## 关键补齐命令

当前没有阻断项。

## 输出文件

- asset rows JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_asset_rows.jsonl`
- summary CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv`
- gap actions JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_cross_dataset_gap_actions.jsonl`
