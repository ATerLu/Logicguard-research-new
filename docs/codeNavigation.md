# LogicGuard 项目代码导航与关键概念复盘

> 盘点对象：`/home/uisee/logicguard/Logicguard-research-new`
>
> 盘点日期：2026-08-11
>
> 当前实验状态：Stage47 已完成，Stage48 尚未开始。

## 1. 先用一张图理解项目

LogicGuard 不是单个分类器，而是一条面向 GraphRAG 多跳问答的“安全检索—恢复—补证—回答验证”链路：

```text
多跳问答数据 / LogicPoison clean & poisoned corpus
                    │
                    ├── 早期：NaiveRAG / 轻量 GraphRAG surrogate
                    │
                    └── 后期：Microsoft GraphRAG 建图、索引、官方 local context
                                      │
                                      ▼
                           已检索的 source context
                                      │
                      Stage43 风险检测 + 非 Oracle 恢复
                                      │
                      Stage44 clean candidate BM25 补证
                                      │
                      Stage45 条件式二跳证据补全
                                      │
                      Stage46 LLM 回答、审计与 Judge
                                      │
                      Stage47 三类自适应攻击压力测试
```

复盘时要始终区分三层对象：

1. **语料与索引层**：原始文档如何被污染，GraphRAG 如何抽取实体、关系和社区。
2. **检索与 source 层**：哪些 evidence/source 被检索进上下文，LogicGuard 如何检测、替换和补证。
3. **回答与评测层**：最终 prompt 实际暴露了什么，LLM 是否答对，错误是否真正由攻击导致。

## 2. 推荐阅读顺序

如果目标是重新理解项目，不建议按 Stage1 一直读到 Stage47。更高效的顺序是：

1. `handoff.md`：当前最权威的状态、Stage47 结论和 Stage48 约束。
2. `artifacts/reports/Stage47_三类自适应攻击初步实验_中文报告.md`：当前最重要的攻击结果。
3. `docs/methodology.md`：完整实验方法和各阶段演进。
4. `docs/results.md`：Stage1–47 汇总结果。
5. `src/logicguard/defense/risk_aware_recovery.py`：Stage43 核心风险检测和恢复。
6. `src/logicguard/defense/source_enrichment.py`：Stage44 补证。
7. `src/logicguard/defense/chain_completion.py`：Stage45 二跳补证。
8. `src/logicguard/attack/adaptive.py`：Stage47 自适应攻击。
9. `src/logicguard/evaluation/adaptive_attack_analysis.py`：Stage47 严格统计口径。

注意：根目录 `README.md` 的前半部分仍停留在 Stage28 左右，后面虽然追加了后续记录，但“当前状态/下一步”不如 `handoff.md` 新。判断当前进度时以 `handoff.md` 和 Stage47 报告为准。

## 3. 仓库一级目录导航

```text
Logicguard-research-new/
├── src/logicguard/       核心 Python 包
├── configs/              实验参数与路径配置
├── tests/                单元测试和流水线回归测试
├── scripts/              维护脚本与批量运行脚本
├── tools/                可视化工具和独立 GraphRAG 环境定义
├── docs/                 方法、结果、复现、评审与注册表
├── artifacts/            精选的小体积冻结实验产物
├── lib/                  HTML 可视化依赖的前端静态库
├── pyproject.toml         主 Python 项目、依赖和 CLI 定义
├── uv.lock                主环境的冻结依赖
├── handoff.md             当前阶段交接文档
└── README.md              项目入口说明，但部分“当前状态”已滞后
```

### 3.1 各大目录保存什么

| 目录 | 保存内容 | 复盘时的定位 |
| --- | --- | --- |
| `src/logicguard/` | 数据、攻击、检索、建图、防御、LLM、评测和报告代码 | 项目核心，重点阅读 |
| `configs/` | 各阶段 YAML；定义输入、输出、阈值、模型和样本规模 | 代码回答“怎么做”，配置回答“这次实验具体怎么跑” |
| `tests/` | 对生产模块、历史兼容入口和 Stage 流水线的回归测试 | 判断模块契约和边界的可靠依据 |
| `scripts/` | 报告清单、实验注册表、缓存清理和旧阶段批量执行 | 项目维护层，不是核心算法 |
| `tools/` | 知识图谱/实验结果可视化；Microsoft GraphRAG 隔离环境定义 | 读图和 official GraphRAG 运行环境 |
| `docs/` | 方法、结果、复现、论文计划、评审意见和清单 | 项目叙事与结论入口 |
| `artifacts/` | Stage40–47 精选 summary、examples、攻击记录和 Stage47 报告 | 当前镜像中可以直接审查的实验依据 |
| `lib/` | `vis-network`、`tom-select` 等静态 JS/CSS | 仅服务 HTML 可视化，不参与模型和防御 |

### 3.2 当前仓库中看不到但代码会引用的目录

配置和文档大量引用 `data/`、`outputs/`，但当前 Git 镜像没有跟踪这些大目录。这是有意设计，不是代码丢失：

- `data/`：原始数据、标准化数据和 LogicPoison clean/poisoned corpus；
- `outputs/ms_graphrag/`：GraphRAG workspace、Parquet 索引、LanceDB、cache；
- `outputs/ms_graphrag_query/`：官方 context、恢复结果、回答和评测明细；
- `outputs/reports/`：历史生成报告；
- `.venv/` 与 `tools/ms_graphrag/.venv/`：主项目和 GraphRAG 隔离环境。

镜像策略见 `SYNC_POLICY.md`。当前仓库只保留能代码审查的源码、配置、测试、文档和轻量精选产物。

此外，HoG-GRAG 论文位于仓库外的同级目录：`/home/uisee/logicguard/papper/HoG-GRAG_ACL2026.pdf`，不属于 LogicGuard 源码树。

## 4. 根目录文件导航

| 文件 | 作用 |
| --- | --- |
| `README.md` | 项目简介、环境、历史进度和主要命令；部分当前状态已滞后 |
| `handoff.md` | Stage47 完成状态、核心漏洞、Stage48 计划和不可违反的实验口径 |
| `REVIEW_CONTEXT.md` | 给外部代码/研究审核者的精简背景与当前问题 |
| `MIRROR_STATUS.md` | 镜像来源、同步日期、精选产物数量 |
| `SYNC_POLICY.md` | 说明哪些内容进入 Git 镜像、哪些大产物被排除 |
| `sync_from_logicguard.ps1` | 从开发工作树向 Git 镜像单向同步的 PowerShell 脚本 |
| `pyproject.toml` | 包名、Python 版本、依赖、可选 research/dev 依赖和 `logicguard` CLI |
| `uv.lock` | `uv` 解析后的主项目冻结依赖 |
| `.python-version` | 项目期望的 Python 版本 |
| `.gitignore` | 数据、环境、缓存和大型运行产物忽略规则 |
| `.gitattributes` | Git 属性与文本处理规则 |

## 5. `src/logicguard/` 总体分层

| 子包 | 职责 |
| --- | --- |
| `core/` | 配置、路径、I/O、哈希和基础指标 |
| `data/` | LogicPoison/多跳数据读取、对齐、标准化和 schema |
| `naive_rag/` | BM25、dense、hybrid 非图检索基线 |
| `graph/` | 早期轻量 GraphRAG surrogate：NetworkX 文档—实体二部图 |
| `attack/` | Entity Swap、Bridge Injection 和 Stage47 自适应攻击 |
| `defense/` | 风险特征、过滤、恢复、补证、二跳补全和消融 |
| `ms_graphrag/` | Microsoft GraphRAG workspace、索引/查询接入及历史兼容入口 |
| `llm/` | 通用提示构造、回答生成、答案分类和 Judge |
| `evaluation/` | Stage26 以后回答审计、可答性、跨数据集和自适应攻击分析 |
| `experiments/` | 多模块实验编排 |
| `reports/` | 中文报告本地化与冻结实验注册表 |

`src/logicguard/cli.py` 是当前稳定 CLI，只暴露仍处于活动状态的回答和 Stage47 工作流。很多旧实验仍通过 `python -m logicguard.<module>` 运行。

## 6. 核心代码逐文件导航

### 6.1 包入口与基础设施

| 文件 | 作用 |
| --- | --- |
| `src/logicguard/__init__.py` | LogicGuard 顶层包入口，目前基本为空 |
| `src/logicguard/cli.py` | `logicguard resolve-config` 和 `logicguard run <step>` 的稳定入口；把命令分发到活动模块 |
| `src/logicguard/py.typed` | 声明该包向类型检查器提供类型信息 |
| `src/logicguard/core/__init__.py` | `core` 包入口 |
| `src/logicguard/core/config.py` | 查找项目根目录、加载 YAML、解析新旧配置路径和 alias |
| `src/logicguard/core/io.py` | JSONL/CSV 读写、增量 append、环境变量检查、SHA-256 |
| `src/logicguard/core/metrics.py` | `ratio`、均值、去重等跨评测复用的确定性指标函数 |

### 6.2 数据层 `data/`

| 文件 | 作用 |
| --- | --- |
| `data/__init__.py` | 数据包入口 |
| `data/schemas.py` | `QueryRecord`、`AnswerRecord`、`CorpusDocument`、`RawDataset`、`NormalizedSample` 等稳定数据契约 |
| `data/loader.py` | 读取 BEIR 风格的 `queries.jsonl`、`answers.jsonl`、`corpus.jsonl`、`qrels/test.tsv`，并检查 ID 对齐 |
| `data/prepare.py` | 将原始数据转为自包含 JSONL 样本，生成数据校验摘要和报告 |
| `data/logicpoison_official.py` | 成对读取 LogicPoison clean/poisoned corpus，生成文档差异、query 完整性和答案表面丢失等元数据 |

### 6.3 非图基线 `naive_rag/`

| 文件 | 作用 |
| --- | --- |
| `naive_rag/__init__.py` | NaiveRAG 包入口，并约定与图检索共用 `RetrievalTrace` |
| `naive_rag/baseline.py` | 实现 BM25、dense、hybrid 检索；将普通文档检索也转为统一 trace |
| `naive_rag/run_baseline.py` | 从 YAML 加载数据和检索模式，写 trace 与中文报告 |

### 6.4 早期轻量图 `graph/`

| 文件 | 作用 |
| --- | --- |
| `graph/__init__.py` | 轻量 GraphRAG 包入口 |
| `graph/schemas.py` | `EntityMention`、`DocumentEntities`、`GraphIndex`、`PathCandidate`、`RetrievalTrace` 等图与路径对象 |
| `graph/entities.py` | 用大写短语、括号内容和年份做确定性规则实体抽取，并规范化实体键 |
| `graph/builder.py` | 使用 NetworkX 构造文档—实体二部图；节点为 `doc:<id>`/`ent:<name>`，边表示文档提及实体 |
| `graph/retriever.py` | 从 query 实体做最短路径检索；深度 3 可形成“query实体→文档A→桥实体→文档B”二跳路径，并计算召回 |
| `graph/baseline.py` | 串联实体抽取、建图、路径检索，输出 entity cache、query entity、trace 和报告 |
| `graph/run_baseline.py` | 轻量图基线的 YAML/命令行入口 |

### 6.5 攻击层 `attack/`

| 文件 | 作用 |
| --- | --- |
| `attack/__init__.py` | 攻击包入口 |
| `attack/schemas.py` | Entity Swap、Bridge Injection、污染暴露等可审计攻击元数据 |
| `attack/entity_swap.py` | 在 gold support 中把正确答案实体替换成错误 benchmark 答案，形成可控实体替换攻击 |
| `attack/run_entity_swap.py` | Entity Swap 实验配置、运行和产物写出入口 |
| `attack/bridge_injection.py` | 生成把 query 实体桥接到错误答案的合成文档；含普通版和 answer-aware v2 |
| `attack/run_bridge_injection.py` | Bridge Injection v1 实验入口 |
| `attack/run_bridge_injection_v2.py` | 更适合回答层 LLM 评测的 answer-aware Bridge Injection v2 入口 |
| `attack/adaptive.py` | Stage47 三类标签盲自适应 source 攻击的生成、约束校验、防御矩阵和 prompt 暴露预检 |

### 6.6 防御层 `defense/`

| 文件 | 作用 |
| --- | --- |
| `defense/__init__.py` | 防御包入口 |
| `defense/schemas.py` | `CandidateRiskScore`、`RerankedCandidate`、`RerankedTrace` 等可序列化解释对象 |
| `defense/features.py` | 对早期路径候选计算透明风险特征，如 provenance、桥实体支持度、路径异常和内容完整性 |
| `defense/reranker.py` | 根据风险重排 trace，并构造 guarded/recovered trace |
| `defense/run_logicguard.py` | 早期本地攻击上的首版离线 LogicGuard 运行器 |
| `defense/run_threshold_scan.py` | 扫描防御阈值组合，分析安全性—召回折中 |
| `defense/run_ablation.py` | 固定同一批 trace，拆分不同风险信号的贡献 |
| `defense/run_logicpoison_defense.py` | official LogicPoison 语料上的 Stage3 防御；区分 provenance、content integrity 和 clean-trace recovery |
| `defense/run_non_oracle_recovery.py` | Stage8：用可信 clean corpus 的 BM25 重检索替代直接读取 clean trace 的 oracle 回填 |
| `defense/oracle_recovery.py` | Stage23：在 official GraphRAG `context_data.sources` 上用 doc_id 对应的 clean source 做 oracle 上界恢复 |
| `defense/non_oracle_recovery.py` | Stage25：从 clean candidate pool 按 query、标题和实体排序，做 doc-id-blind source 恢复 |
| `defense/risk_aware_recovery.py` | Stage28/43：先用 clean-candidate consistency 检测风险，再执行非 Oracle 恢复；当前核心 detector 所在文件 |
| `defense/source_enrichment.py` | Stage35/44：保留已恢复证据，用 query BM25 从 clean candidate pool 追加 source，默认研究 top-12 |
| `defense/chain_completion.py` | Stage38/45：诊断多跳证据链是否完整，并按桥实体条件式追加二跳候选，默认研究 top-14 |

### 6.7 回答与通用 LLM 层 `llm/`

| 文件 | 作用 |
| --- | --- |
| `llm/__init__.py` | LLM 工具包入口 |
| `llm/provider.py` | 最小 OpenAI-compatible chat client；密钥只从环境变量读取，记录模型和 token 用量 |
| `llm/context.py` | 将检索候选/source 渲染为回答 prompt 和消息 |
| `llm/evaluation.py` | 归一化回答，按 correct/incorrect/abstained 等规则分类 |
| `llm/answer_judge.py` | 构造答案等价性 Judge prompt，解析 Judge 结果 |
| `llm/run_answer_judge.py` | 对既有回答 JSONL 运行离线/按需 Judge 并写汇总 |
| `llm/run_generation_pilot.py` | 早期小规模真实 API pilot，对比 clean/poisoned/guarded/recovered 四种上下文 |
| `llm/run_logicpoison_answer_eval.py` | official LogicPoison trace 的回答层实验，生成四条件答案并统计攻击成功 |
| `llm/run_stage6_summary.py` | 聚合 Stage6 多数据集回答与 Judge 结果 |
| `llm/merge_stage8_recovery.py` | 将 Stage8 non-oracle recovered 回答与 Stage6 基线条件合并 |

### 6.8 评测层 `evaluation/`

| 文件 | 作用 |
| --- | --- |
| `evaluation/__init__.py` | 回答评测包入口 |
| `evaluation/answer_proxy.py` | Stage26 不调用 LLM，根据答案表面和未恢复污染暴露估计可答、拒答与攻击成功风险 |
| `evaluation/answer_generation.py` | Stage27 以后 official source context 的真实 LLM 回答生成和基础分类 |
| `evaluation/answer_audit.py` | Stage29 离线回答归一化、错误归因、source 引用和代表样例审计 |
| `evaluation/answerability_ablation.py` | Stage31 比较 source ordering、top-k、字符预算对可答性的影响 |
| `evaluation/llm_comparison.py` | Stage32 对不同 source 渲染策略做真实 LLM 配对比较 |
| `evaluation/judge_audit.py` | Stage34 对本地规则不能可靠判断的答案做语义 Judge 复核 |
| `evaluation/cross_dataset_audit.py` | Stage40 检查 2Wiki、HotpotQA、MuSiQue 的数据、索引、context 和后续实验就绪状态 |
| `evaluation/answer_preflight.py` | Stage46 冻结四种 context 变体，渲染实际 prompt，并在调用 LLM 前检查暴露 |
| `evaluation/cross_dataset_analysis.py` | Stage46 汇总两个数据集的最终回答结果和配对增量 |
| `evaluation/adaptive_attack_analysis.py` | Stage47 合并攻击、预检、回答、审计和 Judge；计算严格分母、broad/targeted ASR 和错误恢复 |

### 6.9 实验编排与报告

| 文件 | 作用 |
| --- | --- |
| `experiments/__init__.py` | 实验编排包入口 |
| `experiments/run_logicpoison_retrieval.py` | Stage2 同时比较 clean/poisoned 上的 BM25 与轻量 graph surrogate 检索影响 |
| `experiments/run_multidataset.py` | 对 2Wiki、HotpotQA、MuSiQue 执行相同的早期检索—攻击—防御流水线 |
| `reports/__init__.py` | 报告包入口 |
| `reports/chinese.py` | 将机器生成 Markdown 指标说明本地化为中文研究记录 |
| `reports/experiment_registry.py` | 生成并校验冻结实验注册表，用 SHA-256 绑定配置、输入、输出、报告和结论 |

## 7. Microsoft GraphRAG 接入代码逐文件导航

这个目录既包含真正的 official GraphRAG 接入，也保留了一批历史 Stage 路径兼容文件。新代码应优先从 `attack/`、`defense/`、`evaluation/` 导入，旧路径主要用于复现实验命令。

### 7.1 Workspace、索引和查询接入

| 文件 | 作用 |
| --- | --- |
| `ms_graphrag/__init__.py` | Microsoft GraphRAG 接入包入口 |
| `ms_graphrag/prepare_workspace.py` | 把 LogicGuard corpus 导出到 GraphRAG `input/*.txt`，写数据来源 manifest |
| `ms_graphrag/minimal_workflow.py` | 写 `settings.yaml`、prompts 和 workflow；区分低成本 minimal 与可 official query 的 query-ready 索引 |
| `ms_graphrag/minimal_experiment.py` | 读取 GraphRAG `documents.parquet`，恢复原始 doc_id，在已索引文档上生成可审计实验 |
| `ms_graphrag/query_experiment.py` | 调用 official GraphRAG CLI 的 local/global/drift/basic query，并记录输出与超时 |
| `ms_graphrag/official_local_context.py` | 在 GraphRAG 隔离环境中直接导出 `LocalSearchMixedContext` 的 `context_data` |
| `ms_graphrag/official_context_recall.py` | 诊断 official local context 对 gold support 的召回 |
| `ms_graphrag/official_entity_diagnostics.py` | 检查 query/seed 实体是否进入 official context、社区和候选空间 |
| `ms_graphrag/official_query_metrics.py` | 将 query/回答 JSONL 聚合成 paper-friendly 指标，不调用 GraphRAG 或 LLM |
| `ms_graphrag/official_query_pipeline.py` | 顺序编排 official context 导出和 LogicGuard 回答时防御 |
| `ms_graphrag/local_defense_data.py` | 为小规模 official 实验构造 clean、poisoned、guarded、recovered 四套 corpus |
| `ms_graphrag/independent_graphs.py` | Stage18 为每个 query 单独准备 GraphRAG 图，并比较 mixed index 与 independent index |

### 7.2 查询层与 indexed artifact 防御

| 文件 | 作用 |
| --- | --- |
| `ms_graphrag/query_time_defense.py` | 读取 official `documents.parquet`/`text_units.parquet`，在回答前构造 poisoned、guarded、recovered evidence |
| `ms_graphrag/query_layer_seeding.py` | 不使用 gold 标签，按 query/title/BM25 构造 local search 实体 seed plan |
| `ms_graphrag/query_layer_context.py` | 将 seed plan 送入 official local context builder，导出 query-guard sources |
| `ms_graphrag/query_layer_evaluation.py` | 在检索完成后评价 query-layer context 的 support recall、changed exposure 和 source 数 |
| `ms_graphrag/stage21_medium_diagnostics.py` | 在 50-query official indexed artifacts 上做轻量、可审计 evidence 排序与恢复诊断 |

### 7.3 历史兼容入口

下列文件基本只做 import/转发，保留旧模块名可运行，不应被误认为存在两套实现：

| 兼容文件 | 当前真实实现 |
| --- | --- |
| `ms_graphrag/answer_level_verification.py` | `evaluation/answer_proxy.py` |
| `ms_graphrag/answer_level_llm_verification.py` | `evaluation/answer_generation.py` |
| `ms_graphrag/source_recovery.py` | `defense/oracle_recovery.py` |
| `ms_graphrag/non_oracle_source_recovery.py` | `defense/non_oracle_recovery.py` |
| `ms_graphrag/risk_non_oracle_source_recovery.py` | `defense/risk_aware_recovery.py` |
| `ms_graphrag/stage29_answer_audit.py` | `evaluation/answer_audit.py` |
| `ms_graphrag/stage31_answerability_ablation.py` | `evaluation/answerability_ablation.py` |
| `ms_graphrag/stage32_llm_comparison.py` | `evaluation/llm_comparison.py` |
| `ms_graphrag/stage34_answer_judge_audit.py` | `evaluation/judge_audit.py` |
| `ms_graphrag/stage35_source_enrichment.py` | `defense/source_enrichment.py` |
| `ms_graphrag/stage38_chain_completeness.py` | `defense/chain_completion.py` |
| `ms_graphrag/stage40_cross_dataset_audit.py` | `evaluation/cross_dataset_audit.py` |
| `ms_graphrag/stage46_answer_preflight.py` | `evaluation/answer_preflight.py` |
| `ms_graphrag/stage46_cross_dataset_answer_analysis.py` | `evaluation/cross_dataset_analysis.py` |
| `ms_graphrag/stage47_adaptive_attack.py` | `attack/adaptive.py` |
| `ms_graphrag/stage47_adaptive_attack_analysis.py` | `evaluation/adaptive_attack_analysis.py` |

## 8. `configs/` 导航

配置数量较多，不适合把每个 YAML 当成独立算法文件阅读。应按命名族理解：

| 配置族 | 内容 |
| --- | --- |
| `data.yaml` | 多数据集标准化入口 |
| `naive_rag_*` | BM25/dense/hybrid 基线 |
| `graphrag_baseline_*` | 早期轻量图基线 |
| `entity_swap_*`、`bridge_injection_*` | 本地可控攻击 |
| `logicguard_*` | 早期防御、阈值扫描和消融 |
| `logicpoison_official*` | clean/poisoned 数据对齐与完整性元数据 |
| `logicpoison_*stage2…8*` | official LogicPoison 的检索、防御、回答、Judge 和 non-oracle recovery |
| `ms_graphrag_stage9…46_*` | official GraphRAG workspace、查询层、source 防御、补证和回答验证 |
| `configs/experiments/stage47/` | 当前规范化的 Stage47 配置树 |
| `config_aliases.yaml` | 将 11 个旧 Stage47 平铺路径映射到新分层路径 |
| `stage19_experiment_registry.yaml` | 冻结实验注册表生成配置 |

Stage47 的目录结构最值得沿用：

```text
configs/experiments/stage47/
├── hotpotqa/
│   ├── context.yaml   冻结 clean official context
│   ├── attack.yaml    生成三类攻击
│   ├── answers.yaml   四种 context 的配对回答
│   ├── audit.yaml     本地确定性审计
│   └── judge.yaml     按需语义裁决
├── musique/           与 HotpotQA 同构
└── analysis.yaml      合并两个数据集
```

如果要知道某次实验的准确输入、阈值和输出，不要只看代码默认值，要看实际 YAML。例如 `risk_aware_recovery.py` 的通用默认 `entity_drift_threshold` 与 Stage43/47 冻结配置中的 `0.10` 可能不同，论文结论应以配置为准。

## 9. `tests/` 导航

测试文件采用“一个生产模块或一个阶段契约对应一个测试文件”的组织方式。

### 9.1 基础、数据、基线和本地攻击

| 测试文件 | 覆盖对象 |
| --- | --- |
| `test_core.py` | 配置、路径和基础 I/O/指标 |
| `test_data_pipeline.py` | 数据读取、标准化和产物写出 |
| `test_logicpoison_official.py` | clean/poisoned 对齐与完整性元数据 |
| `test_naive_rag_baseline.py` | BM25/dense/hybrid 与统一 trace |
| `test_graphrag_baseline.py` | 规则实体、NetworkX 建图和路径检索 |
| `test_entity_swap_attack.py` | Entity Swap |
| `test_bridge_injection_attack.py` | Bridge Injection/v2 |
| `test_multidataset_experiment.py` | 多数据集编排 |

### 9.2 早期防御与回答层

| 测试文件 | 覆盖对象 |
| --- | --- |
| `test_logicguard_defense.py` | 风险特征、重排、过滤与恢复 |
| `test_threshold_scan.py` | 阈值网格 |
| `test_ablation.py` | 防御信号消融 |
| `test_logicpoison_retrieval_experiment.py` | Stage2 检索对比 |
| `test_logicpoison_defense_experiment.py` | Stage3 official LogicPoison 防御 |
| `test_non_oracle_recovery.py` | Stage8 BM25 非 Oracle 恢复 |
| `test_llm_generation.py` | prompt、provider 假客户端和生成逻辑 |
| `test_answer_judge.py` | Judge prompt/解析 |
| `test_answer_judge_runner.py` | Judge 运行器 |
| `test_logicpoison_answer_eval.py` | official LogicPoison 回答层 |
| `test_stage6_summary.py` | Stage6 聚合 |
| `test_stage8_recovery_merge.py` | Stage8 回答合并 |
| `test_chinese_reports.py` | 中文报告转换 |
| `test_experiment_registry.py` | 冻结注册表和哈希审计 |

### 9.3 Microsoft GraphRAG 与 Stage21–47

| 测试文件 | 覆盖对象 |
| --- | --- |
| `test_ms_graphrag_prepare.py` | workspace 文档导出 |
| `test_ms_graphrag_minimal_workflow.py` | minimal/query-ready settings |
| `test_ms_graphrag_minimal_experiment.py` | indexed documents 读取 |
| `test_ms_graphrag_query_experiment.py` | official CLI query |
| `test_ms_graphrag_local_defense_data.py` | 四种 defense corpus |
| `test_ms_graphrag_independent_graphs.py` | mixed/independent graph |
| `test_ms_graphrag_official_local_context.py` | official context 导出 |
| `test_ms_graphrag_official_context_recall.py` | context support recall |
| `test_ms_graphrag_official_entity_diagnostics.py` | 实体候选诊断 |
| `test_ms_graphrag_official_query_metrics.py` | official query 指标 |
| `test_ms_graphrag_official_query_pipeline.py` | context→defense 编排 |
| `test_ms_graphrag_query_time_defense.py` | indexed text-unit 防御 |
| `test_ms_graphrag_query_layer_seeding.py` | 非 gold 实体 seeding |
| `test_ms_graphrag_query_layer_context.py` | query-layer context |
| `test_ms_graphrag_query_layer_evaluation.py` | query-layer 指标 |
| `test_ms_graphrag_stage21_medium_diagnostics.py` | Stage21 中规模诊断 |
| `test_ms_graphrag_source_recovery.py` | Stage23 oracle source recovery |
| `test_ms_graphrag_non_oracle_source_recovery.py` | Stage25 non-oracle source recovery |
| `test_ms_graphrag_stage26_answer_verification.py` | Stage26 answer proxy |
| `test_ms_graphrag_stage27_answer_llm_verification.py` | Stage27 真实回答 |
| `test_ms_graphrag_stage28_risk_non_oracle_recovery.py` | Stage28/43 风险检测与恢复 |
| `test_ms_graphrag_stage29_answer_audit.py` | Stage29 审计 |
| `test_ms_graphrag_stage31_answerability_ablation.py` | Stage31 可答性消融 |
| `test_ms_graphrag_stage32_llm_comparison.py` | Stage32 LLM 比较 |
| `test_ms_graphrag_stage34_answer_judge_audit.py` | Stage34 Judge 审计 |
| `test_ms_graphrag_stage35_source_enrichment.py` | Stage35/44 clean 补证 |
| `test_ms_graphrag_stage38_chain_completeness.py` | Stage38/45 链完整性 |
| `test_ms_graphrag_stage40_cross_dataset_audit.py` | Stage40 跨数据集就绪审计 |
| `test_ms_graphrag_stage46_answer_preflight.py` | Stage46 prompt 暴露预检 |
| `test_ms_graphrag_stage46_cross_dataset_answer_analysis.py` | Stage46 配对分析 |
| `test_ms_graphrag_stage47_adaptive_attack.py` | 三类攻击生成、约束和防御矩阵 |
| `test_ms_graphrag_stage47_adaptive_attack_analysis.py` | 严格分母、ASR 和跨数据集汇总 |

## 10. `scripts/`、`tools/` 和 `lib/` 导航

### 10.1 维护和批量脚本

| 文件 | 作用 |
| --- | --- |
| `scripts/build_report_manifest.py` | 为旧 Markdown 报告生成大小、SHA-256、分类和归档位置清单 |
| `scripts/update_experiment_registry.py` | 幂等补写 Stage21 之后的实验里程碑到 `docs/实验注册表.csv` |
| `scripts/cleanup_generated_artifacts.py` | 默认 dry-run 盘点 GraphRAG cache；仅 `--apply` 删除经过白名单验证的 cache |
| `scripts/run_stage7_graph.ps1` | 批量运行三数据集 Stage7 graph-surrogate 回答与 Judge |
| `scripts/run_stage8_answer.ps1` | 批量运行 Stage8 non-oracle recovery 回答、Judge 和合并，带日志 |

### 10.2 可视化和 GraphRAG 环境

| 文件/目录 | 作用 |
| --- | --- |
| `tools/visualize.py` | 单 query 轻量图、NaiveRAG、official GraphRAG、guard/recovery 对比可视化 |
| `tools/visualize_comprehensive.py` | 论文级架构、检索、攻击、防御、恢复退化、消融和综合仪表盘 |
| `tools/generate_knowledge_graph_contrast_visualization.py` | 读取 clean/poisoned GraphRAG 实体关系和 Stage21 trace，生成知识图谱与单 query 路径对比 HTML |
| `tools/generate_showcase_visualizations.py` | 读取既有 CSV/JSONL/Parquet，生成中文组会/论文展示页面 |
| `tools/generate_stage43_47_visualization.py` | 读取冻结 Stage46/47 artifacts，生成 detector、recovery、三类自适应攻击和 `75→35→21→19` 漏斗的独立 HTML |
| `tools/ms_graphrag/pyproject.toml` | official GraphRAG 隔离环境依赖定义 |
| `tools/ms_graphrag/uv.lock` | 隔离环境冻结依赖 |
| `lib/vis-9.1.2/` | 图网络可视化 JS/CSS |
| `lib/tom-select/` | HTML 下拉选择控件 |
| `lib/bindings/utils.js` | 可视化页面的绑定辅助代码 |

## 11. `docs/` 与 `artifacts/` 导航

### 11.1 项目文档

| 文件 | 作用 |
| --- | --- |
| `docs/thesisPlan.md` | 论文问题、章节和实验计划 |
| `docs/methodology.md` | Stage1–47 方法、威胁模型和实验边界 |
| `docs/results.md` | Stage1–47 的统一结果总报告 |
| `docs/reproducibility.md` | 环境、成本等级、命令和复现注意事项 |
| `docs/开发记录.md` | 按时间/阶段记录开发与实验推进 |
| `docs/实验注册表.csv` | 每个重要实验的 ID、输入、配置、输出、结论和限制 |
| `docs/progressReview.md` | 第三方审核意见及待回应问题 |
| `docs/report_manifest.csv` | 历史报告 SHA-256 与合并去向 |
| `docs/report_archive.sha256` | 历史报告压缩包摘要 |
| `docs/legacy_document_manifest.csv` | 过时/历史文档清单 |
| `docs/codeNavigation.md` | 本文档：代码与概念导航 |

### 11.2 精选实验产物

| 目录 | 内容 |
| --- | --- |
| `artifacts/attacks/` | Stage47 HotpotQA/MuSiQue 的冻结攻击 records 和 no-oracle integrity rows |
| `artifacts/reports/` | 当前保留的 Stage47 中文主报告及说明 |
| `artifacts/results/` | Stage40 readiness、Stage46 回答和 Stage47 自适应攻击的 summary/examples |
| `artifacts/visualizations/` | 从冻结 artifacts 生成、可直接在浏览器打开的独立研究可视化 |

这些是从完整 `outputs/` 中精选出的轻量证据。CSV 通常看总体指标，JSONL examples 用于逐例追溯 source、prompt、回答和攻击目标。

## 12. 之前在 LogicGuard 中构建过知识图谱吗？

结论：**构建过，而且有两种不同层次的知识图谱实现。**

### 12.1 第一种：早期自研轻量文档—实体图

主要代码：

- `src/logicguard/graph/entities.py`
- `src/logicguard/graph/builder.py`
- `src/logicguard/graph/retriever.py`
- `src/logicguard/graph/baseline.py`

其结构是 NetworkX 无向二部图：

```text
doc:<文档ID>  --mentions-->  ent:<规范化实体>
```

实体从标题和正文中用规则抽取。检索时先从 query 抽实体，再在图上做最短路径搜索。最大深度为 3 时，可以得到：

```text
query entity → document A → bridge entity → document B
```

这套图的价值是便宜、确定性强、路径完全可解释，适合早期实现攻击钩子、bridge risk 和 trace；它不是 Microsoft GraphRAG，也没有 LLM 生成的实体描述、关系摘要和社区报告。运行时主要保存实体 cache 和路径 trace，而不是把 NetworkX 图作为当前生产索引长期保存。

### 12.2 第二种：Microsoft GraphRAG official 知识图谱

主要代码：

- `src/logicguard/ms_graphrag/prepare_workspace.py`
- `src/logicguard/ms_graphrag/minimal_workflow.py`
- `src/logicguard/ms_graphrag/official_local_context.py`
- `src/logicguard/ms_graphrag/query_layer_*.py`
- `tools/ms_graphrag/`

流程是：

```text
LogicGuard corpus
  → workspace/input/*.txt
  → GraphRAG extract_graph / extract_graph_nlp
  → entities + relationships
  → communities + community reports
  → embeddings / LanceDB
  → official LocalSearchMixedContext
```

典型索引产物包括：

- `documents.parquet`
- `text_units.parquet`
- `entities.parquet`
- `relationships.parquet`
- `community_reports.parquet`
- `output/lancedb/`

项目不只是“读取别人已经建好的图”。`prepare_workspace.py` 和 `minimal_workflow.py` 会为 clean、poisoned、不同数据集和不同 query 规模准备独立 workspace，随后由 official GraphRAG 环境执行索引。Stage41 还为 HotpotQA、MuSiQue 补建了 clean/poisoned query-ready workspace。

### 12.3 知识图谱与当前 LogicGuard 防御的真实关系

当前核心防御主要工作在 **GraphRAG 已经检索出的 source/context 之后**：

- Stage43 对 source 做风险检测和 clean-candidate recovery；
- Stage44 从 clean candidate pool 追加 source；
- Stage45 补充缺失的二跳证据；
- Stage46/47 检查实际 prompt 和回答。

因此，LogicGuard 用到了知识图谱产生的 indexed artifacts 和 official context，但 Stage43–47 的核心并不是修改 GraphRAG 的建图算法本身，而是做 query-time/post-retrieval 防御。

## 13. 自适应攻击是什么？

一般意义上，自适应攻击指：**攻击者知道或近似知道防御规则，并专门构造输入去绕过这些规则或利用恢复机制。** 它比固定攻击更能检验防御是否真的鲁棒。

在 LogicGuard 中，Stage47 冻结 Stage43–46 的参数后，设计了三类攻击：

### 13.1 低实体漂移 `low_drift`

- 保留 source 标题和大部分命名实体；
- 只篡改关系、日期、数值或属性；
- 目标是让 `entity_drift < 0.10`，绕过 Stage43 的实体漂移检测。

它攻击的是 detector 的特征盲区：**实体没怎么变，不等于事实关系没变。**

### 13.2 候选碰撞 `candidate_collision`

- 故意构造一个能被判风险的 source；
- 让标题精确碰撞某个错误 trusted candidate；
- 诱导 recovery 把攻击 source 替换成攻击者选择的错误 clean source。

它不追求绕过检测，而是攻击“检出后一定能正确恢复”的假设。Stage47 严格有效的 5 个样本都被检测，但 5/5 都恢复到了被攻击者诱导的非 gold candidate；回答 ASR 降为 0，不代表恢复结构正确。

### 13.3 无可信对应源自然桥接 `natural_bridge`

- 注入语言自然、与 query 相关的新 source；
- trusted candidate pool 中没有一一对应的 clean counterpart；
- 利用当前 `candidate is None → is_risky=False` 的默认行为。

这是 Stage47 暴露出的最大缺口。MuSiQue 上 Stage43 对这类攻击没有直接检出能力；Stage44/45 追加 clean evidence 只能稀释攻击影响，不能可靠移除攻击 source。

### 13.4 Stage47 攻击者知道什么、不知道什么

攻击生成器可以看到：

- query；
- clean official GraphRAG 已检索 sources；
- query BM25 排出的 clean candidate 摘要。

攻击生成时看不到：

- gold answer；
- gold support doc IDs；
- `changed_support_doc_ids`；
- “某 source 已污染”等 benchmark 标签。

这些标签只在攻击记录冻结后用于评测 join，避免把 oracle 信息泄漏给攻击生成器。

### 13.5 Stage47 能证明什么，不能证明什么

Stage47 是 **post-retrieval source perturbation**：先从 clean official GraphRAG 取回 sources，再在 source 层施加扰动，然后运行冻结防御和回答链路。

它能验证：

- detector 是否漏检；
- recovery 是否被诱导；
- enrichment/second-hop 是否只是稀释攻击；
- 恶意答案是否进入实际截断后的 prompt；
- LLM 是否命中攻击目标。

它不能证明：

- 污染文档经过 GraphRAG 重建索引后一定会被检索；
- 攻击会如何改变实体/关系抽取、embedding、community 和 community report；
- 攻击会如何改变原始检索排名。

完整的“污染 corpus → 重新建图/索引 → official 检索 → LogicGuard → 回答”应由 Stage48 完成。

## 14. 当前实现最重要的三个判断

1. **LogicGuard 已经较好处理固定 LogicPoison 攻击，但不能据此宣称自适应鲁棒。** Stage46 上 Stage43–45 的最终 ASR 为 0；Stage47 已证明自然桥接和低漂移仍可绕过。
2. **`candidate=None` 代表无法核验，不代表安全。** 当前实现把无 counterpart source 当作安全，是最明确的设计缺口。
3. **“检测成功”“恢复正确”“回答没中攻击目标”是三件事。** 候选碰撞显示：可以检测成功、恢复错误，但最终回答暂时没有命中攻击目标。论文必须分别报告。

## 15. 后续复盘和推进建议

### 第一轮：读懂现状

- 先读 `handoff.md` 和 Stage47 报告；
- 再按 Stage43 → 44 → 45 → 46 → 47 阅读核心实现；
- 用对应测试确认每个模块的输入输出契约；
- 用 `artifacts/results/stage47_adaptive_attack_examples.jsonl` 做逐例追踪。

### 第二轮：补齐端到端证据

- 冻结 Stage47 已成功攻击，不重新随机生成；
- 把攻击写回完整 corpus，记录 clean/poisoned corpus hash；
- 为三类攻击分别重建 official GraphRAG index；
- 测量建图变化、检索命中、排序、截断后暴露，再调用回答模型；
- 先运行原封不动的 Stage43–45，建立 Stage48 基线后再改防御。

### 第三轮：针对机制缺口改进

- 给无 counterpart source 增加“不确定/隔离/多源验证”分支；
- 增加关系、属性、数值和时间一致性特征，不能只看实体集合漂移；
- 为 recovery 增加候选身份与关系一致性约束，单独评估 wrong-recovery rate；
- 将 Stage45 保持为条件触发，避免无差别扩充 context；
- 始终同时报告生成有效、评测有效、实际 prompt 暴露、broad ASR、targeted ASR 和恢复正确性。
