# Stage30 项目整理与报告整合

更新日期：2026-07-02

## 目标

Stage30 不改变实验算法、不重跑外部 LLM，也不删除支撑结论的原始结果。它只做三件事：

1. 收束阅读入口，让后续优先阅读一个总报告和一个索引。
2. 标注重复/阶段性报告的角色，避免在 smoke、formal、summary 报告之间反复查找。
3. 给出安全清理清单，区分可以清理的缓存、可以归档的大产物、暂不应删除的证据文件。

## 推荐阅读入口

| 优先级 | 文件 | 用途 |
| ---: | --- | --- |
| 1 | `outputs/reports/实验结果总报告.md` | 当前唯一主报告，保留 Stage1-37 的核心结论和关键指标。 |
| 2 | `outputs/reports/Stage30_项目整理与报告整合.md` | 报告索引、归档规则、清理建议。 |
| 3 | `outputs/reports/Stage29_AnswerAudit_20QueryFormal.md` | Stage29 回答层审计的详细过程、样例和 source 片段。 |
| 4 | 各阶段综合报告 | 审计证据；需要追溯某阶段时再打开。 |
| 5 | 各阶段 5-query smoke / 20-query formal 单项报告 | 历史子报告；默认不作为读者入口。 |

## 报告整合表

| 阶段 | 主入口 | 子报告处理方式 | 保留理由 |
| --- | --- | --- | --- |
| Stage23 | `Stage23_官方GraphRAG_Sources级Recovery_5Query实验报告.md` | 保留为早期 official sources recovery 证据。 | 只有 5-query 单项结果，体积很小。 |
| Stage24 | `Stage24_官方GraphRAG_Sources级Recovery_20_50Query综合报告.md` | 20/50-query 单项报告、seed 审计和 context 导出报告视为子证据。 | 综合报告已覆盖主要结论；子报告用于追溯产物路径和 seed 审计。 |
| Stage25 | `Stage25_官方GraphRAG_NonOracleSourcesRecovery_20_50Query综合报告.md` | 20/50-query 单项报告视为子证据。 | 综合报告已覆盖 non-oracle recovery 结论。 |
| Stage26 | `Stage26_官方GraphRAG_AnswerProxy_5_20Query综合报告.md` | 5-query smoke 和 20-query 单项报告视为子证据。 | 综合报告已覆盖 proxy 层结论。 |
| Stage27 | `Stage27_OfficialGraphRAG_LLMAnswer_5_20Query_Summary.md` | 5-query smoke 和 20-query formal 报告视为子证据。 | 综合报告已覆盖真实 LLM 回答层第一轮结果。 |
| Stage28 | `Stage28_RiskNonOracle_5_20Query_Summary.md` | source recovery、answer proxy、LLM answer 单项报告视为子证据。 | 综合报告已覆盖 risk-non-oracle + recovery-non-oracle 主结论。 |
| Stage29 | `Stage29_AnswerAudit_20QueryFormal.md` | 保留为详细正式报告。 | 包含逐样本流程、source 片段和错误归因，不能只看 CSV。 |
| Stage1-37 全局 | `实验结果总报告.md` | 作为唯一主叙事入口。 | 用于导师汇报和论文阶段复盘。 |
| Stage37 | `Stage37_EvidencePrompt_20Query_中文综合报告.md` | 保留为 Stage37 详细分析入口。 | 解释 prompt-only 复验为何未继续提升 utility，并定位剩余二跳证据链瓶颈。 |

## 当前规模判断

扫描结果显示，项目“显得杂”的主要来源不是源码，而是实验产物：

- `outputs` 约 599 MB，4419 个文件，是主要膨胀来源。
- `data` 约 33 MB。
- `src` 约 0.82 MB，源码本身不大。
- `configs` 有 95 个配置文件，但总体约 0.11 MB，主要是命名和阶段数量造成视觉负担。

因此 Stage30 不建议优先删源码，而应先处理 `outputs` 的索引、重复产物和缓存。

## 可安全清理

| 类别 | 路径 | 建议 |
| --- | --- | --- |
| Python 缓存 | `**/__pycache__`、`*.pyc` | 可删除；不影响实验结论，可由 Python 自动再生成。 |
| pytest/ruff 缓存 | `.pytest_cache`、`.ruff_cache` | 可删除；只影响下一次工具运行速度。 |
| 完全重复 context 文件 | `stage24_poisoned20_query_guard_contexts.jsonl` 与 `stage24_poisoned20_query_guard_contexts_full_query_guard.jsonl` | 暂不删除；在 manifest 中标为可归档候选，避免破坏旧路径引用。 |
| 完全重复 context 文件 | `stage24_poisoned50_query_guard_contexts.jsonl` 与 `stage24_poisoned50_query_guard_contexts_full_query_guard.jsonl` | 暂不删除；在 manifest 中标为可归档候选。 |

## 暂不应删除

| 类别 | 原因 |
| --- | --- |
| `outputs/ms_graphrag_query/stage23` 到 `stage29` 的 summary/metrics/results/examples | 支撑总报告关键数字，可复现实验结论依赖这些产物。 |
| `outputs/reports` 下的阶段综合报告 | 虽然部分内容被总报告吸收，但仍是阶段审计证据。 |
| `configs` 下的历史 YAML | 体积很小，并且对应可复现实验命令；删除会削弱复现链。 |
| `src/logicguard/ms_graphrag` 的阶段模块 | 多数被测试、配置或文档引用；当前不适合直接删。 |

## 代码整理结论

源码层面没有发现可以无风险删除的大文件。更合适的后续做法是抽公共逻辑，而不是删阶段脚本：

| 候选重复区域 | 建议 |
| --- | --- |
| `source_recovery.py`、`non_oracle_source_recovery.py`、`risk_non_oracle_source_recovery.py` | 抽出 `source_utils.py` / `recovery_common.py`，复用 source parsing、doc_id、render context、summary 写入逻辑。 |
| `answer_level_verification.py`、`answer_level_llm_verification.py`、`stage29_answer_audit.py` | 抽出 `answer_utils.py`，复用答案归一化、拒答检测、答案匹配和报告表格生成。 |
| `run_bridge_injection.py`、`run_entity_swap.py` | 后续可合并 CLI runner 框架，但不是当前主线瓶颈。 |
| `run_ablation.py`、`run_threshold_scan.py` | 后续可抽 defense experiment runner 公共配置。 |

## Stage30 已执行动作

1. 修复 `src/logicguard/graph/baseline.py` 第一行历史语法错误，使全量 pytest 可以重新作为安全网。
2. 新增 `outputs/reports/Stage30_项目整理与报告整合.md` 作为报告索引。
3. 新增 `outputs/reports/stage30_report_inventory.csv`，标注报告主入口、子报告和归档证据。
4. 新增 `outputs/reports/stage30_cleanup_manifest.csv`，标注可清理、可归档、需保留对象。
5. 更新 README、总报告、路线图和可复现实验命令清单，将 Stage30 作为项目整理阶段记录。

## 后续建议

Stage31 已完成 recovery 后的 source ordering / top-k / prompt answerability 离线消融；Stage32 完成真实 LLM 小规模复验，确认 `title_query_overlap` 能把 utility 从 `0.1500` 提升到 `0.2500` 且不引入 attack success；Stage33 已将该排序策略固化进 answer generation / audit pipeline，审计后 utility 达到 `0.3000`。Stage34 增加 judge-aware answer audit，只对 uncertain incorrect row 调用 LLM judge，最终 utility 达到 `0.3500`，incorrect 和 attack success 均为 `0.0000`。Stage35 完成 source enrichment 离线诊断，`query_bm25_append + top-12` 将 support answer surface 从 `0.5500` 提升到 `0.7500`，clean answerable rate 达到 `0.8000`。Stage36 完成 enriched contexts 真实 LLM 复验，judge-aware final utility 达到 `0.8500`，attack success 仍为 `0.0000`。Stage37 完成 evidence prompt 复验，final utility 与 Stage36 持平，说明剩余瓶颈更偏向 evidence-chain completeness。后续建议进入 Stage38：新增 chain-completeness 诊断和 second-hop targeted append，再继续推进跨数据集扩展和自适应攻击。
