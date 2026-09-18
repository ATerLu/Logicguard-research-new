# LogicGuard 跨攻击、跨 GraphRAG 对比实验预注册 v1.0

草案日期：2026-09-01  
状态：`PRELIMINARY_DRAFT_PAUSED_FOR_REVIEW`；尚未运行公开攻击、LightRAG 或外部防御的锁定测试。2026-09-02 的论文与公开资产审计发现攻击终点、数据重合度和代码版本存在需要修订的问题，执行以 `docs/comparativeExperimentLiteratureAudit.md` 为先；本 v1.0 不再视为可直接执行的冻结协议。

## Material passport

| 字段 | 内容 |
| --- | --- |
| Origin skill | `academic-research-suite / experiment-agent` |
| Origin mode | `plan` |
| Verification status | `SUPERSEDED DRAFT`；由文献/资产审计提出 v1.1 修订，待用户审核后再冻结 |
| Version label | `logicguard_comparative_prereg_v1.0` |
| Freeze point | 在公开攻击/防御 adapter 实现、validation 运行和 locked test 解封之前 |
| Amendments | 任何数据、指标、阈值、样本数或方法替换必须先追加版本与理由；看过 test 结果后不得追溯修改 v1.0 |

## 1. 研究问题与预注册假设

**RQ-C1：** 四类公开攻击在相同数据、污染预算和回答模型下，能否跨 Microsoft GraphRAG 与 LightRAG 形成可复现的 corpus-to-answer 攻击链？

**RQ-C2：** LogicGuard 相对无防御、项目内部旧方法、GraphRAG 专用防御与通用 RAG 投毒防御，能否降低系统级攻击成功率，同时控制 clean utility、错误恢复和拒答代价？

预注册假设如下：

- **H1（攻击现实性）**：至少两类 wrong-answer 攻击在两个后端、至少两个数据集上同时达到 Prompt 暴露率不低于 20% 且 system targeted ASR 不低于 10%。
- **H2（主要安全效应）**：完整 LogicGuard 相对无防御使 paired system targeted ASR 绝对下降至少 10 个百分点或相对下降至少 30%。
- **H3（恢复完整性）**：完整 LogicGuard 相对当前 Stage43 将 wrong recovery 至少降低 50%。
- **H4（效用约束）**：相对同后端 clean/no-defense，完整 LogicGuard 的 clean EM 绝对下降不超过 5 个百分点，abstention 绝对增加不超过 10 个百分点。

H2–H4 必须同时满足才通过方法价值门；只降低 ASR 但以大量错误恢复、拒答或 clean utility 崩溃换取，不算通过。

## 2. 冻结实验对象

### 2.1 数据与划分

使用项目已标准化的 HotpotQA、MuSiQue、2WikiMultihopQA 各 500 个 query。每个数据集按 hop group 分层，再以 `fingerprint_json({version: comparison-v1, dataset, query_id})` 排序，固定划分为：

| split | 每数据集 query 数 | 用途 | 是否允许调参 |
| --- | ---: | --- | --- |
| development | 100 | adapter、字段映射、单元测试、参数可运行性 | 允许，但必须留痕 |
| validation | 100 | 攻击资格门、一次性防御阈值选择 | 仅按预注册网格 |
| locked test | 300 | 主结果、统计检验和论文表格 | 禁止调参或替换样本 |

三个 split 的 query ID、gold answer、support ID 和语料哈希在任何模型/API 调用前落盘。攻击生成阶段不得读取 gold answer、support ID、污染标签或 locked-test 结果；这些字段只在冻结攻击后由评估器连接。完整 clean corpus 用于索引，不把 support-only 小图当主实验。

### 2.2 RAG 后端

| ID | 后端 | 主查询模式 | 主实验边界 |
| --- | --- | --- | --- |
| S1 | Microsoft GraphRAG | official Local Search | 完整语料索引；固定 chunk、embedding、top-k、Prompt 和模型版本 |
| S2 | LightRAG | official hybrid mode | 使用同一 clean/poison corpus 与回答模型；冻结其原生图/向量配置 |

Microsoft GraphRAG global/community search 与 LightRAG 其他 query modes 只做敏感性分析，不并入主排名。不能为了让某一攻击或防御成功而为两个后端使用不同答案 Prompt 或不同污染文本。

### 2.3 攻击轨道

| ID | 攻击 | 轨道 | 主终点 | 接入规则 |
| --- | --- | --- | --- | --- |
| A1 | PoisonedRAG | wrong-answer poisoning | system targeted ASR | 优先官方实现；记录 commit 与原生/适配数据集 |
| A2 | LogicPoison | logical poisoning | clean-correct attack flip 与 untargeted error；不伪装成 PoisonedRAG targeted ASR | 官方 HF 仅提供生成输入；项目已有 clean/poisoned 成对资产属于本地适配产物，须先审计 NER 改动、commit 与 changed-doc 映射 |
| A3 | GraphRAG under Fire | graph-specific poisoning | system targeted ASR | 使用论文官方攻击实现；若仓库方法名为 GRAGPoison，保留别名和 commit |
| A4 | BadRAG | trigger/backdoor | trigger ASR、trigger retrieval、false activation | 独立轨道，不与 wrong-answer ASR 宏平均 |

Stage47/48 的 natural bridge、low drift、candidate collision 保留为内部 adaptive challenge/失败机制附录，不替代四类公开攻击，也不因新预注册而补跑原 fixed-50。

### 2.4 污染预算

主比较同时报告 paper-native budget 与 matched budget。matched 主预算为每个目标 query 最多 1 个污染文档、污染文本不超过对应 clean chunk 的 token 上限；敏感性预算为每目标 3 个污染文档。每个语料 variant 记录污染文档数、污染 token、语料占比、目标 query 数与跨 query 泄漏。所有防御复用完全相同的 attacked index/context 输入；不得为不同防御重新挑攻击。

### 2.5 防御方法

| ID | 方法 | 角色 | 是否参加现实方法排名 |
| --- | --- | --- | --- |
| D0 | no defense | 必需下界 | 是 |
| D1 | Stage43 risk recovery | 项目旧方法 | 是 |
| D2 | Stage43 + Stage44/45 | 项目旧完整链/内部消融 | 是 |
| D3 | HoG-GRAG | GraphRAG 专用外部防御 | 是 |
| D4 | RAGDefender | 通用 RAG 投毒外部防御 | 是 |
| D5 | LogicGuard full | 新方法：provenance + claim consistency + path completeness + recovery integrity | 是 |
| D6 | oracle clean recovery | 可达上界 | 否 |

D3/D4 只有在官方代码通过 E0 adapter tests 后才能以论文方法名报告。若 D4 官方实现因确定的兼容性问题无法复现，可在 locked test 解封前发布 amendment，将其替换为 CEG-RAG；不得把自写弱化版本仍称为原方法。

## 3. 固定漏斗与指标

所有 wrong-answer 攻击按下列漏斗逐层保存计数，分母不得混用：

`attempted → generation-valid → evaluation-valid → index-included → retrieved → prompt-exposed → answered → targeted-success`

### 3.1 主要指标

| 类别 | 指标 | 固定定义 |
| --- | --- | --- |
| 攻击 | `systemTargetedAsrAttempted` | targeted success / 全部固定 attempted query；主攻击现实性指标 |
| 防御 | `pairedTargetedAsr` | 同一 locked attack instance 在各防御下的 targeted success 比例 |
| 效用 | clean EM/F1 与 attacked EM/F1 | 同 query、同后端、同模型配对；同时报绝对变化 |
| 恢复 | correct / wrong / none | 三类互斥；`wrongRecoveryRate = wrong / recovery_attempted` |
| BadRAG | trigger ASR 与 false activation | 有 trigger 与无 trigger 配对计算，独立于 targeted-answer 轨道 |

### 3.2 次要与诊断指标

- generation/evaluation-valid yield、index inclusion、source/entity/relation/community surface inclusion；
- Hit@k、攻击 source rank、Prompt source/target 共暴露率、chain hit 与 chain completeness；
- detection precision/recall/FPR/AUPRC；answerability、abstention、普通错误率；
- 每 query 延迟、索引时间、显存/内存峰值、模型/embedding tokens、调用数和人民币目录价；
- clean/attacked 的 source count、Prompt 字符数与 token 数，定位截断混杂。

所有比例报告双侧 95% Wilson CI。条件 ASR（例如 targeted success / prompt-exposed）只作机制诊断，不能替代 attempted 或完整 paired 分母。

## 4. 执行阶段与决策门

### E0：Comparative Benchmark Readiness

先实现统一 schema、确定性 split、四种攻击 adapter、两个后端 adapter、D3/D4 adapter、artifact manifest 与本地 smoke tests。每个 adapter 必须保存官方来源、commit、许可证、原生设置与适配差异。E0 只允许 development split；任何付费批运行前必须通过 unit tests、ruff、配置 dry-run 和成本预估。

### E1：Public Attack Qualification

在 validation 的每个 `(dataset, system, attack)` 单元固定尝试 100 个 query，防御固定 D0。wrong-answer 单元同时满足以下条件才进入主防御比较：

1. attempted 固定为 100，generation/evaluation 失败全部保留；
2. evaluation-valid yield 不低于 60%；
3. Prompt 共暴露率不低于 20%；
4. system targeted ASR / attempted 不低于 10%；
5. 无 gold/support/changed-label 泄漏，且没有按检索或回答结果补样。

研究计划只有在至少两类 wrong-answer 攻击于两个后端、至少两个数据集通过 E1 后，才进入完整 E2。BadRAG 的独立资格门为 trigger retrieval 不低于 60%、trigger ASR 不低于 20%、clean false activation 不高于 5%。不通过的单元作为复现负结果报告，不计为防御胜利。

### E2：Locked Cross-System Defense Benchmark

只对 E1 合格攻击解封 locked test，每个合格 `(dataset, system, attack)` 使用 300 个 attempted query，并在 D0–D6 上运行完全配对比较。clean/no-attack control 对每个 `(dataset, system, defense)` 运行同一批 300 query。先完成 context-only 漏斗和成本门，再执行回答；test 一旦开始，不再修改阈值、Prompt、top-k、target 规则或方法实现。

### E3：消融与敏感性

只在 E2 的主结论成立后运行：去 provenance、去 claim consistency、去 path completeness、去 recovery integrity、filter-only、forced top-1 recovery；并检查污染预算 3、GraphRAG global/community 与 LightRAG mode 变化。E3 不得反向改写 E2 主结果。

## 5. 统计分析

- 配对单位固定为 `(dataset, query_id, attack, seed, system)`；同一单位跨防御共享攻击与回答配置。
- ASR、clean accuracy、wrong recovery、abstention 用 paired bootstrap 95% CI；二元配对差异用 McNemar 检验。
- EM/F1 的配对差值用 query-level bootstrap；不得把多个回答当独立样本。
- 多数据集、多攻击、多防御的确认性检验采用 Holm 校正，并报告绝对差、相对差和 CI，不只报告 p 值。
- 先分数据集/攻击/系统报告，再给等权 macro average；BadRAG 不进入 wrong-answer 宏平均。
- 至少 10% test 回答和全部 disputed judge case 由双人盲审；报告 Cohen's kappa、分歧数与裁决规则。

## 6. 停止、失败与禁止事项

- E0 或 E1 未通过时停止对应单元，不自动增加 query、seed、攻击预算或改 Prompt；如需重做，创建新版本和新 namespace。
- 不把 generation invalid、未检索或 Prompt 未暴露记为防御成功；它们保留在系统 attempted 分母并在漏斗中解释。
- 不使用 gold answer、support ID、changed labels 或精确 clean doc ID 进行在线攻击生成、检测、排序或恢复；D6 是唯一 oracle 例外且不排名。
- 不在 `.logicguard_remote_backup` 开发，不覆盖 Stage48 付费 workspace，不重新生成 Stage48 fixed-50 攻击。
- 不在 E1 前运行完整 E2，不在 E2 前宣称 LogicGuard 优于公开基线。

机器可读执行表 `docs/对比实验预注册表.csv` 同属 v1.0 暂停草案，当前不得据此启动 cell。待用户审核 `docs/comparativeExperimentLiteratureAudit.md` 中的分轨结构、共同数据源和 D0–D7 防御矩阵后，先发布 v1.1 amendment，再执行 **E0-A：资产 manifest、确定性 split、参数 diff 与 adapter contract tests**；该阶段本身不需要付费 API。
