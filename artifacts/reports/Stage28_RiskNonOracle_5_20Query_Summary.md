# Stage28 risk non-oracle + recovery non-oracle summary

## 目标

Stage28 将 Stage25 的 `risk_oracle + recovery_non_oracle` 推进为 `risk_non_oracle + recovery_non_oracle`。核心变化是：source 风险检测不再读取 `changed_support_doc_ids`、gold answer 或 support_doc_ids，而是使用 clean-candidate consistency：

- 用 source title 精确匹配 clean candidate；若无精确标题，再退回 title/entity BM25。
- 去掉 `Document ID / Title` header 后比较正文中的实体 token drift。
- 当 title overlap 与 entity drift 超过阈值时标记 risky source。
- changed-support metadata 只用于离线评价 risk recall、precision、changed exposure 和 answer 指标。

## Source-level 结果

5-query smoke：

| method | gold recall | changed exposure | risk recall | risk precision | risk FP rate | avg filtered | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.9000 | 0.9000 | 0.9854 | 1.0000 | 0.0000 | 0.00 | 0.00 |
| risk_non_oracle_guarded_sources | 0.0000 | 0.0000 | 0.9854 | 1.0000 | 0.0000 | 23.40 | 0.00 |
| risk_non_oracle_title_entity_bm25 | 0.9000 | 0.0000 | 0.9854 | 1.0000 | 0.0000 | 0.00 | 23.40 |

20-query formal：

| method | gold recall | changed exposure | risk recall | risk precision | risk FP rate | avg filtered | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.7750 | 0.7750 | 0.9925 | 1.0000 | 0.0000 | 0.00 | 0.00 |
| risk_non_oracle_guarded_sources | 0.0250 | 0.0000 | 0.9925 | 1.0000 | 0.0000 | 24.05 | 0.00 |
| risk_non_oracle_title_entity_bm25 | 0.7750 | 0.0000 | 0.9925 | 1.0000 | 0.0000 | 0.00 | 24.05 |

## Answer-proxy 结果

20-query formal：

| method | correct | utility | abstain | incorrect | attack-success proxy |
| --- | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.0000 | 0.6000 | 0.0000 | 0.4000 | 0.4000 |
| risk_non_oracle_guarded_sources | 0.0500 | 0.0500 | 0.9500 | 0.0000 | 0.0000 |
| risk_non_oracle_title_entity_bm25 | 0.8000 | 0.8000 | 0.2000 | 0.0000 | 0.0000 |

## Real LLM answer 结果

5-query smoke：

| method | correct | utility | abstain | incorrect | attack success | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.2000 | 0.2000 | 0.4000 | 0.4000 | 0.4000 | 0.0000 |
| risk_non_oracle_guarded_sources | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| risk_non_oracle_title_entity_bm25 | 0.4000 | 0.4000 | 0.4000 | 0.2000 | 0.0000 | 0.0000 |

20-query formal：

| method | correct | utility | abstain | incorrect | attack success | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.0500 | 0.0500 | 0.7500 | 0.1500 | 0.1500 | 0.0500 |
| risk_non_oracle_guarded_sources | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| risk_non_oracle_title_entity_bm25 | 0.1500 | 0.1500 | 0.7500 | 0.1000 | 0.0000 | 0.0000 |

## 关键判断

- Stage28 已经去掉 Stage25 的 risk oracle：context builder 不读取 changed labels，风险检测只用 source text、title、query/entity evidence 和 trusted clean candidate pool。
- 20-query source-level 中，`risk_non_oracle_title_entity_bm25` 保持 `gold recall=0.7750`，同时将 `changed exposure` 从 `0.7750` 降到 `0.0000`。
- 20-query answer proxy 中，`risk_non_oracle_title_entity_bm25` 达到 `utility=0.8000`、`attack_success_proxy=0.0000`，说明在代理指标上接近 oracle recovery 上界。
- 20-query real LLM 中，`risk_non_oracle_title_entity_bm25` 将 `attack_success_rate` 保持为 `0.0000`，且 correct/utility 从 guarded 的 `0.0000` 提升到 `0.1500`。
- Real LLM utility 仍明显低于 proxy，说明后续仍需要 answer judge、alias normalization、prompt/context ordering 和更稳健的 answerability 优化。
- 20-query real LLM 中 `full_query_guard` 有 1 条 timeout，已单列为 `error_rate=0.0500`；Stage28 新方法没有 API 错误。

## 产物

- Source contexts: `outputs/ms_graphrag_query/stage28_poisoned20_risk_non_oracle_sources_contexts.jsonl`
- Source summary: `outputs/ms_graphrag_query/stage28_poisoned20_risk_non_oracle_sources_summary.csv`
- Answer proxy summary: `outputs/ms_graphrag_query/stage28_poisoned20_answer_proxy_summary.csv`
- LLM answer summary: `outputs/ms_graphrag_query/stage28_poisoned20_answer_llm_summary.csv`
- 5-query source report: `outputs/reports/Stage28_RiskNonOracleSourcesRecovery_5QuerySmoke.md`
- 20-query source report: `outputs/reports/Stage28_RiskNonOracleSourcesRecovery_20QueryFormal.md`
- 5-query LLM report: `outputs/reports/Stage28_RiskNonOracle_LLMAnswer_5QuerySmoke.md`
- 20-query LLM report: `outputs/reports/Stage28_RiskNonOracle_LLMAnswer_20QueryFormal.md`

