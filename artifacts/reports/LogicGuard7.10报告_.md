# LogicGuard 项目全面分析报告 (Stage37)

审查日期：2026-07-09
审查范围：全部源码（ms_graphrag 15,490 行，总测试 194 passed）、全部实验报告（23 组实验）、全部配置与产物
上次审查：2026-06-23（Stage20时期）

---

## 一、项目当前状态总览

### 1.1 规模变化

| 指标 | 上次审查 (Stage20) | 当前 (Stage37) | 变化 |
|---|---|---|---|
| ms_graphrag 代码行数 | ~1,900 行 | 15,490 行 | +8 倍 |
| 测试通过数 | 147 | 194 | +47 |
| 实验阶段 | LG-A 到 LG-H (Stage20) | 推进到 Stage37 | +17 个阶段 |
| 核心实验报告 | 105 份 | 150+ 份 | 大幅增加 |
| MS GraphRAG 查询规模 | 1-5 query | 20-50 query | 4-10 倍 |

### 1.2 整体判断

项目已从"研究原型闭环、主实验未收敛"的状态，大幅推进到"**MS GraphRAG official answer-level 端到端管线已打通，核心指标（utility 0.85 + attack success 0.00）已在一个受控规模上确立**"。但仍未完成跨数据集、自适应攻击和大规模统计验证。

---

## 二、当前架构全貌

### 2.1 新增模块体系

Stage21-37 期间新增了四大核心能力层：

```
┌──────────────────────────────────────────────────────────────────┐
│                    Stage21-37 新增架构层                          │
│                                                                  │
│  Layer 5: Answer Pipeline (Stage27-37)                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ answer_level_llm_verification.py  ← LLM 回答生成 + 渲染策略 │  │
│  │ stage29_answer_audit.py           ← 回答审计 + 归一化 + 归因│  │
│  │ stage34_answer_judge_audit.py     ← LLM Judge 增强审计      │  │
│  │ stage31_answerability_ablation.py ← 离线可答性消融           │  │
│  │ stage35_source_enrichment.py      ← 候选源扩展诊断           │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Layer 4: Risk Detection (Stage28)                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ risk_non_oracle_source_recovery.py  ← 非oracle风险检测       │  │
│  │   - clean-candidate consistency detector                   │  │
│  │   - source title/entity drift 检测                         │  │
│  │   - 不读取 changed labels / gold answer / support_doc_ids  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Layer 3: Source Recovery (Stage23-25)                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ source_recovery.py               ← Official sources 级恢复  │  │
│  │ non_oracle_source_recovery.py    ← doc_id-blind candidate   │  │
│  │   - query_bm25 / title_entity_bm25 / hybrid_policy         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Layer 2: Medium-scale Query Layer (Stage21-22)                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ stage21_medium_diagnostics.py    ← 50-query indexed 诊断    │  │
│  │ query_layer_*                    ← official query layer     │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 当前完整链路

```
数据 (clean/poisoned corpus)
  │
  ▼
MS GraphRAG Indexing (graphrag 3.1.0 official)
  │  entities.parquet, relationships.parquet, communities.parquet, LanceDB
  ▼
Query-Layer Entity Control (Stage20/22: include/exclude via official API)
  │  title_seeding, query_guard
  ▼
Official Local Search Context Export
  │  context_data.sources, entities, relationships, reports
  ▼
Source-Level Risk Detection (Stage28: clean-candidate consistency)
  │  risk_non_oracle_guarded_sources
  ▼
Source-Level Recovery (Stage25/28: non-oracle title_entity_bm25)
  │  query_bm25, title_entity_bm25, hybrid_policy
  ▼
Source Ordering (Stage31/33: title_query_overlap)
  │  rendering_policies: order_policy, max_sources, max_chars_per_source
  ▼
Source Enrichment (Stage35/36: query_bm25_append + top-12)
  │  追加非 oracle clean candidate
  ▼
Answer Generation (Stage36/37: qwen3.7-plus + evidence_compare prompt)
  │  poisoned / guarded / recovered contexts
  ▼
Answer Audit + Judge (Stage29/34: normalization + selective LLM judge)
  │  correct / partial / incorrect / abstained / attack_success
  ▼
Metrics & Reports
```

---

## 三、已完成的核心功能

### 3.1 风险检测去 Oracle 化

**这是项目目前最重要的方法贡献。**

Stage28 的 `risk_non_oracle_source_recovery.py` 实现了一个**不读取 changed labels、不读取 gold answer、不读取 support_doc_ids** 的风险检测器：

- 用 clean candidate pool 做 source title 匹配
- 比较 source body entity drift（clean 候选与 current source 的实体差异）
- 只有 changed-support metadata 被离线评估使用（不作为检测器输入）

**结果**：
- Risk recall: 0.9925
- Risk precision: 1.0000
- Risk FP rate: 0.0000
- Changed exposure after recovery: 0.0000

证明了 Oracle 风险信息（已知哪些文档被 LogicPoison 改写）可以被一个纯 inference-time 的 clean-candidate consistency 检测器替代。这是从"实验条件"到"可部署方案"的关键一步。

### 3.2 Non-Oracle Source Recovery

三种非 oracle 候选恢复策略：
- `non_oracle_query_bm25`：用原问题检索 clean candidate pool
- `non_oracle_title_entity_bm25`：用 title + entity 检索
- `non_oracle_hybrid_policy`：混合策略

50-query 下最佳方法 (`title_entity_bm25`) 达到 gold recall 0.5450，oracle gap 0.2400。相比 guarded_sources 的 0.0400，恢复了 13.6 倍。

### 3.3 Answer-Level 全链路打通

从 source recovery → ordering → enrichment → answer generation → audit → judge，完成了一条端到端的 answer-level 管线：

| 里程碑 | 阶段 | 结果 |
|---|---|---|
| 首次真实 LLM 回答 | Stage27 | utility 0.05-0.20, attack success 0.00 |
| 排序优化 | Stage31-33 | utility 0.25 → 0.30 |
| Judge 增强 | Stage34 | utility 0.35, incorrect 0.00 |
| **Source Enrichment** | **Stage35-36** | **utility 0.85, attack success 0.00** |
| Prompt 消融 | Stage37 | utility 0.85（持平），确认瓶颈不在 prompt |

### 3.4 渲染策略配置化

`answer_level_llm_verification.py` 中的 `rendering_policies` 机制将 source ordering、top-k、max_chars/source 等从硬编码变成了配置驱动：

```yaml
rendering_policies:
  risk_non_oracle_title_entity_bm25:
    order_policy: title_query_overlap
    max_sources: 8
    max_chars_per_source: 450
```

旧 Stage27/28 配置默认仍为 `official_order`，保持向后兼容。

### 3.5 分层审计体系

三级审计架构：
1. **本地归一化**（Stage29）：答案字符串归一化修正严格匹配低估
2. **LLM Judge**（Stage34）：只裁判 uncertain incorrect 行（成本极低，20 query 只用 1 次 judge call）
3. **失败归因**：将拒答拆分为 `abstain_without_gold_answer_surface` / `abstain_despite_gold_answer_surface` / `abstain_chain_incomplete`

---

## 四、当前已产出的关键结论

### 4.1 有强证据支撑的结论

1. **Risk oracle 可被替代**（Stage28）：clean-candidate consistency detector 能在不读取 changed labels 的情况下达到 recall 0.9925、precision 1.0000。

2. **Non-oracle recovery 显著优于纯过滤**（Stage25）：title_entity_bm25 将 guarded 的 gold recall 0.04 恢复到 0.55，同时保持 changed exposure=0。

3. **Source enrichment 是当前最大增益来源**（Stage35-36）：`query_bm25_append + top-12` 将 utility 从 0.35 提升到 0.85，attack success 保持 0。

4. **Source ordering 不是无关细节**（Stage31-32）：`title_query_overlap` 相比 `official_order` 将真实 LLM utility 从 0.15 提升到 0.25，并消除所有 support hit 失败。

5. **Prompt-only 改进已达瓶颈**（Stage37）：evidence_compare prompt 没有带来 utility 增益，剩余失败根因是 evidence-chain incompleteness。

6. **过滤+恢复的安全性可以传递到真实 LLM 回答层**（Stage27-37 全程保持 attack success=0.00）。

### 4.2 还不能下的结论

- 不能声称 Risk Non-Oracle 检测器对所有攻击类型有效（当前仅在 LogicPoison 20 query 上验证）。
- 不能说 non-oracle recovery 的 oracle gap (0.24) 能在不引入额外知识的情况下完全闭合。
- 不能说 source enrichment 在 HotpotQA/MuSiQue 等不同特征的数据集上有同等增益。
- 不能声称对 adaptive attacker 的防御有效。
- 不能把 20-query 结论推广到 500-query 统计规模。

---

## 五、当前不足与待补齐

### 5.1 方法层面

| 问题 | 严重度 | 说明 |
|---|---|---|
| Clean candidate pool 仍依赖可信库 | **中高** | Risk non-oracle 检测器和 non-oracle recovery 都假设存在可信 clean candidate pool。这是比"已知 changed doc_ids"更真实的假设，但仍需在 threat model 中显式声明并在论文中讨论退化情况 |
| Evidence-chain completeness 未解决 | **中** | Stage37 确认剩余 3 条拒答都是缺二跳证据。需要 second-hop targeted append，但这可能让候选池进一步膨胀 |
| 自适应攻击未评估 | **高** | 当前所有攻击者都是 oblivious 的 |
| Risk detector 只在单一攻击类型上验证 | **中高** | 只在 LogicPoison 原位替换上验证，未在 Bridge Injection 等新增文档攻击上测试 |

### 5.2 实验层面

| 问题 | 严重度 | 说明 |
|---|---|---|
| 仅 2WikiMultihopQA 一个数据集 | **高** | Stage27-37 的全部 answer-level 实验都在 2Wiki 的 20 query 上 |
| 仅 20-50 query | **中高** | 远不足以报告置信区间和显著性 |
| HotpotQA/MuSiQue 未跑 MS GraphRAG | **高** | 这两个数据集的 MS GraphRAG 实验仅在检索层（Stage21-24 的 context-only），未进入 answer-level |
| 仅一个回答模型 | **低中** | qwen3.7-plus，缺少多模型一致性验证 |

### 5.3 工程层面

| 问题 | 严重度 | 说明 |
|---|---|---|
| 实验编号体系膨胀 | **中** | Stage21-37 的编号跨越了 17 个阶段，部分中间阶段产物可以归档 |
| 缺乏统一 CLI 入口 | **低** | 各阶段仍通过独立 python -m 调用 |
| README 需要更新 | **低** | 反映 Stage37 的最新管线 |

---

## 六、下一步推进建议

### 6.1 优先级排序

```
Priority 1 (必须做，否则论文核心站不住):
├── 跨数据集 answer-level 复验 (HotpotQA/MuSiQue, 各 20 query)
├── 至少一种 adaptive attacker 试点
└── 50-query 扩展 + bootstrap 置信区间

Priority 2 (显著提升论文竞争力):
├── Evidence-chain completeness 诊断与修复
├── 回答层多模型一致性验证
├── Clean candidate pool 假设的形式化与退化分析
└── 跨数据集 source enrichment 效果对比

Priority 3 (锦上添花):
├── 统一 CLI 入口
├── 实验注册表更新到 Stage37
└── README 和论文矩阵更新
```

### 

### 论文核心叙事（建议结构）

```
Title: LogicGuard: Non-Oracle Risk Detection and Trusted Evidence Recovery for GraphRAG under Logic Poisoning

1. Introduction
   - GraphRAG 被广泛采用 → 逻辑投毒威胁 (LogicPoison)
   - 现有防御：过滤 (安全但不可用) 或重新检索 (假设已知污染位置)
   - LogicGuard: 非 oracle 风险检测 + 可信证据恢复

2. Threat Model
   - 攻击者：可原位改写语料文档 (LogicPoison threat)
   - 防御者：有 ingestion 时的 clean candidate pool（无 changed label）
   - 防御目标：changed exposure → 0，同时维护 answer utility

3. LogicGuard Design
   - 3.1 Risk-Non-Oracle Detection (Stage28)
   - 3.2 Non-Oracle Source Recovery (Stage25)
   - 3.3 Source Ordering & Enrichment (Stage31-35)
   - 3.4 Answer-Level Guard & Recovery Pipeline

4. Experiments
   - 4.1 Experimental Setup (3 datasets, 2 retrievers, 4 conditions)
   - 4.2 Source-Level Defense (context-only, 50-query)
   - 4.3 Answer-Level Results (20-query, utility + attack success)
   - 4.4 Ablation: Risk Oracle → Non-Oracle Degradation
   - 4.5 Ablation: Source Enrichment Contribution
   - 4.6 Adaptive Attacker Analysis (Phase B 产出)

5. Discussion
   - Clean candidate pool 假设与退化分析
   - Evidence-chain completeness 的剩余挑战
   - MS GraphRAG 规模限制与未来工作

6. Conclusion
```

---

最关键的突破是两条：

1. **风险检测去 Oracle 化**（Stage28）：证明了 clean-candidate consistency 可以在不读取 changed labels 的情况下高精度检测风险 source。这是从"benchmark 实验"到"可部署方案"的关键一步。

2. **Source Enrichment 驱动的高效用回答**（Stage35-36）：在 20-query 上达到 utility 0.85 + attack success 0.00，同时证明这个增益不依赖 prompt hack 而是实实在在的证据补充。

### 最大的剩余风险

- **单数据集单规模**：全部 answer-level 实验仅在 2Wiki 20-query 上。扩张到 HotpotQA/MuSiQue 时 utility 可能显著下降。
- **Adaptive attacker 完全空白**：如果攻击者知道 LogicGuard 用 clean-candidate consistency 做检测，可以同时污染候选池。
- **Oracle gap 仍存在**：Non-oracle recovery 的 gold recall 0.55 远低于 oracle 的 0.79。这个差距能否通过更好的 ranking 闭合尚未知。



> **LogicGuard 已在 MS GraphRAG official answer-level 管线上形成了一个有说服力的端到端结果（utility 0.85 / attack success 0.00），并完成了从 oracle 到 non-oracle 风险检测的关键方法迁移。目前的当务之急不是继续在 2Wiki 20-query 上消融，而是把同一管线扩展到另外两个数据集 + 至少一种 adaptive attacker，然后果断进入论文写作阶段。**

无可信参考时，LogicGuard 必须依赖一些弱信号组合：

1. **多源一致性检测**
   不再相信单个 source。对检索结果里的多个 source 抽取原子事实，比如：
   `人物 A 的母亲是 B`
   `电影 X 的导演是 Y`
   `电影 X 的上映时间是 T`

   然后看关键 claim 是否被多个相互独立的 source 支持。如果某个答案关键事实只出现在一篇 source 里，其他 source 没有支持，甚至存在冲突，就标风险。

2. **图结构异常检测**
   LogicPoison 通常会篡改多跳链路中的某个实体关系，让检索路径被带偏。可以检测：

   - 某条关键边只由单个文档支持；
   - 某个实体突然连接到不常见/类型不匹配的实体；
   - query entity 到 answer entity 的路径过于孤立；
   - source 在 GraphRAG 图里像“突然插入的桥”。

3. **检索行为异常检测**
   攻击文档往往为了被检索到，会和 query 高度贴合，但证据质量弱。可以看：

   - source 与 query 词面相似很高，但与其他证据不一致；
   - source 被异常频繁地检索到；
   - source 含有过多 query 相关实体堆叠；
   - source 对答案很“直接”，但缺少周边支持。

4. **claim-level 冲突检测**
   不是只判断整篇文档，而是判断文档中参与回答的关键句。比如：

   - source A 说导演是 X；
   - source B/C 说导演是 Y；
   - source A 又单独推出最终答案 Z。

   这时 LogicGuard 应该标记 A 或相关 claim 为高风险，并拒绝基于它直接回答。

5. **来源元数据/版本异常**
   即使没有 clean 内容，也可能有元数据：

   - 文档来源是否可信；
   - 是否最近异常更新；
   - 是否缺少来源、作者、时间戳；
   - 是否来自低可信 ingestion channel；
   - 是否和历史 hash/version 不一致。

   这些不能单独证明污染，但可以进入风险评分。

6. **回答阶段保守策略**
   没有可信参考时，最重要的是不要强行恢复。正确动作应该是：

   - 高风险 source 不进入最终回答；
   - 只用被多源支持的 claim；
   - 证据不足时回答“不足以确定”；
   - 给出冲突来源，而不是编一个确定答案。
