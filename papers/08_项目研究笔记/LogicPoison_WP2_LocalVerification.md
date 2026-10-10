# LogicPoison WP2 本地链路验收

_2026-09-08；恢复中断任务，完成 A2 工程链路与本地锚点，尚未完成 WP2 全部比较实验。_

---

## 📋 Material Passport

| 字段 | 内容 |
| --- | --- |
| Origin skill | academic-research-suite / experiment-agent；markdown-mermaid-writing |
| Origin mode | 用户已批准的开发与本地验证 |
| Verification status | 本地运行 VERIFIED；真实攻击效果 UNVERIFIED |
| Version | comparison-v1.2 / WP2-A2-local |
| 唯一开发目录 | `F:\LogicGuard_project\logicguard` |

## 📍 已完成的范围

中断前留下的 `logicpoison_pipeline.py`、`logicpoison_corpus.py`、合成 fixture 和 20 项测试已经存在，但交接文档仍停在 WP1。本轮先验证原有测试，再补上参数边界、合成结果标签与运行身份记录，完成两个本地锚点。没有重新生成 Stage48 样本，也没有修改 v1.1 runner 的历史行为。

| 阶段 | 本轮可执行能力 | 产物 |
| --- | --- | --- |
| global | text-only NER、括号预处理、稳定频率排序 | `global_stats.json` |
| query | question-only、有界单次提取、严格字段检查、逐请求 checkpoint | `query_entities.jsonl` |
| logic | 频率前 5% 与 query 实体组成类型内池，反向循环映射 | `replacement_plan.json` |
| corpus | 单次最长优先边界替换、保留 ID/title、记录变更位置与前后 hash | `corpus.jsonl`、`changed_documents.jsonl` |

入口为 [logicpoison_pipeline.py](../../src/logicguard/benchmark/logicpoison_pipeline.py)，纯语料逻辑见 [logicpoison_corpus.py](../../src/logicguard/benchmark/logicpoison_corpus.py)。源码机制依据是本地固定版本的 `vendor/upstream/LogicPoison/src/global_poison.py`、`query_centric.py`、`logic_poison.py`，不是根据论文名称猜测的替代算法。

## 📊 实际运行结果

| 锚点 | NER | query 提取 | 文档变更 | 替换次数 |
| --- | --- | --- | ---: | ---: |
| synthetic anchor | 显式合成 fixture | 2 条合成响应 | 3/4 | 7 |
| trained-NER anchor | `en_core_web_trf 3.8.0` | 2 条合成响应 | 3/4 | 7 |

两个命令均退出 0，状态 `CORPUS_MATERIALIZED`，完成四个阶段。两个锚点使用不同的合成文本，不应把相同计数解释为真实数据上的复现一致性。trained-NER anchor 的文本字节从 195 改为 192；synthetic anchor 为 114→114。数据集字段 `hotpotqa` 只是接口测试标签，问题均为专门编写的 synthetic fixtures，不是 HotpotQA 正式样本。

结果明确标记 `corpus_materialization_valid=true`、`generation_valid=false`、`evaluation_valid=null`、`attack_effect_measured=false`、`paper_faithful_certified=false`。因此，本轮证明代码链路可以运行，不能推断 ASR、clean-correct flip、GraphRAG 传播效果或防御排名。

产物目录分别为：

- `artifacts/benchmark/research_revision_v1_2/wp2/logicpoison_synthetic_anchor/`
- `artifacts/benchmark/research_revision_v1_2/wp2/logicpoison_trf_anchor/`

各目录保存 manifest、checkpoint、summary 及四阶段产物，manifest 记录输入、实现、请求构建、dispatch 和 provider 源码 hash。真实 NER manifest 另外保存 Python、spaCy、torch、模型包版本及模型文件 hash 清单，不允许静默替换成 `en_core_web_lg` 或 `en_core_web_sm`。

## 🔍 验证与边界

相关测试共 `44 passed, 1 deselected`：其中 A2 新链路 32 项、WP1 审计/指标 8 项、历史 A1/A2/A3 runner 的无网络函数回归 4 项。跳过会写入旧 validation dry-run namespace 的一项；未重跑会改写旧 E0/E1 readiness 的测试。`ruff check src tests` 通过，`ruff format --check src tests` 为 195 files already formatted。11 个 WP1 受保护历史文件 hash 全部未变。

覆盖的关键行为包括：

- 对无歧义 fixture，映射和改写后的逐文档 JSON 与固定 upstream `logic_poison.py` 一致；同词跨类型歧义明确拒绝，而非后写覆盖。
- 同源文档 ID/title 保留，最长匹配与单遍替换不发生级联，非实体前缀不误替换，变更 provenance 可回溯。
- 文档数、变更比例、替换次数、最终语料字节预算在发布语料前检查；超预算不偷偷裁剪攻击。计数必须为整数、比例不得超过 1。
- query/corpus 采用字段白名单，拒绝 evaluator 标签；运行只允许 development 和新的 v1.2 WP2 子目录。
- API 前持久化费用预留；成功返回后按 usage 核账。缺失 usage、异常、超限或残留 in-flight 请求停止，不能自动重试重复计费。
- 已完成 query 在可安全恢复的中断后不重发；已完成 namespace 重入只做身份/hash 核验，不重新执行请求。代码、输入或配置改变时禁止混接旧断点。
- provider 异常只保存异常类型，不把错误正文中的潜在凭据写入产物。

费用门是基于配置 token/价格上限的请求准入控制。UTF-8 字节加 framing 余量只是输入估计，不是 provider tokenizer 的已认证上界；服务端偏离上限时本次可能已产生费用，代码会记录违例并停止后续请求，不能声称具有服务端绝对账单封顶保证。

强制终止留下的 `run.lock` 不自动删除或抢占；必须先检查原进程及 checkpoint。语料通过最终 summary/hash 验收后才可供后端消费，不能仅检查 `corpus.jsonl` 是否存在。

## ⚠️ 与官方方法的差异和剩余工作

保留的适配差异包括：query 阶段改成严格 JSON 与单次有界请求；按冻结问题顺序处理，而非上游线程完成顺序；同词跨类型映射拒绝；攻击输出不复制 answers/qrels。当前替换仍然是实体表面字符串级，不是逐位置重新做语义类型验证。NER 模型一致不等于 query LLM 或攻击强度已与论文一致。

WP2 全部任务尚未完成。下一实施项是 T0/T1 共享可信池与等预算对照；同时还需 A1/A3 机制资格、D3/D4 论文模型锚点、真实 dev60 query 提取和污染语料、双后端 clean/attacked 回答及完整成本门。现有两组本地锚点不能代替这 60 个开发问题的实验。正式独立确认集、D6 四组件和大规模排名仍未解锁。

## 🔧 复现与费用

命令及依赖详见主入口 [reproducibility.md](../../docs/reproducibility.md)。本轮在 LogicPoison 隔离环境中仅增加 `PyYAML==6.0.3`，未升级 NER、torch 或主环境。真实 NER 使用已有本地权重，设置离线模式；出现 upstream torch 权重加载 FutureWarning，但进程成功退出，没有下载模型。

两个锚点共 4 次模拟 query 响应；真实 provider 请求 0，新增费用 ¥0。`fixture_simulated_catalog_cost_cny` 每锚点 0.0012 只是测试账本数值，不是已产生的费用；不得累加到历史付费总额。
