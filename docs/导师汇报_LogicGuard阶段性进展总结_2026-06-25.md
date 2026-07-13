# LogicGuard 阶段性进展总结汇报

汇报日期：2026-06-25  
项目方向：面向 RAG / GraphRAG 逻辑投毒的检测、防御与证据恢复  
当前状态：已形成可复现实验框架、完成多组检索层与回答层实验，Microsoft GraphRAG official 查询层仍处于小规模探索阶段。

## 一、汇报摘要

本项目围绕 RAG / GraphRAG 系统中的逻辑投毒问题开展研究。攻击者通过修改或注入看似相关的证据，使检索系统把污染证据送入大模型上下文，进而诱导模型输出错误答案。项目目前提出并实现了 LogicGuard 原型，核心思想是：先识别和隔离高风险证据，再通过 recovery 机制尽量恢复可用证据，避免简单过滤导致模型只能拒答。

截至目前，项目已经完成以下主要工作：

1. 完成 2WikiMultiHopQA、HotpotQA、MuSiQue 三个数据集的标准化处理，每个数据集固定 500 个 query，形成 1500 query 的本地研究子集。
2. 接入外部 LogicPoison 项目生成的 clean / poisoned corpus，并复制到 LogicGuard 项目数据目录中进行独立验证和实验，不直接修改外部项目文件。
3. 构建了早期 GraphRAG-style 轻量图检索代理、NaiveRAG BM25 基线、LogicPoison 检索层实验、回答层 LLM 实验和消融实验。
4. 初步接入 Microsoft GraphRAG official 组件，在小规模 2WikiMultiHopQA 子集上生成 documents、text_units、entities、relationships、communities、community_reports 等索引产物，并通过 official local query / LocalSearchMixedContext 进行查询层实验。
5. 完成 Stage21 的 50-query 中等规模诊断实验，证明在已知污染文档且存在 clean reference 的设定下，LogicGuard recovery 能在保持证据召回的同时将未恢复污染暴露降为 0。
6. 完成 Stage22 的 official GraphRAG query-ready 小规模实验，证明 query-layer 控制可以提升 official local context 的 gold support recall，但目前尚不能有效降低 changed support exposure。
7. 整理了中文实验报告、实验注册表、可复现实验命令清单和可视化页面，便于后续复现、汇报和论文写作。

当前最重要的阶段性结论是：**仅过滤污染证据可以显著降低安全风险，但会造成空上下文和拒答；recovery 是维持可用性的关键。** 但当前 recovery 很大程度依赖 clean reference 或可信参考源，尚不能直接声称适用于没有干净库、污染识别不完全、自适应攻击者存在的真实开放环境。

## 二、研究问题与威胁模型

### 2.1 研究问题

本项目关注的问题是：当 RAG / GraphRAG 系统的知识库或索引被逻辑污染后，如何在检索和回答阶段阻断污染证据影响，同时尽量恢复原有回答能力。

具体研究问题可以拆成三个层次：

1. 污染证据是否会稳定进入检索上下文？
2. LogicGuard 能否识别并过滤污染证据？
3. 过滤后能否通过 recovery 恢复可用证据，避免安全性提升但可用性崩溃？

### 2.2 攻击设定

项目目前覆盖了三类攻击或污染来源：

1. **早期自建模拟攻击**  
   包括 Bridge Injection 和 Entity Swap，用于快速验证逻辑投毒在图检索代理中的暴露现象。这类攻击模板较明显，适合作为原型阶段测试，不适合作为最终论文核心攻击。

2. **自然化 BridgeV2 / Answer-aware Bridge Injection**  
   在早期攻击基础上尝试让污染文本更自然，并面向最终答案影响进行构造，用于观察 LLM 回答层是否会受污染上下文影响。

3. **LogicPoison official poisoned corpus**  
   当前更重要的攻击来源。该语料来自外部 LogicPoison 项目生成结果，表现为对原有文档的同 ID 原位内容改写。LogicGuard 项目将其复制到本地 `data/logicpoison_official` 下进行验证和实验。

### 2.3 防御者假设

当前实验中存在不同强度的防御者假设：

1. **强假设**：知道哪些文档发生了 changed / poisoned，并且有 clean reference 可用于替换。
2. **中等假设**：没有直接 oracle 替换，但可以从可信 clean corpus 中重新检索候选证据。
3. **后续目标设定**：没有完整 clean corpus，污染识别不完全，需要依赖多路径检索、图结构一致性、证据冗余和风险评分进行 recovery。

当前最成熟的实验仍处于第一类和第二类设定之间，因此结论需要谨慎表述。

## 三、LogicGuard 方法设计

LogicGuard 当前可以概括为三阶段流程：风险识别、证据恢复、回答控制。

### 3.1 阶段一：风险识别与证据 Guard

风险识别阶段的目标是判断哪些证据不应直接进入 LLM 上下文。当前已经实现或实验过的信号包括：

1. **Provenance 信号**  
   关注证据来源是否异常，例如新增文档、异常来源、攻击注入片段等。早期自建 Bridge Injection 中 provenance 对新增桥接证据较有效。

2. **Content Integrity 信号**  
   关注同一 doc_id 的内容是否发生改写。LogicPoison official poisoned corpus 主要是同 ID 原位改写，因此 content integrity 对这类攻击更关键。

3. **Support Consistency / Gold Support 对齐信号**  
   用于评估检索结果是否覆盖原本应支持答案的文档。该信号当前主要用于实验评估和诊断，距离真实无 gold 场景还有差距。

4. **Graph / Entity 异常信号**  
   在 Microsoft GraphRAG 查询层中，关注 query-to-entity mapping 是否偏移、是否召回异常实体簇、是否需要 include / exclude 某些实体。

Guard 的基本策略是：对高风险证据降权、过滤或从上下文中移除。实验显示，仅过滤可以显著降低污染暴露，但经常造成空上下文或拒答。

### 3.2 阶段二：Recovery 证据恢复

Recovery 是 LogicGuard 当前最重要的设计。其作用不是让模型“纠正污染文本”，而是在污染证据不能直接使用时，找回可替代的可信证据。

当前实现过三类 recovery：

1. **Oracle clean-reference recovery**  
   已知污染 doc_id 后，直接用 clean corpus 中同一 doc_id 的干净版本替换污染版本。这是 Stage21 中效果最清晰的设定。

2. **Non-oracle BM25 trusted recovery**  
   不直接使用 oracle 替换，而是从可信语料中重新检索候选证据。Stage8 结果显示，该方案保留了大部分 oracle recovery 收益，但仍依赖可信 clean corpus。

3. **Official GraphRAG context 后 recovery**  
   在 Microsoft GraphRAG official local context 导出后，对 sources 层证据进行 Guard 和 clean-reference recovery。Stage20 回答层实验显示，recovery 可以明显提升回答正确率，但样本规模仍很小。

需要强调的是，当前 recovery 的强结果依赖 clean reference。因此，在论文表述中应写为：

> 在已知污染文档且存在可信参考版本的设定下，LogicGuard recovery 能恢复证据召回并降低未恢复污染暴露。

不应写为：

> LogicGuard 在真实开放环境下保证污染暴露为 0。

后续应将 recovery 升级为 uncertainty-aware evidence recovery，即在没有完美干净库时，通过多源检索、图结构一致性验证、跨检索器投票、实体关系约束和无法确认时拒答来恢复证据。

### 3.3 阶段三：回答控制与 Judge 评估

回答控制阶段将过滤或恢复后的上下文送入 LLM，并使用自动 Judge 对回答进行评估。当前使用过的模型包括 qwen3.7-plus、deepseek-v4-flash，以及 qwen-plus 作为 Judge。

回答层关注以下指标：

1. `is_correct`：回答是否命中 gold answer。
2. `is_abstained`：模型是否拒答或输出 UNKNOWN。
3. `is_incorrect`：模型是否给出非拒答错误答案。
4. `judge_label`：Judge 给出的 correct / partial / wrong / abstained 判断。

回答层实验显示：guarded 条件通常能降低错误输出，但经常导致 100% 拒答；recovered 条件能恢复部分正确回答，是安全性和可用性之间更有价值的折中。

### 3.4 Microsoft GraphRAG 查询层扩展

除传统检索后处理外，项目还探索了把 LogicGuard 接入 Microsoft GraphRAG official local query 层。当前做法包括：

1. 使用 Microsoft GraphRAG 官方索引产物，如 entities、relationships、text_units、community_reports。
2. 使用 official `api.local_search` 或 `LocalSearchMixedContext` 生成 context。
3. 在 query-layer 控制 include_entity_names 和 exclude_entity_names。
4. 比较 mixed baseline、budget expansion、title seeding、entity rerank、cluster suppression 和 full_query_guard。

这部分目前属于探索性实验。它证明了 LogicGuard 可以影响 official GraphRAG 的上下文构建，但尚未在 official query 层完成成熟的污染隔离和 recovery。

## 四、数据集与实验资产

### 4.1 数据集使用情况

当前主实验使用三个多跳问答数据集的研究子集：

| 数据集 | query 数 | clean corpus 文档数 | poisoned corpus 文档数 | 当前用途 |
| --- | ---: | ---: | ---: | --- |
| 2WikiMultiHopQA | 500 | 6119 | 6119 | 主实验与 Microsoft GraphRAG 接入 |
| HotpotQA | 500 | 9811 | 9811 | 多数据集检索和回答层验证 |
| MuSiQue | 500 | 11656 | 11656 | 多数据集检索和回答层验证 |

需要说明：当前并未使用原始数据集的全部 split 和全部语料，而是每个数据集固定 500 query 的研究子集。该设计便于可复现和成本控制，但论文最终若追求更强说服力，应扩大数据规模或明确说明研究子集构造规则。

### 4.2 LogicPoison 资产接入

LogicPoison official clean / poisoned corpus 已复制到 LogicGuard 项目下，并完成字段对齐验证。当前实验不直接修改外部 LogicPoison 项目目录，而是在 LogicGuard 内部数据目录进行读取和实验。

主要路径包括：

- `data/logicpoison_official/clean`
- `data/logicpoison_official/poisoned`
- `outputs/attacks/logicpoison_official`

### 4.3 Microsoft GraphRAG 索引资产

当前最重要的 Microsoft GraphRAG query-ready workspace 是：

`outputs/ms_graphrag/2wikimultihopqa/stage10_debug50_poisoned_query_ready/output`

该 workspace 产物包括：

| 索引文件 | 记录数 | 含义 |
| --- | ---: | --- |
| `documents.parquet` | 120 | 输入文档 |
| `text_units.parquet` | 120 | 文本单元 |
| `entities.parquet` | 165 | 抽取实体 |
| `relationships.parquet` | 984 | 抽取关系 |
| `communities.parquet` | 38 | 图社区 |
| `community_reports.parquet` | 38 | 社区报告 |

这说明项目确实跑通了小规模 Microsoft GraphRAG 的实体抽取、关系抽取、社区发现和 community report 生成。但这仍不是全量、生产级 Microsoft GraphRAG 实验。

## 五、已完成实验与结果

### 5.1 多数据集标准化与轻量图检索

项目首先完成了三数据集标准化，并构建了早期 GraphRAG-style 轻量图检索代理。该代理不是 Microsoft GraphRAG official，而是基于实体重叠和图结构的本地检索模拟，用于快速验证攻击和防御原型。

轻量图检索 clean baseline 的 gold recall@10 分别为：

| 数据集 | gold recall@10 |
| --- | ---: |
| 2WikiMultiHopQA | 0.4585 |
| HotpotQA | 0.4050 |
| MuSiQue | 0.2595 |

结果说明：轻量图检索可以运行，但召回能力有限，不足以作为最终 GraphRAG 论文实验的唯一基础。

### 5.2 早期模拟攻击实验

早期 Bridge Injection 和 Entity Swap 实验覆盖三数据集 500 query。结果显示：

| 攻击 | 2WikiMultiHopQA | HotpotQA | MuSiQue | 解释 |
| --- | ---: | ---: | ---: | --- |
| Bridge exposure | 1.0000 | 1.0000 | 0.9475 | 新增桥接证据几乎总能进入当前图代理检索 |
| Entity Swap exposure | 0.0949 | 0.2842 | 0.0763 | 原位实体替换的暴露率较低，跨数据集差异明显 |

该结果对方法原型有帮助，但攻击模板较明显，不能作为最终安全论文的核心攻击证据。

### 5.3 LogicPoison official 检索层影响

LogicPoison official poisoned corpus 的检索层实验显示，污染文档能够稳定进入检索结果。

关键结果：

- changed-doc retrieval = 1.0000。
- BM25 poisoned gold recall 分别约为 0.649、0.706、0.321。
- changed-gold exposure 分别约为 0.930、0.912、0.662。

解释：污染证据并非偶然出现，而是能够稳定被检索系统召回，因此具有真实防御价值。

### 5.4 LogicGuard 检索层防御与消融

检索层防御实验表明：

1. Content integrity 对 LogicPoison 这类同 ID 改写攻击最关键。
2. Provenance 对新增文档类攻击更有效。
3. 仅过滤可以降低 changed exposure，但可能造成上下文为空。
4. 加入 recovery 后可以恢复 gold support recall。

消融结果支持目前设计：provenance 与 content integrity 覆盖不同攻击面，组合使用比单独使用更合理。

### 5.5 回答层 LLM 实验

#### Stage6：BM25 检索下三数据集回答层实验

实验覆盖三数据集，每个数据集 20 query，两个回答模型，共 60 query、480 条回答结果。

主要结论：

| 条件 | 现象 |
| --- | --- |
| clean | 可用性基线，仍存在模型拒答和部分错误 |
| poisoned | 正确率下降，错误非拒答上升 |
| guarded | 错误基本被阻断，但全部拒答 |
| recovered | 可用性接近 clean，错误率显著低于 poisoned |

根据实验注册表中的综合指标：

- clean Utility = 0.4667。
- poisoned Utility = 0.1167，错误非拒答率 = 0.2667。
- guarded 错误为 0，但全拒答。
- recovered Utility = 0.4750，错误率 = 0.0417。

解释：过滤本身能保证安全，但可用性很差；recovery 能恢复接近 clean 的回答能力。

#### Stage7：Graph surrogate 检索下回答层实验

Stage7 使用 graph surrogate 检索。结果显示：

- poisoned 错误非拒答率 = 0.1833。
- recovered 错误非拒答率降至 0.0250。
- recovered Utility = 0.3083。

解释：LogicGuard 在图代理下仍能降低错误输出，但可用性受到图代理召回能力限制。

#### Stage8：Non-oracle BM25 recovery

Stage8 尝试非 oracle recovery，即不直接使用 oracle doc-id 替换，而从可信语料中重新检索恢复证据。

结果：

- non-oracle recovered Utility = 0.4083。
- 错误非拒答率 = 0.0583。
- 效果低于 oracle recovery 的 Utility = 0.4750，但保留了大部分收益。

解释：从 oracle clean replacement 转向更现实的 trusted retrieval recovery 是可行方向，但仍依赖可信 clean corpus。

### 5.6 Microsoft GraphRAG official 接入实验

项目已完成 Microsoft GraphRAG 小规模接入，但需要明确：这不是完整生产级 GraphRAG 全流程。

当前接入包括：

1. 将 LogicGuard 数据转换为 Microsoft GraphRAG workspace 输入文本。
2. 跑通 query-ready workflow。
3. 生成 entities、relationships、communities、community_reports。
4. 使用 official CLI 的 basic / local / global query 做早期 smoke test。
5. 使用 official Python `api.local_search` 和 `LocalSearchMixedContext` 导出 local context。
6. 在 official context 后接入 LogicGuard Guard 和 Recovery。

早期 minimal workflow 能生成实体、关系、社区和 embedding，但缺少 `community_reports.parquet`。后续 query-ready workflow 补齐了 `create_community_reports`，因此可以支持 official local query。

### 5.7 Stage20：Microsoft GraphRAG query-layer 实验

Stage20 在 5 query、12 篇 support-only 文档的小图上，对 official LocalSearchMixedContext 做 query-layer 消融。

检索层结果：

| 方法 | gold support recall | changed support exposure | context recall failure |
| --- | ---: | ---: | ---: |
| mixed_baseline | 0.2000 | 0.2000 | 4 |
| all_entities_baseline | 1.0000 | 1.0000 | 0 |
| title_seeding | 1.0000 | 1.0000 | 0 |
| cluster_suppression | 1.0000 | 1.0000 | 0 |
| full_query_guard | 1.0000 | 1.0000 | 0 |

回答层结果：

| 条件 | 结果 |
| --- | --- |
| poisoned | 2/5 正确，3/5 错误 |
| guarded | 4/5 拒答，安全但可用性低 |
| recovered | 4/5 严格正确 |

解释：在小图中，query-layer 可以修复召回失败；recovery 对回答有明显帮助。但该实验样本极小，且 support-only 图过于理想，不能作为最终主结论。

### 5.8 Stage21：50-query 中等规模诊断

Stage21 是当前最清晰的中等规模结果。它使用 Microsoft GraphRAG minimal indexed artifacts 中的 documents / text_units，并在其上做可审计 BM25 / title ranking、Guard 和 Recovery 诊断。

Top-10 结果如下：

| 方法 | gold recall | changed exposure | empty context rate | recovered evidence |
| --- | ---: | ---: | ---: | ---: |
| poisoned_bm25 | 0.8050 | 1.0000 | 0.0000 | 0.0000 |
| title_boosted_poisoned | 0.8050 | 1.0000 | 0.0000 | 0.0000 |
| guarded_filter | 0.0250 | 0.0000 | 0.7200 | 0.0000 |
| recovered_by_doc_id | 0.8050 | 0.0000 | 0.0000 | 9.6200 |
| clean_bm25_reference | 0.7900 | 0.0000 | 0.0000 | 0.0000 |

该结果说明：

1. 污染检索能保持较高 gold recall，但污染暴露为 1.0000，风险极高。
2. Guard 能将污染暴露降为 0，但 gold recall 几乎归零，且 72% 查询出现空上下文。
3. Recovery 能把 gold recall 恢复到 0.8050，同时将未恢复污染暴露保持为 0。

这是当前支持 LogicGuard recovery 机制最有力的结果之一。但该实验仍依赖 clean reference，且使用的是可审计排名层，不等同于完整 official LocalSearchMixedContext。

### 5.9 Stage22：official GraphRAG query-ready 5-query 实验

Stage22 使用 query-ready 的 poisoned debug50 workspace。该 workspace 包含：

- documents：120
- text_units：120
- entities：165
- relationships：984
- communities：38
- community_reports：38

Stage22 对 official local query 层进行 5-query 实验。

主要结果：

| 方法 | gold support recall | changed support exposure | source count |
| --- | ---: | ---: | ---: |
| mixed_baseline | 0.4000 | 0.4000 | 27.0000 |
| budget_expansion | 1.0000 | 1.0000 | 95.8000 |
| title_seeding | 0.9000 | 0.9000 | 28.0000 |
| cluster_suppression | 0.5000 | 0.5000 | 24.0000 |
| full_query_guard | 0.9000 | 0.9000 | 25.8000 |

解释：

1. Query-layer seeding 能提升 gold support recall。
2. 但 changed support exposure 也同步升高，说明召回正确证据的同时仍召回了污染证据。
3. 当前 query-layer Guard 尚未实现真正的污染隔离和 recovery。
4. Microsoft GraphRAG official 查询层目前仍是探索性结果，而不是成熟主实验。

## 六、当前可支持的阶段性结论

### 6.1 证据较强的结论

1. LogicPoison 的污染证据能够稳定进入检索结果，检索层防御是必要的。
2. 仅过滤污染证据可以降低安全风险，但会导致严重拒答或空上下文。
3. Recovery 是 LogicGuard 的核心贡献点，能显著改善过滤后的可用性。
4. Provenance 和 content integrity 信号具有互补性，分别覆盖新增证据攻击和同 ID 改写攻击。
5. 在 BM25 / graph surrogate / Stage21 中等规模诊断中，LogicGuard 均体现出“过滤降低污染暴露、恢复改善可用性”的趋势。

### 6.2 证据中等或探索性的结论

1. Microsoft GraphRAG official 接入已经工程跑通，但仍是小规模、诊断性实验。
2. Query-layer entity control 可以改善 official local context 的 gold support recall。
3. 当前 GraphRAG query-layer 防御还不能有效降低 changed support exposure。
4. official GraphRAG 层的 recovery 尚未成熟，需要继续开发。

### 6.3 目前不能过度声称的结论

1. 不能声称 LogicGuard 在真实开放环境下保证污染暴露为 0。
2. 不能声称当前 Microsoft GraphRAG 实验已经是生产级完整 GraphRAG 评测。
3. 不能声称 current recovery 不依赖 clean corpus。
4. 不能声称已经覆盖自适应攻击。
5. 不能把早期自建 Bridge Injection / Entity Swap 的结果作为最终论文核心攻击证明。

## 七、当前主要缺陷

### 7.1 Recovery 仍依赖 clean reference

目前最强结果来自 clean-reference recovery，即用干净版本替换污染证据。这对证明机制有效有价值，但防御假设偏强。真实场景下往往没有完整干净库，也不一定知道哪些文档被污染。

后续需要研究：

1. 无干净库时如何 recovery。
2. 污染识别不完全时如何做风险感知恢复。
3. 无法确认时如何安全拒答。

### 7.2 缺少自适应攻击

当前攻击大多是固定模板或外部 LogicPoison corpus。尚未系统设计 defense-aware 自适应攻击。安全论文中，攻击者应至少知道防御大方向，并尝试绕过：

1. 避开明显异常实体。
2. 分散污染到多个文档。
3. 模仿正常文体。
4. 使用别名、缩写、同名实体。
5. 微调关系而非明显替换答案。

### 7.3 检索基线还不够现代

目前最完整的是 BM25 和 graph surrogate。还缺少：

1. Dense vector retrieval。
2. BM25 + dense hybrid retrieval。
3. Cross-encoder reranker。
4. 更接近真实 RAG 系统的多阶段召回与重排流程。

如果最终论文要面向 RAG 安全，建议补齐至少一个现代 hybrid retrieval baseline。

### 7.4 Microsoft GraphRAG 实验规模不足

当前 Microsoft GraphRAG official 实验已经跑通小规模索引和查询，但存在限制：

1. 主要集中在 2WikiMultiHopQA。
2. official query-layer 主要是 1-query / 5-query / 50-query 诊断。
3. 部分实验使用 support-only 小图。
4. full workflow 中某些重步骤曾因模型兼容或耗时问题卡住，因此采用 query-ready 子流程。

后续若要把 Microsoft GraphRAG 作为论文主实验对象，需要进一步扩大规模并稳定完整流程。

### 7.5 评估指标需要统一解释

当前项目已经形成多个阶段指标，但部分指标容易混淆。例如：

- `changed exposure` 是上下文层污染暴露，不等于攻击成功率。
- `is_poisoned` 或错误非拒答更接近回答层攻击效果。
- `gold recall` 高不一定安全，因为召回的可能是污染版本。
- `guarded` 安全但常常拒答，不能只看污染暴露。

后续论文写作中需要把指标分为检索层、安全层和回答层三类，并统一命名。

## 八、后续推进计划

建议后续按六个阶段推进。

### 阶段 A：方法边界与论文问题重定义

目标：把当前项目从“做了很多实验”整理成一个清晰研究问题。

建议聚焦表述：

> 面向 RAG / GraphRAG 逻辑投毒，研究一种风险感知的证据过滤与恢复框架，在降低污染证据暴露的同时缓解过滤导致的可用性损失。

本阶段产出：

1. 明确 threat model。
2. 明确 defense assumptions。
3. 明确当前 clean-reference recovery 是上界设定。
4. 明确后续要提出 recovery 2.0。

### 阶段 B：补齐现代 RAG 检索基线

目标：避免论文被质疑“只有 BM25 和简化图代理”。

建议补充：

1. BM25 baseline。
2. Dense embedding retrieval。
3. BM25 + dense hybrid retrieval。
4. 可选 reranker。

产出：

1. 三数据集 500-query 检索层结果。
2. clean / poisoned / guarded / recovered 四条件对比。
3. 不同检索器下的 changed exposure 与 gold recall 对比。

### 阶段 C：Recovery 2.0

目标：降低对 clean reference 的依赖。

设计方向：

1. 多路径候选池：BM25、dense、GraphRAG local、entity neighbors、community reports。
2. 风险评分：来源异常、内容异常、图结构矛盾、单路径孤立召回等。
3. 证据一致性验证：多个证据是否支持同一实体关系链。
4. 恢复策略：替换、降权、扩大检索、拒答。
5. 无法恢复时输出 UNKNOWN，而不是强行回答。

产出：

1. `RiskScorer`、`CandidatePool`、`EvidenceVerifier`、`RecoveryPolicy` 模块。
2. clean-free 或 weak-clean recovery 实验。
3. 与 oracle recovery / non-oracle recovery 的差距分析。

### 阶段 D：自适应攻击实验

目标：走出自圆其说困境。

建议设计三类自适应攻击：

1. Stealth Bridge：不再使用明显异常桥接实体。
2. Distributed Poisoning：把污染分散到多个 support 和 distractor 文档。
3. Entity Alias Attack：利用别名、缩写、同名实体绕过实体匹配。

产出：

1. 攻击生成脚本。
2. 攻击强度分级。
3. LogicGuard 在非自适应和自适应攻击下的性能对比。

### 阶段 E：Microsoft GraphRAG official 实验增强

目标：从小规模 official GraphRAG 接入走向更严谨的 GraphRAG 实验。

建议：

1. 稳定 query-ready workflow。
2. 尝试恢复或替代完整 workflow 中卡住的重步骤。
3. 从 5 query 扩到 20、50 query official local context。
4. 增加 distractor 文档，不只使用 support-only 小图。
5. 在 official context 内实现 sources-level recovery。

产出：

1. official GraphRAG local query 检索矩阵。
2. official GraphRAG query-layer Guard + Recovery。
3. GraphRAG 层污染暴露与回答层效果对齐。

### 阶段 F：论文实验矩阵与写作

目标：形成可写论文的实验结构。

建议主表：

1. Clean / Poisoned / Guarded / Recovered 四条件。
2. BM25 / Dense / Hybrid / GraphRAG official local 四检索器。
3. 非自适应 / 自适应两类攻击。
4. 检索层指标、上下文安全指标、回答层指标。

建议主要图：

1. LogicGuard 方法流程图。
2. 过滤与 recovery 的安全-可用性权衡图。
3. 不同检索器的 changed exposure 对比。
4. Recovery 机制的 evidence replacement 示例图。
5. 自适应攻击下性能退化曲线。

## 九、近期建议优先级

如果近期目标是向导师汇报并争取下一步方向认可，建议按以下优先级推进：

1. **优先级 1：明确论文贡献边界**  
   把当前结果定位为“证据过滤 + recovery 的框架原型”，不要过度承诺真实开放环境安全性。

2. **优先级 2：补齐 Recovery 2.0 设计**  
   回答“没有干净库怎么办”的核心质疑。这是当前项目最关键的理论和方法缺口。

3. **优先级 3：补齐 dense / hybrid retrieval baseline**  
   提升 RAG 系统真实性，避免 BM25-only 质疑。

4. **优先级 4：设计自适应攻击**  
   提升安全论文说服力，避免攻防流程看起来循环论证。

5. **优先级 5：扩大 Microsoft GraphRAG official 实验**  
   继续推进 official local query 层，但短期不应把它作为唯一主线，因为成本和不稳定性较高。

## 十、向导师汇报时建议强调的内容

建议重点讲三点：

1. **问题价值**  
   逻辑投毒不是简单 prompt injection，而是污染证据进入检索上下文的问题。GraphRAG 因为存在实体、关系和社区摘要，可能产生更复杂的污染传播路径。

2. **当前核心发现**  
   过滤可以降低污染暴露，但会造成拒答；recovery 是维持可用性的关键。Stage21 50-query 结果非常清晰地体现了这一点。

3. **后续关键挑战**  
   当前 recovery 依赖 clean reference，下一步要研究无干净库、污染识别不完全和自适应攻击下的风险感知 recovery。

## 十一、附件：关键文件索引

### 项目总览与记录

- `docs/项目总览与路线图.md`
- `outputs/reports/实验结果总报告.md`
- `docs/实验注册表.csv`
- `docs/可复现实验命令清单.md`
- `docs/开发记录.md`

### Stage21 50-query 诊断

- `outputs/ms_graphrag_query/stage21_medium_summary.csv`
- `outputs/ms_graphrag_query/stage21_medium_metrics.csv`
- `outputs/ms_graphrag_query/stage21_medium_evidence.jsonl`

### Stage22 official GraphRAG query-ready

- `outputs/ms_graphrag_query/stage22_poisoned5_query_guard_summary.csv`
- `outputs/ms_graphrag_query/stage22_poisoned5_query_guard_metrics.csv`
- `outputs/ms_graphrag_query/stage22_poisoned5_query_guard_contexts_full_query_guard.jsonl`

### Microsoft GraphRAG 索引产物

- `outputs/ms_graphrag/2wikimultihopqa/stage10_debug50_poisoned_query_ready/output`
- `outputs/ms_graphrag/2wikimultihopqa/stage14_local_defense_5_poisoned_query_ready/output`

### 可视化页面

- `outputs/visualizations/00_索引_中文可视化说明.html`
- `outputs/visualizations/01_总览_Stage21_50问防御效果.html`
- `outputs/visualizations/03_对比_Stage22_官方GraphRAG查询层.html`
- `outputs/visualizations/05_总流程_LogicGuard攻防流程.html`
- `outputs/visualizations/08_恢复图_Stage21证据替换效果.html`

## 十二、总体判断

LogicGuard 当前已经不是单纯想法，而是具备完整数据、代码、实验和可复现记录的研究原型。最扎实的结果来自 LogicPoison official corpus、BM25 / graph surrogate 回答层实验，以及 Stage21 的 50-query recovery 诊断。这些结果可以支持一个明确的阶段性结论：**在已知污染和可信恢复源设定下，LogicGuard 能显著降低污染证据影响，并通过 recovery 缓解过滤导致的可用性损失。**

但是，距离高水平论文仍有明显差距。最重要的缺口不是继续堆更多同类实验，而是把 recovery 从 clean-reference replacement 升级为更现实的 uncertainty-aware evidence recovery，并引入现代 hybrid retrieval、自适应攻击和更稳定的 Microsoft GraphRAG official 实验。

因此，下一阶段不宜盲目扩大所有实验，而应围绕“无干净库时如何恢复可信证据”这一核心问题集中推进。只要 Recovery 2.0 和自适应攻击验证能够补齐，LogicGuard 才能从工程原型进一步上升为有论文贡献的方法框架。
