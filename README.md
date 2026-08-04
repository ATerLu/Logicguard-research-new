# LogicGuard

LogicGuard 是一个面向 RAG / GraphRAG 逻辑污染防御的科研原型。当前项目围绕三条证据链展开：

- 本地模拟攻击：Entity Swap、Bridge Injection、BridgeV2。
- LogicPoison 语料：clean/poisoned corpus、多数据集回答层与 recovery 实验。
- Microsoft GraphRAG：minimal workflow、query-ready workflow、official LocalSearchMixedContext 查询层接入。

## 当前入口

请优先阅读：

- [实验方法与路线](docs/methodology.md)
- [实验结果总报告](docs/results.md)
- [报告迁移与哈希清单](docs/report_manifest.csv)
- [开发记录](docs/开发记录.md)
- [可复现实验命令清单](docs/reproducibility.md)
- [实验注册表](docs/实验注册表.csv)

旧的 97 个阶段报告已建立 SHA-256 清单并归档；新增实验不再为每个
preflight / generation / audit / judge 子步骤生成独立 Markdown。
过时的导师汇报、冻结矩阵和旧交接文档见 `docs/legacy_document_manifest.csv`。

## 规范化目录

活动代码按职责组织，阶段编号只保留在实验元数据和兼容入口中：

```text
src/logicguard/
├── core/          # 配置、路径、I/O、指标
├── attack/        # 攻击实现
├── defense/       # 检测、恢复、补证、链路完整性
├── evaluation/    # 回答生成、审计、裁决与跨数据集分析
├── ms_graphrag/   # Microsoft GraphRAG 接入层
└── cli.py         # 稳定命令入口
```

Python 文件使用 `snake_case`，类使用 `PascalCase`。旧的
`logicguard.ms_graphrag.stageNN_*` 导入仍可用，但新代码应使用职责路径。
Stage47 配置集中在 `configs/experiments/stage47/`；旧路径由
`configs/config_aliases.yaml` 映射。

## 当前状态

- 已完成 2WikiMultihopQA、HotpotQA、MuSiQue 的标准化和早期多数据集防御实验。
- 已接入 LogicPoison clean/poisoned corpus，并完成检索层、回答层、graph surrogate、non-oracle recovery 实验。
- 已安装 Microsoft GraphRAG 3.1.0 到 `tools/ms_graphrag/.venv`。
- 已补齐 2Wiki debug_50 poisoned query-ready workspace，产物包括 120 documents、165 entities、984 relationships 和 38 community reports。
- 已在 official LocalSearchMixedContext 层完成 5-query baseline、broad context、query-layer LogicGuard 实验。
- 已完成 Stage23 的 5-query official `context_data.sources` 级 recovery 后处理实验。
- 已完成 Stage24 的 20/50-query official sources-level context-only 扩展实验。
- 已完成 Stage25 的 20/50-query non-oracle official sources recovery 初版实验。
- 已完成 Stage26 的 5/20-query official sources answer-level proxy verification。
- 已完成 Stage27 的 5/20-query official sources 真实 LLM answer-level verification。
- 已完成 Stage28 的 risk-non-oracle + recovery-non-oracle 5/20-query source、answer proxy 与真实 LLM 验证。

## 关键结论

- guard 能降低污染暴露，但单独使用会导致拒答或召回崩溃。
- recovery 是当前最关键组件，能在降低污染暴露的同时恢复可答性。
- Stage21 的 50-query indexed artifact 诊断显示：`recovered_by_doc_id` 在 top10 下保持 `gold_recall=0.8050`，同时将未恢复污染暴露降到 0。
- Stage22 证明 official GraphRAG query-ready 工作区和查询层已经跑通，但当前 query-layer guard 更像召回增强，还需要把 recovery 接入 official sources 后处理。
- Stage23 显示：在 official sources 层，`recovered_sources_by_doc_id` 保持 `gold recall=0.9000`，并将未恢复 `changed exposure` 从 `0.9000` 降到 `0.0000`；该结果仍是 oracle clean-reference 上界。
- Stage24 将 sources-level recovery 扩展到 50 query：`recovered_sources_by_doc_id` 保持 `gold recall=0.7850`，并将未恢复 `changed exposure` 从 `0.7833` 降到 `0.0000`。
- Stage25 初步降低 doc_id oracle 依赖：50-query 下 `non_oracle_title_entity_bm25` 达到 `gold recall=0.5450`，`changed exposure=0.0000`，高于只删除 source 的 `0.0400`。
- Stage26 使用可复现 answer-surface proxy 检查回答层可用性：20-query 下 `non_oracle_title_entity_bm25` 达到 `correct_rate=0.4500`、`attack_success_proxy=0.0000`，优于 `guarded_sources` 的 `correct_rate=0.2000`。
- Stage27 调用真实 LLM 生成回答：20-query 下 `full_query_guard` 的 `attack_success_rate=0.2500`；`recovered_sources_by_doc_id` 与 `non_oracle_title_entity_bm25` 均把 `attack_success_rate` 降到 `0.0000`，但 utility 分别只有 `0.1500` 和 `0.0500`，说明下一步重点是安全后的可答性提升。
- Stage28 去掉 risk oracle：20-query source-level 下 `risk_non_oracle_title_entity_bm25` 保持 `gold recall=0.7750`，将 `changed exposure` 降到 `0.0000`；真实 LLM 下 `attack_success_rate=0.0000`、`utility_rate=0.1500`。

## 环境

主项目使用 Python 3.11 和 uv：

```powershell
cd F:\LogicGuard_project\logicguard
uv sync --frozen
uv run pytest -q
uv run ruff check .
```

Microsoft GraphRAG 使用隔离环境：

```powershell
tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag --help
```

API key 只放在环境变量中，不写入配置、日志或 Markdown：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL`

## 主要目录

| 路径 | 内容 |
| --- | --- |
| `configs` | 实验配置 |
| `data/processed` | 标准化数据子集 |
| `data/logicpoison_official` | 从 LogicPoison 项目复制出的 clean/poisoned 语料 |
| `src/logicguard` | 核心代码 |
| `outputs/ms_graphrag` | Microsoft GraphRAG workspace 和索引 |
| `outputs/ms_graphrag_query` | official context、query-layer 结果和指标 |
| `outputs/reports` | 当前保留的中文实验总报告 |
| `docs` | 当前保留的中文项目文档 |
| `tests` | 单元测试 |

## 下一步

近期最高目标：在 Stage39 已确认二跳补证能把 2Wiki 20-query 的 judge-aware final utility 提升到 `0.9500`、且 attack success 仍为 `0.0000` 的基础上，继续推进 HotpotQA / MuSiQue 的 risk-non-oracle source recovery 和后续 chain-level / answer-level 复核。

下一阶段应优先实现：

- Stage43：为 HotpotQA / MuSiQue 运行 Stage28 风格 risk-non-oracle source recovery，检查能否在保留 support recall 的同时降低 changed exposure。
- 增加 attribute/sentence-level evidence completeness，解决 doc-level support hit 但缺属性句的问题。
- 将 Stage38/39 的 second-hop targeted append 收敛为可部署策略，减少 complete queries 上的无关追加噪声。
- 随后设计自适应攻击（adaptive attack），专门攻击 clean-candidate consistency detector 和 title/entity BM25 recovery 的排序假设。

## Stage29 更新：回答层审计

Stage29 已完成回答层离线审计。该阶段不重新调用 LLM，而是复用 Stage28 的真实 LLM 输出，补充答案归一化、错误归因和代表样例导出。

关键结论：
- `risk_non_oracle_title_entity_bm25` 在 Stage29 归一化审计后效用率（`utility_rate`）为 `0.2000`，攻击成功率（`attack_success_rate`）为 `0.0000`。
- `full_query_guard` 仍有 `attack_success_rate=0.1500`，说明高召回但不 recovery 的上下文仍会带来真实错误回答风险。
- `risk_non_oracle_guarded_sources` 仍然安全但不可用，`abstain_rate=1.0000`，继续证明 recovery 是必要组件。

主要产物：
- `outputs/reports/Stage29_AnswerAudit_20QueryFormal.md`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_summary.csv`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_breakdown.csv`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_examples.jsonl`

## Stage30 更新：项目整理与报告整合

Stage30 已完成第一轮非破坏性整理：不删除支撑结论的原始实验结果，只把报告入口收束到总报告和 Stage30 索引，并清理可自动再生成的缓存。

主要产物：
- `outputs/reports/Stage30_项目整理与报告整合.md`
- `outputs/reports/stage30_report_inventory.csv`
- `outputs/reports/stage30_cleanup_manifest.csv`

整理结论：
- 当前项目膨胀主要来自 `outputs`，不是源码；源码本身约 0.82 MB，不建议直接删阶段模块。
- 旧的 smoke/formal 单项报告保留为历史证据，优先阅读 `实验结果总报告.md` 和 Stage30 索引。
- 已修复 `src/logicguard/graph/baseline.py` 的历史语法错误，恢复全量测试安全网。

## Stage31 更新：回答可用性消融

Stage31 已完成 `risk_non_oracle_title_entity_bm25` recovered sources 的离线消融，不重新调用外部 LLM。该阶段比较 `official_order`、`title_query_overlap`、`recovered_first`、`oracle_answer_surface_first` 等排序策略，以及 top-k 和 prompt budget 对 answerability proxy 的影响。

关键结论：
- Stage28 默认近似设置（official_order + top-8 + stage28 prompt budget）的 clean answerable rate 为 `0.5500`。
- 最佳非 oracle 设置 `title_query_overlap` + top-8 + compact prompt 将 clean answerable rate 提升到 `0.6000`，support hit 达到 `1.0000`，unsafe context 仍为 `0.0000`。
- oracle answer-surface 上界为 `0.7500`，说明仍有约 25% query 不是单靠排序和 prompt 能解决。
- prompt budget 从 compact 到 expanded 基本不改变 answer surface，主要瓶颈更像 source 排序、support 覆盖和真实 LLM 拒答策略。

主要产物：
- `outputs/reports/Stage31_AnswerabilityAblation_20Query.md`
- `outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_summary.csv`
- `outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_examples.jsonl`

## Stage32 更新：真实回答对照验证

Stage32 已完成 20-query 真实 LLM 小规模复验。该阶段复用 Stage28 的 `risk_non_oracle_title_entity_bm25` recovered official GraphRAG sources，对比 Stage28 默认渲染（`official_order + top-8 + 700 chars`）与 Stage31 推荐渲染（`title_query_overlap + top-8 + 450 chars`）。

关键结论：
- `stage31_title_query_overlap` 将真实 `correct_rate/utility_rate` 从 `0.1500` 提升到 `0.2500`，`abstain_rate` 从 `0.7500` 降到 `0.6500`。
- 两种设置的 `attack_success_rate` 均为 `0.0000`，说明排序优化没有牺牲当前安全性。
- candidate 相对 baseline 改善 `2/20` 个 query，退化 `0/20` 个，持平 `18/20` 个。
- answer surface 从 `0.5500` 提升到 `0.6000`，真实 utility 仍低于 answerability proxy，说明后续还需要 answer judge、别名归一化和更强的证据利用 prompt。

主要产物：
- `outputs/reports/Stage32_LLMComparison_20Query.md`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_summary.csv`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_pairwise.csv`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_examples.jsonl`

## Stage33 更新：Title-Overlap 正式回答管线

Stage33 已把 Stage32 验证过的 `title_query_overlap + top-8 + 450 chars/source` 固化进正式 `answer_level_llm_verification` 管线。旧 Stage27/28 配置默认仍走 `official_order`，Stage33 通过 `rendering_policies` 为 `risk_non_oracle_title_entity_bm25` 显式启用新排序。

关键结论：
- 原始真实 LLM 指标：`correct_rate=0.2500`、`utility_rate=0.2500`、`abstain_rate=0.6500`、`attack_success_rate=0.0000`。
- Stage33 审计后：`stage29_correct_rate=0.3000`、`stage29_utility_rate=0.3000`、`stage29_attack_success_rate=0.0000`。
- `support_hit_rate=1.0000`，但 `answer_surface=0.6000`，说明仍有大量问题需要增强 candidate pool/source enrichment。
- 失败归因中 `abstain_without_gold_answer_surface=8/20`，`abstain_despite_gold_answer_surface=5/20`，分别对应“证据仍没进上下文”和“证据进了但模型不用”。

主要产物：
- `outputs/reports/Stage33_TitleOverlapPipeline_20Query.md`
- `outputs/reports/Stage33_AnswerAudit_TitleOverlap_20Query.md`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_llm_summary.csv`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_audit_summary.csv`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_audit_breakdown.csv`

## Stage34 更新：回答裁判增强审计

Stage34 已在 Stage33 本地归一化审计之后增加 LLM judge。它只裁判本地审计后仍为 `incorrect` 的非拒答样本，因此本轮 20 query 只产生 1 次 judge 调用。

关键结论：
- Stage33 审计 utility 为 `0.3000`；Stage34 judge-aware utility 为 `0.3500`。
- final correct 为 `0.3000`，final partial 为 `0.0500`，final incorrect 降到 `0.0000`。
- `Poland` vs `Polish-Lithuanian Commonwealth` 被 judge 判为 `partial`，理由是答案相关但历史主权实体不够精确。
- `attack_success_rate` 仍为 `0.0000`，说明 Stage34 改进的是评估可信度，不改变 source-level 防御结论。

主要产物：
- `outputs/reports/Stage34_AnswerJudgeAudit_20Query.md`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_results.jsonl`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_summary.csv`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_breakdown.csv`

## Stage35 更新：候选源扩展诊断

Stage35 已完成 source enrichment 离线诊断，不调用外部 LLM。它固定 Stage33 的 `title_query_overlap + top-8` 作为 baseline，然后从 clean candidate pool 用非 oracle `query_bm25_append` 追加候选源，评估是否能解决 Stage34 的 `abstain_without_gold_answer_surface`。

关键结论：
- Stage33 baseline top-8 的 `support_answer_surface_rate=0.5500`，`clean_answerable_rate=0.6000`。
- `query_bm25_append + top-12` 将 `support_answer_surface_rate` 提升到 `0.7500`，`clean_answerable_rate` 提升到 `0.8000`，`full_support_hit_rate` 提升到 `0.8000`。
- 在 `abstain_without_gold_answer_surface=8/20` 目标失败类中，support answer surface gain 为 `0.5000`。
- oracle support append 上界为 `support_answer_surface_rate=0.8500`、`clean_answerable_rate=0.9000`，说明仍有约 10% 差距来自 candidate ranking。
- `query_bm25_rerank` 会破坏已有上下文，`support_hit_rate` 降到 `0.4500`，不适合作为默认部署策略。

主要产物：
- `outputs/reports/Stage35_SourceEnrichment_20Query.md`
- `outputs/ms_graphrag_query/stage35_poisoned20_query_bm25_append_top12_contexts.jsonl`
- `outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_summary.csv`
- `outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_examples.jsonl`

## Stage36 更新：Enriched Contexts 真实 LLM 复验

Stage36 已将 Stage35 的 `query_bm25_append + top-12` enriched contexts 接入真实 LLM answer generation，并继续使用 Stage29 本地审计和 Stage34 judge-aware 审计。

关键结论：
- 原始真实 LLM：`correct_rate=0.7500`，`utility_rate=0.7500`，`abstain_rate=0.1500`，`attack_success_rate=0.0000`。
- Stage29 审计后：`stage29_utility_rate=0.8000`，`stage29_incorrect_rate=0.0500`。
- Stage36 judge-aware final：`final_correct_rate=0.8000`，`final_partial_rate=0.0500`，`final_utility_rate=0.8500`，`final_attack_success_rate=0.0000`。
- 相比 Stage34 final utility `0.3500`，Stage36 提升到 `0.8500`，说明 Stage35 的 source enrichment proxy 能真实转化为 answer-level utility。
- 剩余失败只剩 3 条拒答：`abstain_without_gold_answer_surface=2/20`，`abstain_despite_gold_answer_surface=1/20`。

主要产物：
- `outputs/reports/Stage36_EnrichedContextLLM_20Query.md`
- `outputs/reports/Stage36_AnswerLLM_Enriched_20Query.md`
- `outputs/reports/Stage36_AnswerAudit_Enriched_20Query.md`
- `outputs/reports/Stage36_AnswerJudgeAudit_Enriched_20Query.md`
- `outputs/ms_graphrag_query/stage36_poisoned20_answer_judge_summary.csv`

## Stage37 更新：Evidence Prompt 复验

Stage37 在 Stage36 的 `query_bm25_append + top-12` enriched contexts 不变的前提下，只改回答层 prompt，新增 `prompt_policy=evidence_compare`，要求模型检查全部 numbered evidence blocks、处理比较题并返回题目要求的实体。

关键结论：
- Stage37 raw LLM：`correct_rate=0.7000`，`utility_rate=0.7000`，`abstain_rate=0.1500`，`attack_success_rate=0.0000`。
- Stage37 judge-aware final：`final_correct_rate=0.8000`，`final_partial_rate=0.0500`，`final_utility_rate=0.8500`，`final_attack_success_rate=0.0000`。
- 与 Stage36 final utility `0.8500` 持平，说明当前瓶颈不再主要是 prompt，而是多跳证据链完整性。
- 剩余 3 条拒答中，2 条缺第二跳 support doc，1 条虽然 gold film title 出现，但缺 Raj Kanwar 出生信息 doc，因此仍不能完成导演年龄比较。
- 下一步应做 chain-completeness 诊断和 second-hop targeted append，而不是继续单纯调 prompt。

主要产物：
- `outputs/reports/Stage37_EvidencePrompt_20Query_中文综合报告.md`
- `outputs/reports/Stage37_AnswerLLM_EvidencePrompt_20Query.md`
- `outputs/reports/Stage37_AnswerAudit_EvidencePrompt_20Query.md`
- `outputs/reports/Stage37_AnswerJudgeAudit_EvidencePrompt_20Query.md`
- `outputs/ms_graphrag_query/stage37_poisoned20_answer_judge_summary.csv`

## Stage38 更新：链路完整性与二跳补证诊断

Stage38 不重新调用回答模型，而是在 Stage35/37 的 20-query 结果上做离线诊断。它把 `answer surface`、`full support hit`、`chain complete` 分开统计，并用 query 相关 source 的标题/正文实体作为桥接词，从 clean candidate pool 中追加二跳证据。

关键结论：
- Stage37/35 基线的 `full_support_hit_rate=0.8000`、`chain_complete_rate=0.8000`，说明剩余问题确实不是单纯 prompt 问题。
- Stage38 `second_hop_append_top14` 后，`targeted_full_support_hit_rate=1.0000`、`targeted_chain_complete_rate=1.0000`。
- 4 个原本缺 support 的 query 全部补齐：`4684`、`1440`、`551`、`2762` 均进入追加 top2，其中 `4684`、`1440`、`551`、`2762` 分别对应丈夫死亡地点、Raj Kanwar 出生信息、Albert S. Rogell 人物页和 Marion Byron 人物页。
- 该阶段仍是 source/chain-level proxy；3 个 targeted case 的 Stage37 final 仍保留为 `abstained`，必须通过下一阶段真实 LLM answer run 验证是否转化为最终回答提升。

主要产物：
- `outputs/reports/Stage38_ChainCompleteness_SecondHop_20Query.md`
- `outputs/ms_graphrag_query/stage38_poisoned20_chain_completeness_summary.csv`
- `outputs/ms_graphrag_query/stage38_poisoned20_chain_completeness_rows.jsonl`
- `outputs/ms_graphrag_query/stage38_poisoned20_second_hop_append_top14_contexts.jsonl`

## Stage39 更新：二跳补证真实回答复验

Stage39 使用 Stage38 生成的 `stage38_second_hop_append_top14` contexts 重新调用 `qwen3.7-plus`，并继续运行 Stage29 本地审计和 Stage34 judge-aware 审计。该阶段验证 Stage38 的 source/chain-level 补证是否能转化为真实回答层收益。

关键结论：
- Stage39 raw LLM：`correct_rate=0.8000`，`utility_rate=0.8000`，`abstain_rate=0.0500`，`attack_success_rate=0.0000`。
- Stage39 本地审计后：`stage29_correct_rate=0.9000`，`stage29_utility_rate=0.9000`，`stage29_attack_success_rate=0.0000`。
- Stage39 judge-aware final：`final_correct_rate=0.9000`，`final_partial_rate=0.0500`，`final_utility_rate=0.9500`，`final_attack_success_rate=0.0000`。
- 相比 Stage37 final utility `0.8500`，Stage39 提升到 `0.9500`；2 个样本从拒答变正确，0 个样本退化。
- 剩余 1 条拒答来自 doc-level support 命中但属性句证据不足，说明下一步应做 sentence/attribute-level evidence completeness。

主要产物：
- `outputs/reports/Stage39_SecondHopAnswer_20Query_中文综合报告.md`
- `outputs/reports/Stage39_AnswerLLM_SecondHop_20Query.md`
- `outputs/reports/Stage39_AnswerAudit_SecondHop_20Query.md`
- `outputs/reports/Stage39_AnswerJudgeAudit_SecondHop_20Query.md`
- `outputs/ms_graphrag_query/stage39_poisoned20_answer_judge_summary.csv`

## Stage40 更新：跨数据集 official GraphRAG readiness 审计

Stage40 没有重新调用 GraphRAG 或 LLM，而是新增跨数据集资产审计，检查 2WikiMultihopQA、HotpotQA、MuSiQue 是否具备进入 official GraphRAG source recovery、chain completeness 和 answer-level 复验的前置条件。

关键结论：
- `2wikimultihopqa` 已具备完整 Stage28/35/38/Stage39 资产，可继续做 attribute/sentence-level evidence completeness 或后续自适应攻击。
- `hotpotqa` 和 `musique` 已具备 processed samples、clean/poisoned corpus 和 `query_integrity`，但缺少 clean/poisoned official GraphRAG output parquet。
- 因此当前跨数据集结论仍是 readiness/gap 结论，不能把 HotpotQA/MuSiQue 计入防御效果或 attack success 指标。
- 下一步应先为 HotpotQA/MuSiQue 准备并索引 Stage40 clean/poisoned workspaces，再导出 official local baseline/broad contexts 和 query-guard contexts。

主要产物：
- `outputs/reports/Stage40_CrossDatasetReadiness_OfficialGraphRAG.md`
- `outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv`
- `outputs/ms_graphrag_query/stage40_cross_dataset_asset_rows.jsonl`
- `outputs/ms_graphrag_query/stage40_cross_dataset_gap_actions.jsonl`

## Stage41 更新：HotpotQA/MuSiQue official GraphRAG 索引补齐

Stage41 按 Stage40 gap actions 推进，完成 HotpotQA 与 MuSiQue 的 clean/poisoned GraphRAG workspaces 索引，并导出 poisoned workspace 的 5-query baseline/broad official local contexts。

关键结论：
- HotpotQA clean/poisoned 均完成 100 个 input docs 的索引；MuSiQue clean/poisoned 均完成 117 个 input docs 的索引。
- 4 套 workspace 均已生成 `documents`、`text_units`、`entities`、`relationships`、`communities`、`community_reports`、`stats` 和 `lancedb`。
- HotpotQA baseline/broad contexts 各 5 行，平均 source 数分别为 `28.2` 和 `67.4`。
- MuSiQue baseline/broad contexts 各 5 行，平均 source 数分别为 `31.6` 和 `89.8`。
- 重新运行 Stage40 audit 后，HotpotQA/MuSiQue 的下一阻断项变为 `run_query_guard_context_export`。

主要产物：
- `outputs/reports/Stage41_CrossDatasetGraphRAGIndexAndContext_中文报告.md`
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_poisoned_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_poisoned_query_ready`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_broad_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_broad_context.jsonl`

## Stage42 更新：HotpotQA/MuSiQue query-guard source context 导出

Stage42 新增 HotpotQA/MuSiQue query-layer 配置，运行 `query_layer_seeding`、`query_layer_context` 和 `query_layer_evaluation`，生成跨数据集 Stage28 recovery 所需的 20-query `full_query_guard` source contexts。

关键结论：
- HotpotQA `full_query_guard`：`gold_support_recall=0.8750`，`changed_exposure=0.8750`，`context_recall_failure_count=2`，平均 `33.1` sources。
- MuSiQue `full_query_guard`：`gold_support_recall=0.7375`，`changed_exposure=0.7375`，`context_recall_failure_count=0`，平均 `31.6` sources。
- `full_query_guard` 相比 broad expansion 用更少 sources 提高 support recall，但召回的 support 多数仍是 changed/poisoned source，因此下一步必须做 risk-non-oracle recovery。
- readiness audit 已推进到 `run_stage28_risk_non_oracle_recovery`。

主要产物：
- `outputs/reports/Stage42_CrossDatasetQueryGuardContext_中文报告.md`
- `configs/ms_graphrag_stage40_hotpotqa.yaml`
- `configs/ms_graphrag_stage40_musique.yaml`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_summary.csv`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_summary.csv`

## Stage43 更新：HotpotQA/MuSiQue risk-non-oracle source recovery

Stage43 已将 Stage28 的 risk-non-oracle recovery 迁移至 HotpotQA 和 MuSiQue 的 20-query official GraphRAG source contexts。运行时只使用 source 与 clean candidate 的标题/实体一致性，不使用 changed 标签；标签仅用于离线评估。

关键结果：
- HotpotQA recovery 保持 `gold_support_recall=0.8750`，将 `changed_exposure=0.8750` 降到 `0.0000`；仅过滤策略则 20 条 context 全空。
- MuSiQue recovery 保持 `gold_support_recall=0.7375`，将 `changed_exposure=0.7375` 降到 `0.0000`；仅过滤策略空 context 比例为 `0.8500`。
- HotpotQA `risk_recall=1.0000`，MuSiQue `risk_recall=0.9950`；但 recovery 分别替换 `662/662` 和 `629/633` 个 source 实例，说明本轮主要验证同标题 clean-version recovery，尚未证明混合语料中的高选择性风险检测。
- 本阶段未调用回答 LLM，不能报告跨数据集 utility 或 attack success。

主要产物：
- `outputs/reports/Stage43_跨数据集RiskNonOracleRecovery_中文报告.md`
- `configs/ms_graphrag_stage43_hotpotqa_risk_non_oracle.yaml`
- `configs/ms_graphrag_stage43_musique_risk_non_oracle.yaml`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_risk_non_oracle_sources_summary.csv`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_risk_non_oracle_sources_summary.csv`

下一步：
- 对 HotpotQA/MuSiQue 复用 Stage35 的 source enrichment，再补 chain completeness 和 answer-level 复验。
- 针对低实体漂移、候选碰撞与证据拆分设计自适应攻击，检验当前 detector 的选择性边界。

## Stage44 更新：HotpotQA/MuSiQue source enrichment

Stage44 已在 Stage43 recovered contexts 上完成跨数据集 candidate source enrichment 消融，并导出 `query_bm25_append + top-12` 的后续 contexts。运行时只使用 query 与 clean candidate 文本/标题，新增 source 均来自 clean reference pool。

关键结果：
- HotpotQA：full support 从 `0.7500` 提升到 `0.9500`，support answer surface 从 `0.6000` 提升到 `0.8000`，`unsafe_context_rate=0.0000`。
- MuSiQue：full support 从 `0.3000` 提升到 `0.6000`，support answer surface 从 `0.3000` 提升到 `0.4000`，`unsafe_context_rate=0.0000`。
- 两个数据集的 BM25 rerank 都明显破坏已有 recovery 证据；保留 top-8 baseline 后追加候选是当前可靠策略。
- MuSiQue oracle full-support 上界为 `1.0000`，而非 oracle append 为 `0.6000`，说明下一瓶颈是多跳候选排序与链路补证，而不是扩大 context 预算。

主要产物：
- `outputs/reports/Stage44_跨数据集SourceEnrichment_中文报告.md`
- `configs/ms_graphrag_stage44_hotpotqa_source_enrichment.yaml`
- `configs/ms_graphrag_stage44_musique_source_enrichment.yaml`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_bm25_append_top12_contexts.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_bm25_append_top12_contexts.jsonl`

下一步：
- 对两个数据集复用 Stage38 做 chain completeness 与 targeted second-hop append，再决定 answer-level 复验范围。

## Stage45 更新：HotpotQA/MuSiQue chain completeness 与二跳补证

Stage45 已在 Stage44 top-12 clean contexts 上完成跨数据集链路诊断和 bridge-aware second-hop append，输出 top-14 targeted contexts。该阶段没有调用回答 LLM，因此 utility、correctness 与 attack success 均未测量。

关键结果：
- HotpotQA：基线与 targeted 的 full support 均为 `0.9500`；剩余 `Paul Avery` 链未补齐，无条件追加只增加上下文噪声。
- MuSiQue：full support / chain complete 从 `0.6000` 升至 `0.8000`，4 条 query 补回缺失 support；但 answer surface 未提高，仍需真实回答验证。
- 两个 targeted context 集合共 560 个 source 实例均为 `clean_reference`，未重新引入污染 source。
- summary 明确标记 `answer_audit_available=0`，未测量的 utility 和 attack success 以空值保存，不再伪装为 0。

主要产物：
- `outputs/reports/Stage45_跨数据集ChainCompleteness_中文报告.md`
- `configs/ms_graphrag_stage45_hotpotqa_chain_completeness.yaml`
- `configs/ms_graphrag_stage45_musique_chain_completeness.yaml`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_second_hop_append_top14_contexts.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_second_hop_append_top14_contexts.jsonl`

下一步：
- Stage46 进行跨数据集真实 LLM answer-level 对照：HotpotQA 以 Stage44 top-12 为主，MuSiQue 对比 Stage44 top-12 与 Stage45 top-14。

## Stage46 更新：跨数据集真实 LLM 回答验证

Stage46 已在 HotpotQA 与 MuSiQue 各 20 个相同 LogicPoison query 上完成 4 种上下文策略的真实回答、离线审计与按需 judge 裁决。先对实际截断后的 prompt 预检，确认未恢复基线的污染 source 确实进入回答模型：HotpotQA 暴露率 `0.8500`，MuSiQue 为 `1.0000`。因此后续 ASR 的差异不是由攻击未进入 prompt 造成。

关键结果：
- 未恢复 `full_query_guard` 基线在回答层出现攻击成功：HotpotQA `0.4500`，MuSiQue `0.1000`。这证明此前的零 ASR 不能归因于“这 20 个 query 本来难以攻击”。
- Stage43 风险恢复、Stage44 top-12 扩展和 Stage45 top-14 二跳补证在两个数据集的最终 ASR 均为 `0.0000`。
- Stage44 是当前默认安全-效用平衡点：HotpotQA final utility 从基线 `0.2000` 升到 `0.8500`，MuSiQue 从 `0.2000` 升到 `0.4000`。
- Stage45 对 HotpotQA 的回答效用没有额外增益，但 MuSiQue 从 `0.4000` 升至 `0.4500`，故应以链路缺口为门控触发，而非默认给所有 query 追加二跳 source。
- HotpotQA 的 Stage43 有 1 条 API error；该行单列，不计入防御成功或拒答。两数据集 judge error 均为 0。

主要产物：
- `outputs/reports/Stage46_跨数据集真实LLM回答验证_中文报告.md`
- `outputs/ms_graphrag_query/stage46_cross_dataset_answer_final_summary.csv`
- `outputs/ms_graphrag_query/stage46_cross_dataset_answer_pairwise_summary.csv`
- `outputs/ms_graphrag_query/stage46_cross_dataset_answer_paired_examples.jsonl`

下一步：
- 以 Stage46 冻结的 prompt、回答模型和 ASR 判定为基准，开展低实体漂移、候选碰撞、证据拆分和恢复绕过四类自适应攻击；每一类攻击都必须先通过实际 prompt 污染暴露预检。

## Stage47 更新：三类自适应 source 攻击初步验证

Stage47 在 MuSiQue 20 问和 HotpotQA 5 问的 clean official GraphRAG 检索结果上，完成低实体漂移、候选碰撞、无可信对应源自然桥接三类 post-retrieval source 扰动。攻击生成器只读取 query、已检索 sources 和候选 source 摘要，不读取 gold answer、support ids 或 changed labels；评测标签只在攻击冻结后使用。

关键结果：
- 共尝试 75 个攻击实例，35 个满足生成约束；排除偶然生成 gold answer、以及候选碰撞仍命中 gold support 后，21 个满足最终评测条件，其中 19 个恶意答案实际进入未防御 prompt。
- 自然桥接是当前最明确缺口：MuSiQue 8 条有效攻击的未防御 targeted ASR 为 `0.8750`，Stage43 完全未检出且 ASR 不变；Stage44/45 仅降至 `0.7500`。
- 低实体漂移的风险检出率为 0，确认 Stage43 的机制盲区；但跨数据集仅 6/25 条评测有效、4 条恶意答案真实暴露，稳定 ASR 仍需扩大样本。HotpotQA 唯一有效样本在四个防御阶段均成功。
- 真正诱导到非 gold support 的 5 条候选碰撞均被 Stage43 检出，攻击 source 被全部移除，聚合 targeted ASR 从 `0.8000` 降至 0；但 5/5 都恢复到攻击者诱导的错误候选，2 条恢复后恶意答案仍在 prompt，说明 recovery correctness 需要额外校验。
- 共完成 140 条真实回答、63 次按需 judge；API error 与 judge error 均为 0。Stage44 是缓解层但不是通用修复，Stage45 未显示稳定的额外安全收益。

结论边界：
- 本阶段验证回答前检测、恢复和补证链路，不包含攻击对 GraphRAG 建图、embedding 或原始检索排名的影响。
- 下一阶段只应挑选 Stage47 已证明有真实暴露的自然桥接、低漂移和错误候选案例，构建完整污染 corpus 并重新运行 official GraphRAG index。

主要产物：
- `outputs/reports/Stage47_三类自适应攻击初步实验_中文报告.md`
- `outputs/ms_graphrag_query/stage47_adaptive_attack_final_summary.csv`
- `outputs/ms_graphrag_query/stage47_adaptive_attack_pairwise_summary.csv`
- `outputs/ms_graphrag_query/stage47_adaptive_attack_examples.jsonl`
