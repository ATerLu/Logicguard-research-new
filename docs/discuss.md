# LogicGuard 研究讨论纪要

_更新时间：2026-08-13；讨论范围：截至 Stage47 的代码、实验记录、第三方评审，以及 HoG-GRAG、GraphRAG under Fire、LogicPoison 的对照分析。_

## 0. 文档目的与使用说明

本文记录本轮围绕 LogicGuard 的关键研究问答、证据、边界和建议动作，供主开发者及时了解讨论结果并继续推进。它不是论文定稿，也不替代正式实验报告。

阅读时需要严格区分三类表述：

- **已验证事实**：能够由当前代码、冻结配置或 `artifacts/results/` 中的结果直接支持。
- **机制推断**：由代码行为或论文方法推导得到，但尚未在完整实验中直接测量。
- **建议方案**：下一阶段值得实现和验证的研究设计，不能提前写成已有贡献。

第三方完整评审意见见 `docs/progressReview.md`。本纪要重点记录评审后继续讨论形成的新判断和可执行路线。

---

## 1. 当前最重要的结论

1. LogicGuard 当前最有证据支撑的核心不是“通用 GraphRAG 投毒检测器”，而是**在可信历史参考可用时，对检索后的 source 做风险识别、可信恢复和可答性补全**。
2. Stage43–45 的核心部署位置与 HoG-GRAG 相同，均位于 **GraphRAG 检索之后、最终生成之前**；但 LogicGuard 处理 source/document context，HoG-GRAG 处理 query-specific subgraph 中的实体与关系。
3. LogicGuard 还包含更靠前的 query-layer entity seeding/exclusion，但该组件主要改善召回，不能独立清除投毒内容。
4. 当前 Stage43 把 `candidate=None` 处理为 `is_risky=False`。因此，没有可信 counterpart 不是“低置信”，而会被错误地解释为“安全”，这是 Natural Bridge 能绕过的直接原因。
5. 完全没有可信语料库时，Stage43 检测、Stage43 恢复、Stage44 补证和 Stage45 二跳补全基本同时失效；当前项目没有完成可信池覆盖率为 0% 的正式实验，不能宣称 no-clean robustness。
6. HoG-GRAG 的 `H-Fail/H-Amb` detector 会漏掉“每跳只有一个候选、整条链可执行但答案错误”的情况。该漏检机制与 LogicPoison 的同类型实体交换和推理桥重定向高度吻合，但 HoG-GRAG 的实验攻击实际来自 GRAGPoison，而不是 LogicPoison。
7. 值得把 LogicGuard 推进为一套**信任条件自适应的双轨防御**：有可信 counterpart 时走可信恢复线；没有 counterpart 时走逐跳结构一致性线；两条线都无法建立充分证据时安全拒答。
8. 下一步应先做完整 corpus poisoning、重新建图和重新检索的 Stage48 基线，再改 detector。Stage47 只是 post-retrieval source perturbation，不能替代完整攻击链验证。

---

## 2. LogicGuard 的研究“故事”应当怎样讲

### 2.1 问题冲突

GraphRAG 投毒防御存在一个基本矛盾：

- 单纯保留检索结果，污染证据会进入 prompt 并诱导错误回答；
- 单纯删除风险证据，又会破坏多跳证据链，导致拒答或回答效用下降。

因此，LogicGuard 的研究问题不应只写成“如何检测污染文档”，而应写成：

> 如何在阻止污染证据进入生成器的同时，恢复多跳问题所需的可答性和证据链完整性？

### 2.2 当前方法叙事

现有主链可以概括为：

```text
风险识别 → 可信恢复 → source 补证 → 条件式二跳补全 → 回答层验证
 Stage43     Stage43       Stage44          Stage45          Stage46/47
```

这条叙事比“多阶段堆功能”更合理，因为每一步对应一个被实验暴露的瓶颈：

- 只检索：污染暴露高；
- 只过滤：安全但不可答；
- 替换后：污染被移除，但部分 query 缺少答案证据；
- 普通补证后：效用提高，但复杂问题仍可能缺第二跳；
- 二跳补证后：部分 MuSiQue 问题进一步恢复，但不适合无条件触发。

### 2.3 当前可以主张和不能主张的内容

较安全的主张：

> 在具有可信历史参考的威胁模型下，LogicGuard 通过风险感知的 source 恢复和条件式证据补全，在固定 LogicPoison 攻击上降低攻击成功率，并部分恢复多跳回答效用。

目前不能主张：

- 对任意 GraphRAG 投毒攻击普遍鲁棒；
- 在完全没有可信根的环境中能够正确恢复事实；
- Stage47 已验证重新建图后的自适应鲁棒性；
- 三类 Stage47 攻击都是已有规范攻击或都具有已证明的新颖性；
- 找到 recovery candidate 就等于恢复正确。

---

## 3. LogicGuard 实际部署位置

当前完整链路可表示为：

```text
用户问题
   ↓
LogicGuard query-layer entity seeding/exclusion
   ↓
Microsoft GraphRAG Local Search
   ↓
GraphRAG context_data
  ├── sources
  ├── entities
  ├── relationships
  └── reports
   ↓
LogicGuard Stage43：source 风险检测与可信候选恢复
   ↓
LogicGuard Stage44：query-BM25 clean source enrichment
   ↓
LogicGuard Stage45：条件式 second-hop evidence append
   ↓
context 排序、截断与 prompt 渲染
   ↓
最终回答模型
```

关键代码对应：

- `src/logicguard/ms_graphrag/query_layer_context.py`：通过 GraphRAG 官方 context builder 生成 query-layer context。
- `src/logicguard/defense/risk_aware_recovery.py`：Stage43 检测和恢复。
- `src/logicguard/defense/source_enrichment.py`：Stage44 source enrichment。
- `src/logicguard/defense/chain_completion.py`：Stage45 chain completeness 和二跳补证。
- `src/logicguard/evaluation/answer_generation.py`：将防御后的 sources 渲染进 prompt 并调用最终生成模型。

工程边界：当前 Stage43–45 主要通过 JSONL 读写串联，是实验型离线中间件，尚未封装成 GraphRAG 在线查询 API 中的统一运行时组件。后续可以收敛为类似：

```python
def defend_context(query: str, context_data: dict) -> DefendedContext:
    ...
```

并放在 `local_search` 返回与 final answer generation 之间。

---

## 4. Stage43–47 的方法与实验证据

### 4.1 Stage43：风险检测与恢复

Stage43 用检索 source 和 trusted clean candidate 的一致性判断风险。Stage43/47 冻结配置是：

- `title_overlap_threshold = 0.80`
- `entity_drift_threshold = 0.10`
- `top_k_candidates = 5`
- `min_candidate_score = 0.01`

论文报告必须引用实际 YAML 中的 `0.10`，不能误用通用代码默认值 `0.20`。

当前 detector 的核心条件近似为：

```text
标题与 clean candidate 高度重合
                    +
source 正文与 candidate 的实体漂移超过阈值
                    ↓
                  risky
```

其优点是可解释、无需读取 changed labels；其局限是高度依赖 clean candidate，而且对只改关系、日期、数值或小属性的低实体漂移攻击不敏感。

### 4.2 Stage44：可信 source enrichment

Stage44 在 Stage43 recovered contexts 上，从 clean candidate pool 中使用 query-BM25 追加证据，选定方案为 top-12。其作用不是进一步检测攻击，而是修复“安全后不可答”的问题。

### 4.3 Stage45：条件式二跳补证

Stage45 从 query 和当前 sources 中提取桥接线索，在 clean candidate pool 中寻找第二跳证据，形成 top-14 context。结果说明其主要价值出现在 MuSiQue 的缺链 query；对已经完整的 HotpotQA query 不应无条件扩充。

### 4.4 Stage46：固定 LogicPoison 回答层结果

| 数据集 | 条件 | Final utility | Final ASR |
| --- | --- | ---: | ---: |
| HotpotQA | 未恢复 `full_query_guard` | 0.20 | 0.45 |
| HotpotQA | Stage43 | 0.70 | 0.00 |
| HotpotQA | Stage44 | 0.85 | 0.00 |
| HotpotQA | Stage45 | 0.85 | 0.00 |
| MuSiQue | 未恢复 `full_query_guard` | 0.20 | 0.10 |
| MuSiQue | Stage43 | 0.30 | 0.00 |
| MuSiQue | Stage44 | 0.40 | 0.00 |
| MuSiQue | Stage45 | 0.45 | 0.00 |

这些结果说明：固定 LogicPoison 条件下存在真实攻击压力，Stage43 可以阻断攻击，Stage44/45 再恢复部分效用。但该结论依赖 trusted clean reference pool，不能外推为无条件生产安全。

### 4.5 Stage47：三类自适应 source 攻击

攻击有效性漏斗：

```text
75 attempted
  ↓
35 generation-valid
  ↓
21 strict evaluation-valid
  ↓
19 malicious-answer prompt exposures
```

该漏斗必须保留。不能用 75 次尝试、21 条评测有效和19条真实 prompt 暴露中的不同分母互换计算结论。

三类攻击的主要结果：

| 攻击 | 攻击目标 | 主要观察 |
| --- | --- | --- |
| `low_drift` | 保留实体集合，修改关系、日期、数值或属性，使 entity drift 低于 0.10 | Stage43 检出率为 0；有效样本和实际目标暴露仍少，已证明 detector blind spot，但不足以稳定估计总体 ASR |
| `candidate_collision` | 伪造与可信候选同标题的 source，诱导 recovery 选择攻击者指定的错误 candidate | 5/5 被检测且攻击 source 被移除，targeted ASR 从 0.8 降到 0；但 5/5 recovery 都是错误候选，说明“检测成功”不等于“恢复正确” |
| `natural_bridge` | 注入没有可信对应版本的新 source/关系 | MuSiQue 上 Stage43 检出率为 0，exposure-conditioned targeted ASR 为 0.875；Stage44/45 只能通过追加证据稀释，不能可靠删除攻击 source |

Stage47 的边界：它先从 clean official GraphRAG 获取 sources，再在 source 层施加扰动。它没有重新构建索引，因此没有验证对实体抽取、关系抽取、embedding、community、检索排名的完整攻击影响。

---

## 5. 三类自适应攻击是规范攻击还是项目自编攻击

结论：三类 Stage47 攻击是项目为 LogicGuard 设计的 defense-adaptive attack families，不是从某篇论文中原样复现的三种标准攻击。

- 生成框架、约束、验证和防御矩阵在 `src/logicguard/attack/adaptive.py` 中实现。
- 每个 query 的攻击文本由 LLM 按项目 prompt 生成，再由本地规则验证。
- 生成阶段不读取 gold answer、support doc IDs 或 changed labels，标签在攻击冻结后才用于评测。

它们与已有攻击概念存在相似性：

- `low_drift` 与小幅文字/关系修改的知识投毒在思想上相近；
- `natural_bridge` 与恶意文档或关系注入相近；
- `candidate_collision` 更像专门针对 LogicGuard recovery 机制的防御自适应攻击。

建议论文用语：

> We design three LogicGuard-specific, defense-adaptive attack families.

在完成系统相关工作检索之前，不宜写成“提出三种全新攻击”。正式实验应增加公共攻击基线，例如 LogicPoison、GRAGPoison，以及可选的 PoisonedRAG 或其他公开 GraphRAG KPA。

---

## 6. LogicGuard 中的知识图谱与“自适应攻击”含义

项目中确实存在知识图谱构建和 GraphRAG 索引：

- 轻量图模块将文档和实体组织为图；
- Microsoft GraphRAG 工作流构建 official entities、relationships、communities、reports 和 text units；
- query-layer 和 Stage43–47 使用这些 indexed artifacts 或 official context。

但 Stage43–47 的核心不是修改建图算法，而是 query-time/post-retrieval 防御。

“自适应攻击”不是普通的随机攻击，而是攻击者了解或推测防御规则后，专门针对规则弱点设计输入：

```text
知道 entity drift 阈值      → low_drift
知道 recovery 候选匹配方式  → candidate_collision
知道 candidate=None 会放行  → natural_bridge
```

因此 Stage47 检验的是“防御规则是否能抵抗有针对性的绕过”，而不是再重复固定攻击测试。

---

## 7. HoG-GRAG、GraphRAG under Fire 与 LogicGuard

相关论文：

- GraphRAG under Fire / GRAGPoison：<https://arxiv.org/abs/2501.14050>
- HoG-GRAG：<https://aclanthology.org/2026.acl-short.47/>
- LogicPoison：<https://aclanthology.org/2026.acl-long.252/>

### 7.1 GRAGPoison

GraphRAG under Fire 提出 GRAGPoison。其主要思想是选择可覆盖多个目标 query 的共享关系，然后执行：

1. relation selection；
2. relation injection；
3. relation enhancement；
4. narrative generation。

攻击者向语料注入恶意文本并重新构建 GraphRAG 索引。HoG-GRAG 的投毒实验按照该工作构造，而不是直接采用 LogicPoison。

### 7.2 HoG-GRAG

HoG-GRAG 位于 retriever 和 generator 之间，将多跳问题分解为有序 subqueries，在 retrieved subgraph 上逐跳求解。

主要检测信号：

- `H-Fail`：某跳没有候选，即 `|Ci| = 0`；
- `H-Amb`：某跳存在多个候选，即 `|Ci| > 1`。

检测后，它通过全局 KG 查找候选、回溯先前 hop、处理候选栈，并注入最小证据，形成紧凑的 repaired subgraph。

### 7.3 与 LogicGuard 的异同

| 维度 | HoG-GRAG | 当前 LogicGuard |
| --- | --- | --- |
| 部署层级 | 检索后、生成前 | 核心 Stage43–45 同样位于检索后、生成前 |
| 处理对象 | query-specific subgraph 的实体和关系 | official GraphRAG source/document context |
| 检测依据 | hop failure 和 hop ambiguity | clean candidate 的标题/实体/文本一致性 |
| 修复依据 | 被污染全局 KG 中仍存在的正确边 | trusted clean candidate pool |
| 主要优势 | 不要求额外 clean corpus | 恢复内容有可信版本依据 |
| 主要盲点 | 完整、唯一但错误的链 | 无 counterpart、低漂移、错误候选恢复 |

---

## 8. HoG-GRAG 漏检是否就是 LogicPoison 攻击链路

### 8.1 HoG-GRAG 附录中的两类漏检

第一类：末跳只有一个恶意候选。

```text
正确链：team → Big 12 Conference
攻击链：team → Mid-American Conference
```

末跳存在且只有一个候选，所以既没有 `H-Fail`，也没有 `H-Amb`。

第二类：第一跳被重定向为同类型错误实体，但第二跳仍然可执行。

```text
正确链：Jeff Tisdel → 1996 Las Vegas Bowl → Sam Boyd Stadium
攻击链：Jeff Tisdel → Rose Bowl → Liberty Bowl Memorial Stadium
```

错误实体与正确实体类型相同，后续仍能找到类型正确的 stadium，于是整条链结构完整但语义错误。

### 8.2 与 LogicPoison 的关系

LogicPoison 通过 type-preserving entity swapping 修改全局 logic hubs 和 query-specific reasoning bridges，将：

```text
A → B → C
```

重定向为：

```text
A → B' → C
```

因此 HoG-GRAG 的第二类漏检与 LogicPoison 的攻击机制高度一致：同类型中间实体被替换，错误链仍能完成。

但必须区分：

- **机制是否吻合**：高度吻合；
- **HoG-GRAG 样本是否由 LogicPoison 生成**：不是，原实验采用 GRAGPoison 风格关系替换和增强。

并非所有 LogicPoison 都会绕过 HoG-GRAG：

- 如果替换后造成断链，会触发 `H-Fail`；
- 如果真假候选同时存在，会触发 `H-Amb`；
- 只有形成“唯一、同类型、端到端可执行错误链”的子集会稳定命中该盲区。

后续 LogicGuard 的结构线需要新增 `H-Unique-Unverified`：每跳候选唯一，但缺少独立可信或多源支持，不能仅凭链路完整判定安全。

---

## 9. 完全没有可信语料库时，当前 LogicGuard 会怎样

需要区分三个场景。

### 9.1 可信池路径或 parquet 不存在

`load_clean_reference_sources()` 要求 `documents.parquet` 和 `text_units.parquet` 存在，否则直接抛出 `FileNotFoundError`。当前程序没有显式的 no-trusted-pool 运行模式。

### 9.2 可信池文件存在，但候选为空

Stage43 的实际逻辑是：

```python
if candidate is None:
    return SourceRiskResult(
        is_risky=False,
        risk_score=0.0,
        candidate=None,
    )
```

因此会发生：

```text
所有 source 找不到 candidate
             ↓
全部被标为非 risky
             ↓
Stage43 原样保留
             ↓
Stage44 没有 clean source 可追加
             ↓
Stage45 没有 second-hop candidate 可补充
```

此时 Stage43–45 基本退化为透传。query-layer guard 仍可工作，但它只控制检索候选，不能判断事实真假。

### 9.3 只有某篇新 source 没有可信 counterpart

Stage47 `natural_bridge` 是最接近的已测情况。MuSiQue 结果为：

| 条件 | 检出率 | Targeted ASR |
| --- | ---: | ---: |
| unprotected | 0 | 0.875 |
| Stage43 | 0 | 0.875 |
| Stage44 | 0 | 0.750 |
| Stage45 | 0 | 0.750 |

Stage44/45 的改善来自仍然存在的其他 clean candidates 对恶意证据进行稀释，而不是发现并移除 Natural Bridge。如果整个可信池都为空，这种补证收益也不存在。

当前没有完成 0% 覆盖率正式实验，因此只能推断完整无可信池结果会接近未恢复基线，不能把这一推断写成测量结果。

### 9.4 根本能力边界

在没有任何可信根时，系统可以发现异常、冲突、断链或证据不足，但通常无法仅凭一个同样可能被污染的 KG 确定哪条事实为真。此时合理目标应从“保证正确恢复”调整为：

- 限制未经验证证据的影响；
- 寻找多个独立来源或独立路径；
- 暴露不确定性；
- 证据不足时拒答。

---

## 10. 建议方向：信任自适应的双轨 LogicGuard

### 10.1 统一研究问题

建议把新方法定义为：

> 面对不完整信任条件，LogicGuard 如何根据证据可验证性，在可信恢复、结构修复和安全拒答之间自适应选择？

这比把两条线写成互不相关的两个系统更有研究凝聚力。

### 10.2 Trust Router

GraphRAG 检索后，先对每条 source/claim 分配状态：

| 状态 | 含义 | 默认动作 |
| --- | --- | --- |
| `verified` | 有可信版本且内容一致 | 保留 |
| `risky` | 与可信版本明确冲突 | 进入可信恢复线 |
| `recoverable` | 存在高置信可信候选 | 替换后复核 |
| `unverifiable` | 没有可信 counterpart | 进入结构一致性线 |
| `ambiguous` | 多个候选或来源冲突 | 结构检查、补证或拒答 |
| `unresolved` | 两条线都无法建立充分证据 | 安全拒答 |

必须首先把当前二元逻辑：

```text
safe / risky
```

改为至少三元逻辑：

```text
verified / risky / unverifiable
```

并把 `candidate=None → safe` 改为 `candidate=None → unverifiable`。

### 10.3 Track-R：可信恢复线

可命名为 `Trusted Recovery Track` 或 `Provenance-backed Recovery`。

复用并强化现有 Stage43–45：

1. 使用可信历史快照、签发记录或受保护副本做差异检测；
2. 识别实体、关系、日期、数值、地点和谓词漂移；
3. 对 risky source 执行可信替换；
4. 校验 recovery candidate 的 query relevance、实体身份和支持链一致性；
5. Stage44 补充缺失证据；
6. Stage45 仅在链路诊断缺失第二跳时触发。

该线可以报告真正的 `correct/wrong/none/ambiguous recovery`，不能只报告是否选择了 candidate。

### 10.4 Track-S：结构一致性线

可命名为 `Structural Consistency Guard` 或 `Hop-wise Structural Track`。

参考 HoG-GRAG，但需要针对 LogicPoison 增强：

1. 将 query 分解为有序 subqueries；
2. 在 retrieved subgraph 上逐跳生成候选和证据映射；
3. 检测 `H-Fail` 和 `H-Amb`；
4. 新增 `H-Unique-Unverified`，处理唯一但没有独立支持的候选；
5. 检查实体类型、实体身份、谓词、日期/数值和前后 hop 一致性；
6. 统计关系由多少独立 source 支持，防止同一注入文档衍生出的多个 text unit 被误当成多源支持；
7. 尝试全局 KG fallback、回溯和最小证据补充；
8. 如果只有一条无法验证的完整链，降低权重或拒答，而不是强制选择。

### 10.5 对 HoG-GRAG 假设的修正

HoG-GRAG 假设攻击主要注入恶意边而不删除 benign edges，所以正确路径仍可能存在于全局 KG。但 LogicPoison 会重写语料中的实体并重新建图，可能直接切断正确路径。

因此：

```text
retrieved subgraph 被污染
          +
用于 fallback 的 global KG 也被污染
```

Track-S 不能把“从全局图找到了候选”直接当作可信恢复。全局 KG fallback 只能提供结构候选，仍要结合来源独立性、关系一致性和拒答机制。

### 10.6 统一输出

建议每条最终证据携带透明元数据：

```json
{
  "source_id": "...",
  "trust_state": "verified",
  "defense_track": "trusted_recovery",
  "independent_support_count": 2,
  "risk_reasons": [],
  "recovery_confidence": 0.93
}
```

最终生成 prompt 应优先使用 verified evidence；unverifiable evidence 只能作为辅助；冲突未解决时不得输出高置信确定答案。

---

## 11. 推荐实验矩阵

### 11.1 可信池覆盖率扫描

```text
100% → 80% → 50% → 20% → 0%
```

覆盖率不能只随机删除 candidate。还应分别模拟：

- 污染前版本快照缺失；
- 新注入文档天然没有历史版本；
- 有 candidate 但候选碰撞；
- trusted source 自身发生供应链污染。

### 11.2 攻击集合

- official LogicPoison；
- GRAGPoison；
- `low_drift`；
- `candidate_collision`；
- `natural_bridge`；
- `unique_wrong_chain` / `hop_feasible_logicpoison`。

### 11.3 防御对照

```text
No Defense
Trusted Recovery Only
Structural Guard Only
Dual-Track LogicGuard
```

### 11.4 指标

- attempted / generated-valid / evaluation-valid；
- source exposure / target exposure；
- broad ASR / targeted ASR；
- detector precision / recall / FPR；
- `verified/risky/unverifiable` 比例；
- `H-Fail/H-Amb/H-Unique-Unverified` 比例；
- correct/wrong/none/ambiguous recovery；
- clean utility；
- abstention rate；
- prompt tokens、额外 LLM 调用和延迟；
- API/judge error rate。

预期的研究目标不是让 0% 可信覆盖时仍宣称完美恢复，而是证明：

```text
可信覆盖率高 → Track-R 提供精确恢复
可信覆盖率下降 → Track-S 接管更多 query
可信覆盖率为 0 → 降低 ASR，但允许拒答率上升
```

---

## 12. 推荐开发顺序

### P0：先建立完整攻击基线

1. 为长实验增加 checkpoint/resume、配置指纹、语料哈希和索引哈希；
2. 把 Stage47 成功攻击冻结为 corpus-level 版本；
3. 重新运行 official GraphRAG indexing 和 query；
4. 跟踪：语料 → entities/relations → community → retrieval/rank → prompt exposure → answer；
5. 原封不动运行 Stage43–45，得到 Stage48 基线后再改 detector。

### P1：修正当前可信恢复线

1. 实现三状态 trust model；
2. `candidate=None` 不再放行；
3. 增加 relation/claim/number/date/place/predicate consistency；
4. 增加 recovery integrity 检查；
5. 做可信池覆盖率扫描。

### P2：实现结构一致性线

1. query decomposition；
2. hop candidate/evidence trace；
3. `H-Fail/H-Amb`；
4. `H-Unique-Unverified`；
5. 回溯、全局 KG 候选和最小证据补充；
6. unresolved abstention。

### P3：双轨融合与扩大实验

1. Trust Router；
2. 统一证据状态和 prompt policy；
3. 加入公共攻击和 HoG-GRAG 对照；
4. HotpotQA 从当前少量自适应样本扩大到至少约20条定向 query；
5. 增加回答模型、随机种子和统计置信区间。

---

## 13. Stage43–47 统一可视化

本次同步以下文件：

- `artifacts/visualizations/Stage43-47_LogicGuard_统一可视化.html`
- `tools/generate_stage43_47_visualization.py`

HTML 是离线单文件，不依赖 CDN 或后端，直接用浏览器打开即可。内容包括：

- Stage43–47 防御流水线；
- Stage43 detector 规则和阈值；
- Stage43 recovery、Stage44 enrichment、Stage45 chain completion；
- Stage46 固定 LogicPoison 跨数据集结果；
- `75 → 35 → 21 → 19` 攻击有效性漏斗；
- low drift、candidate collision、natural bridge 三类攻击；
- 数据集/总体切换、代表样例和边界说明。

重新生成：

```bash
python3 tools/generate_stage43_47_visualization.py
```

浏览：

```bash
xdg-open artifacts/visualizations/Stage43-47_LogicGuard_统一可视化.html
```

可视化从以下冻结轻量产物读取数据：

- `artifacts/results/stage46_cross_dataset_answer_final_summary.csv`
- `artifacts/results/stage47_adaptive_attack_final_summary.csv`
- `artifacts/results/stage47_adaptive_attack_examples.jsonl`

当前 HTML 的 SHA-256：

```text
12e2df98e71b9c4a0262fa9d67ab1732b6ecbf4af1fae05c915e51812460c00f
```

注意：可视化呈现的是 Stage43–47 冻结实验结果，不代表已经完成 no-clean、完整 re-index 或双轨 LogicGuard 实验。

---

## 14. 建议主开发者优先确认的决策

1. 是否接受将论文主问题升级为“incomplete-trust / trust-adaptive GraphRAG defense”。
2. 可信根在目标部署中具体是什么：版本快照、签名文档、审核语料还是外部权威源。
3. Track-S 的目标是“尽量恢复”还是“风险检测＋必要时拒答”；建议选择后者，避免无可信证据时过度承诺。
4. 是否把 GRAGPoison 和 HoG-GRAG 纳入正式攻击/防御基线。
5. 是否先冻结 Stage48 完整 re-index 基线，再开始修改 Stage43 detector。
6. 是否把 `H-Unique-Unverified` 作为区别于 HoG-GRAG 的关键结构检测贡献之一。

如果上述方向得到确认，下一份实施文档应把 Stage48 拆成明确配置、数据产物、运行预算、checkpoint 和验收指标，避免继续只用阶段编号描述研究推进。
