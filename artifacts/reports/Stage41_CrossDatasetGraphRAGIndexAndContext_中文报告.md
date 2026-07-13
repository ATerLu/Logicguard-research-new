# Stage41 跨数据集 official GraphRAG 索引与 baseline/broad context 补齐报告

## 实验目的

Stage40 已确认 HotpotQA 与 MuSiQue 具备 processed samples、clean/poisoned corpus 和 query integrity，但缺少 official GraphRAG 索引资产。Stage41 的目标是补齐这两个数据集的 clean/poisoned query-ready workspaces，并导出 poisoned workspace 上的 5-query baseline/broad official local contexts，使后续可以进入 query-guard source context export。

本阶段仍不报告 HotpotQA/MuSiQue 的防御 utility 或 attack success，因为还没有运行 Stage28/35/38/39 的 source recovery、chain completeness 和 answer-level 复验。

## 执行内容

1. 使用 `prepare_workspace` 为 HotpotQA/MuSiQue 各导出 clean 与 poisoned workspace input。
2. 复用 2Wiki Stage10 的 GraphRAG `settings.yaml` 与 `prompts`，保持模型、chunking、workflow、local search 口径一致。
3. 使用 `tools/ms_graphrag/.venv` 运行 `graphrag index --method fast`，完成 4 套 workspaces 的索引。
4. 使用 `official_local_context` 导出 HotpotQA/MuSiQue poisoned workspace 的 5-query baseline 与 broad contexts。
5. 重新运行 Stage40 readiness audit，确认下一阻断项已经推进到 `run_query_guard_context_export`。

## GraphRAG 索引结果

| 数据集 | variant | input docs | query数 | documents | text units | entities | relationships | communities | community reports |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HotpotQA | clean | 100 | 50 | 100 | 100 | 131 | 284 | 32 | 32 |
| HotpotQA | poisoned | 100 | 50 | 100 | 100 | 127 | 240 | 23 | 23 |
| MuSiQue | clean | 117 | 50 | 117 | 117 | 118 | 362 | 25 | 25 |
| MuSiQue | poisoned | 117 | 50 | 117 | 117 | 130 | 446 | 24 | 24 |

4 套 workspace 均已生成：
- `documents.parquet`
- `text_units.parquet`
- `entities.parquet`
- `relationships.parquet`
- `communities.parquet`
- `community_reports.parquet`
- `stats.json`
- `output/lancedb`

## Official local context 导出结果

| 数据集 | context | rows | source数范围 | 平均 source数 |
| --- | --- | ---: | ---: | ---: |
| HotpotQA | baseline | 5 | 26-31 | 28.2 |
| HotpotQA | broad | 5 | 66-69 | 67.4 |
| MuSiQue | baseline | 5 | 30-33 | 31.6 |
| MuSiQue | broad | 5 | 89-91 | 89.8 |

这些 contexts 的主要用途是为下一阶段 query-guard seed planning 提供 baseline entity exposure 与 broad retrieval reference。它们不是最终回答层指标。

## Readiness 变化

Stage41 后重新运行 Stage40 audit：

| 数据集 | clean workspace | poisoned workspace | baseline context | broad context | source context | 下一步 |
| --- | --- | --- | --- | --- | --- | --- |
| 2WikiMultihopQA | ready | ready | ready | ready | ready | `ready_for_attribute_sentence_completeness_or_adaptive_attack` |
| HotpotQA | ready | ready | ready | ready | missing | `run_query_guard_context_export` |
| MuSiQue | ready | ready | ready | ready | missing | `run_query_guard_context_export` |

## 重要观察

- HotpotQA/MuSiQue 的 official GraphRAG 索引已经补齐，Stage40 中最大的跨数据集阻断项已经解除。
- HotpotQA/MuSiQue 的下一步不是直接跑 answer-level LLM，而是先导出 `full_query_guard` source contexts，再接 Stage28 risk-non-oracle recovery。
- HotpotQA baseline/broad 的 official local response 多数为 `I do not know`，说明原始 local search response 不应作为最终效果指标；后续仍要用 LogicGuard 的 source-level recovery 和 answer-level audit 判断防御收益。
- 第一次 HotpotQA clean 索引因为 20 分钟命令超时中断在 community report 阶段，后续确认根因是 timeout 不足而非配置错误；重跑后利用 cache 完成索引。
- GraphRAG 运行时出现 `botocore` 相关 LiteLLM warning，但不影响 DashScope/OpenAI-compatible 路径，4 套 pipeline 均 `Pipeline complete`。

## 主要产物

索引 workspaces：
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_poisoned_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_poisoned_query_ready`

Official local contexts：
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_broad_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_broad_context.jsonl`

配置：
- `configs/ms_graphrag_stage40_hotpotqa_official_local_baseline.yaml`
- `configs/ms_graphrag_stage40_hotpotqa_official_local_broad.yaml`
- `configs/ms_graphrag_stage40_musique_official_local_baseline.yaml`
- `configs/ms_graphrag_stage40_musique_official_local_broad.yaml`

## 下一阶段

Stage42 应为 HotpotQA/MuSiQue 运行 query-guard context export：

1. 新增 HotpotQA/MuSiQue 的 query-layer config。
2. 运行 `query_layer_seeding`、`query_layer_context` 和 `query_layer_evaluation`。
3. 生成 `stage40_hotpotqa_poisoned20_query_guard_contexts_full_query_guard.jsonl` 与 `stage40_musique_poisoned20_query_guard_contexts_full_query_guard.jsonl`。
4. 之后复用 Stage28/35/38/39 管线，比较跨数据集 source recovery、chain completeness 与 answer-level utility。
