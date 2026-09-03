# LogicGuard 近一年相关论文阅读清单（逐篇解读）

更新时间：2026-09-03。清单对应 [papper/](./papper/) 中的 40 篇 PDF；日期、venue、原始链接和文件校验信息以 [papers_manifest.tsv](./papers_manifest.tsv) 为准。阅读窗口为 2025-09-03—2026-09-03；早期 arXiv 在窗口内形成正式会议/期刊版本的论文按正式版本计入。

## 如何阅读这份清单

每篇均按“研究背景、目标问题、核心方法、实验设置、结果/结论分析、LogicGuard 启示”记录。攻击论文中的 ASR 是攻击者目标答案命中率，防御论文中的 ASR 通常是防御后仍被攻击者控制的比例；两者不能直接横向比较。综述和威胁模型论文没有自有的大规模实证结果，文中会明确注明。最终复现时应再次核对论文版本、代码 commit、模型 API 版本和数据许可。

## 1. GraphRAG under Fire（IEEE S&P 2026）

- 本地论文：[PDF](./papper/GraphRAG_under_Fire.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2501.14050)。
- 研究背景：GraphRAG 将文本抽成实体—关系图，并通过局部子图和社区摘要支持多跳问答。传统 PoisonedRAG 只在文本中写入“问题—错误答案”往往会被图抽取、社区聚合或多源证据稀释。
- 目标问题：在攻击者只能修改输入语料、不能改 GraphRAG 代码的条件下，能否让错误关系进入图、被检索并支配最终回答；同时比较普通 RAG 与 GraphRAG 的脆弱性差异。
- 核心方法：提出 GRAG-POISON。先注入竞争关系，再增加支持性实体和边提高端点度数、社区覆盖率，最后用 LLM 生成不超过 30 token 的自然文本；支持全局、多查询和 query-centric 关系攻击。
- 实验设置：MuSiQue、Geographic、Medical、Cyber-Security 四类多跳数据，每类约 300 个问题；比较 NaiveRAG、GraphRAG、LightRAG，并使用 GPT-4o/Llama-3.1-8B 生成毒文档。报告 ASR、关系 ASR（R-ASR）、clean accuracy、QPP、TPQ 和注入文本量。
- 结果/结论分析：GraphRAG 上 GRAG-POISON 明显超过 PoisonedRAG；例如 MuSiQue 的 GPT-4o ASR 为 89.2%（PoisonedRAG 57.6%），Cyber-Security 可达 96.4%。成功通常只需少量增强实体，说明“图结构稀释文本攻击”并不等于安全。
- LogicGuard 启示：把关系/路径变化、社区污染和答案错误分开计数；Stage48 必须真正重建 GraphRAG index，记录建图前后实体、边、社区和排名变化，而不能只做 post-retrieval 文本扰动。

## 2. Defense Against Knowledge Poisoning Attack on GraphRAG（HoG-GRAG，ACL 2026）

- 本地论文：[PDF](./papper/HoG-GRAG_ACL2026.pdf)；原始版本：[ACL PDF](https://aclanthology.org/2026.acl-short.47.pdf)。
- 研究背景：图语料被加入伪实体或伪关系后，GraphRAG 可能沿着错误 hop 完成看似连贯的推理；仅看文档相似度无法定位是哪一跳失效。
- 目标问题：不依赖污染标签和 gold support ID，如何发现多跳链中的“无候选”或“多候选”节点，并在回答前恢复一个紧凑、可信的子图。
- 核心方法：HoG-GRAG 将复杂问题拆成有序子查询，逐 hop 维护候选集合；集合为空标记 H-Fail，集合多于一个标记 H-Amb。遇到失败就回溯并补充最小缺失证据，最终仅把修复子图交给生成器。
- 实验设置：HotpotQA、MuSiQue；每个数据集 300 个 poisoned questions 和 300 个 benign questions。使用 Microsoft GraphRAG 与 LightRAG，毒文由 gpt-5-mini 生成。指标包括 H-Fail/H-Amb 的 TPR/FPR、Answer Match、Graph Compactness、Poison Removal Rate。
- 结果/结论分析：逐 hop 监控能够恢复大量被污染后丢失的答案，并显著减少伪实体/伪边；但终点 hop 的歧义消解仍依赖 tie-breaker，query decomposition 错误会传递到修复阶段。
- LogicGuard 启示：直接复用其“hop 级故障类型”作为审计标签；对 Stage44/45 的补证据操作增加链完整性、候选歧义率和修复后最短路径验证，不能只报告 source 被删掉多少。

## 3. LogicPoison: Logical Attacks on GraphRAG（ACL 2026）

- 本地论文：[PDF](./papper/LogicPoison_ACL2026.pdf)；原始版本：[ACL](https://aclanthology.org/2026.acl-long.252/)。
- 研究背景：GraphRAG 的实体/关系抽取会过滤简单的表面注入，但多跳逻辑连接仍可能被悄悄改写。语法流畅、实体类型正确的文本因此具有较强隐蔽性。
- 目标问题：攻击者不破坏实体类型和语言自然度，只替换关键实体或桥接关系，是否足以让图检索沿错误逻辑链回答。
- 核心方法：type-preserving entity swapping；包括全局 logic hub 和 query-centric logic bridge 两种攻击，使用循环置换/实体替换保持局部语义流畅，同时改变跨文档拓扑。
- 实验设置：HotpotQA、2WikiMultihopQA、MuSiQue；GraphRAG、GFM-RAG、HippoRAG2、NaiveRAG 等系统，top-k=10，目标实体比例约 5%；测试 GPT-4o-mini、Llama-3.1-8B、Qwen-3-32B。指标为 ASR、语义等价判定 ASR-G、逻辑链命中率和困惑度检测 AUC。
- 结果/结论分析：在多套 GraphRAG 上取得 SOTA 攻击效果；例如某些系统逻辑链命中率从约 80% 降至 5% 以下，ASR-G 仍可达约 95%。毒文 PPL AUC 约 0.57，接近随机，简单困惑度检测失效。
- LogicGuard 启示：现有 low_drift、candidate_collision、natural_bridge 三类自适应攻击正好对应其逻辑攻击面；评测须同时保存图路径、关系变化和最终答案，不能用文本异常分数替代逻辑审计。

## 4. Query-Efficient Agentic Graph Extraction Attacks on GraphRAG Systems（ACL 2026）

- 本地论文：[PDF](./papper/QueryEfficient_Agentic_Graph_Extraction_ACL2026.pdf)；原始版本：[ACL PDF](https://aclanthology.org/2026.acl-long.727.pdf)。
- 研究背景：GraphRAG 返回的不只是段落，还可能暴露实体、边、度数和社区信息。攻击者可以通过反复问答逐渐重建内部图，为后续定向污染提供侦察。
- 目标问题：在黑盒接口、有限查询预算下，能否高覆盖率地抽取隐藏图结构，并量化哪些节点/边最容易泄露。
- 核心方法：AGEA 是闭环 agent，包括自适应 query generator、正则抽取与 LLM filter、graph memory/query memory；用 epsilon-greedy 在探索未知区域和利用已知高价值节点之间切换，并同时维护 raw/filtered graph。
- 实验设置：医疗、农业和小说语料（Dragon Blood、Short Story Collection、20 本小说）；Microsoft GraphRAG 与 LightRAG；GPT-4o-mini 负责查询/抽取，DeepSeek-V3.1 作为受害生成器，text-embedding-3-large、top-k=10，预算 T=1000。与 TGTB、PIDE、CopyBreakRAG、IKEA 比较节点/边 coverage、precision 及度数/PageRank 加权泄露。
- 结果/结论分析：AGEA 在 1000 次查询内可恢复接近 90% 的节点和边，并保持较高 precision，明显超过固定模板和单轮提取基线；高中心性节点更容易先被重建。
- LogicGuard 启示：加入侦察阶段和查询预算维度；记录每次 query 造成的节点/边增量、中心性加权泄露和攻击迁移效果，并考虑限速、异常查询序列检测。

## 5. Exposing Privacy Risks in GraphRAG（ACL Findings 2026）

- 本地论文：[PDF](./papper/Exposing_Privacy_Risks_GraphRAG_ACL2026.pdf)；原始版本：[ACL PDF](https://aclanthology.org/2026.findings-acl.899.pdf)。
- 研究背景：传统 RAG 的隐私评估多关注原文片段泄露，而 GraphRAG 还会泄露结构化实体和关系；即使回答没有逐字复述，图结构仍可能暴露敏感事实。
- 目标问题：比较 Naive RAG、GraphRAG、LightRAG 在实体/关系抽取、提示词变化、检索窗口和查询次数变化下的泄露风险。
- 核心方法：设计 targeted/untargeted extraction queries，分别测实体泄露、关系泄露、上下文与源文本 ROUGE、重复率，并改变检索实体/关系数量和攻击者 query 数量。
- 实验设置：Enron Email 和 Healthcare/HealthCareMagic 语料；Naive RAG、GraphRAG、LightRAG；测试 Qwen-Turbo、DeepSeek-V3 等生成器，每种设置约 250 个攻击查询。
- 结果/结论分析：图系统可能降低原始文本 ROUGE，却提高结构化泄露；Healthcare 上 GraphRAG 的关系泄露最高约 72.8%。专门构造的命令式 C3 比泛化“请重复”提示更有效，增大检索窗口和查询次数会持续增加泄露。
- LogicGuard 启示：把 provenance、访问节点/边和回答内容分别记录；安全报告中增加“完整性攻击”和“机密性泄露”两条独立轴，不能因为答案正确就判定系统安全。

## 6. Bias Amplification in RAG: Poisoning Knowledge Retrieval to Steer LLMs（IEEE TDSC 2026）

- 本地论文：[PDF](./papper/Bias_Amplification_RAG_TDSC2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2506.11415)。
- 研究背景：检索污染不仅会制造事实错误，也会放大模型和语料中的群体偏见；传统 ASR/EM 看不出“答案仍正确但立场更歧视”的风险。
- 目标问题：攻击者能否通过操纵文档 embedding 和排名，持续把某一群体的偏见证据推入上下文，并衡量检索变化到公平性变化的因果链。
- 核心方法：BRRA（Biased Retrieval and Reward Attack）将目标偏见写入多目标 reward，投影到 embedding 子空间提升目标文档排名，并采用生成—评估—再注入的自强化循环。
- 实验设置：BBQ（性别、残障等维度）与 StereoSet（年龄、种族等维度）；测试多种开源/闭源 LLM 和 dense retriever。指标包括任务准确率、bias selection rate、bias variation、Bias Amplification Factor、Statistical Parity、Disparate Impact 和综合公平分数。
- 结果/结论分析：BRRA 可显著放大偏见；部分 Llama-3-8B BBQ 设置准确率从 0.80 降到 0.10。随机检索扰动或公平约束能缓解一部分风险，但效果依赖模型，单纯过滤检索结果并不稳定。
- LogicGuard 启示：在多跳事实任务外增加立场/公平性回归测试；保存“污染比例—排名—上下文占比—偏见输出”的中间量，避免只以 exact-match 衡量防御。

## 7. Who Taught the Lie? Responsibility Attribution for Poisoned Knowledge in RAG（IEEE S&P 2026）

- 本地论文：[PDF](./papper/Who_Taught_the_Lie_SandP2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2509.13772)。
- 研究背景：发现答案错误并不等于知道哪篇文档导致错误。生产系统需要在错误发生后定位责任 source、支持回滚和审计。
- 目标问题：在多个检索文档相互冲突时，能否区分“只是相关”与“真正导致错误生成”的文档，并在不知道污染标签的情况下给出稳定归因。
- 核心方法：RAGOrigin 组合 Expected Similarity、Semantic Consistency、Generation Contribution 三个信号，计算 responsibility score；用 z-score 与 K-means 两簇自动分出可疑文档，避免固定阈值。
- 实验设置：NQ、HotpotQA、MS MARCO、BoolQ、SQuAD；覆盖 PoisonedRAG 黑/白盒、Prompt Injection、HijackRAG、LIAR、Jamming、BadRAG、Phantom、AgentPoison 等 9 类攻击。E5-base-v2 top-k=5，GPT-4o-mini judge，Llama-3.1-8B proxy；与 Norm、PPL、SELF-RAG、RobustRAG、PFDNN、RAGForensics 比较。
- 结果/结论分析：RAGOrigin 在 NQ/HotpotQA 多种攻击上 DACC 常约 0.97–0.99，FPR/FNR 接近 0–0.03；对拒答/DoS 等单信号难处理攻击仍稳健，单查询约 1.3 秒。
- LogicGuard 启示：Stage43 输出 recovery candidate 的同时增加责任分数和 top-k 贡献；把“检测正确但恢复错误”单独作为 failure type，支持事后追溯而非只看最终 ASR。

## 8. RAG Security and Privacy: Formalizing the Threat Model and Attack Surface（IEEE ICDMW 2025）

- 本地论文：[PDF](./papper/RAG_Security_Privacy_Threat_Model_ICDMW2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2509.20324)。
- 研究背景：RAG 把知识从模型参数转移到外部库、向量索引和检索接口，已有工作常把通用 LLM 攻击与 RAG 特有风险混在一起。
- 目标问题：给出可复用的系统模型、攻击者权限和安全目标，覆盖文档存在性推断、内容重建、投毒、提示注入和差分隐私。
- 核心方法：形式化 q→embedding→vector DB→retrieval→augmented query→generation 流程；按黑盒、灰盒、白盒访问区分 adversary，并定义 membership inference、reconstruction、poisoning 等威胁。
- 实验设置：这是威胁模型/形式化论文，没有统一的大规模实证 benchmark 或可直接比较的 ASR 表格；主要用流程、定义和示例说明攻击面。
- 结果/结论分析：贡献在于明确“攻击者知道什么、能改什么、观察什么”和受保护资产；它不能证明某一防御的有效率，也不能替代真实实验。
- LogicGuard 启示：把该文转成实验注册表字段：access（black/gray/white）、knowledge（query/gold/index）、capability（inject/reindex/query）、objective（integrity/availability/confidentiality）和 observation。

## 9. Semantic Chameleon: Corpus-Dependent Poisoning Attacks and Defenses in RAG Systems（arXiv 2026）

- 本地论文：[PDF](./papper/Semantic_Chameleon_RAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2603.18034)。
- 研究背景：同一个梯度或语义攻击在不同语料密度、重复率和主题分布下表现差异很大；固定阈值的异常检测可能只在单一 corpus 有效。
- 目标问题：量化 corpus composition 对 poison retrieval、隐蔽性和混合检索迁移的影响，并寻找 corpus-dependent defense。
- 核心方法：提出 semantic chameleon 攻击；用语料中心漂移、TF-IDF 稀有度、co-retrieval clustering 和 temporal retrieval 做诊断；测试 BM25+vector 的归一化混合分数。
- 实验设置：Security SE 和 FEVER Wikipedia。阶段一每语料 9 个攻击（3 场景×3 次），阶段二 50 个攻击 top-5，阶段三混合权重 alpha=0.3/0.5/0.7，阶段四 15 个场景×5 个 LLM；FEVER 另取 2000 文档、25 个攻击比较 top-5/top-10。
- 结果/结论分析：Security SE co-retrieval 约 44.4%、stealth 66.7%、总体授权绕过 11.1%；FEVER 某些设置 co-retrieval 100% 但 stealth/总体成功为 0。混合检索通常压低攻击，但强烈依赖 corpus。
- LogicGuard 启示：大规模实验按 corpus density、实体长尾、重复率、chunk size 分层；报告每层置信区间，不能把单一索引上的阈值直接推广。

## 10. Eyes-on-Me: Scalable RAG Poisoning through Transferable Attention-Steering Attractors（arXiv 2025）

- 本地论文：[PDF](./papper/Eyes_on_Me_RAG_2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2510.00586)。
- 研究背景：以往文档投毒通常为每个目标 query 单独优化，攻击成本随问题数线性增加；真实攻击更可能复用一篇毒文档影响大量查询。
- 目标问题：能否把一个 attention-steering trigger 迁移到不同问题、retriever 和生成器，并在极低 poison ratio 下保持效果。
- 核心方法：将毒文拆为 Attention Attractor（把注意力吸到 payload）和 Focus Region（承载错误内容），并用 LLM-Gen 自动生成多样化诱导文本。
- 实验设置：MS MARCO、NQ、TriviaQA；每个数据集 5 个 trigger phrase，单文档注入，触发词频 0.5–1%，共 18 个 RAG 配置。覆盖 BCE/SFR 等 retriever、Llama-3.2-1B、Qwen2.5-0.5B、Gemma-2B，并迁移到 GPT-4o-mini/Gemini-2.5-Flash。指标 E2E-ASR、R-ASR、G-ASR。
- 结果/结论分析：EYES-ON-ME+LLM-Gen 平均 E2E-ASR 57.8%，显著高于 Phantom 14.6%；单独 attractor 31.2%。跨 held-out retriever 的迁移常达 96–100%，且只需一篇毒文档。
- LogicGuard 启示：新增“共享毒文档、多 query、跨模型迁移”协议；用 query-disjoint train/test 和 poison lifetime 统计验证 detector 是否只记住目标问题。

## 11. Influence Factors on RAG Poisoning（arXiv 2026）

- 本地论文：[PDF](./papper/Influence_Factors_RAG_Poisoning_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2606.12469)。
- 研究背景：攻击成功由 retriever、top-k、chunk、数据库数量和 generator 共同决定，单因素实验很容易把交互效应误认为方法收益。
- 目标问题：识别主效应和交互效应最大的 pipeline 因素，为可复现的防御比较提供统计设计。
- 核心方法：在 HotpotQA、MS MARCO 上做 full-factorial/OLS 分析，联合建模 dataset、retriever、top-k、chunk size/overlap、数据库数量、毒库数量和 generator。
- 实验设置：100 个语义相似问题对，约 432 个配置；比较 BM25、BGE dense 和 graph retriever。指标 Poison@k、Poison Rank、Score Margin、Abstention Rate、ASR、Correct Answer Rate。
- 结果/结论分析：retriever、dataset、top-k 是最强 retrieval 因素，增大 top-k 往往增加毒文暴露；BM25 暴露通常最高。毒库复制会放大 ASR，加入 clean DB 能缓解；dataset×retriever 交互约 0.1551，三阶交互约 0.1340。
- LogicGuard 启示：采用正交/分层实验而非只报默认点；固定随机种子并做 bootstrap/ANOVA，至少绘制 poison ratio×top-k×retriever 三维切片。

## 12. DenialRAG: Single-Document RAG Poisoning via Embedded Parametric Denial（arXiv 2026）

- 本地论文：[PDF](./papper/DenialRAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2608.02678)。
- 研究背景：多数投毒直接写错误答案；DenialRAG 发现“明确提到正确答案但否认它、再支持错误答案”更能对抗模型参数中的正确知识。
- 目标问题：单文档、低预算的 denial/DoS 污染能否在不同规模和厂商的模型上稳定让系统拒答或选择错误答案。
- 核心方法：围绕 query 生成短 passage，包含正确答案 X 的否认、攻击者答案 Y 及权威式解释，并用规则验证同时出现 Y 和 denial X。
- 实验设置：NQ、HotpotQA、MS MARCO，每个数据集 100 个 clean-correct query；8 个 LLM（Mistral-7B、Llama3.1-8B、GPT-4o-mini、GPT-5-mini、GPT-4o、GPT-5.2、GPT-5.5、DeepSeek-V4-flash），Contriever top-k=5。与 PoisonedRAG-N1、AuthChain、PIA-direct、CorruptRAG-AK 比较，并测试 paraphrase、InstructRAG、TrustRAG、AstuteRAG、RobustRAG。
- 结果/结论分析：在 Mistral 上 DenialRAG ASR 可达 NQ 89%、HotpotQA 94%、MS MARCO 86%；去掉 denial 组件平均下降约 17.1 个百分点。防御效果显著依赖模型，没有单一方法通吃。
- LogicGuard 启示：将 targeted wrong-answer、拒答、错误过度拒答分开计数；增加 clean query 的 availability/abstention 指标，避免把“没答攻击者答案”误判为安全。

## 13. When Context Bites: Detecting RAG Poisoning via Document-Level Attention Collapse（arXiv 2026）

- 本地论文：[PDF](./papper/When_Context_Bites_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2608.06947)。
- 研究背景：被污染的生成有时会表现为更高 token probability、更低采样分歧，形成“自信但错误”；输出困惑度因此是盲点。
- 目标问题：能否利用生成时对文档和 token 的注意力塌缩现象，在答案生成前定位毒文档，即使攻击没有完全成功。
- 核心方法：发现 Attention Collapse，提出 D-SCAN，联合 document-level attention density/entropy 和 token-level sparsity，使用轻量分类器输出文档风险。
- 实验设置：Llama-3.1-8B；2WikiMultihopQA、HotpotQA、MuSiQue；用 PoisonedRAG 替换两个 benign docs，比较 token probability、sampling consistency、PPL 等 zero-shot/vanilla detector。报告 AUC、F1，测试 N=1/2/4/8/16 采样。
- 结果/结论分析：D-SCAN 在 2Wiki、Hotpot、MuSiQue 的 AUC/F1 约为 0.934/0.858、0.833/0.778、0.906/0.836；去掉文档或 token 注意力分支均下降。模型在毒文上更“自信”，说明置信度不等于可靠性。
- LogicGuard 启示：可作为回答前 detector 基线，但需暴露 cross-attention/attention logit；必须跨 Qwen、Llama 和闭源模型校准，并重点盲测 low_drift、natural_bridge。

## 14. RAGPart & RAGMask: Retrieval-Stage Defenses Against Corpus Poisoning（arXiv 2025）

- 本地论文：[PDF](./papper/RAGPart_RAGMask_2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2512.24268)。
- 研究背景：很多防御依赖额外 LLM 判断，成本高且可能被 generator 误导；检索阶段的分区/掩蔽有机会在毒证据进入上下文前将其隔离。
- 目标问题：不改变生成器的前提下，能否通过片段组合和 token masking 降低 gradient-based 与可解释攻击的检索成功率。
- 核心方法：RAGPart 将文档切分成片段并组合嵌入、聚合检索；RAGMask 遮蔽高影响 token 并观察相似度变化；AdvRAGgen 作为可解释攻击基线。
- 实验设置：NQ（约 2,681,468 文档）和 FIQA（57,638 文档）；512 个训练 query，每题 3 个 irrelevant poison、10 个 golden docs；Contriever、ANCE、multilingual-E5、GTE-large。攻击包括 HotFlip、spread-out HotFlip、query-as-poison、AdvRAGgen；指标 poison retrieval ASR、gold retrieval SR、性能跌幅。
- 结果/结论分析：对 HotFlip 等梯度攻击，paraphrase/PPL 和 RAGPart/RAGMask 均有效；但前两者对 query-as-poison、AdvRAGgen 失效，RAGPart/RAGMask 更稳健，majority vote 比 intersection 更能保留效用。
- LogicGuard 启示：将其作为纯 retrieval-stage 对照，单独报告 poison exposure、gold recall、延迟和索引开销；不要把检索过滤成功等同于最终答案恢复。

## 15. BiRD: A Bidirectional Ranking Defense Mechanism for RAG（arXiv 2026）

- 本地论文：[PDF](./papper/BiRD_RAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2605.20123)。
- 研究背景：仅按 query→document 的相关性排序会把“语义像但不可信”的毒文排到前面，尤其在 candidate-collision 中容易发生。
- 目标问题：能否用文档之间的反向排序一致性恢复可信上下文，并在不调用额外大模型的情况下提升安全和准确率。
- 核心方法：正向 rank 计算 query-document relevance；把每个文档反过来当 query 形成 backward ranking，计算 context consistency，再与 relevance 合成为 composite score，阈值 epsilon 过滤。
- 实验设置：NQ、MS MARCO、HotpotQA；DPR、Contriever、ANCE；PoisonedRAG 与 prompt injection，默认污染数 m=5、top-k=20、epsilon=2.5。比较 VanillaRAG、RobustRAG、InstructRAG、ReliabilityRAG 等，指标 ASR、ACC、运行时。
- 结果/结论分析：表格中最高可减少约 87% ASR，摘要给出最高约 54% ASR 降幅和 56% ACC 提升，效用损失通常小于 5%；增加约 0.9 秒延迟。Spearman 组合优于 Jaccard/RBO 单一信号。
- LogicGuard 启示：把 BiRD 作为 reranker/过滤基线，观察其对 candidate-collision 的 precision–recall；记录 epsilon 敏感性，防止阈值只适配单一 corpus。

## 16. KEPo: Knowledge Evolution Poison on Graph-based RAG（arXiv 2026）

- 本地论文：[PDF](./papper/KEPo_Graph_RAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2603.11501)。
- 研究背景：图知识库会持续更新，攻击者可以伪造“旧事实→新事实”的演化链，使毒节点看起来像合理版本升级，而不是孤立异常。
- 目标问题：在 GraphRAG 的全局/局部检索中，时间上连贯的伪演化路径是否比普通文本注入更难发现；多目标毒子图连接是否会放大影响。
- 核心方法：先抽取原始答案实体/关系，再生成从原事实到毒终点的 temporal evolution path，加入背景叙述；多目标时用中心节点和答案相似度连接多个 poisoned sub-community。
- 实验设置：GraphRAG-Bench-Story、GraphRAG-Bench-Medical、MuSiQue，并在附录测试 HotpotQA；GraphRAG、LightRAG（global/local）、HippoRAG2、NaiveRAG。比较 PoisonedRAG、CorruptRAG、GRAG-Poison，使用 GPT-4o judge，报告 ASR 和 clean-conditioned CASR。
- 结果/结论分析：KEPo-single/multi 在各图系统上总体超过基线；local search 通常高于 global，multi-target 通过跨社区连接进一步提升。去掉“原事实—毒事实”路径后，ASR 明显下降，证明时间链是关键。
- LogicGuard 启示：Stage48 加入版本化 corpus、增量 reindex、时间到检测（TTD）和回滚实验；恢复时验证时间一致性及跨社区边，而不是只看当前文本相似度。

## 17. Knowledge Poisoning Attacks on Medical Multi-Modal RAG（M3Att，arXiv 2026）

- 本地论文：[PDF](./papper/M3Att_Medical_Multimodal_RAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2605.10253)。
- 研究背景：医学多模态 RAG 同时依赖图像和文本，显式错误可能被 LVLM 的医学先验纠正；但图像 embedding 高度聚集，又给 query-agnostic 触发提供了机会。
- 目标问题：在不知道未来用户 query、只能估计知识库分布的弱黑盒条件下，能否用少量视觉触发器和含蓄文本误导诊断、报告或分类。
- 核心方法：先对图像 embedding 聚类，选簇中心作为 proxy target，用受限 PGD（epsilon=16/255、500 步）做不可见视觉检索劫持；再用 GPT-5 以临床歧义编辑文本，采用 urgency suppression/defensive overreach 等渐进式错误表达。
- 实验设置：IU-XRay、MIMIC-CXR（VQA/报告生成）、CRC100k、MHIST、PCam（病理图像分类）；五个 LVLM、CLIP/BGE-VL/SigLIP 等 retriever，训练库与测试 query 实例级不重叠；比较 LIAR、w/o hijack、w/o injection，并测 Top-1/3/5 retrieval ASR、任务 utility、跨模态防御。
- 结果/结论分析：毒率低于 0.01% 时仍能劫持检索；毒率增至约 0.08% 时 ASR 接近 100%。完整 M3Att 相比 clean RAG 平均降低下游 utility 约 8.78%，且黑盒结果接近白盒；简单图像聚类、文本困惑度和图文一致性过滤仍可被绕过。
- LogicGuard 启示：预留 modality、触发器和跨模态一致性字段；即使当前只做文本 GraphRAG，也应在 threat matrix 中记录“图像/文本/结构属性混合污染”作为未来迁移测试。

## 18. Defending Retrieval-Augmented Intrusion Detection Against Knowledge Poisoning and Prompt Injection（arXiv 2026）

- 本地论文：[PDF](./papper/Defending_RAG_Intrusion_Detection_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2608.08100)。
- 研究背景：RAG-IDS 需要从网络流量检索相似 incident report 并用自然语言解释；知识库污染会把攻击流量重标为 benign，prompt injection 则直接改变分类/解释。
- 目标问题：在极端类别不平衡和高攻击率下，分层防御是否能恢复分类质量，同时控制误报和解释层注入。
- 核心方法：RAG-IDS 使用 BGE-M3+FAISS 检索、LECC/soft reranking、推理与响应代理；D1/D2/D3 分别处理检索污染、上下文/提示和输出约束，强调高精度 ML 前置门。
- 实验设置：CIC-UNSW-NB15（约 354 万 flows、10 类），对比 RF、XGBoost、CNN-LSTM 与 RAG；CEXP02–CEXP08 覆盖 clean、不同 poison rate、label flip 和单/多文档 prompt injection，三随机种子，主要指标 macro-F1、per-class F1、FPR、恢复率 R。
- 结果/结论分析：RAG 在 clean 子集 macro-F1 约 0.270，传统 RF/XGB 更高；在 CEXP04 中完整防御相对 undefended 的恢复率在 1% 污染时约 R=1.0，30% 时降至约 0.57。强 prompt payload 仍可使 defended F1 下降，作者明确不把结果推广到分布漂移。
- LogicGuard 启示：将 poisoning 与 prompt injection 做 2×2 组合矩阵；报告 macro-F1、FPR、per-class rare-class 性能及防御恢复率，避免只看平均准确率。

## 19. Securing Retrieval-Augmented Generation: A Taxonomy of Attacks, Defenses, and Future Directions（arXiv 2026）

- 本地论文：[PDF](./papper/Securing_RAG_Taxonomy_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2604.08304)。
- 研究背景：现有 RAG 安全研究分散在污染、检索操纵、上下文利用和知识抽取，攻击目标与防御阶段缺少统一坐标。
- 目标问题：建立能同时描述攻击面、防御层、安全目标和真实目标对象的层次化 taxonomy，并诊断研究空白。
- 核心方法：SLOT 以 Surface、Layer、Objective、Target 四轴组织研究：S1 知识/索引、S2 检索、S3 上下文、S4 知识抽取；镜像 L1–L4 防御层，区分 T1 单问题翻转和 T2 跨 query 的 claim 操纵。
- 实验设置：综述/地图论文，没有新训练集上的统一实证结果；通过论文覆盖矩阵、攻击—防御对应表和 benchmark 汇总比较已有工作。
- 结果/结论分析：指出攻击越来越 corpus-fitting、自然化，而防御仍集中在下游；上游摄入、索引和访问控制薄弱。未来应做 no-blind-spot、自适应、multimodal/agentic 评测。
- LogicGuard 启示：把 SLOT 标签加入 papers_manifest 和实验结果 schema，保证每个实验明确 S/L/O/T；优先补齐上游 full-corpus poisoning 和 T2 多查询 claim 攻击。

## 20. Retrieved But Not Reliable: A Survey on Attacks and Defenses in RAG（arXiv 2026）

- 本地论文：[PDF](./papper/Retrieved_But_Not_Reliable_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2608.24977)。
- 研究背景：检索到的上下文只是“被选中”，并不代表真实、相关或安全；RAG 还叠加了隐私、偏见和多模态/agentic 风险。
- 目标问题：统一梳理攻击者目标、能力和 pipeline 阶段，并总结当前防御和 benchmark 的不可比之处。
- 核心方法：按 integrity、availability、confidentiality、fairness 三类目标，覆盖 corpus poisoning、retrieval manipulation、prompt injection、privacy extraction、attribution 与防御阶段。
- 实验设置：没有自有实验；整理 NQ、HotpotQA、SQuAD、SafeRAG 等数据集及 ACC、F1、ASR、Recall@k、泄露率等已有指标。
- 结果/结论分析：综述指出许多攻击仍假设白盒，隐蔽性与可迁移性不足；traceback 多为事后诊断，静态 benchmark 难覆盖动态 corpus 和查询分布。
- LogicGuard 启示：报告三层漏斗：retrieved exposure → evidence support → answer correctness，并把攻击预算、查询分布和动态更新作为必填字段。

## 21. Towards Secure Retrieval-Augmented Generation: A Comprehensive Review of Threats, Defenses and Benchmarks（arXiv 2026）

- 本地论文：[PDF](./papper/Towards_Secure_RAG_Review_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2603.21654)。
- 研究背景：RAG 的多模块架构同时引入数据投毒、对抗输入、成员推断和隐私泄露，现有评估缺少端到端标准。
- 目标问题：沿 RAG workflow 对威胁、输入/输出防御、数据集和安全标准做统一回顾，为后续实验提供 benchmark 组合。
- 核心方法：按 pre-retrieval、retrieval、rerank、generation、traceback 组织防御；总结 SafeRAG、RSB、NQ/Hotpot 等数据与 ACC、F1、ASR、F1(correct/incorrect)、transferability 等指标。
- 实验设置：综述论文，没有新模型或攻击的统一实证表格；主要贡献是文献分类、评价标准整理和数据集比较。
- 结果/结论分析：指出静态数据集无法反映黑盒排名攻击、动态 corpus 和 stealth poisoning；安全与效用指标高度耦合，必须采用模块化、可组合协议。
- LogicGuard 启示：沿其建议拆分 attack/detect/recover/generate/cost 五阶段；在 [实验规划.md](./实验规划.md) 中固定 benchmark、威胁模型、指标和显著性检验。

## 22. RIPRAG: Hack a Black-box Retrieval-Augmented Generation QA System with Reinforcement Learning（ACL Findings 2026）

- 本地论文：[PDF](./papper/RIPRAG_ACL2026.pdf)；原始版本：[ACL PDF](https://aclanthology.org/2026.findings-acl.833.pdf)。
- 研究背景：白盒攻击需要 retriever 梯度，旧黑盒攻击又无法利用系统反馈，在 hybrid/GraphRAG 和低污染率下容易失效。
- 目标问题：攻击者只有“注入文档”和“聊天问答”两种权限，能否利用二值黑盒反馈自适应生成高检索率、低污染量的毒文。
- 核心方法：RIPRAG 的 RLBF 用 similarity reward 与 attack reward 联合训练 poisoning SLM；BRPO（Batch Relative Policy Optimization）跨 query 做批量优势归一化，避免普通 GRPO 在稀疏奖励下崩溃。
- 实验设置：NQ、HotpotQA、MS MARCO；Contriever naive retriever 与 hybrid/complex retriever；M=1/3，比较 PoisonedRAG、Topic-FlipRAG 及 fake-white-box 版本。测试 Qwen3-8B、InternLM2.5-7B、GLM4-9B、DeepSeek-V3.2-Exp 等，报告 ASR、k 敏感性、消融和训练成本。
- 结果/结论分析：摘要给出相对基线最高 +0.72 ASR；表中 M=3 时 NQ 0.72、HotpotQA 0.82、MS-MARCO 0.78，单文档仍可达 0.35–1.00。对 query rewrite、HyDE、RAGuard 仍有残余 ASR 0.10–0.16；去掉 similarity reward 后 ASR 几乎坍塌。
- LogicGuard 启示：把查询次数、训练/测试 query 隔离、反馈可见性和 poison budget 纳入 adaptive threat model；防御评测必须允许攻击者看到输出并进行迭代，而不是一次性离线生成。

## 23. A Systematic Literature Review of Retrieval-Augmented Generation: Techniques, Metrics, and Challenges（Big Data and Cognitive Computing 2025）

- 本地论文：[PDF](./papper/RAG_Systematic_Review_2025.pdf)；原始版本：[期刊 PDF](https://www.mdpi.com/2504-2289/9/12/320/pdf)。
- 研究背景：RAG 组件、数据集和指标快速膨胀，不同论文使用不同 top-k、generator 和 judge，结果难以比较。
- 目标问题：系统汇总 2020—2025 年 RAG 技术、评测指标、应用和挑战，建立统一术语和研究地图。
- 核心方法：对约 128 篇文献做检索、筛选和分类，覆盖 vanilla/advanced/GraphRAG、检索器、重排、prompt、hallucination、faithfulness 与 efficiency。
- 实验设置：没有提出新的攻击或防御，也没有统一运行的 RAG 实验；证据来自文献统计和定性比较。
- 结果/结论分析：综述强调 retrieval quality、generation faithfulness、latency/cost、robustness 之间存在 trade-off；只报一个平均分会掩盖检索失败或上下文冲突。
- LogicGuard 启示：把安全、效用和成本分开列为主表；所有实验固定 seed、检索器、top-k、生成温度和 judge prompt，并记录版本。

## 24. Enhancing Adversarial Resilience in Semantic Caching for Secure RAG Systems（Scientific Reports 2026）

- 本地论文：[PDF](./papper/Adversarial_Semantic_Caching_2026.pdf)；原始版本：[Nature](https://www.nature.com/articles/s41598-026-36721-w.pdf)。
- 研究背景：语义缓存通过 embedding 相似度复用旧答案，但共享缓存允许恶意 query 与 benign query 碰撞，绕过最新检索和防御。
- 目标问题：黑盒攻击者能否污染缓存中的 Q–A 对；用 cluster-centroid 而非单 query embedding 是否能降低 embedding collision。
- 核心方法：SAFE-CACHE 离线组合 Q&A embedding，用 FAISS 建图和 Louvain 聚类；以 purity<0.85 或最小 intra-similarity<0.85 标记噪声簇，再用 bge-small bi-encoder 和 LoRA Gemma-3-1B 做细化/意图扩充；运行时匹配簇中心。
- 实验设置：RGB 两个 300-intent 集合；GPTCache 扩充数据 1800 triplets/600 fine-tuning examples，评估 benign 1800、adversarial 900，共 2700 Q&A。MetMap 与 GPT-4.1 生成实体替换、数字漂移、极性变化攻击；黑盒只提交 query、观察回答，成功标准是恶意样本进入 benign cluster。
- 结果/结论分析：GPTCache 基线攻击成功率 52.77%，SAFE-CACHE 降到 14.27%，提升约 72%；温度 1 的细微扰动最危险。作者也指出异步 cache update 使 targeted probing 失效，flooding 更现实。
- LogicGuard 启示：若未来加入缓存，必须记录 hit/miss、污染传播、scheduled update、失效时间和回滚成本；不能仅在冷启动索引上测安全。

## 25. ReliabilityRAG: Effective and Provably Robust Defense for RAG-based Web-Search（arXiv 2025）

- 本地论文：[PDF](./papper/ReliabilityRAG_2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2509.23519)。
- 研究背景：检索结果带有排序和 reliability score，但许多防御只做关键词过滤，既丢失有用文档又无法扩展到几十个候选。
- 目标问题：在有限比例文档被污染、且 benign 文档本身可能无关时，如何从冲突证据中找出可靠多数，并给出理论保证。
- 核心方法：MIS（maximum independent set）在 NLI contradiction graph 中选相互一致的文档子集；大 k 时用按检索权重采样的 Sampling+MIS，再聚合多个上下文答案。理论上当恶意数小于 k/2 且 NLI 误差受限时，恶意选择概率随 k 增长而下降。
- 实验设置：RealtimeQA、NQ、TriviaQA 和长文本 Biography；Mistral-7B-Instruct、Llama3.2-3B、GPT-4o-mini。MIS 用 top-k=10，Sampling+MIS 用 k=50、m=2、T=20、gamma=0.9；攻击文档放在位置 1/10 或 1/25/50，比较 Vanilla、RobustRAG、AstuteRAG、InstructRAG。
- 结果/结论分析：MIS 在 benign 和攻击下都保持较高准确率；例如 Mistral-RQA 位置 1/10 为 68/60%，明显高于多种基线。Sampling+MIS 在 NQ k=50 中对中低排名污染最稳健，即使污染到 40% 仍渐进退化；代价是多次生成。
- LogicGuard 启示：把冲突图和 source reliability 权重加入 candidate recovery；单独测 k、污染位置和恶意比例，验证“少数污染”理论假设何时失效。

## 26. Oracle Poisoning: Corrupting Knowledge Graphs to Weaponise AI Agent Reasoning（arXiv 2026）

- 本地论文：[PDF](./papper/Oracle_Poisoning_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2605.09822)。
- 研究背景：agent 通过 MCP/Neo4j 查询知识图，通常把工具返回的结构化事实当作“oracle”，不会像普通文本那样主动怀疑来源。
- 目标问题：攻击者修改节点、边或属性后，模型是否会在完全正确的推理过程中稳定接受错误事实；inline 文本评估是否会低估真实 tool-use 风险。
- 核心方法：定义 Oracle Poisoning，覆盖 package squatting、依赖链注入、call-graph security evasion、telemetry rerouting、代码生成污染和零节点 property modification 六类场景；用攻击者熟练度 L0–L3 和 VUT（Visibility–Understanding–Traceability）分析防御。
- 实验设置：生产级约 4200 万节点代码 KG，真实 Neo4j 5.x/MCP 工具调用；OpenAI、Anthropic、Google 九个模型，每模型 N=30、温度 0.5，另做 inline/simulated/real delivery 对比和多工具交叉验证。报告 trust rate、95% Clopper–Pearson CI、预算和防御捕获率。
- 结果/结论分析：L2 定向查询 270 次中 269 次接受伪造安全声明，所有有效模型信任率约 100%；只需 3 个节点（约 0.000007% 图规模）。GPT-5.1 inline 为 0% 但 simulated/real tool-use 为 100%，说明 delivery mode 是一阶混淆因素。只读 ACL 可消除直接写入，交叉工具验证可降到 0–25%，其他防御依赖模型。
- LogicGuard 启示：Stage48 以后增加 agent/tool-use 轨道；至少提供真实结构化查询、只读/可写 ACL、inline 对照和 delivery-mode 标签，避免把文本 RAG 的结论外推到工具图。

## 27. Defending RAG Against Knowledge Poisoning Using Cross-Encoder Activation Signals（CEG-RAG，PMLR 2026）

- 本地论文：[PDF](./papper/CEG_RAG_PMLR2026.pdf)；原始版本：[PMLR PDF](https://raw.githubusercontent.com/mlresearch/v318/main/assets/moradi26a/moradi26a.pdf)。
- 研究背景：cross-encoder reranker 已在 RAG 中产生 query–passage 交互表示，但多数防御只使用最终分数，浪费了内部激活信号。
- 目标问题：仅用 context-level 标签训练一个 detector，能否同时发现污染上下文、定位具体 chunk，并在固定 context budget 下替换高风险证据。
- 核心方法：将 top-N reranked chunks 视为 MIL bag；Set Transformer 建模 chunk 间交互，attention MIL 输出 bag-level poison score 和 chunk-level scores；触发后删除高风险 chunk，并用低风险候选补齐上下文。
- 实验设置：MS MARCO、NQ、HotpotQA；比较 BGE、mGTE、MS reranker 等配置，报告 context/chunk TPR、FPR、ASR、修复后 ACC。训练只用 bag label，不使用 chunk poison label。
- 结果/结论分析：MS MARCO context/chunk TPR 0.9833/0.9764，FPR 0.0667/0.1125；NQ ASR 6.30%（约 93.7% 降幅），MS MARCO ASR 11.20%（88.8% 降幅），HotpotQA ASR 16.28%。不同 reranker 仍有差异，ACC 与最低 ASR 之间存在取舍。
- LogicGuard 启示：保留 cross-encoder 的中间表示，新增 localization F1、replacement provenance 和固定预算约束；对 Stage43 做“检测-only vs 检测+repair”消融，验证收益是否来自恢复而非误删。

## 28. Secure Retrieval-Augmented Generation against Poisoning Attacks（RAGuard，ACSAC/IEEE BigData 2025）

- 本地论文：[PDF](./papper/RAGuard_Secure_Poisoning_2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2510.25025)。
- 研究背景：毒文可能排在 top-k 前列，若只过滤当前 top-k，删除后没有足够的 clean evidence；需要扩大候选范围再 rescue。
- 目标问题：能否通过 retrieval scope expansion 与 chunk-level 统计信号，筛掉困惑度/相似度异常的文档并恢复未污染上下文。
- 核心方法：RAGuard 先取更大的候选池，再用 chunk PPL、query similarity 等特征进行两阶段筛选和 clean-context 重组；与 RobustRAG、Discern-and-Answer 对比。
- 实验设置：NQ、HotpotQA、MS MARCO 等开放域 QA；多种 generator/retriever，设置不同 poison ratio、top-k 和 adversarial passage 数量，报告 ASR、clean ACC、召回/误删及时间。
- 结果/结论分析：在某些 Gemini 设置中毒文占合法文 4 倍时，RAGuard 将 ASR 从约 0.89 降至 0.02；RobustRAG/Discern-and-Answer 约为 0.69/0.24。方法对语义自然、低困惑度和自适应毒文的保证有限。
- LogicGuard 启示：复现时必须分开 filter-only、rescue 和最终回答；记录 clean support recall、误删率、候选池扩大倍数和额外 latency，重点测 low-drift 与 candidate collision。

## 29. FlippedRAG: Black-Box Opinion Manipulation Adversarial Attacks（ACM CCS 2025）

- 本地论文：[PDF](./papper/FlippedRAG_CCS2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2501.02968)。
- 研究背景：RAG 的风险不限于事实问答，攻击者还可以把争议议题的检索排序和回答立场推向 Pro/Con，造成渐进的观点操纵。
- 目标问题：在不知道黑盒 retriever 参数的情况下，能否先模仿其排序，再生成可迁移、低可疑度的观点触发器。
- 核心方法：从目标 RAG 排名采集正/负 pair，训练 BERT surrogate；再用 PAT 生成同时提升目标观点相关性和隐蔽性的 trigger，插入表达目标立场的文档。
- 实验设置：MS MARCO Passage Ranking + PROCON.org，随机 30 个争议主题；目标 retriever Contriever、Co-Condenser、ANCE、Qwen3-Embedding-4B，LLM 为 Llama-3、Vicuna、Mixtral，k=3、毒文数 3–10。指标 NDCG、Inter、Top3v、RASR、BRank、OMSR、ASV，并有 7 点 Likert 用户实验。
- 结果/结论分析：黑盒模仿后 surrogate 的 NDCG 接近目标 retriever；FlippedRAG 使 LLM 观点翻转约 40–50%，ASV 约 0.46，Llama/Mixtral 比 Vicuna 更易受影响。触发器 TF-IDF/困惑度接近自然文，简单 spam 检测和 paraphrase 防御不稳定。
- LogicGuard 启示：把“观点/claim 操纵”作为 T2 攻击；除 exact-match ASR 外报告 stance shift、用户/模型一致性和关键词隐蔽性。

## 30. One Shot Dominance: Knowledge Poisoning Attack on RAG Systems（AuthChain，EMNLP 2025）

- 本地论文：[PDF](./papper/One_Shot_Dominance_EMNLP2025.pdf)；原始版本：[ACL Anthology](https://aclanthology.org/2025.findings-emnlp.1023.pdf)。
- 研究背景：多文档投毒容易被发现，简单把 query 拼进一篇文档又难以战胜多源共识和 LLM 参数知识；复杂多跳问题尤其如此。
- 目标问题：一篇毒文档能否在大语料、复杂关系和内部正确知识存在时同时获得检索可见性、外部可信度和生成支配地位。
- 核心方法：AuthChain 由三个 agent 迭代：CoE 生成自包含证据链，Authority generator 加入机构背书/时间戳，revision agent 检查逻辑完整性；最终形成覆盖问题所有元素的单文档链。
- 实验设置：HotpotQA、MS MARCO、NQ；六个 LLM，top-5 retriever；与 PoisonedRAG（PRAG）、HijackRAG（HRAG）比较，并在 AstuteRAG、RobustRAG 防御下测 ACC/ASR。还测试 query paraphrase、contextual parametric knowledge（CDP）和 multi-turn。
- 结果/结论分析：AuthChain 平均 ASR 约为 HotpotQA 87.0%、MS MARCO 81.5%、NQ 77.8%，较基线提高约 21.7–46.5 个百分点；authority 与 CoE 组件均重要，paraphrase 后仍保持较高 ASR。防御下仍能显著降低 ACC。
- LogicGuard 启示：将 one-shot 作为最低预算强基线；记录文档数量、证据链覆盖、authority cues、PPL/RSR，并把“单文档支配但未命中目标答案”的情况单独分析。

## 31. Covert Knowledge Poisoning Attacks in Retrieval-Augmented Code Generation（IEEE TDSC 2026）

- 本地论文：[PDF](./papper/Covert_Poisoning_Code_RAG_TDSC2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2502.03233)。
- 研究背景：代码 RAG 会把检索到的示例直接用于生成；一个看似相关但含漏洞的函数（如不安全输入处理）可能把安全缺陷传播到新代码。
- 目标问题：在程序意图已知或隐藏时，知识库中少量 vulnerable examples 是否足以提高生成代码的漏洞率，以及语言、相似度和 shot 数如何影响风险。
- 核心方法：从每个任务构造 clean/vulnerable 成对示例，按 cluster 选择 poisoned examples；设置 Scenario I（意图暴露，定向挑选）和 Scenario II（意图隐藏，按比例污染），比较 JINA 和 BM25。
- 实验设置：Python、C、C++、Java 的真实开发场景，约 12,054–12,062 个代码示例；四个 LLM、两个 retriever、两种场景共 16 个子场景。指标 vulnerable rate（VR）、vulnerable retrieval ratio (VRRC)、similarity、MRR、SR@k、代码安全审计 precision/recall/F1。
- 结果/结论分析：单个 poisoned sample 就可能使约 48% 生成代码含漏洞；JINA 下增加 1→9 个样本显著提高 VR，CodeLlama 在 9 个样本时约 0.53。one-shot→three-shot 可再升约 6.5%；隐藏意图降低攻击效率但仍有明显 VRRC。
- LogicGuard 启示：把“功能正确但安全属性错误”视为独立目标；未来扩展 code/GraphRAG 时同时测功能通过率、漏洞率、retrieval poison ratio 和人工审计一致性。

## 32. Secure Multifaceted-RAG: Hybrid Knowledge Retrieval with Security Filtering（Information 2025）

- 本地论文：[PDF](./papper/Secure_Multifaceted_RAG_2025.pdf)；原始版本：[期刊 PDF](https://www.mdpi.com/2078-2489/16/9/804/pdf?version=1758020090)。
- 研究背景：企业 RAG 仅检索内部文档会漏信息，调用闭源外部 LLM 又可能泄露机密；安全、覆盖和成本需要同时优化。
- 目标问题：如何在内部企业库、预写专家知识和按需外部知识之间路由，同时阻止 security-sensitive prompt 发送到外部模型。
- 核心方法：SecMulti-RAG 使用 Qwen2.5-3B-Instruct 做机密过滤、BGE-M3 fine-tuned retriever、Qwen2.5-14B-Instruct 本地生成；只有安全 query 才调用 GPT-4o 生成外部背景，并限制每题最多一个外部文档。
- 实验设置：韩国汽车工程报告任务；企业库 5,625 chunks，预写专家知识 540 chunks，另有 675 keyword-report pairs（8:1:1）。过滤器 train/val/test=2340/292/294，retriever top-5；与 Traditional RAG 做 correctness、richness、helpfulness 的人评和 LLM pairwise 比较。
- 结果/结论分析：过滤器在含项目名的 easy set recall 99.01%，加入无项目名 hard query 后 recall 74.35%、accuracy 82.31%。135 个测试 query 中 101 个被判敏感；SecMulti-RAG 相比传统 RAG 人评 win rate 56.3–70.4%，LLM 评估 79.3–91.9%，报告平均长度 2660 vs 1632 tokens。
- LogicGuard 启示：作为 hybrid retrieval、来源分级和 ACL/provenance 的 clean control；同时警惕外部生成文档一旦进入池，后续敏感 query 仍可能检索到它，需做来源生命周期管理。

## 33. RAP-RAG: A Retrieval-Augmented Generation Framework with Adaptive Retrieval Task Planning（Electronics 2025）

- 本地论文：[PDF](./papper/RAP_RAG_2025.pdf)；原始版本：[期刊 PDF](https://www.mdpi.com/2079-9292/14/21/4269/pdf?version=1761839436)。
- 研究背景：不同问题需要不同检索策略；固定 GraphRAG 或向量检索在多跳、实体关系和混合知识任务上会产生冗余和存储开销。
- 目标问题：能否根据 query 特征动态选择检索任务，融合异构图和多种 retriever，提升多跳准确率并降低资源消耗。
- 核心方法：RAP-RAG 构建 heterogeneous weighted graph index，包含实体、文档和关系权重；adaptive planner 预测任务类型，在 GraphRAG、关键词、向量和邻居扩展之间组合。
- 实验设置：LiHua-World、MultiHop-RAG、Hybrid-SQuAD；对比 GraphRAG、LightRAG、MiniRAG 等，测多跳 QA accuracy、retrieval completeness、响应时间和存储。
- 结果/结论分析：论文报告相对基线约 3–5% accuracy 提升和约 15% storage reduction，planner 在复杂问题上比固定检索更稳定；收益依赖图构建质量，错误任务分类会放大漏检。
- LogicGuard 启示：用作结构化检索 clean baseline 和效率控制组；安全实验需固定 planner 或把 planner 作为因素，否则防御收益可能来自更强的自适应检索。

## 34. SURE-RAG: Sufficiency and Uncertainty-Aware Evidence Verification for Selective RAG（arXiv 2026）

- 本地论文：[PDF](./papper/SURE_RAG_2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2605.03534)。
- 研究背景：RAG 系统常在证据不足或相互冲突时仍强行回答；“拒答”应由证据充分性和不确定性驱动，而不是只看模型置信度。
- 目标问题：能否判定 evidence 是 supported、refuted 还是 insufficient，并在高风险 query 上选择性 abstain，降低错误回答风险。
- 核心方法：对 claim–evidence pair 提取 coverage、relation strength、disagreement、conflict、uncertainty，聚合成 selective score；校准阈值后输出三类状态和最终答案/拒答。
- 实验设置：HotpotQA-RAG v3 控制多跳证据，加入 shortcut baseline、counterfactual swap、no-oracle 检查和 GPT-4o audit；外部 HaluBench 用于跨数据迁移。比较 DeBERTa mean pooling、GPT-4o judge、concat cross-encoder 和 SURE-RAG，报告 Macro-F1、risk–coverage。
- 结果/结论分析：HotpotQA-RAG v3 Macro-F1=0.9075（原始约 0.8951±0.0069），高于 DeBERTa 0.6516、GPT-4o judge 0.7284、concat 0.8888；30% coverage 时 risk 0.1642，比 0.2588 低约 37%。HaluBench 上 GPT-4o unsafe detection 0.7389，而 SURE 迁移仅 0.3343，显示域迁移限制。
- LogicGuard 启示：为 natural_bridge 和无 candidate 场景加入 evidence-insufficient 分支；报告 risk–coverage、abstention utility 和 counterfactual swap，而不是把所有非目标答案归为攻击失败。

## 35. Understanding the Fundamental Design Decisions of Retrieval-Augmented Generation Systems（ACM TOSEM 2026）

- 本地论文：[PDF](./papper/RAG_Design_Decisions_TOSEM2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2411.19463)。
- 研究背景：RAG 论文常把 chunk、embedding、retriever、prompt 和 generator 一起更换，导致安全或准确率变化无法归因。
- 目标问题：在控制变量下回答“是否应该部署 RAG、取多少文档、如何整合证据”，并量化数据集/模型交互。
- 核心方法：三组研究问题：RQ1 改变 retrieval recall 与 base LLM 比较；RQ2 扫描 k 和统计显著性；RQ3 比较 Prompt Tuning、Thought Generation、Chain-of-Note、Self-Refine、Few-shot 等整合方法。
- 实验设置：六个数据集：CoNaLa、DS1000、Pandas_Numpy_Eval（代码）和 NQ、TriviaQA、HotpotQA（QA）；每个 QA 随机抽 2000 query；主要 retriever 为 text-embedding-3-small，并复核 BM25/miniLM；generator 含 GPT-4o-mini、GPT-3.5、Llama2 等。指标 accuracy、pass@1、retrieval recall、PPL 和 McNemar/bootstrap。
- 结果/结论分析：QA 在 recall 0.2–0.6 就能受益，k 大于约 10 后收益趋于平台；代码任务对 k 更不稳定，PNE 甚至在 golden docs 全部给出时仍可能低于 base LLM。prompt 收益高度依赖模型和数据集，复杂 CoT 并不总是更好。
- LogicGuard 启示：安全对比固定组件、温度和 k；至少做一次 k/retriever/generator 敏感性，防止把更大上下文或更强模型误写成防御能力。

## 36. XRAG: Examining the Core—Benchmarking Foundational Components in Advanced RAG（IEEE ICDE 2026）

- 本地论文：[PDF](./papper/XRAG_ICDE2026.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2412.15529)。
- 研究背景：现有 RAG toolkit 的随机种子、generator、retriever、指令和数据格式不统一，组件级结果难以复现和比较。
- 目标问题：提供覆盖 pre-retrieval、retrieval、post-retrieval、generation 及 agent orchestrator 的统一 benchmark/harness。
- 核心方法：XRAG 模块化实现三种 query rewriting、六种 retrieval units、三种 post-processors、OpenAI/Meta/DeepSeek generators 和 sequential/conditional/iterative/parallel/hybrid 五类 orchestrator；同时提供 conventional token metrics 与 LLM cognitive evaluator。
- 实验设置：统一四类数据集：HotpotQA（multi-hop）、FinanceBench（financial）、Drop/NaturalQA 等 numerical/constrained/set-logical 任务；温度设 0，固定 BGE/JINA retriever、BGE reranker，报告 retrieval hit/precision/recall、generation accuracy/WER/CER、LLM judge 和 orchestrator success。
- 结果/结论分析：不同数据集对 retriever、reranker 和 orchestrator 的敏感性不同；高 Hit@10（>0.8）并不保证生成正确，长上下文和复杂 orchestrator 会造成额外失败。XRAG 的主要结果是可比性和组件诊断，而非安全防御 SOTA。
- LogicGuard 启示：用 XRAG 思想重构实验 harness，固定组件后只替换 defense；为每个安全结果附上 retrieval 与 generation 两级原始日志。

## 37. Rescuing the Unpoisoned: Efficient Defense Against Knowledge Corruption Attacks on RAG Systems（RAGDefender，ACSAC 2025）

- 本地论文：[PDF](./papper/RAGDefender_ACSAC2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2511.01268)。
- 研究背景：top-k 中混入毒文后，粗暴删除会同时删掉 gold evidence；防御需要从更大候选池“救回”未污染文档，并控制额外 LLM 调用。
- 目标问题：chunk-level PPL、similarity 和扩展检索是否能在不同攻击比例下恢复 clean context，且不牺牲 benign utility。
- 核心方法：扩大检索范围，计算候选 chunk 的 perplexity/语义相似度，筛选低风险文档并重组上下文；论文提供 filter/rescue 两类流程，与 RobustRAG、Discern-and-Answer 对照。
- 实验设置：NQ、HotpotQA、MS MARCO；多种 dense retriever 和 LLM，扫 poisoned passage 数、top-k、攻击位置和 clean/attack 场景。指标 ASR、ACC、gold recall、误删率、延迟和 token/API 成本。
- 结果/结论分析：作者报告 Gemini 在 adversarial passages 达合法 passages 4 倍时，RAGDefender 将 ASR 约 0.89 降至 0.02；RobustRAG、Discern-and-Answer 分别约 0.69、0.24。对低 PPL、语义自然及 adaptive attack 的检测仍可能失效。
- LogicGuard 启示：复现实验必须保留“扩展候选但不检测”“检测不恢复”“检测+恢复”三种消融；统计 clean support recall 和 recovery correctness，防止只看 ASR 降幅。

## 38. PRA-RAG: Provably Robust Aggregation in Retrieval-Augmented Generation against Retrieval Corruption（ACL Findings 2026）

- 本地论文：[PDF](./papper/PRA_RAG_ACL2026.pdf)；原始版本：[ACL PDF](https://aclanthology.org/2026.findings-acl.1794.pdf)。
- 研究背景：检索结果可被集合级污染，已有防御常缺乏理论界限，或需大量重复 LLM 生成；当 LLM 本身不了解事实时，内部知识判断也不可靠。
- 目标问题：在固定数量的 retrieved texts 被污染时，能否通过多子集采样和几何鲁棒聚合限制毒文的最大语义影响。
- 核心方法：扩展候选集，随机采样多个文本组合；在组合 embedding 空间寻找覆盖多数样本的 minimum-radius ball，以中心作为 robust subset，再做加权平均。给出 Provable Average Deviation（PAD）上界。
- 实验设置：NQ、MS MARCO、HotpotQA；Mistral-7B、Llama3-8B、Vicuna-7B、Qwen3-8B、GPT-3.5-turbo、GPT-5-mini；top-k=8、subset n=3、poisoning rate=20%，攻击 PoisonedRAG、DoS、AdvDec、CorruptRAG；比较 RobustRAG、InstructRAG、AstuteRAG、TrustRAG、RAGForensics。
- 结果/结论分析：在 MS MARCO 20% 污染上，Vicuna ACC 0.68、ASR 0.01；整体 ASR 可降至 1% 左右，clean ACC 保持。top-k 增大、每个子集包含更多 clean 文本会降低 PAD；但毒文超过理论阈值会削弱保证，且子集采样带来额外开销。
- LogicGuard 启示：把 PAD/semantic deviation 作为机制级指标；做 10 次以上独立运行、95% CI 和 paired test，明确 corruption fraction、subset size、随机种子及延迟。

## 39. Exploring Knowledge Poisoning Attacks to Retrieval-Augmented Generation（KG-RAG，Information Fusion 2026）

- 本地论文：[PDF](./papper/KG_RAG_Poisoning_Information_Fusion2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2507.08862)。
- 研究背景：KG-RAG 通过三元组、关系路径和结构化推理增强 QA，但已有文本投毒结论不能直接覆盖实体/关系插入攻击。
- 目标问题：在黑盒、只允许 injection、攻击者知道 query 但不知道 gold answer/内部参数的情况下，构造已有实体/关系组成的误导链，是否能跨多种 KG-RAG 稳定影响答案。
- 核心方法：注入错误三元组、关系路径或完整 misleading chain，比较普通文本、结构化检索和 KG reasoning 方法；重点区分 retrieval-stage exposure 与生成阶段错误。
- 实验设置：WebQSP、ComplexWebQuestions 全测试集；四种 KG-RAG 方法，比较不同 KG reasoning LLM。指标 adversarial triple retrieval coverage、ASR、EM、F1，并分析推理能力与脆弱性的关系。
- 结果/结论分析：超过 90% 的问题会检索到至少一个 adversarial triple；检索阶段是主要脆弱点，推理能力更强的模型反而更容易沿错误路径完成答案。说明实体/关系插入不需要 prompt injection 就能形成系统性 integrity 风险。
- LogicGuard 启示：这是最直接的结构化污染基线；Stage48 应重建 KG/GraphRAG index，记录 triple coverage、path hit、community rank 和最终 targeted/broad ASR，而非只比较文本 source 检出率。

## 40. SeCon-RAG: A Two-Stage Semantic Filtering and Conflict-Free Framework for Trustworthy RAG（NeurIPS 2025）

- 本地论文：[PDF](./papper/SeCon_RAG_NeurIPS2025.pdf)；原始版本：[arXiv](https://arxiv.org/abs/2510.09710)。
- 研究背景：只做 embedding clustering 会误删有用文档，只做语义相似度又可能放过结构自然的毒文；检索证据与模型内部知识冲突时还需要推理阶段处理。
- 目标问题：通过“检索前语义门 + 生成前冲突门”同时降低高比例 poisoning 和 prompt injection 下的 ASR，并维持 clean accuracy。
- 核心方法：SCF 用 clustering 与 EIRE（entity–intent–relation extraction）联合过滤；CAF 在生成前让 LLM 判断 evidence 是否 poisoned、conflicting、irrelevant，删除冲突项后再回答；联合过滤使用保守 AND 逻辑。
- 实验设置：NQ、HotpotQA、MS MARCO；多种 LLM（Mistral-12B、Qwen-7B、GPT-4o、DeepSeek-R1 等），污染比例从 0% 到 100%，比较 VanillaRAG、InstructRAG、AstuteRAG、TrustRAG。指标 ACC、ASR、消融、阈值敏感性、延迟。
- 结果/结论分析：HotpotQA+GPT-4o 在 100% poisoning 下 ACC 83.6%、ASR 2.4%；MS MARCO+GPT-4o ACC 93.6%、ASR 0%。去掉 SCF 后 HotpotQA ASR 8%→25%，去掉 CAF 可升到 56%；NQ 某些模型在 100% poisoning 仍保持约 90% ACC。
- LogicGuard 启示：可作为“语义门+冲突门”强基线；绘制 security–utility Pareto 曲线，单独分析 EIRE、cluster、CAF 对 low_drift、candidate_collision、natural_bridge 的贡献和误删代价。

## 跨论文综合观察

1. **攻击面正在从文本转向结构和动态过程。** GraphRAG under Fire、LogicPoison、KEPo、KG-RAG 与 Oracle Poisoning 均说明实体/关系/时间/工具返回值可能比表面文本更关键。
2. **“检出污染”与“恢复正确证据”是两个问题。** HoG-GRAG、RAGOrigin、CEG-RAG、RAGDefender 和 LogicGuard Stage47 都支持分别记录 detection、localization、recovery correctness、answer correctness。
3. **低可见度攻击会击穿单信号检测。** PPL/关键词在 LogicPoison、AuthChain、M3Att、FlippedRAG 等设置中不稳定；应组合结构、冲突、责任和生成行为信号，并做自适应攻击盲测。
4. **实验可比性依赖严格控制。** RAG Design Decisions、XRAG、Influence Factors 共同表明 retriever、top-k、chunk、generator、prompt 和 corpus 交互显著；论文间 ASR 数值不能脱离预算和设置直接比较。
5. **LogicGuard 下一阶段优先级。** 先完成完整 corpus poisoning + reindex（HotpotQA、MuSiQue、2Wiki），再加入 KG triple/path、temporal evolution、one-shot/denial、adaptive black-box 和 agent/tool-use；主表同时报告 retrieval exposure、graph/path integrity、detector TPR/FPR、recovery exactness、targeted/broad ASR、clean utility、latency/cost。

## 使用说明

1. papper/ 中的 PDF 是本次阅读的本地证据；文件名是稳定资料 ID，不因后续版本更新而改变。
2. 论文中的数值只在原论文的 threat model、数据子集、模型、top-k、判定规则下成立；复现实验应记录版本号、SHA-256、seed、API 日期和 judge prompt。
3. LogicGuard 的实验设计与阶段边界见 [实验规划.md](./实验规划.md)，Stage47 的已知盲点见 [handoff.md](./Logicguard-research-new/handoff.md) 和 Stage47 报告。
