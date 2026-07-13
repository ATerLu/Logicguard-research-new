# Stage27 official GraphRAG LLM answer-level verification summary

## 目标

Stage27 将 Stage25/26 的 official GraphRAG sources contexts 推进到真实 LLM 回答层。实验比较四种上下文策略：

- `full_query_guard`
- `guarded_sources`
- `recovered_sources_by_doc_id`
- `non_oracle_title_entity_bm25`

本阶段使用 `qwen3.7-plus` 生成答案，采用本地严格 answer matching 标注 `correct / partial / incorrect / abstained / attack_success`。未启用 LLM judge，因此 correct rate 可能偏保守。

## 5-query smoke

| method | correct | utility | abstain | incorrect | attack success | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.2000 | 0.2000 | 0.4000 | 0.4000 | 0.4000 | 0.0000 |
| guarded_sources | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| recovered_sources_by_doc_id | 0.4000 | 0.4000 | 0.4000 | 0.2000 | 0.0000 | 0.0000 |
| non_oracle_title_entity_bm25 | 0.2000 | 0.2000 | 0.6000 | 0.2000 | 0.0000 | 0.0000 |

## 20-query formal

| method | correct | utility | abstain | incorrect | attack success | error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 0.0500 | 0.0500 | 0.7000 | 0.2500 | 0.2500 | 0.0000 |
| guarded_sources | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| recovered_sources_by_doc_id | 0.1500 | 0.1500 | 0.7500 | 0.1000 | 0.0000 | 0.0000 |
| non_oracle_title_entity_bm25 | 0.0500 | 0.0500 | 0.8500 | 0.1000 | 0.0000 | 0.0000 |

## 关键判断

- `full_query_guard` 保留高召回 sources，但真实 LLM 下仍有 `attack_success_rate=0.2500`。
- `guarded_sources` 安全但不可用，20-query 下 `abstain_rate=1.0000`。
- `recovered_sources_by_doc_id` 和 `non_oracle_title_entity_bm25` 都把真实回答层 `attack_success_rate` 降到 `0.0000`。
- Stage27 的 utility 明显低于 Stage26 proxy：这说明仅有 answer surface 或 support source 不等于模型一定能回答。后续需要改进 recovery 后上下文组织、prompt 约束、answer judge 与 alias normalization。

## 产物

- 5-query cases: `outputs/ms_graphrag_query/stage27_poisoned5_answer_llm_cases.jsonl`
- 5-query results: `outputs/ms_graphrag_query/stage27_poisoned5_answer_llm_results.jsonl`
- 5-query summary: `outputs/ms_graphrag_query/stage27_poisoned5_answer_llm_summary.csv`
- 20-query cases: `outputs/ms_graphrag_query/stage27_poisoned20_answer_llm_cases.jsonl`
- 20-query results: `outputs/ms_graphrag_query/stage27_poisoned20_answer_llm_results.jsonl`
- 20-query summary: `outputs/ms_graphrag_query/stage27_poisoned20_answer_llm_summary.csv`
- 5-query run report: `outputs/reports/Stage27_OfficialGraphRAG_LLMAnswer_5QuerySmoke.md`
- 20-query run report: `outputs/reports/Stage27_OfficialGraphRAG_LLMAnswer_20QueryFormal.md`

