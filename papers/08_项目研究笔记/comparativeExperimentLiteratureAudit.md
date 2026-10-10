# LogicGuard 大规模对比实验：文献、数据与公开资产审计

状态：`RESEARCH_PLAN_DRAFT_FOR_REVIEW`<br>
审计日期：2026-09-02<br>
执行状态：尚未启动公开攻击、LightRAG、外部防御、重新索引或付费实验<br>
适用范围：HotpotQA、MuSiQue、2WikiMultiHopQA；Microsoft GraphRAG、LightRAG

## Material passport

| 字段 | 内容 |
| --- | --- |
| 研究目的 | 在写代码和产生费用前，核清已有论文怎样做实验、哪些公开资产真的可复用，并据此确定 LogicGuard 的数据、攻击、防御、指标和执行门 |
| 本地事实源 | `F:\LogicGuard_project\logicguard`；禁止把 `.logicguard_remote_backup` 或外部仓库作为开发目录 |
| 文献范围 | 盘点 `papers_2025_06_to_2026_06` 的 41 篇 PDF 与 `logicguard_research_paper` 的 30 篇 PDF；对 10 篇最相关攻击/防御论文及其公开仓库做深审计 |
| 证据优先级 | 论文正文/附录 > 固定 commit 的官方代码与数据树 > 官方 README > 项目二手综述 |
| 计划性质 | 本文是供审核的研究与实施方案，不是已冻结预注册；获批后再形成 v1.1 预注册和机器执行表 |
| 本轮费用 | ¥0；未调用付费 API，未生成攻击，未建索引 |

## 1. 审计后的直接结论

1. 三个数据集和两个后端可以组成一套有研究价值的比较实验，但不能直接做成 `3 数据集 × 4 攻击 × 2 后端 × 全部防御` 的无差别全因子表。四类攻击的威胁目标、原生数据、分母和公开资产成熟度不同，强行混算会得到不可解释的平均值。
2. 主实验应分成两层：先做论文原生设置的**锚点复现**，证明 adapter 没有把方法改坏；再做相同 500-query 语料上的**跨数据集、跨后端可移植性比较**。原生结果与适配结果必须分表。
3. PoisonedRAG、LogicPoison、GRAGPoison 可构成 wrong-answer/logical-poisoning 主轨；BadRAG 是 trigger/backdoor 攻击，必须作为独立探索轨，不与前三者的 ASR 宏平均。
4. 公开资产通常只覆盖“原始干净集、论文处理集、攻击实例、完整污染语料/索引”中的一部分。当前没有任何一个攻击为本项目的三数据集、双后端矩阵同时提供可直接运行的完整 clean/poisoned index。
5. 主防御矩阵应保留无防御、两个廉价弱控制、一个通用强基线、一个 GraphRAG 专用强基线、LogicGuard 当前链、LogicGuard 完整方法和 oracle 上界。RAGuard、SDAG 等作为条件性扩展，不应在第一轮阻塞主结果。
6. 当前最先要做的不是运行攻击，而是冻结 asset passport、query split、攻击语义和 adapter fidelity tests。只有这些通过并经审核，才进入付费资格实验。

## 2. 怎样判断“官方数据可直接使用”

后续每个资产必须标明下列等级，不能只写“使用官方数据”：

| 等级 | 资产含义 | 是否足以直接跑防御比较 |
| --- | --- | --- |
| L1 | 数据集作者发布的原始 QA 数据/语料 | 否；还没有论文特定攻击 |
| L2 | 攻击论文发布的处理后 query/corpus/qrels | 否；可能只是攻击生成输入 |
| L3 | 攻击论文发布的 target、恶意文本或 changed-doc map | 部分；仍需组装污染语料并为目标后端重建索引 |
| L4 | 完整 clean/poisoned corpus 及可审计映射 | 可以重建索引，但仍不是可复用 index |
| L5 | 固定版本、完整配置、clean/poisoned index 与结果 | 最接近直接复现，但仍要验证后端/依赖版本 |

所有外部资产要保存 URL、commit/revision、许可证、文件 SHA-256、下载日期和本地只读镜像路径。README 声称包含 poisoned version 但文件树没有独立污染版本时，以文件树和生成代码为准。

## 3. 核心攻击论文怎样设计实验

### 3.1 PoisonedRAG

**论文路径。** 以 NQ、HotpotQA、MS-MARCO 为数据集；每个数据集选 100 个目标问题，使用 GPT-4 生成一个人工核查的错误目标答案。黑盒攻击把问题信息与错误答案组合成恶意文本，白盒版本使用 HotFlip；主设置每个目标问题注入 5 条恶意文本，检索 top-k 为 5。后端是 Contriever、Contriever-ms、ANCE 等稠密检索器，并跨多个回答模型评测。

**论文指标。** 主攻击终点是回答是否包含攻击者指定目标答案，即 targeted ASR；同时报告检索 precision/recall/F1、攻击查询次数和运行时间。

**公开资产。** 官方仓库在固定 commit `f660d72174f06b13fae5163ce656e7b235db858f` 下提供 BEIR 下载脚本，以及 NQ、HotpotQA、MS-MARCO 各 100 条目标问题的 target 和 5 条 `adv_texts`。这是 L3 攻击实例，不是完整污染语料或 GraphRAG index。

**与本项目的实际重合。** 官方 HotpotQA 100 条攻击实例与 `data/logicpoison_official/clean/hotpotqa/queries.jsonl` 的 500 条共同基准只有 **6 条 query ID 重合**。因此可把 6 条作为 golden contract cases，但不能把官方 100 条直接宣称为共同 500-query benchmark 的攻击集。MuSiQue、2WikiMultiHopQA 没有官方 PoisonedRAG 处理资产。

**采用决定。** 纳入 wrong-answer 主轨。HotpotQA 先用官方 6 条重合样本验证字段和目标语义，再按论文算法在冻结 validation/test query 上生成适配实例；MuSiQue、2Wiki 明确标注为 dataset port。不能把 port 后结果写成论文原生复现。

### 3.2 LogicPoison

**论文路径。** 使用 HotpotQA、MuSiQue、2WikiMultiHopQA，各 500 个 validation query；后端包括 Microsoft GraphRAG、HippoRAG2、GFM-RAG，并给出 Naive RAG 对照。攻击先识别 corpus-level 逻辑枢纽和 query-centric bridge entities，再在相同实体类型内做双射置换并重写语料；主设置针对 top 5% 实体。

**论文指标。** 主表中的 ASR 基本语义是 ground-truth answer 不再出现的 untargeted error，并辅以 LLM 语义判定；它不等同于 PoisonedRAG 的“命中攻击者指定错误答案”。因此本项目必须以 `clean-correct → attacked-wrong` 的 paired attack flip rate 为 LogicPoison 主终点，另报 clean/attacked EM/F1，不能伪造统一 targeted ASR。

**公开资产。** 官方仓库 commit `6699736681aa275e33a1d0cc32ef9b47ee17e632` 是项目当前本地基础版本；截至审计日上游 main 已加入 LogicPoison++，必须与原 LogicPoison 分开。官方 Hugging Face revision `8d2f7f5a357f9bb1572c17b62ebde5f75703885b` 只有每数据集一个 `corpus.jsonl`、`queries.jsonl`、`answers.jsonl` 和 qrels。官方代码把这些文件当作 `datasets/` 输入，并将污染结果写到 `results/poisoned_data/`，所以这些文件是 L2 处理后干净输入，不是单独发布的完整 poisoned corpus；dataset card 的笼统表述不能覆盖这一代码事实。

**本项目已有资产。** `data/logicpoison_official/clean` 和 `data/logicpoison_official/poisoned` 已有三数据集成对语料：HotpotQA 9,811 docs、MuSiQue 11,656 docs、2Wiki 6,119 docs，query 均为 500 条。但生成时的外部仓库当前存在用户修改：NER 从上游 `en_core_web_trf` 改为 `en_core_web_lg`，这会改变实体集合和替换映射；现有产物也没有把上游 diff/commit 固化进独立 manifest。因此它们是**项目既有适配资产**，不能再标成“官方预制污染数据”或论文严格复现。

**采用决定。** 纳入主轨。Microsoft GraphRAG 是原生系统锚点，LightRAG 是后端 port。获批后先审计已有 changed-doc、query integrity、语料 hash 和生成环境；若无法证明 paper fidelity，必须用只读固定上游副本在新 namespace 重建，而不能修改或覆盖 `external_repos/logicPoison`。

### 3.3 GraphRAG under Fire / GRAGPoison

**论文路径。** 原论文使用 Geographic、Medical、Cyber-security 和 MuSiQue，而不是 HotpotQA/2Wiki；每类约 300 个问题。系统包括 NaiveRAG、Microsoft GraphRAG、LightRAG 和 nano-GraphRAG。攻击者黑盒、KG-agnostic，通过跨 query 共用目标关系降低 QPP，再做 relation injection 与 relation enhancement。论文还用 PoisonedRAG 作为攻击对照。

**论文指标。** targeted/untargeted ASR、relation ASR、queries per poisoning text、tokens per query 和 clean accuracy。其重要实验思路是同时报告攻击效果和攻击效率，而不是只看错误率。

**公开资产与版本漂移。** 官方仓库 commit `316422f315748a903ae8f2e94e2bedbc66f84343` 只有一个公开数据目录 `misuque_3_black_shuffle_0601`。实际树包含 `question_multi_v3.json`、`test0_corpus.json`、settings、prompts、input 和 notebook；README 声称存在 filtered/output/cache 等文件，但当前树并不完整一致。仓库当前默认 `N_alpha=10`、约 400 words/恶意文本，也与论文中的短文本预算不一致，不能把仓库默认值直接当论文设置。

**与本项目的实际重合。** 公开 `question_multi_v3.json` 含 67 个 MuSiQue 问题，与项目 500-query MuSiQue 共同基准只有 **14 条 ID/问题文本精确重合**。它们可作 golden cases，不能支撑 100/300 的主估计。HotpotQA、2Wiki 没有官方 GRAGPoison 资产。

**采用决定。** 纳入 wrong-answer 主轨。MuSiQue × Microsoft GraphRAG/LightRAG 是论文原生锚点；HotpotQA、2Wiki 是明确的 dataset port。E0 要同时冻结“论文参数”和“代码参数”，主实验优先论文原设定，仓库新默认只作版本敏感性。

### 3.4 BadRAG

**论文路径。** BadRAG/TrojRAG 是语义 trigger 后门：攻击 passage 在带 trigger 的查询上被高概率检索，对普通查询保持低激活，再驱动拒答、情感操纵等 payload。原论文使用 NQ、MS-MARCO、SQuAD，生成任务使用 WikiASP；检索器为 Contriever、DPR、ANCE，生成模型包括 GPT-4、Claude-3-Opus、LLaMA-2-7B。主设置只注入 10 条恶意 passage，约占语料 0.04%。

**论文指标。** trigger retrieval success、clean false activation、拒答率、accuracy/response quality、ROUGE-2、情感方向；这些指标不等价于 factual targeted ASR。

**公开资产。** 截至 2026-09-02，没有从论文、作者主页、GitHub 搜索或 Papers With Code 找到可归因的官方代码/数据仓库。三个目标多跳数据集和两个 GraphRAG 后端均不是论文原生设置。

**采用决定。** 保留用户要求的 BadRAG，但放入独立 exploratory backdoor track。只有在 E0 完成 faithful reimplementation checklist，并在 development 上复现论文量级的 trigger retrieval/低 false activation 趋势后，才进入 validation；失败不阻塞三类 wrong-answer 主轨。

### 3.5 RAG Safety 的 KG triple injection

项目 P03 论文使用 WebQSP、ComplexWebQuestions 和显式 KG-RAG 后端，通过为多个错误答案注入短关系路径/三元组来误导 RoG、GCR、G-Retriever、SubgraphRAG。它说明“攻击图中的路径”可以独立于纯文本检索成立，但数据、知识表示和后端都不属于本项目的三数据集 text-to-graph 设置。它不进入 A1–A4 主矩阵，仅作为结构攻击相关工作与未来显式 KG sensitivity。

## 4. 核心防御论文怎样设计实验

### 4.1 HoG-GRAG

HoG-GRAG 在 HotpotQA、MuSiQue 上使用 Microsoft GraphRAG 与 LightRAG，按 hop 分解问题，检测污染诱发的不一致，再做局部裁剪和最小证据恢复。论文先从 clean-correct 且 attack-success 的池中筛出每设置 300 条 poisoned questions，另取 300 条 benign questions；因此高 ASR/TPR 是条件样本结果，不能与 attempted 分母直接比较。公开仓库 commit `b3197f5cb03b161ce4d29365ab73f1b3ed3adb02` 提供 detection、repair、trace analysis、evaluation、query paraphrase 和 PPL baseline 代码，但没有数据集和攻击生成器。

采用为 GraphRAG 专用强基线。HotpotQA/MuSiQue 属于原生数据；2Wiki 只有在 ordered-hop decomposition contract 通过后才能作为 port。为了公平，LogicGuard 主结果不能复用 HoG 的 clean-correct/attack-success 后筛选作为唯一分母，需同时保留 attempted 与 clean-correct 条件结果。

### 4.2 RAGDefender

RAGDefender 是 post-retrieval 通用防御，原论文使用 NQ、HotpotQA、MS-MARCO，攻击包括 PoisonedRAG、Tan et al. 和 GARAG，并与 RobustRAG、Discern-and-Answer 比较。它不增加 LLM 调用，适合作为跨后端的强通用基线。

官方仓库 commit `ba2a17efba165d45409114df2d70b030ade1e1b8` 有 artifacts、三项 reproducibility claims 和测试，但 v0.2.0 CHANGELOG 明确指出：package 默认 embedder 不是论文的 Stella；multi-hop concentration formula 计划在 v0.3.0 才改为论文 AND/median 形式；artifact 与 package 仍有两套实现。采用时必须走 paper artifact/pinned implementation，并做同输入 byte-equivalence 和 passage-order tests，不能直接 `pip install` 最新版后称为论文复现。

### 4.3 Query paraphrasing 与 PPL

LogicPoison、GraphRAG under Fire、HoG-GRAG 都使用或讨论了 query paraphrasing/PPL 类方法，并普遍发现效果有限。它们仍有价值，因为是便宜、易解释的 weak controls：若一个新防御只打赢它们而打不过强基线，研究产出仍不足。二者进入主矩阵，但在论文中明确标为 sanity controls，不包装成 state-of-the-art。

### 4.4 RAGuard、FilterRAG、SDAG 的位置

- **RAGuard**：在 NQ、MS-MARCO、HotpotQA 上用扩大检索集、perplexity 差和 query-text similarity 分位过滤，覆盖多类攻击和 adaptive attacks；未找到与论文对应的官方代码。适合作为获批后的纸面复现扩展，不作为第一轮必需基线。
- **FilterRAG/ML-FilterRAG**：主要针对 PoisonedRAG，并在受控的 `2 clean + 2 adversarial → top-2` 检索集合上训练/评测；监督数据和人为平衡上下文使它不适合直接代表真实 GraphRAG end-to-end 防御。保留在附录候选。
- **SDAG**：通过修改生成模型 sparse attention mask 防御，适合开源权重 LLM；Microsoft GraphRAG/LightRAG 若使用闭源回答 API，无法公平接入。只在后续 open-weight generator sensitivity 中运行。

## 5. 最终确定的数据集

### 5.1 共同主基准

共同主基准固定使用 LogicPoison 官方 Hugging Face revision 对应的处理后干净输入格式，因为它同时覆盖三数据集，且项目已有每数据集 500 query 和配套 qrels：

| 数据集 | 共同语料规模 | query | qrels 行数（含表头） | 原始官方来源 | 作用 |
| --- | ---: | ---: | ---: | --- | --- |
| HotpotQA | 9,811 docs | 500 | 1,001 | <https://hotpotqa.github.io/> | 2-hop、支持事实明确；PoisonedRAG/HoG 原生数据 |
| MuSiQue | 11,656 docs | 500 | 1,313 | <https://github.com/StonyBrookNLP/musique> | 2–4 hop；GRAGPoison/HoG 原生数据 |
| 2WikiMultiHopQA | 6,119 docs | 500 | 1,209 | <https://github.com/Alab-NII/2wikimultihop> | 多种 reasoning type；LogicPoison 原生但其他攻击多为 port |

三者都采用 `100 development / 100 validation / 300 locked test` 的确定性分层划分。分层至少考虑 hop count、question/reasoning type 和原始 query ID；同一 query 在所有攻击、后端和防御中保持相同 split。

### 5.2 原生锚点数据

共同主基准之外保留小型 paper-native anchor：PoisonedRAG 官方 HotpotQA 攻击实例、GRAGPoison 公开 MuSiQue workspace，以及 LogicPoison 论文原生 Microsoft GraphRAG 设置。anchor 的目的只是在开发集证明适配器保持论文语义，不与共同 benchmark 合并统计。

### 5.3 原始官方数据的角色

HotpotQA fullwiki、MuSiQue 官方 release、2Wiki 官方 release 用于许可证、字段和支持事实追溯，以及必要的外部有效性敏感性实验。它们不与共同处理语料混在同一主表，否则 corpus size、distractor 构成和检索难度会成为混杂因素。

## 6. 最终确定的攻击安排

| ID | 攻击 | 威胁轨 | 原生锚点 | 共同三数据集状态 | 主终点 |
| --- | --- | --- | --- | --- | --- |
| A1 | PoisonedRAG black-box | 指定错误答案注入 | HotpotQA，官方 6 条重合 golden cases | Hotpot 适配扩展；MuSiQue/2Wiki dataset port | targeted ASR / attempted |
| A2 | LogicPoison v1 | 逻辑拓扑/实体置换 | 三数据集 × Microsoft GraphRAG | Microsoft 原生；LightRAG backend port | clean-correct attack flip、EM/F1 drop |
| A3 | GRAGPoison | 关系注入与增强 | MuSiQue × 两后端，官方 14 条重合 golden cases | Hotpot/2Wiki dataset port | targeted/untargeted ASR、R-ASR、QPP、TPQ |
| A4 | BadRAG | trigger/backdoor | 无本项目原生锚点 | 三数据集均为 faithful reimplementation port | trigger retrieval、payload ASR、false activation |

Stage47/48 的 natural bridge、low drift、candidate collision 继续作为 A5 internal adaptive challenge，仅用于解释 LogicGuard 的已知盲区和做 white-box adaptive appendix，不冒充公开 baseline。

### 6.1 污染预算原则

不强行把本质不同的攻击压成一个预算。每个方法同时报告：

- `paper_native_budget`：复现论文原参数；
- `matched_budget`：按每个目标 query 的新增/修改 token、文档数和全语料修改比例形成共同资源包络；
- `budget_sensitivity`：至少一个低预算和一个高预算点，只有主设置成立后才运行。

LogicPoison 的全局文档重写、GRAGPoison 的跨 query 共享关系、PoisonedRAG 的每 query 追加文本和 BadRAG 的全局 trigger passage，不能只用“每 query 几篇文档”假装完全可比。主表报告各自 threat-native success；跨攻击综合只比较标准化 mitigation，不平均原始 ASR。

## 7. 最终确定的防御安排

| ID | 防御 | 定位 | 进入主排名 | 接入条件 |
| --- | --- | --- | --- | --- |
| D0 | No defense | 攻击基线 | 是 | 每个 attacked index 必须先完成 |
| D1 | Query paraphrasing | 廉价 weak control | 是 | 固定改写数、模型、温度；所有防御共享攻击输入 |
| D2 | PPL/PTI filtering | 廉价 weak detector | 是 | 阈值只在 validation 冻结；报告 clean FPR |
| D3 | RAGDefender | 通用强基线 | 是 | paper-faithful artifact、固定 embedder/formula、adapter tests 通过 |
| D4 | HoG-GRAG | GraphRAG 专用强基线 | 是 | Hotpot/MuSiQue 原生；2Wiki decomposition gate 通过后才加入 |
| D5 | LogicGuard Stage43–45 | 项目当前方法/消融参照 | 是 | 不修改现有阈值后先跑，避免 moving baseline |
| D6 | LogicGuard full dual-track | 拟议主方法 | 是 | provenance、claim consistency、path completeness、recovery integrity 均冻结 |
| D7 | Oracle clean recovery | 上界 | 否 | 可读 gold/clean mapping，必须与现实方法分表 |

RAGuard 作为 D8 optional paper reimplementation；SDAG 作为 D9 open-weight-only sensitivity。它们不阻塞 D0–D7 主矩阵。

## 8. 指标体系

### 8.1 攻击原生终点

| 威胁 | 主指标 | 不能替代主指标的诊断量 |
| --- | --- | --- |
| PoisonedRAG | attacker target 命中且 gold 未命中的 `targeted ASR / attempted` | `ASR / prompt-exposed` 只说明生成器服从性 |
| LogicPoison | 在 clean 回答正确的配对 query 中，attacked 回答转错的比例；同时报全体 EM/F1 drop | 单纯 ground-truth 缺失率不能解释原本就答错的 query |
| GRAGPoison | targeted/untargeted ASR / attempted，按配置分表 | R-ASR、QPP、TPQ 解释关系传播与攻击效率 |
| BadRAG | trigger retrieval、payload success、clean false activation | 拒答率、情感等只在对应 payload 子任务内解释 |

### 8.2 统一端到端漏斗

所有攻击至少保存：

`attempted → generation-valid → evaluation-valid → corpus-modified → index-included → graph-surfaced → retrieved → prompt-exposed → answered → threat-native-success`

同时报告 attempted 无条件分母和 clean-correct/prompt-exposed 条件诊断。未检索、未暴露是系统级攻击失败，但不是防御成功；只有同一攻击在 D0 成功、在防御下失败，才支持 paired mitigation。

### 8.3 防御、效用与结构指标

- 安全：paired attack-success 绝对差、相对 Attack Mitigation Rate、95% CI；
- 检测：precision、recall、FPR、AUPRC，避免只报 accuracy；
- 恢复：`correct / wrong / none / ambiguous` 四类互斥，另报 wrong-recovery rate；
- 答案效用：官方 EM、token F1、语义等价 judge；judge 不覆盖原始答案和透明规则；
- 支持链：support recall/F1、chain completeness、hop completeness、malicious source rank；
- 图传播：恶意 entity/relation/claim/community 是否进入图、被检索、进入最终 Prompt；
- 拒答与校准：abstention、answerability、错误拒答；
- 效率：索引时间、query latency、内存/显存峰值、LLM/embedding tokens、调用次数、人民币目录价；
- 隐蔽性：修改语料比例、文本相似度/流畅度、跨 query collateral damage。

### 8.4 统计规则

- 配对单位为 `(dataset, query_id, attack_instance, seed, system)`；同一单位跨 D0–D7 共享完全相同的 attacked corpus/index/context。
- 二元结果用 McNemar；比例给 Wilson 95% CI；EM/F1 和 paired effect 用 query-level bootstrap。
- 确认性多重比较用 Holm 校正，报告效应量和 CI，不只报 p 值。
- 先分数据集、攻击、后端报告，再给等权宏平均；BadRAG 不进入 wrong-answer 宏平均。
- 至少 10% locked-test 和全部 disputed judge cases 双人盲审，报告 Cohen's kappa。

## 9. 两层实验结构

### Layer A：论文原生锚点复现

目的：验证攻击/防御 adapter 没有改变方法定义。只在 development/golden cases 上运行，先通过字段、预算、输出、指标和趋势门。锚点包括：

1. PoisonedRAG 官方 HotpotQA 重合样本；
2. GRAGPoison 官方 MuSiQue 重合样本与论文参数；
3. LogicPoison 三数据集 × Microsoft GraphRAG 的固定 v1 流程；
4. HoG-GRAG 的 HotpotQA/MuSiQue hop trace；
5. RAGDefender 官方 artifact claim 与本项目 passage adapter 等价性。

golden case 很少，只用于 correctness contract，不产出论文 ASR 结论。

### Layer B：统一可移植性主比较

在共同 500-query 数据、相同 split、相同回答模型和污染语料上运行 Microsoft GraphRAG local search 与 LightRAG hybrid。先在 validation 资格门筛选攻击，再只对合格单元解封 locked test。论文中将每个单元标注 `native / backend-port / dataset-port / reimplementation`，使结果既可比较又不掩盖适配距离。

### 独立 backdoor track

BadRAG 使用 trigger/no-trigger 成对 query，独立 clean corpus control 和 payload-specific evaluator。该轨道可以产出“LogicGuard 对非事实型后门是否泛化”的扩展结论，但不能决定 wrong-answer 主假设是否通过。

## 10. 修订后的任务规划与决策门

### R0：文献与资产审计——本轮完成

- 完成核心论文实验设计、指标和资产等级对照；
- 核对六个官方仓库/数据源的固定 revision；
- 核出 PoisonedRAG 仅 6 条、GRAGPoison 仅 14 条与共同基准重合；
- 识别 LogicPoison 本地产物的 NER 改动与 provenance 缺口；
- 形成本文，暂停 v1.0 预注册执行。

### E0-A：资产资格与冻结——审核通过后的第一项开发任务

只做本地、无付费工作：

1. 为三原始数据、四攻击、两后端、两个外部强防御建立 `asset_manifest`；
2. 将上游代码复制到新的只读、commit-pinned vendor/cache 目录，不触碰现有 dirty `external_repos/logicPoison`；
3. 冻结 100/100/300 split，输出 query overlap、hop/type 分布与 leakage audit；
4. 将“论文参数、官方代码参数、本项目适配参数”做成逐字段 diff；
5. 为每个 attack/defense adapter 写 golden contract tests 和统一 schema；
6. 给 v1.1 预注册与机器表生成完整 cell 状态：native、port、blocked、optional。

**通过门：** 来源、许可证、commit、hash 完整；split 无重叠；gold/support 不进入攻击生成；所有 adapter 用保存的小 fixture 可重复运行；没有把 L2/L3 资产错报为 L4/L5。

### E0-B：本地 fidelity smoke

先用 6/14 条公开重合案例和本地 fixtures 验证字段、攻击语义、文档预算、评测器与后端导入，不运行批量 API。对 LogicPoison 旧产物重算 changed-doc/hash/provenance；若无法证明来源，标记 `legacy_adapted`，不得进入 paper-faithful anchor。

**通过门：** 输出语义与论文一致；targeted/untargeted/trigger 三类指标不会串线；相同输入得到相同 manifest 和结果。

### E1-A：付费原生锚点资格

获批后先跑小规模 paper-native anchors；每个单元固定尝试数和停止规则，不因结果补样。只有锚点趋势与论文语义相符，才解封对应 port。

### E1-B：validation 攻击资格

每数据集 100 validation query，D0 无防御。wrong-answer/logical 单元至少满足：evaluation-valid yield ≥60%、Prompt 暴露 ≥20%，并在自己的 threat-native endpoint 上达到预注册效应；BadRAG 单列 trigger retrieval、payload success 和 false activation 门。具体阈值在 v1.1 冻结，不能沿用统一 targeted ASR 粗暴覆盖 LogicPoison。

### E2：locked defense benchmark

只对 E1 合格的 `(dataset, system, attack)` 解封 300 locked test，并完全配对运行 D0–D7。先完成 context-only 漏斗和成本审计，再运行回答。test 开始后不得改阈值、Prompt、top-k、污染文本或方法实现。

### E3：扩展、消融和敏感性

主结论成立后再做 LogicGuard 组件消融、污染预算、GraphRAG global/community、LightRAG mode、RAGuard 和 open-weight SDAG。E3 不反向修改 E2。

## 11. 预计可以得到的结论

若按上述门执行，最终能区分而不是混在一起的结论包括：

1. 哪些攻击只在论文原生系统/数据上成立，哪些能跨 Microsoft GraphRAG 与 LightRAG、跨 2–4 hop 数据泛化；
2. 攻击失败发生在生成、入图、检索、Prompt 截断还是回答服从层，以及不同后端的瓶颈是否相同；
3. LogicGuard 相对弱控制、RAGDefender、HoG-GRAG 是否真正降低 paired attack success，而不是依赖拒答或 clean utility 损失；
4. trusted recovery 和 structural consistency 分别对哪类攻击有效，双轨组合是否具有互补性；
5. LogicGuard 是否只能防事实型 wrong-answer poisoning，还是对 trigger/backdoor 也有有限泛化；
6. 安全收益需要多少索引、查询、LLM 调用与人民币成本，是否具备实际部署价值。

若 E1 只有 LogicPoison/GRAGPoison 的少数原生单元成立，则论文应收缩为 GraphRAG logical/topological poisoning defense；若至少两类攻击跨两后端、两数据集成立且 D6 稳定优于 D3/D4，才足以支撑较强的通用 LogicGuard 结论。

## 12. 禁止事项

- 审核前不得启动 E0 代码实现、付费 API、攻击重生成、索引或 LightRAG 批运行；
- 不使用 `.logicguard_remote_backup`，不修改或覆盖 dirty `external_repos/logicPoison`；
- 不把官方处理后干净输入写成官方 poisoned corpus；
- 不把只有 6/14 条重合的公开攻击资产扩写成 100/300 条官方样本；
- 不把 LogicPoison untargeted error、PoisonedRAG targeted ASR 和 BadRAG trigger ASR 合成一个原始 ASR；
- 不按 clean-correct、检索成功或回答成功事后补样后只报告成功池；
- 不为不同防御重新生成或挑选攻击；
- 不把 oracle clean recovery 纳入现实方法排名；
- 不在 E1 前运行 E2，不在 E2 前宣称 LogicGuard 优于公开强基线。

## 13. 待审核的三个研究决定

1. 是否批准“原生锚点复现 + 统一可移植性比较 + 独立 BadRAG 轨”的三层结构；
2. 是否批准以 LogicPoison 处理后 500-query 干净语料作为共同主基准，原始官方 fullwiki/release 只做追溯和敏感性；
3. 是否批准 D0–D7 为第一轮主防御矩阵，RAGuard/SDAG 延后为可选扩展。

在这三项获得审核前，项目保持 `PLANNING_HOLD`。

## 14. 核心来源

### 本地论文

- `..\..\papers_2025_06_to_2026_06\P01_PoisonedRAG_Knowledge_Corruption_Attacks_to_Retrieval_Augmented_Generation.pdf`
- `..\..\papers_2025_06_to_2026_06\P03_RAG_Safety_Exploring_Knowledge_Poisoning_Attacks_to_Retrieval_Augmented_Generation.pdf`
- `..\..\papers_2025_06_to_2026_06\P09_Logical_Attacks_on_Graph_Retrieval_Augmented_Generation.pdf`
- `..\tmp\pdfs\GraphRAG_Under_Fire_2501.14050.pdf`
- `..\tmp\pdfs\BadRAG_2406.00083.pdf`
- `..\..\papers_2025_06_to_2026_06\P41_HoG-GRAG_Defense_Against_Knowledge_Poisoning_Attack_on_GraphRAG.pdf`
- `..\..\papers_2025_06_to_2026_06\P06_Secure_Retrieval_Augmented_Generation_against_Poisoning_Attacks.pdf`
- `..\..\papers_2025_06_to_2026_06\P04_Defending_Against_Knowledge_Poisoning_Attacks_During_Retrieval_Augmented_Generation.pdf`
- `..\..\logicguard_research_paper\15_2602.04711.pdf`

### 官方数据与代码

- PoisonedRAG：<https://github.com/sleeepeer/PoisonedRAG>
- LogicPoison：<https://github.com/Jord8061/logicPoison>
- LogicPoison 数据：<https://huggingface.co/datasets/Jord8061/datasets>
- GraphRAG under Fire：<https://github.com/JACKPURCELL/GraphRAG_Under_Fire>
- HoG-GRAG：<https://github.com/CyberScienceLab/HoG-GRAG>
- RAGDefender：<https://github.com/SecAI-Lab/RAGDefender>
- HotpotQA：<https://hotpotqa.github.io/>
- MuSiQue：<https://github.com/StonyBrookNLP/musique>
- 2WikiMultiHopQA：<https://github.com/Alab-NII/2wikimultihop>
- BadRAG 论文：<https://arxiv.org/abs/2406.00083>
