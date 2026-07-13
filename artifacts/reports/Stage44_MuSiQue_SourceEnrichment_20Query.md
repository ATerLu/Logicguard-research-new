# Stage44-MuSiQue 候选源扩展诊断

## 实验目的

在 recovered official GraphRAG sources 的基础上，从干净 candidate pool 追加非 oracle 候选源，评估能否补回检索阶段遗漏的支持证据。

## 重要边界

- `query_bm25_append` 只使用 query 与 clean candidate 文本的 BM25/标题重叠，不使用 gold answer 或 support doc_id。
- `oracle_support_append` 只作为诊断上界，使用 support doc_id，不能作为部署策略。
- 本阶段是 answerability/source-enrichment proxy；真实回答收益需要后续 LLM answer run 复验。

## 实验设置

- 数据集：`musique`
- 输入 contexts：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- clean candidate pool：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready/output`
- 评估行数：`240`
- enriched context rows：`20`
- selected context：`query_bm25_append` + top-12

## 汇总结果

| 方法 | 扩展策略 | oracle? | max sources | query数 | answer surface | support answer surface | baseline support surface | support gain | clean answerable | support hit | full support | unsafe | avg tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 8 | 20 | 0.3500 | 0.3000 | 0.3000 | 0.0000 | 0.3500 | 0.9500 | 0.3000 | 0.0000 | 1089.05 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 12 | 20 | 0.3500 | 0.3000 | 0.3000 | 0.0000 | 0.3500 | 1.0000 | 0.3000 | 0.0000 | 1598.85 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 16 | 20 | 0.3500 | 0.3000 | 0.3000 | 0.0000 | 0.3500 | 1.0000 | 0.3500 | 0.0000 | 2116.70 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 8 | 20 | 0.3500 | 0.3000 | 0.3000 | 0.0000 | 0.3500 | 0.9500 | 0.3000 | 0.0000 | 1089.05 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 12 | 20 | 0.4000 | 0.4000 | 0.3000 | 0.1000 | 0.4000 | 1.0000 | 0.6000 | 0.0000 | 1594.05 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 16 | 20 | 0.4000 | 0.4000 | 0.3000 | 0.1000 | 0.4000 | 1.0000 | 0.7000 | 0.0000 | 2098.35 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 8 | 20 | 0.1000 | 0.1000 | 0.3000 | 0.1000 | 0.1000 | 0.5500 | 0.0000 | 0.0000 | 1089.60 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 12 | 20 | 0.1000 | 0.1000 | 0.3000 | 0.1000 | 0.1000 | 0.5500 | 0.0000 | 0.0000 | 1591.20 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 16 | 20 | 0.1000 | 0.1000 | 0.3000 | 0.1000 | 0.1000 | 0.5500 | 0.0500 | 0.0000 | 2077.60 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 8 | 20 | 0.3500 | 0.3000 | 0.3000 | 0.0000 | 0.3500 | 0.9500 | 0.3000 | 0.0000 | 1089.05 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 12 | 20 | 0.4500 | 0.4500 | 0.3000 | 0.1500 | 0.4500 | 1.0000 | 1.0000 | 0.0000 | 1204.60 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 16 | 20 | 0.4500 | 0.4500 | 0.3000 | 0.1500 | 0.4500 | 1.0000 | 1.0000 | 0.0000 | 1204.60 |

## 主要结论

最佳非 oracle 设置是 `query_bm25_append` + top-12，support answer surface rate 为 `0.4000`，clean answerable rate 为 `0.4000`。

oracle support append 上界为 `0.4500`，用于判断剩余缺口是否来自 candidate ranking，而不是回答 prompt。

## 代表样例

| query_id | 策略 | max sources | label | gold answer | added docs | support hit | first answer rank |
| --- | --- | ---: | --- | --- | --- | --- | ---: |
| `2hop__460091_405771` | `oracle_support_append` | 12 | `answerable_clean` | `Coleoptera` | `6688` | `6681;6688` | 9 |
| `2hop__460091_405771` | `oracle_support_append` | 16 | `answerable_clean` | `Coleoptera` | `6688` | `6681;6688` | 9 |
| `4hop1__802394_153080_159767_81096` | `oracle_support_append` | 12 | `answerable_clean` | `Mario Andretti` | `1036;1042;962;959` | `1036;1042;962;959` | 12 |
| `4hop1__802394_153080_159767_81096` | `oracle_support_append` | 16 | `answerable_clean` | `Mario Andretti` | `1036;1042;962;959` | `1036;1042;962;959` | 12 |
| `4hop1__802394_153080_159767_81096` | `query_bm25_append` | 12 | `answerable_clean` | `Mario Andretti` | `1042;959;4906;962` | `1042;962;959` | 10 |
| `4hop1__802394_153080_159767_81096` | `query_bm25_append` | 16 | `answerable_clean` | `Mario Andretti` | `1042;959;4906;962;11097;10370;11563;584` | `1042;962;959` | 10 |
| `4hop1__802394_153080_159767_81096` | `query_bm25_rerank` | 8 | `answerable_clean` | `Mario Andretti` | `1042;959;4906;962;11097;10370;813;5307` | `1042;962;959` | 2 |
| `4hop1__802394_153080_159767_81096` | `query_bm25_rerank` | 12 | `answerable_clean` | `Mario Andretti` | `1042;959;4906;962;11097;10370;813;5307;9333;11234;10101;11129` | `1042;962;959` | 2 |
| `4hop1__802394_153080_159767_81096` | `query_bm25_rerank` | 16 | `answerable_clean` | `Mario Andretti` | `1042;959;4906;962;11097;10370;813;5307;9333;11234;10101;11129;582;10690;9782;570` | `1042;962;959` | 2 |
| `2hop__126306_396277` | `query_bm25_rerank` | 8 | `missing_answer_surface` | `Doctor De Soto` | `11234;1042;5175;3148;761;6100;10690;8260` | `` |  |
| `2hop__126306_396277` | `query_bm25_rerank` | 12 | `missing_answer_surface` | `Doctor De Soto` | `11234;1042;5175;3148;761;6100;10690;8260;10101;584;2290;4318` | `` |  |
| `2hop__126306_396277` | `query_bm25_rerank` | 16 | `missing_answer_surface` | `Doctor De Soto` | `11234;1042;5175;3148;761;6100;10690;8260;10101;584;2290;4318;4956;1534;1061;7589` | `` |  |

## 产物路径

- 扩展后 context JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_query_bm25_append_top12_contexts.jsonl`
- 扩展明细 JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_source_enrichment_rows.jsonl`
- 汇总 CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_source_enrichment_summary.csv`
- 代表样例 JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_source_enrichment_examples.jsonl`
