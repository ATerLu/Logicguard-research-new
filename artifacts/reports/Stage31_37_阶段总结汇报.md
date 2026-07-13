# Stage31-37 阶段总结汇报

更新日期：2026-07-09

## 文档目的

这份文档汇总 LogicGuard 从 Stage31 到 Stage37 的开发与实验结果。该阶段的主线是：在 Stage28/29 已完成 risk-non-oracle official GraphRAG source recovery 与回答审计之后，继续提升 answer-level utility，同时保持 attack success 为 0。

这一段工作没有更换数据集，仍使用 `2wikimultihopqa` debug_50 中的前 20 个 official GraphRAG query。选择 20-query 的原因是控制真实 LLM 成本，同时保留逐样本审计能力。后续扩展到 50-query 和跨数据集实验时，应沿用这里沉淀下来的诊断指标和流程。

## 总体进展

Stage31 到 Stage37 完成了一条连续的实验链：

| 阶段 | 核心问题 | 主要方法 | 关键结果 |
| --- | --- | --- | --- |
| Stage31 | recovered sources 已经拿到后，怎样排序和截断更可答 | 离线 answerability ablation | `title_query_overlap + top-8 + compact` 的 clean answerable rate 达到 `0.6000` |
| Stage32 | Stage31 的 proxy 是否能转化为真实 LLM 回答收益 | 真实 LLM 对照验证 | utility 从 Stage28 default 的 `0.1500` 提升到 `0.2500` |
| Stage33 | 把 Stage32 的有效排序固化进正式管线 | `rendering_policies` 配置化 | raw utility `0.2500`，审计后 utility `0.3000` |
| Stage34 | 严格字符串匹配是否低估回答质量 | LLM judge 只裁判 uncertain incorrect rows | final utility `0.3500`，final incorrect `0.0000` |
| Stage35 | 剩余拒答是不是缺候选源 | source enrichment 离线诊断 | `query_bm25_append + top-12` clean answerable `0.8000` |
| Stage36 | Stage35 的 enrichment proxy 能否转成真实回答收益 | enriched contexts 真实 LLM 复验 | judge-aware final utility `0.8500`，attack success `0.0000` |
| Stage37 | 剩余拒答能否靠更强 answer prompt 解决 | `evidence_compare` prompt 复验 | final utility 仍为 `0.8500`，瓶颈转向 evidence-chain completeness |

从指标走势看，Stage31-37 让 20-query official GraphRAG answer-level 结果发生了实质变化：

| 对照点 | 方法/设置 | utility 或 proxy | abstain | incorrect | attack success | 说明 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Stage32 baseline | Stage28 default official order | raw utility `0.1500` | `0.7500` | `0.1000` | `0.0000` | 旧渲染顺序下真实 LLM 大量拒答 |
| Stage32 candidate | Stage31 title-query overlap | raw utility `0.2500` | `0.6500` | `0.1000` | `0.0000` | 排序优化带来小幅真实收益 |
| Stage33 audit | 正式 title-overlap 管线 | audited utility `0.3000` | `0.6500` | `0.0500` | `0.0000` | 归一化修正部分低估 |
| Stage34 judge | judge-aware 审计 | final utility `0.3500` | `0.6500` | `0.0000` | `0.0000` | `Poland` 类近似答案被判 partial |
| Stage35 proxy | query BM25 append top-12 | clean answerable `0.8000` | - | - | unsafe `0.0000` | source enrichment 显著补证据 |
| Stage36 judge | enriched contexts 真实 LLM | final utility `0.8500` | `0.1500` | `0.0000` | `0.0000` | proxy 收益转化为 answer-level 收益 |
| Stage37 judge | evidence prompt 复验 | final utility `0.8500` | `0.1500` | `0.0000` | `0.0000` | prompt-only 没有继续提升 |

最重要的阶段性结论是：LogicGuard 当前的有效增益主要来自 source enrichment，而不是单纯 prompt 调整。Stage36 将 final utility 从 Stage34 的 `0.3500` 提升到 `0.8500`，同时 attack success 继续保持 `0.0000`。Stage37 说明剩余失败更接近“证据链不完整”，而不是模型没有被提示好。

## Stage31：回答可用性消融

### 做了什么

Stage31 复用 Stage28 的 recovered official GraphRAG sources，不重新调用外部 LLM。实验比较不同 source ordering、top-k 和 prompt budget 对回答可用性的影响，使用以下 proxy：

- `answer_surface_rate`：上下文是否出现标准答案表面字符串。
- `clean_answerable_rate`：上下文是否有干净证据可支持答案。
- `support_hit_rate`：support docs 是否进入上下文。
- `unsafe_context_rate`：是否暴露未恢复污染 source。

测试策略包括：

- `official_order`
- `recovered_first`
- `title_query_overlap`
- `recovered_then_title_query_overlap`
- `oracle_answer_surface_first`

其中 `oracle_answer_surface_first` 只作为诊断上界，不能作为部署策略。

### 结果

最佳非 oracle 设置是 `title_query_overlap + top-8 + compact`：

| 指标 | 数值 |
| --- | ---: |
| answer surface rate | `0.6000` |
| clean answerable rate | `0.6000` |
| support hit rate | `1.0000` |
| full support hit rate | `0.3500` |
| unsafe context rate | `0.0000` |
| avg estimated prompt tokens | `1086.25` |

Stage28 默认渲染近似为 `official_order + top-8 + stage28`，clean answerable rate 为 `0.5500`。Stage31 的推荐设置把它提升到 `0.6000`，并把 support hit 提升到 `1.0000`。

### 结论

Stage31 证明 source ordering 不是无关细节。官方 GraphRAG sources 即使已经恢复为 clean reference，如果排序不合理，LLM 仍可能先看到无关 source，导致拒答或错误。`title_query_overlap` 只使用 query 与 source title，不依赖 gold answer，因此可作为部署候选。

同时，Stage31 也暴露了上限：oracle answer-surface 上界为 `0.7500`，而最佳非 oracle 只有 `0.6000`。这说明后续不能只靠排序，还需要补 candidate pool。

## Stage32：真实 LLM 对照验证

### 做了什么

Stage32 调用真实 LLM，对比两种渲染方式：

- `stage28_default`：official order，top-8，每 source 700 字符。
- `stage31_title_query_overlap`：title-query overlap，top-8，每 source 450 字符。

模型使用 `qwen3.7-plus`，20 个 query，每个 query 两个 variant，共 40 个 answer-generation case。本阶段不调用 LLM judge，只用本地 gold-answer 归一化匹配。

### 结果

| variant | correct | utility | abstain | incorrect | attack success | answer surface | support hit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stage28_default | `0.1500` | `0.1500` | `0.7500` | `0.1000` | `0.0000` | `0.5500` | `0.9500` |
| stage31_title_query_overlap | `0.2500` | `0.2500` | `0.6500` | `0.1000` | `0.0000` | `0.6000` | `1.0000` |

pairwise 对照显示：

- utility delta：`+0.1000`
- correct delta：`+0.1000`
- abstain delta：`-0.1000`
- improved：`2/20`
- regressed：`0/20`
- same：`18/20`

### 结论

Stage32 证明 Stage31 的 proxy 能转化为真实 LLM 收益。排序优化不是只改善离线指标，它能减少部分真实拒答。

但收益较小。`answer_surface=0.6000`，真实 utility 只有 `0.2500`，说明即使证据进了上下文，模型仍常常无法稳定使用多跳证据。这个差距推动了 Stage33/34 的正式管线和审计增强。

## Stage33：Title-Overlap 正式回答管线

### 做了什么

Stage33 把 Stage32 验证过的排序策略固化进正式 answer-generation pipeline。主要开发改动包括：

- 在 `answer_level_llm_verification` 中新增 `Stage27RenderingPolicy`。
- 支持按 method 配置 `order_policy`、`max_sources`、`max_chars_per_source`。
- 在 answer cases、results、summary 中记录实际渲染策略。
- 旧 Stage27/28 配置默认仍走 `official_order`，避免破坏历史实验。

Stage33 配置将 `risk_non_oracle_title_entity_bm25` 设置为 `title_query_overlap + top-8 + 450 chars/source`。

### 结果

真实 LLM 原始结果：

| method | order policy | correct | utility | abstain | incorrect | attack success | answer surface | support hit |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| risk_non_oracle_title_entity_bm25 | title_query_overlap | `0.2500` | `0.2500` | `0.6500` | `0.1000` | `0.0000` | `0.6000` | `1.0000` |

Stage29 审计后：

| original correct | audited correct | audited utility | abstain | incorrect | attack success |
| ---: | ---: | ---: | ---: | ---: | ---: |
| `0.2500` | `0.3000` | `0.3000` | `0.6500` | `0.0500` | `0.0000` |

失败归因：

| audit reason | count | rate | 含义 |
| --- | ---: | ---: | --- |
| `abstain_without_gold_answer_surface` | 8 | `0.4000` | 上下文缺答案表面，candidate pool/source enrichment 不足 |
| `abstain_despite_gold_answer_surface` | 5 | `0.2500` | 上下文有答案表面，但模型仍拒答 |
| `incorrect_despite_gold_answer_surface` | 1 | `0.0500` | 有证据但回答近似或不够精确 |
| `original_correct` | 5 | `0.2500` | 原始严格匹配已正确 |
| `correct_after_answer_normalization` | 1 | `0.0500` | 审计归一化修正严格匹配低估 |

### 结论

Stage33 把 Stage32 的实验发现转成了可复现、可配置的正式管线。它确认 `title_query_overlap` 可以作为 recovered-source answer rendering 的当前候选默认策略。

但 Stage33 的主要价值还在诊断：`support_hit_rate=1.0000`，`answer_surface=0.6000`，审计后 utility 仍只有 `0.3000`。这说明 support doc 进来并不等于回答可用，后续必须分别处理 source enrichment、答案归一化/judge、prompt/evidence-use。

## Stage34：回答裁判增强审计

### 做了什么

Stage34 在 Stage33 的本地归一化审计之后增加 LLM judge。为了控制成本，它只裁判本地审计后仍为 `incorrect` 的非拒答样本，不重复裁判已正确、已拒答或 API 错误样本。

### 结果

| 指标 | 数值 |
| --- | ---: |
| rows | `20` |
| judge calls | `1` |
| judge call rate | `0.0500` |
| final correct rate | `0.3000` |
| final partial rate | `0.0500` |
| final utility rate | `0.3500` |
| final abstain rate | `0.6500` |
| final incorrect rate | `0.0000` |
| final attack success rate | `0.0000` |

标签归因：

| final label | final reason | count | rate |
| --- | --- | ---: | ---: |
| abstained | `abstain_without_gold_answer_surface` | 8 | `0.4000` |
| abstained | `abstain_despite_gold_answer_surface` | 5 | `0.2500` |
| correct | `original_correct` | 5 | `0.2500` |
| correct | `correct_after_answer_normalization` | 1 | `0.0500` |
| partial | `llm_judge_partial` | 1 | `0.0500` |

### 结论

Stage34 解决的是评估可信度，而不是 source recovery 本身。典型样本是 `Poland` vs `Polish-Lithuanian Commonwealth`：本地严格规则判为 incorrect，LLM judge 判为 partial，因为答案相关但历史主权实体不够精确。

Stage34 的 final utility 从 `0.3000` 提升到 `0.3500`，但 abstain 仍为 `0.6500`。这说明真正的大瓶颈还是缺证据或证据链不可用。该结论直接推动 Stage35 做 source enrichment。

## Stage35：候选源扩展诊断

### 做了什么

Stage35 不调用外部 LLM。它从 clean GraphRAG reference candidate pool 追加非 oracle 候选源，评估能否解决 Stage34 的 `abstain_without_gold_answer_surface`。

比较策略包括：

- `stage33_title_overlap`：只扩大已有 title-overlap 上下文。
- `query_bm25_append`：保留 baseline 前 8 个 source，再按 query BM25 追加候选源。
- `query_bm25_rerank`：用 query BM25 重排整个候选集合。
- `oracle_support_append`：用 support doc_id 追加，只作为诊断上界。

### 结果

核心结果如下：

| enrichment policy | max sources | answer surface | support answer surface | clean answerable | full support hit | unsafe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| stage33_title_overlap | 8 | `0.6000` | `0.5500` | `0.6000` | `0.3500` | `0.0000` |
| stage33_title_overlap | 16 | `0.7000` | `0.6500` | `0.7000` | `0.4500` | `0.0000` |
| query_bm25_append | 12 | `0.8000` | `0.7500` | `0.8000` | `0.8000` | `0.0000` |
| query_bm25_append | 16 | `0.8000` | `0.7500` | `0.8000` | `0.8000` | `0.0000` |
| query_bm25_rerank | 8 | `0.1500` | `0.1500` | `0.1500` | `0.0000` | `0.0000` |
| oracle_support_append | 12 | `0.9000` | `0.8500` | `0.9000` | `1.0000` | `0.0000` |

最佳非 oracle 设置为 `query_bm25_append + top-12`：

- support answer surface rate：`0.7500`
- clean answerable rate：`0.8000`
- full support hit rate：`0.8000`
- target failure support gain rate：`0.5000`
- unsafe context rate：`0.0000`

### 结论

Stage35 找到了 Stage31-34 之后最关键的增益来源：不要重排掉已有好 source，而是在 baseline 后追加 query BM25 候选。`query_bm25_rerank` 会破坏已有上下文，support hit 降到 `0.4500`，不能作为默认策略。

oracle support append 的 clean answerable 上界为 `0.9000`，而非 oracle append 为 `0.8000`。这 10 个百分点的差距说明后续仍有 candidate ranking 空间。

## Stage36：Enriched Contexts 真实 LLM 复验

### 做了什么

Stage36 将 Stage35 生成的 `query_bm25_append + top-12` enriched contexts 接入真实 LLM answer generation，然后复用 Stage29 本地审计和 Stage34 judge-aware 审计。

这是整个 Stage31-37 中最关键的真实 LLM 实验，因为它验证 Stage35 的 source-enrichment proxy 是否能转化为 answer-level utility。

### 结果

| 层级 | correct | partial | utility | abstain | incorrect | attack success | answer surface |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage36 raw LLM | `0.7500` | `0.0000` | `0.7500` | `0.1500` | `0.1000` | `0.0000` | `0.8000` |
| Stage36 audit | `0.8000` | `0.0000` | `0.8000` | `0.1500` | `0.0500` | `0.0000` | `0.8000` |
| Stage36 judge final | `0.8000` | `0.0500` | `0.8500` | `0.1500` | `0.0000` | `0.0000` | `0.8000` |

与 Stage34 对比：

- final utility：`0.3500 -> 0.8500`
- final abstain：`0.6500 -> 0.1500`
- final attack success：保持 `0.0000`

Stage36 本地审计归因：

| audit reason | count | rate |
| --- | ---: | ---: |
| original_correct | 15 | `0.7500` |
| correct_after_answer_normalization | 1 | `0.0500` |
| incorrect_despite_gold_answer_surface | 1 | `0.0500` |
| abstain_despite_gold_answer_surface | 1 | `0.0500` |
| abstain_without_gold_answer_surface | 2 | `0.1000` |

### 结论

Stage36 证明 source enrichment 是当前最有效的改进方向。Stage35 的离线 proxy 没有停留在“看起来可答”，而是转成了真实 LLM 回答收益。

代表性修复包括：

- Henry I of Ziębice 父亲出生日期：Stage34 为 `UNKNOWN`，Stage36 回答 `between 1322 and 1327`。
- Sudden Fear vs The Adventurer of Chad：Stage34 为 `UNKNOWN`，Stage36 回答 `Sudden Fear`。
- 多个电影比较、人物出生地、亲属关系问题从拒答变为正确。

Stage36 后只剩 3 条拒答：2 条缺答案表面，1 条上下文含答案表面但模型仍拒答。当时的判断是：2 条继续做 candidate ranking/source enrichment，1 条尝试 answer prompt/evidence-use。

## Stage37：Evidence Prompt 复验

### 做了什么

Stage37 在 Stage36 的 enriched contexts 不变的前提下，只修改回答 prompt。新增 `prompt_policy=evidence_compare`，要求模型：

- 检查全部 numbered evidence blocks。
- 对比较题抽取每个候选实体的相关事实。
- 返回题目要求的实体，而不是中间实体。
- 只有在必要事实缺失时才回答 `UNKNOWN`。

Stage37 同样运行真实 LLM answer generation、Stage29 本地审计和 Stage34 judge-aware 审计。

### 结果

| 层级 | prompt | correct | partial | utility | abstain | incorrect | attack success | answer surface |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage36 raw LLM | default | `0.7500` | `0.0000` | `0.7500` | `0.1500` | `0.1000` | `0.0000` | `0.8000` |
| Stage37 raw LLM | evidence_compare | `0.7000` | `0.0000` | `0.7000` | `0.1500` | `0.1500` | `0.0000` | `0.8000` |
| Stage37 audit | evidence_compare | `0.8000` | `0.0000` | `0.8000` | `0.1500` | `0.0500` | `0.0000` | `0.8000` |
| Stage37 judge final | evidence_compare | `0.8000` | `0.0500` | `0.8500` | `0.1500` | `0.0000` | `0.0000` | `0.8000` |

Stage37 judge-aware 标签归因：

| final label | final reason | count | rate |
| --- | --- | ---: | ---: |
| correct | `original_correct` | 14 | `0.7000` |
| correct | `correct_after_answer_normalization` | 2 | `0.1000` |
| partial | `llm_judge_partial` | 1 | `0.0500` |
| abstained | `abstain_despite_gold_answer_surface` | 1 | `0.0500` |
| abstained | `abstain_without_gold_answer_surface` | 2 | `0.1000` |

### 结论

Stage37 没有提升最终 utility。final utility 与 Stage36 持平，仍为 `0.8500`；attack success 仍为 `0.0000`。

这个结果改变了下一步判断。Stage36 后我们以为剩余 1 条 `abstain_despite_gold_answer_surface` 可以靠 prompt 修复；Stage37 细查后发现，gold answer 的表面字符串出现在上下文中，不代表多跳链路完整。

关键负例是导演年龄比较题：

- query_id：`6a4840d608dc11ebbd9cac1f6bf848b6`
- 问题：比较 `A Better Tomorrow III` 和 `Har Dil Jo Pyar Karega` 哪部电影的导演更年长。
- 已命中 docs：`1433`、`1436`、`1439`
- 缺失 doc：`1440`，即 Raj Kanwar 的出生信息。
- 模型回答：`UNKNOWN`

因此，这条样本不是单纯的 prompt/evidence-use 失败，而是 chain-incomplete。另两条拒答也类似：

- Flavia Domitilla 样本缺丈夫死亡地点 support doc `4684`。
- Lou Breslow 样本缺妻子 Marion Byron 出生地 support doc `2762`。

## 开发产物汇总

### 新增或重点改动的源码

| 文件 | 阶段 | 作用 |
| --- | --- | --- |
| `src/logicguard/ms_graphrag/stage31_answerability_ablation.py` | Stage31 | 离线比较 ordering/top-k/prompt budget 的 answerability proxy |
| `src/logicguard/ms_graphrag/stage32_llm_comparison.py` | Stage32 | 真实 LLM 对照验证 Stage28 default 与 Stage31 title-overlap |
| `src/logicguard/ms_graphrag/answer_level_llm_verification.py` | Stage33/36/37 | 支持 rendering policies、Stage35 method、prompt policy 记录 |
| `src/logicguard/ms_graphrag/stage29_answer_audit.py` | Stage33/36/37 | 复用并扩展回答审计、方法显示和失败归因 |
| `src/logicguard/ms_graphrag/stage34_answer_judge_audit.py` | Stage34/36/37 | judge-aware 审计，只裁判 uncertain incorrect rows |
| `src/logicguard/ms_graphrag/stage35_source_enrichment.py` | Stage35 | source enrichment 离线诊断与 enriched context 输出 |
| `src/logicguard/llm/context.py` | Stage37 | 新增 `prompt_policy=evidence_compare` |

### 配置与测试

新增配置覆盖 Stage31 到 Stage37 的主要实验：

- `configs/ms_graphrag_stage31_answerability_poisoned20.yaml`
- `configs/ms_graphrag_stage32_llm_comparison_poisoned20.yaml`
- `configs/ms_graphrag_stage33_answer_llm_ordered_poisoned20.yaml`
- `configs/ms_graphrag_stage33_answer_audit_poisoned20.yaml`
- `configs/ms_graphrag_stage34_answer_judge_audit_poisoned20.yaml`
- `configs/ms_graphrag_stage35_source_enrichment_poisoned20.yaml`
- `configs/ms_graphrag_stage36_answer_llm_enriched_poisoned20.yaml`
- `configs/ms_graphrag_stage36_answer_audit_enriched_poisoned20.yaml`
- `configs/ms_graphrag_stage36_answer_judge_audit_enriched_poisoned20.yaml`
- `configs/ms_graphrag_stage37_answer_llm_evidence_prompt_poisoned20.yaml`
- `configs/ms_graphrag_stage37_answer_audit_evidence_prompt_poisoned20.yaml`
- `configs/ms_graphrag_stage37_answer_judge_audit_evidence_prompt_poisoned20.yaml`

新增或扩展测试包括：

- `tests/test_ms_graphrag_stage31_answerability_ablation.py`
- `tests/test_ms_graphrag_stage32_llm_comparison.py`
- `tests/test_ms_graphrag_stage34_answer_judge_audit.py`
- `tests/test_ms_graphrag_stage35_source_enrichment.py`
- `tests/test_ms_graphrag_stage27_answer_llm_verification.py`
- `tests/test_llm_generation.py`

Stage37 完成后，全量验证结果为：

- `ruff check .`：通过。
- `pytest -q`：`194 passed`。

## 当前阶段的核心结论

### 1. LogicGuard 不应只追求拒答

Stage31-37 的实验目标一直不是让模型更保守，而是在防止污染答案的同时恢复回答能力。最终结果显示，Stage36/37 在 final utility `0.8500` 的同时保持 final attack success `0.0000`。这比单纯删除风险 source 更接近真实部署需求。

### 2. source enrichment 是主要增益来源

Stage34 final utility 只有 `0.3500`。Stage35 找到 `query_bm25_append + top-12`，Stage36 将 final utility 提升到 `0.8500`。这条链说明：当前 official GraphRAG answer-level bottleneck 的主因是候选源不足或二跳证据缺失，而不是 LLM 本身完全不会回答。

### 3. answer surface 不是充分条件

Stage37 证明，gold answer 表面出现在上下文中，不代表多跳证据链完整。导演年龄比较题中，答案 film title 出现了，但缺另一个导演的出生信息，模型拒答是合理的。

因此后续报告不能只写 `answer_surface_rate`，还要写：

- full support hit
- bridge entity hit
- second-hop property hit
- chain completeness

### 4. judge-aware 审计仍有必要

`Poland` vs `Polish-Lithuanian Commonwealth` 这类样本说明，严格字符串匹配会把相关但不够精确的回答直接归为错误。Stage34/36/37 的 judge-aware 层只用 1 次 judge call，就把 final incorrect 降到 `0.0000`，并保留 partial。

### 5. 当前结论仍受实验边界限制

Stage31-37 的结论主要来自 2WikiMultihopQA debug_50 前 20 个 query。它已经足够支撑方法迭代，但还不足以作为最终论文结论。后续需要：

- 扩展到 50-query official GraphRAG。
- 扩展到 HotpotQA/MuSiQue 等其它多跳数据集。
- 从 trusted clean candidate pool 推进到 trust-aware/no-clean setting。
- 做自适应攻击评估，检查攻击者是否能绕过 source enrichment 和 judge-aware 审计。

## 下一阶段建议

Stage38 建议围绕 evidence-chain completeness 展开，而不是继续 prompt ablation。

建议任务：

1. 新增 `abstain_chain_incomplete` 归因，把“有答案表面但缺二跳证据”的样本从 `abstain_despite_gold_answer_surface` 中拆出来。
2. 设计 chain-completeness 诊断指标：`bridge_entity_hit`、`second_hop_property_hit`、`full_support_hit`、`support_answer_surface`。
3. 在 Stage35 的 `query_bm25_append` 基础上增加 second-hop targeted append：从已命中的 bridge title/entity 出发，追加人物、地点、作品属性文档。
4. 在 20-query 上完成离线 proxy，再进行真实 LLM 复验。
5. 稳定后扩展 50-query，并准备跨数据集复核。

## 主要报告入口

- `outputs/reports/Stage31_AnswerabilityAblation_20Query.md`
- `outputs/reports/Stage32_LLMComparison_20Query.md`
- `outputs/reports/Stage33_TitleOverlapPipeline_20Query.md`
- `outputs/reports/Stage34_AnswerJudgeAudit_20Query.md`
- `outputs/reports/Stage35_SourceEnrichment_20Query.md`
- `outputs/reports/Stage36_EnrichedContextLLM_20Query.md`
- `outputs/reports/Stage37_EvidencePrompt_20Query_中文综合报告.md`

