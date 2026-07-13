# Stage35 Source Enrichment / 候选源扩展诊断

## 实验目的

Stage35 复用 Stage28/33 的 recovered official GraphRAG sources，不调用外部 LLM。它从干净 GraphRAG reference candidate pool 中追加非 oracle 候选源，评估能否解决 Stage34 暴露的 `abstain_without_gold_answer_surface`。

## 重要边界

- `query_bm25_append` 只使用 query 与 clean candidate 文本的 BM25/标题重叠，不使用 gold answer 或 support doc_id。
- `oracle_support_append` 只作为诊断上界，使用 support doc_id，不能作为部署策略。
- 本阶段是 answerability/source-enrichment proxy；真实回答收益需要后续 LLM answer run 复验。

## 实验设置

- 数据集：`2wikimultihopqa`
- 输入 contexts：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage28_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- clean candidate pool：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag/2wikimultihopqa/stage10_debug50_clean_query_ready/output`
- 评估行数：`240`
- enriched context rows：`20`
- selected context：`query_bm25_append` + top-12

## 汇总结果

| 方法 | enrichment | oracle? | max sources | query数 | answer surface | support answer surface | baseline support surface | support gain | clean answerable | target support gain | support hit | full support | unsafe | avg tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 8 | 20 | 0.6000 | 0.5500 | 0.5500 | 0.0000 | 0.6000 | 0.0000 | 1.0000 | 0.3500 | 0.0000 | 1086.25 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 12 | 20 | 0.6500 | 0.6000 | 0.5500 | 0.0500 | 0.6500 | 0.1250 | 1.0000 | 0.4000 | 0.0000 | 1589.10 |
| `risk_non_oracle_title_entity_bm25` | `stage33_title_overlap` | 0 | 16 | 20 | 0.7000 | 0.6500 | 0.5500 | 0.1000 | 0.7000 | 0.2500 | 1.0000 | 0.4500 | 0.0000 | 2072.05 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 8 | 20 | 0.6000 | 0.5500 | 0.5500 | 0.0000 | 0.6000 | 0.0000 | 1.0000 | 0.3500 | 0.0000 | 1086.25 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 12 | 20 | 0.8000 | 0.7500 | 0.5500 | 0.2000 | 0.8000 | 0.5000 | 1.0000 | 0.8000 | 0.0000 | 1554.65 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_append` | 0 | 16 | 20 | 0.8000 | 0.7500 | 0.5500 | 0.2000 | 0.8000 | 0.5000 | 1.0000 | 0.8000 | 0.0000 | 2058.85 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 8 | 20 | 0.1500 | 0.1500 | 0.5500 | 0.1500 | 0.1500 | 0.3750 | 0.4500 | 0.0000 | 0.0000 | 1047.25 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 12 | 20 | 0.1500 | 0.1500 | 0.5500 | 0.1500 | 0.1500 | 0.3750 | 0.4500 | 0.0000 | 0.0000 | 1523.55 |
| `risk_non_oracle_title_entity_bm25` | `query_bm25_rerank` | 0 | 16 | 20 | 0.1500 | 0.1500 | 0.5500 | 0.1500 | 0.1500 | 0.3750 | 0.4500 | 0.0000 | 0.0000 | 1967.15 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 8 | 20 | 0.6000 | 0.5500 | 0.5500 | 0.0000 | 0.6000 | 0.0000 | 1.0000 | 0.3500 | 0.0000 | 1086.25 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 12 | 20 | 0.9000 | 0.8500 | 0.5500 | 0.3000 | 0.9000 | 0.7500 | 1.0000 | 1.0000 | 0.0000 | 1157.65 |
| `risk_non_oracle_title_entity_bm25` | `oracle_support_append` | 1 | 16 | 20 | 0.9000 | 0.8500 | 0.5500 | 0.3000 | 0.9000 | 0.7500 | 1.0000 | 1.0000 | 0.0000 | 1157.65 |

## 主要结论

最佳非 oracle 设置是 `query_bm25_append` + top-12，support answer surface rate 为 `0.7500`，clean answerable rate 为 `0.8000`。

oracle support append 上界为 `0.9000`，用于判断剩余缺口是否来自 candidate ranking，而不是回答 prompt。

## 代表样例

| query_id | policy | max sources | Stage34 reason | label | gold answer | added docs | support hit | first answer rank |
| --- | --- | ---: | --- | --- | --- | --- | --- | ---: |
| `076288460bde11eba7f7acde48001122` | `oracle_support_append` | 12 | `abstain_without_gold_answer_surface` | `answerable_clean` | `1322` | `653` | `658;653` | 9 |
| `076288460bde11eba7f7acde48001122` | `oracle_support_append` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `1322` | `653` | `658;653` | 9 |
| `076288460bde11eba7f7acde48001122` | `query_bm25_append` | 12 | `abstain_without_gold_answer_surface` | `answerable_clean` | `1322` | `653;4290;4670;4043` | `658;653` | 9 |
| `076288460bde11eba7f7acde48001122` | `query_bm25_append` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `1322` | `653;4290;4670;4043;2591;2101;3754;4689` | `658;653` | 9 |
| `076288460bde11eba7f7acde48001122` | `stage33_title_overlap` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `1322` | `2347;3572;4299;1777;4637;653;1182;1314` | `658;653` | 14 |
| `07f2140e0bdc11eba7f7acde48001122` | `oracle_support_append` | 12 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Roman` | `4684` | `4689;4684` | 9 |
| `07f2140e0bdc11eba7f7acde48001122` | `oracle_support_append` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Roman` | `4684` | `4689;4684` | 9 |
| `2330faf1097511ebbdb0ac1f6bf848b6` | `oracle_support_append` | 12 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Sudden Fear` | `1542` | `1542;1539` | 9 |
| `2330faf1097511ebbdb0ac1f6bf848b6` | `oracle_support_append` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Sudden Fear` | `1542` | `1542;1539` | 9 |
| `2330faf1097511ebbdb0ac1f6bf848b6` | `query_bm25_append` | 12 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Sudden Fear` | `1542;5289;1992;5386` | `1542;1539` | 9 |
| `2330faf1097511ebbdb0ac1f6bf848b6` | `query_bm25_append` | 16 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Sudden Fear` | `1542;5289;1992;5386;3846;3841;5684;2342` | `1542;1539` | 9 |
| `2330faf1097511ebbdb0ac1f6bf848b6` | `query_bm25_rerank` | 8 | `abstain_without_gold_answer_surface` | `answerable_clean` | `Sudden Fear` | `1542;5289;1992;5386;3846;3841;2342;2591` | `1542` | 1 |

## 产物路径

- enriched contexts JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage35_poisoned20_query_bm25_append_top12_contexts.jsonl`
- enrichment rows JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_rows.jsonl`
- summary CSV：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_summary.csv`
- examples JSONL：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_examples.jsonl`
