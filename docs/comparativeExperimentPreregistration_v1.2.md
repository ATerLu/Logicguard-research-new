# LogicGuard 比较实验协议修订 v1.2

> 执行进展补记（2026-09-10，非追溯性预注册）：WP2 的 A1/A3 两样本物化、真实 LightRAG clean trace 与双后端 0%-coverage 合同已通过。D3 发布工件 MiniLM 和库文档声明 Stella 的固定权重锚点均通过；前者存在顺序敏感，两者仍受论文公式差异限制。D4 官方工件因源码编译错误及提示词缺失保持 unavailable。该进展不改变指标或选样规则，也不代表完整 dev60、真实 trusted-pool retrieval 或效果资格。见 [D3/D4 资格报告](F:/LogicGuard_project/logicguard/docs/D3_D4_ExternalDefense_WP2_Qualification.md)。

_日期：2026-09-06；本地、带版本的执行前协议修订。_

本文不声称已经在第三方平台注册。已有实验结果不能被本文件追溯性地变成预注册结果。

---

## Material passport

| 字段 | 内容 |
| --- | --- |
| Origin skill | academic-research-suite / experiment-agent |
| Mode | 经用户批准的计划实施：WP1 本地审计与协议修订 |
| Evidence status | 历史产物与当前源码已核查；方法优势、独立确认集与统计功效未验证 |
| Fact source | `F:\LogicGuard_project\logicguard`，不使用备份目录开发 |
| Machine protocol | `configs/benchmark/comparison_v1_2_protocol.yaml` |
| Fidelity review | `configs/benchmark/comparison_v1_2_fidelity_review.yaml` |
| Audit output | `artifacts/benchmark/research_revision_v1_2/history_summary.json` |

本修订优先约束未来执行。v1.1 文档、split、readiness 和既有结果保持原样，作为历史记录。旧 readiness 的 `ready` 只代表当时工程门，不再自动授权正式比较。

## 1. 研究问题与允许声称的范围

核心问题收敛为：在可信证据覆盖不完整、攻击者可污染非可信语料时，来源、命题和路径联合验证能否在**相同信息与资源预算**下，减少错误恢复和污染回答，而非仅增加拒答？

三数据集 HotpotQA、MuSiQue、2WikiMultihopQA 和双后端 Microsoft GraphRAG、LightRAG 的目标保留。A1 PoisonedRAG、A2 LogicPoison、A3 GraphRAG under Fire/GRAGPoison 为主轨；A4 BadRAG 是触发器独立轨，不因其尚未复现而阻塞主轨的本地开发。内部 Stage47/48 攻击用于补充机制和后续自适应挑战，不代替公开攻击基线。

当前不能声称 LogicGuard 已优于外部强防御、已获得统计显著优势、已抵御针对最终 D6 的自适应攻击，或已完成三数据集正式测试。Stage48 Gate A 失败结论不变。历史 natural bridge `4/20` 是已选 evaluation-valid/indexed 子集内的 system 比例，不是全部 fixed-50 生成尝试的总体 ASR；`4/4` 仅为暴露条件比例。保留原数值与原实验语境。

## 2. 历史使用审计：事实、解释和限制

审计扫描 977 个 JSON/JSONL/CSV 文件，另外 20 个按规则排除，解析错误 0；产生 74,349 条去重到“文件×问题”的匹配证据，覆盖 1,500 个现有问题。文件清单及 SHA-256、首条记录位置、匹配方式均独立保存；不把答案复制进审计输出。

| 数据集 | 旧 development 中有执行/分析记录 | 旧 validation 中有记录 | 旧 locked test 中有记录 |
| --- | ---: | ---: | ---: |
| HotpotQA | 100/100 | 100/100 | 300/300 |
| MuSiQue | 100/100 | 100/100 | 300/300 |
| 2WikiMultihopQA | 100/100 | 100/100 | 300/300 |

三个数据集的 `outputs/retrieval/logicpoison_official/<dataset>/naive_bm25_clean_traces.jsonl` 各自直接包含全部 500 个对应问题。因此，这不是仅由模糊文件名分类得到的判断。此前只检查 Stage48 fixed-50 得到的 32/30 条 locked-test 重叠，只是历史使用范围的下界。

**解释边界：**有历史产物不等于研究者看过所有答案，更不等于已经证明调参泄漏。纯粹、盲态且不反馈开发的预计算不必然破坏独立性。但当前缺少访问、开发决策和结果隔离证据，不能把“split 互不相交”作为“从未接触的独立测试集”的证明。现有 500 问可继续用于开发、探索和明确标注的历史基准比较；不能认证为新的确认性 holdout。

扫描不覆盖其他机器、未配置的外部路径、所有运行日志或人工浏览历史；分类含文件名启发式，未找到记录也不能证明未使用。文档级、实体级、关系级及训练数据污染另行审查。

确认性测试前，从原始数据源建立新的候选问题池，核对本地及可获得的外部历史，按规范化问题、ID、近重复、来源/关系分组排除不适合的候选。冻结选择规则、dataset revision、hash 与访问记录，将评测标签从攻击/防御运行路径隔离。不能重新洗牌这 500 问并改名为 fresh test。原始数据不足时，缩小“独立确认”主张，而非隐瞒复用。

## 3. 攻击与防御实现保真度

| 方法 | 已观察到的实现 | 正式比较前缺口 |
| --- | --- | --- |
| A1 | question-only 单次 target/evidence 生成；官方 HotpotQA 100×5 asset/prefix 审计通过；1 个 existing pilot 已物化 | 完整 dev60 生成/物化；真实污染语料双后端效果资格 |
| A2 | query entity 阶段，返回 `phases_completed=1` | global 语料统计、类型约束映射、logic 阶段、语料改写及完整 provenance |
| A3 | 单 query 三阶段有界生成；官方 74-row artifact 审计通过；1 个 existing pilot 已物化为 8 occurrences/6 unique | 完整 dev60 跨问题共享关系物化；端到端资格；保留相邻去重/索引重叠 caveat |
| A4 | trigger/no-trigger 词法 surrogate | dense 优化与 payload 回答，不得标作论文负复现 |
| D3 RAGDefender | 固定 MiniLM 与 Stella 权重锚点通过；工件/包双路径一致，发现 MiniLM 顺序敏感和公式差异 | 以发布工件 MiniLM 为主、Stella 为敏感性；固定检索顺序上的真实 development 防御执行 |
| D4 HoG-GRAG | 官方工件核心源码无法编译且缺两个提示词 | 作者修正版或单独预注册 bounded reimplementation；不得标作论文负复现 |
| D5 旧 LogicGuard | Stage43–45 历史实现 | 作为旧方法对照；披露 clean candidate pool 信息优势 |
| D6 新 LogicGuard | 四组件研究设计 | 命题、来源、路径验证和恢复完整性门尚未实现 |

特别修正：A2 的 gold-free NER/staging 成功不代表完整 LogicPoison attack 完成。源码证据及版本 hash 见 fidelity review 与 history summary。A1/A3 在完成论文机制锚点前只能标为 inspired/adapted；不得用这些适配器的弱攻击结果替论文下结论。

攻击产物须记录 clean/poisoned corpus hash、变更文档、注入/修改方式、字数/token/文档预算、目标、seed、调用数和失败原因。预算应同时报告绝对量与相对语料比例，不假设不同攻击的自然预算单位等价。跨后端共享冻结攻击语料是迁移评估；若改为后端定制优化，须作为另一实验轨报告相同查询与优化预算。

## 4. 公平信息对照与可信根

主场景是攻击者不能修改的、覆盖不完整的 protected snapshot。可信标签在投毒前按来源组确定，不使用 gold/support/精确 clean mapping。当前公开数据上的可信元数据属于受控模拟，不是实际来源认证。

可信覆盖按来源组设置 100%、50%、20%、0%，同源 chunk 不得拆成独立可信来源。覆盖不足时输出 unverifiable/abstain，不允许将缺失候选当作安全证据。0% 覆盖用于识别边界，不要求方法凭空恢复真相。

必须增加 T0“只检索可信池”和 T1“普通可信扩检索/补证”，与 D6 使用相同池、候选访问权限、token、检索及模型调用预算。保留 D0 无防御、D3/D4 外部强防御、D5 旧方法、D7 精确映射 oracle；D7 只作上界，不进入公平排名。增加资源匹配的 text-RAG 对照，检验复杂图验证是否确有必要。

外部方法按论文原设定的结果与获得同等可信信息后的结果分面板报告，不能悄悄改变其算法仍称官方实现。比较应包括相近回答覆盖下的安全—效用关系；只靠拒答降低 ASR 不足以支持方法优势。

## 5. 指标、分母与缺失结果

主指标按威胁目标分开，不对四攻击原始 ASR 求统一平均。

- A1：`targeted success / fixed attempted`，generation-invalid 等机制失败仍保留在事前分母。有效或暴露条件比例仅作诊断。
- A2：在可评估的 clean-correct 配对问题上计算 attacked-wrong flip；clean 运行错误单列，不能默认为 clean-incorrect。另报全部问题的 clean/attacked EM、token F1。
- A3：在执行前冻结关系攻击终点及其单位（关系、问题或受影响问题集合），并单列 targeted/untargeted 答案指标。共享关系造成的问题相关性必须保留。
- A4：triggered payload success 与 no-trigger false activation 分开，检索命中不等于 payload 成功。

基础设施错误、usage 缺失和未完成回答为 unknown，不按“攻击失败”偷偷降低 ASR。报告成功数、固定分母、unknown 数及最坏/最好界。只有能从完整威胁终点确定的机制失败才能记为失败；回答被基础设施错误中断时不能仅凭未见命中记失败。未知 clean correctness 会影响 A2 可评估总体，必须披露。

防御配对净效果为“D0 成功→防御失败”减“D0 失败→防御成功”，不能只算阻断数而忽略防御诱发的新攻击成功。恢复正确/错误/未决同时按已执行恢复和全部计划问题报告。结果表另列 clean/attacked EM、F1、拒答、回答覆盖、延迟、模型调用、tokens 与费用。

`index_included`、`graph_surfaced`、`retrieved`、`prompt_exposed` 是独立过程诊断，不强制假定严格嵌套：原文 chunk 可能不经图关系路径直接进入检索。全系统 utility 必须评估所有计划问题，不只回答 target-exposed 子集。

新纯函数 `amendment_metrics.py` 已实现固定分母 unknown 边界、clean-correct flip 和配对净效果；其测试通过不等于这些统计已经接入全部旧 runner。

## 6. 执行路线与退出门

| 工作包 | 实际交付与通过条件 | 当前状态 |
| --- | --- | --- |
| WP1 纠偏与冻结 | 历史审计、v1.2 协议、保真度表、可信池对照、dev60 清单、指标测试 | 本轮完成 |
| WP2 小规模可执行基准 | A1–A3 真实污染语料；D3/D4 原设定锚点；T0/T1；clean baseline；双后端完整 trace 与成本保护 | 部分完成：攻击资产/两样本物化、T0/T1 合同、双后端 clean trace admission 与 D3 模型锚点已通过；D4 官方工件 fail-closed。完整 dev60、真实 trusted retrieval、D4 bounded port 与效果仍待完成 |
| WP3 方法与机制 | 实现 D6 四组件及失败处理；在 development 做组件消融、可信覆盖敏感性和错误恢复分析 | 待 WP2 支撑 |
| WP4 正式三数据集比较 | 新确认集、验证阶段资格、冻结方法/阈值/统计与预算，才解锁正式排名 | 未解锁 |
| WP5 学术收口 | 攻击适应冻结 D6、跨模型复核、盲审、配对统计、失败案例与可复现表格 | 未开始 |

WP2 从旧 development 每数据集确定性选 20 问，共 60 问；在已有 stratum 内按原 order_key 排序并轮转抽取，不读取 gold 或效果来选样。清单已写入新 namespace；不是新攻击生成结果。双后端对应 120 个 clean query-backend 配对；三攻击对应 360 个 attacked 配对。以上不是 API 调用数，也未包含方法数、覆盖档、重试或索引开销。

**接下来第一项开发任务：**冻结完整 dev60 A1/A2/A3 请求与 materialization 启动清单，包括模型 revision、最大调用/token/费用、unknown/in-flight 计账和停止规则；执行时不能看攻击成败后替换问题。D4 bounded reimplementation 另作进入外部防御效果比较前的阻塞项，不能修改或覆盖本轮官方工件失败证据。真实 trusted-pool retrieval 和 D6 equal-information 执行在相应后端索引准备后完成。

开始 A2 前核查：`src/logicguard/benchmark/attack_runner.py`、`execution_protocols.py`、`e1_preparation.py`、`vendor/upstream/LogicPoison/main.py` 及它实际导入的三阶段模块、现有 gold-free request 配置、attacker-safe split 和新 dev60 清单。开始公平对照前核查 `risk_aware_recovery.py`、`non_oracle_recovery.py` 的 clean pool 读入与候选缺失分支。

如果 T1 已达到 D6 的效果，不扩张优势主张：先通过消融判断新验证是否只增加成本。如果合格攻击在足够开发样本上仍没有可测影响，报告攻击资格不足，检查保真度/后端适配，不能补选高 ASR 测试问题制造排名。如果无可信根时性能下降，应作为边界结果。

## 7. 正式统计与费用决策

60 问仅回答工程可行性和机制问题，不保证功效。用 development 的配对不一致率和效应范围做正式样本量/最小可检测效应设计；之后冻结主对比 D6 与 development 选定的最强非 oracle 基线。报告效应量和区间，预设多重比较校正；二元配对的小不一致计数用 exact McNemar，连续指标用相应配对分析。共享问题、关系、索引与攻击 seed 的依赖分别说明，不把多次后端执行当独立样本。仅单次索引时，区间只能解释为对该固定索引条件下的不确定性，不能代表构图随机性。

盲态人工复核全部争议样本及至少 10% 正式测试样本；报告裁判分歧和敏感性分析。功效、聚类单元、主要对比数目和随机种子必须在正式测试前具体冻结，当前仍 pending。

原 ¥2,958.622–¥4,322.297 来自少量且选样不同的文档外推，是方案情景估计，不是置信区间或 hard cap。100 文档计量可以帮助校准，但不是科学上的必经门；先确定语料复用/索引隔离方案，并按请求预留最大费用、usage 回收核账、unknown 和在途请求保守计账、触顶停止。不能把复用攻击语料误做 clean/poisoned 索引交叉污染。

历史 E1 preparation 为 102 次付费请求、目录价估计 ¥0.403953（embedding tokens 含估算）。本轮 WP1 新 provider 调用、攻击生成与索引均为 0，新增费用 ¥0。既有付费授权保留，不另行要求重复授权；未冻结预算和执行资格是技术门，不是权限问题。

## 8. 解释质量检查

本轮只作审计和协议实施，没有进行新效果假设检验。检查原则：历史相关不推断人为调参因果；总体与分层不混淆；条件比例不替代总体比例；探索不冒充确认；技术 smoke 不冒充复现；适配失败不冒充论文失败；不以不显著证明等效；不以样本数替代功效；不忽略多重比较；不以拒答掩盖效用损失；不把预算投影写成统计区间。尚未验证的假设继续保留为假设。
