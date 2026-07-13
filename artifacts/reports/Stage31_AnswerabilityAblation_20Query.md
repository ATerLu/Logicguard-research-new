# Stage31 回答可用性消融

## 实验目的

Stage31 复用 Stage28 的 recovered official GraphRAG sources，不重新调用外部 LLM。它离线比较 source ordering / top-k / prompt budget 对回答可用性的影响，用 gold answer surface、support hit 和 unrecovered changed exposure 作为可复现 proxy。

## 重要边界

- 非 oracle 排序策略只使用 query、source title、source state 和 recovery 标记。
- `oracle_answer_surface_first` 只作为诊断上界，使用 gold answer 判断 source 是否含答案，不能作为部署策略。
- 本阶段解释 Stage29 的低 utility 来源，不改变 Stage28/29 的真实 LLM 结果。

## 实验设置

- 数据集: `2wikimultihopqa`
- 输入 contexts: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage28_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- 评估行数: `900`
- 方法: `risk_non_oracle_title_entity_bm25`
- 排序策略: `official_order`, `recovered_first`, `title_query_overlap`, `recovered_then_title_query_overlap`, `oracle_answer_surface_first`
- top-k: 3, 5, 8
- prompt budgets: `compact`=450, `stage28`=700, `expanded`=1100

## 汇总结果

| 方法 | 排序策略 | oracle? | top-k | prompt budget | query数 | answer surface | clean answerable | support hit | full support | unsafe | avg tokens |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 3 | `compact` | 20 | 0.3000 | 0.3000 | 0.8500 | 0.1000 | 0.0000 | 448.40 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 3 | `expanded` | 20 | 0.3000 | 0.3000 | 0.8500 | 0.1000 | 0.0000 | 681.75 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 3 | `stage28` | 20 | 0.3000 | 0.3000 | 0.8500 | 0.1000 | 0.0000 | 557.10 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 5 | `compact` | 20 | 0.4500 | 0.4500 | 0.9500 | 0.2000 | 0.0000 | 709.20 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 5 | `expanded` | 20 | 0.4500 | 0.4500 | 0.9500 | 0.2000 | 0.0000 | 1116.60 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 5 | `stage28` | 20 | 0.4500 | 0.4500 | 0.9500 | 0.2000 | 0.0000 | 899.10 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 8 | `compact` | 20 | 0.5500 | 0.5500 | 0.9500 | 0.2500 | 0.0000 | 1088.50 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 8 | `expanded` | 20 | 0.5500 | 0.5500 | 0.9500 | 0.2500 | 0.0000 | 1748.25 |
| `risk_non_oracle_title_entity_bm25` | `official_order` | 0 | 8 | `stage28` | 20 | 0.5500 | 0.5500 | 0.9500 | 0.2500 | 0.0000 | 1402.80 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 3 | `compact` | 20 | 0.2500 | 0.2500 | 0.8500 | 0.0500 | 0.0000 | 456.05 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 3 | `expanded` | 20 | 0.2500 | 0.2500 | 0.8500 | 0.0500 | 0.0000 | 699.75 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 3 | `stage28` | 20 | 0.2500 | 0.2500 | 0.8500 | 0.0500 | 0.0000 | 570.15 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 5 | `compact` | 20 | 0.4000 | 0.4000 | 0.9500 | 0.1500 | 0.0000 | 716.95 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 5 | `expanded` | 20 | 0.4000 | 0.4000 | 0.9500 | 0.1500 | 0.0000 | 1151.55 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 5 | `stage28` | 20 | 0.4000 | 0.4000 | 0.9500 | 0.1500 | 0.0000 | 918.45 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 8 | `compact` | 20 | 0.5000 | 0.5000 | 0.9500 | 0.2000 | 0.0000 | 1095.75 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 8 | `expanded` | 20 | 0.5000 | 0.5000 | 0.9500 | 0.2000 | 0.0000 | 1777.80 |
| `risk_non_oracle_title_entity_bm25` | `recovered_first` | 0 | 8 | `stage28` | 20 | 0.5000 | 0.5000 | 0.9500 | 0.2000 | 0.0000 | 1422.45 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 3 | `compact` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 441.80 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 3 | `expanded` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 673.35 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 3 | `stage28` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 550.50 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 5 | `compact` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 704.60 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 5 | `expanded` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 1122.60 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 5 | `stage28` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 900.00 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 8 | `compact` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1086.25 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 8 | `expanded` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1766.75 |
| `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 0 | 8 | `stage28` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1410.00 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 3 | `compact` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 441.80 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 3 | `expanded` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 673.35 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 3 | `stage28` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 550.50 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 5 | `compact` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 704.60 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 5 | `expanded` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 1122.60 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 5 | `stage28` | 20 | 0.5000 | 0.5000 | 1.0000 | 0.2500 | 0.0000 | 900.00 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 8 | `compact` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1086.25 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 8 | `expanded` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1766.75 |
| `risk_non_oracle_title_entity_bm25` | `recovered_then_title_query_overlap` | 0 | 8 | `stage28` | 20 | 0.6000 | 0.6000 | 1.0000 | 0.3500 | 0.0000 | 1410.00 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 3 | `compact` | 20 | 0.7500 | 0.7500 | 0.9000 | 0.4000 | 0.0000 | 437.85 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 3 | `expanded` | 20 | 0.7500 | 0.7500 | 0.9000 | 0.4000 | 0.0000 | 661.45 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 3 | `stage28` | 20 | 0.7500 | 0.7500 | 0.9000 | 0.4000 | 0.0000 | 538.00 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 5 | `compact` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 703.30 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 5 | `expanded` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 1094.45 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 5 | `stage28` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 886.90 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 8 | `compact` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 1090.50 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 8 | `expanded` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 1776.40 |
| `risk_non_oracle_title_entity_bm25` | `oracle_answer_surface_first` | 1 | 8 | `stage28` | 20 | 0.7500 | 0.7500 | 1.0000 | 0.4000 | 0.0000 | 1411.70 |

## 主要结论

最佳非 oracle 设置是 `title_query_overlap` + top-8 + `compact`，clean answerable rate 为 `0.6000`，answer surface rate 为 `0.6000`。

Stage28 默认渲染近似为 `official_order` + top-8 + `stage28`，其 clean answerable rate 为 `0.5500`。

oracle answer-surface 上界最高达到 `0.7500`，用于衡量排序和截断仍有多少可解释空间。

## 代表样例

| query_id | 方法 | 排序 | top-k | prompt | 标签 | gold answer | support hit | first answer rank | first support rank |
| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `compact` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `expanded` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `stage28` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 5 | `compact` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 5 | `expanded` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 5 | `stage28` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 8 | `compact` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 8 | `expanded` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `064edb0908cd11ebbd93ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 8 | `stage28` | `answerable_clean` | `Il Seduttore` | `4262;4264` | 2 | 1 |
| `149af27608ab11ebbd81ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `compact` | `answerable_clean` | `Marius Mapou` | `4782;4777` | 2 | 1 |
| `149af27608ab11ebbd81ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `expanded` | `answerable_clean` | `Marius Mapou` | `4782;4777` | 2 | 1 |
| `149af27608ab11ebbd81ac1f6bf848b6` | `risk_non_oracle_title_entity_bm25` | `title_query_overlap` | 3 | `stage28` | `answerable_clean` | `Marius Mapou` | `4782;4777` | 2 | 1 |

## 产物路径

- ablation rows JSONL: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_rows.jsonl`
- summary CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_summary.csv`
- examples JSONL: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_examples.jsonl`
