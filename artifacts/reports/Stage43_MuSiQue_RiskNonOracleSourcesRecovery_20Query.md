# Stage43-MuSiQue 非 Oracle 风险识别与官方来源恢复

## 实验目的

本阶段以 clean candidate consistency 风险检测器替代 changed-support 风险标签。运行时不读取 changed 标签；changed-support 元数据仅用于离线指标计算。

## 风险检测与恢复机制

- 优先用 source 标题精确匹配 clean candidate；无精确匹配时使用 title/entity/BM25 排序。
- 比较当前 source 与 candidate 的大写实体词漂移。
- 当标题重合度和实体漂移均超过阈值时，将 source 标为高风险。

## 汇总结果

| method | queries | gold recall | changed exposure | risk recall | risk precision | risk FP rate | avg filtered | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 20 | 0.7375 | 0.7375 | 0.9950 | 1.0000 | 0.0000 | 0.00 | 0.00 |
| risk_non_oracle_guarded_sources | 20 | 0.0250 | 0.0000 | 0.9950 | 1.0000 | 0.0000 | 31.45 | 0.00 |
| risk_non_oracle_title_entity_bm25 | 20 | 0.7375 | 0.0000 | 0.9950 | 1.0000 | 0.0000 | 0.00 | 31.45 |

## 产物

- context JSONL: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- query metrics CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_metrics.csv`
- method summary CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_summary.csv`
