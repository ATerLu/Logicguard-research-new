# Stage44-HotpotQA 候选源扩展诊断

## 实验目的

在 recovered official GraphRAG sources 的基础上，从干净 candidate pool 追加非 oracle 候选源，评估能否补回检索阶段遗漏的支持证据。

## 重要边界

- `query_bm25_append` 只使用 query 与 clean candidate 文本的 BM25/标题重叠，不使用 gold answer 或 support doc_id。
- `oracle_support_append` 只作为诊断上界，使用 support doc_id，不能作为部署策略。
- 本阶段是 answerability/source-enrichment proxy；真实回答收益需要后续 LLM answer run 复验。

## 实验设置

- 数据集：`hotpotqa`
- 输入 contexts：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- clean candidate pool：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready/output`
- 评估行数：`240`
- enriched context rows：`20`
- selected context：`query_bm25_append` + top-12

## 汇总结果

| 方法 | 扩展策略 | oracle? | max sources | query数 | answer surface | support answer surface | baseline support surface | support gain | clean answerable | support hit | full support | unsafe | avg tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 8 | 20 | 0.6000 | 0.6000 | 0.6000 | 0.0000 | 0.6000 | 0.8500 | 0.7500 | 0.0000 | 1042.45 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 12 | 20 | 0.7000 | 0.6500 | 0.6000 | 0.0500 | 0.7000 | 0.8500 | 0.8000 | 0.0000 | 1544.80 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 16 | 20 | 0.7000 | 0.6500 | 0.6000 | 0.0500 | 0.7000 | 0.8500 | 0.8000 | 0.0000 | 2029.50 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 8 | 20 | 0.6000 | 0.6000 | 0.6000 | 0.0000 | 0.6000 | 0.8500 | 0.7500 | 0.0000 | 1042.45 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 12 | 20 | 0.8500 | 0.8000 | 0.6000 | 0.2000 | 0.8500 | 1.0000 | 0.9500 | 0.0000 | 1517.05 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 16 | 20 | 0.8500 | 0.8000 | 0.6000 | 0.2000 | 0.8500 | 1.0000 | 0.9500 | 0.0000 | 2011.10 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 8 | 20 | 0.2000 | 0.1000 | 0.6000 | 0.1000 | 0.2000 | 0.1500 | 0.0500 | 0.0000 | 1026.70 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 12 | 20 | 0.3500 | 0.1500 | 0.6000 | 0.1000 | 0.3500 | 0.2000 | 0.1000 | 0.0000 | 1518.80 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 16 | 20 | 0.3500 | 0.1500 | 0.6000 | 0.1000 | 0.3500 | 0.2000 | 0.1000 | 0.0000 | 2009.65 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 8 | 20 | 0.6000 | 0.6000 | 0.6000 | 0.0000 | 0.6000 | 0.8500 | 0.7500 | 0.0000 | 1042.45 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 12 | 20 | 0.8500 | 0.8500 | 0.6000 | 0.2500 | 0.8500 | 1.0000 | 1.0000 | 0.0000 | 1087.80 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 16 | 20 | 0.8500 | 0.8500 | 0.6000 | 0.2500 | 0.8500 | 1.0000 | 1.0000 | 0.0000 | 1087.80 |

## 主要结论

最佳非 oracle 设置是 `query_bm25_append` + top-12，support answer surface rate 为 `0.8000`，clean answerable rate 为 `0.8500`。

oracle support append 上界为 `0.8500`，用于判断剩余缺口是否来自 candidate ranking，而不是回答 prompt。

## 代表样例

| query_id | 策略 | max sources | label | gold answer | added docs | support hit | first answer rank |
| --- | --- | ---: | --- | --- | --- | --- | ---: |
| `5a729cc25542991f9a20c532` | `oracle_support_append` | 12 | `answerable_clean` | `Paul Avery` | `5654;5655` | `5654;5655` | 9 |
| `5a729cc25542991f9a20c532` | `oracle_support_append` | 16 | `answerable_clean` | `Paul Avery` | `5654;5655` | `5654;5655` | 9 |
| `5a77322055429972597f1494` | `oracle_support_append` | 12 | `answerable_clean` | `DeskMate` | `400;395` | `400;395` | 9 |
| `5a77322055429972597f1494` | `oracle_support_append` | 16 | `answerable_clean` | `DeskMate` | `400;395` | `400;395` | 9 |
| `5a77322055429972597f1494` | `query_bm25_append` | 12 | `answerable_clean` | `DeskMate` | `395;400;4015;3666` | `400;395` | 10 |
| `5a77322055429972597f1494` | `query_bm25_append` | 16 | `answerable_clean` | `DeskMate` | `395;400;4015;3666;3755;8065;3659;3507` | `400;395` | 10 |
| `5a774e9c55429972597f14f3` | `oracle_support_append` | 12 | `answerable_clean` | `Larnelle Harris` | `4466;4470` | `4466;4470` | 10 |
| `5a774e9c55429972597f14f3` | `oracle_support_append` | 16 | `answerable_clean` | `Larnelle Harris` | `4466;4470` | `4466;4470` | 10 |
| `5a774e9c55429972597f14f3` | `query_bm25_append` | 12 | `answerable_clean` | `Larnelle Harris` | `4470;4466;7312;3120` | `4466;4470` | 9 |
| `5a774e9c55429972597f14f3` | `query_bm25_append` | 16 | `answerable_clean` | `Larnelle Harris` | `4470;4466;7312;3120;9154;1307;2363;1807` | `4466;4470` | 9 |
| `5a774e9c55429972597f14f3` | `query_bm25_rerank` | 8 | `answerable_clean` | `Larnelle Harris` | `4470;4466;7312;3120;2363;1807;6068;2079` | `4466;4470` | 1 |
| `5a774e9c55429972597f14f3` | `query_bm25_rerank` | 12 | `answerable_clean` | `Larnelle Harris` | `4470;4466;7312;3120;2363;1807;6068;2079;3483;5347;1432;5194` | `4466;4470` | 1 |

## 产物路径

- 扩展后 context JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_bm25_append_top12_contexts.jsonl`
- 扩展明细 JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_source_enrichment_rows.jsonl`
- 汇总 CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_source_enrichment_summary.csv`
- 代表样例 JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_source_enrichment_examples.jsonl`
