# WP2 D3/D4 外部防御资格报告

_2026-09-10；comparison-v1.2；模型/工件小样本资格，不是后端攻击防御效果实验。_

---

## 📋 Material passport

| 字段 | 内容 |
| --- | --- |
| Origin skill | academic-research-suite / experiment-agent；markdown-mermaid-writing |
| 事实源 | `F:\LogicGuard_project\logicguard` |
| 配置 | `configs/benchmark/comparison_v1_2_external_defense_qualification_anchor.yaml` |
| 入口 | `logicguard.benchmark.external_defense_qualification` |
| 有效产物 | `artifacts/benchmark/research_revision_v1_2/wp2/d3_d4_external_defense_qualification_anchor_v5/` |
| 历史诊断 | 无后缀至 `_v4` 均保留；v2 修正排列门语义，v3 记录 Stella 依赖失败，v4 尚未把 runner hash 纳入 identity，均不覆盖 |
| Provider 调用 / 新增费用 | 0 / ¥0 |

## 🎯 资格问题

本轮只回答两个问题：D3 是否真的加载了固定权重并执行论文发布工件的过滤路径；D4 固定上游提交是否具备可运行的检测与修复主路径。它不回答 D3/D4 在 LogicGuard 三数据集、双 GraphRAG 后端上的攻击缓解率，也不用于比较 LogicGuard 优劣。

## 📊 D3 RAGDefender 结果

固定上游提交为 `ba2a17efba165d45409114df2d70b030ade1e1b8`。论文发布工件 `artifacts/main.py` 显式使用 `sentence-transformers/paraphrase-MiniLM-L6-v2`，因此主锚点固定模型 revision `c9a2bfebc254878aee8c3aca9e6844d5bbb102d1`，加载 384 维权重 `model.safetensors`：90,868,373 bytes，SHA-256 `2ce4480dc3b2f8edeee50c43765c72768e79fc0113d3f73773dded4887cca298`。

运行器从固定 `artifacts/main.py` 与 `artifacts/src/utils.py` 提取并执行原函数 AST，同时执行固定仓库 v0.2.0 公共 API。两条官方 regression fixture 上，`N_adv` 和删除索引逐条完全一致。

| Fixture | 任务类型 | 文档数 | `N_adv` | 删除索引 | Precision | Recall | F1 |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| `legacy_v011_singlehop.json` | single-hop | 6 | 3 | `[0,3,5]` | 0.667 | 0.667 | 0.667 |
| `legacy_v011_multihop.json` | multi-hop | 5 | 3 | `[1,3,4]` | 0.667 | 1.000 | 0.800 |

允许标签为 `RAGDefender_published_artifact_implementation`，且正式执行必须冻结并保留后端原始检索顺序。single-hop fixture 反序后有一个删除文档发生变化；multi-hop fixture 按文本集合保持一致。因此，D3 可进入 development 比较，但必须把顺序敏感性作为实现属性报告，不能宣称 passage-order invariant。

另一个不能隐去的差异是：发布工件的 multi-hop 计算使用 `OR`、移位 median threshold 和 result-flip，而论文文字描述的是 `AND/median`。当前锚点证明“发布工件可执行且包接口与它一致”，不证明“论文公式逐字忠实”。

固定库文档另称 Stella 为论文模型，因此增加了不替代主锚点的模型敏感性运行。`dunzhang/stella_en_1.5B_v5@781706...` 的最小可运行快照实际为 6,191,135,894 bytes；主权重 SHA-256 为 `222c4379...46471`，1024 维投影权重 SHA-256 为 `59f17a69...e94f`。完整仓库 dry-run 为 32.2 GB，与上游 README 的约 1.5 GB 描述不一致。

Stella 使用模型自带记录的 `sentence-transformers 3.0.1 + transformers 4.42.3` 运行。两条 fixture 的工件/API 输出一致、反序一致，且 Precision/Recall/F1 均为 1.0。该 2 条合成 fixture 结果只证明权重与路径可执行，并显示 embedder 选择能改变结果；不得解释为 Stella 的总体性能或相对 MiniLM 的稳定优势。

## 🚫 D4 HoG-GRAG 结果

固定上游提交 `b3197f5cb03b161ce4d29365ab73f1b3ed3adb02` 未通过 paper-native 可执行门：

- `Src/repairer.py` 第 304 行触发 `IndentationError: unexpected indent`
- `get_response.md` 未发布
- `prompts/response_subquestion.md` 未发布
- 源码绑定 `gpt-5-mini`，但在编译与提示词前置条件失败后未发起调用

因此 D4 当前 `comparison_eligibility=unavailable`。这不是“HoG-GRAG 防御无效”的负结果，只是固定公开工件无法支持 paper-native 执行。进入防御比较前必须取得作者修正版，或单独预注册一个有明确差异表、提示词来源、调用预算和行为测试的 bounded reimplementation；后者不能标作官方复现。

## ✅ 决策与下一任务

D3 的发布工件模型与库文档声明模型均完成真实权重锚点；正式主标签仍采用发布工件实际 MiniLM 配置，并冻结检索顺序。D4 官方工件资格失败并已 fail-closed。两者都没有产生后端效果结论。

下一项开发任务回到既定 WP2 路线：冻结完整 dev60 的 A1/A2/A3 请求、模型、最大调用数、token/费用 hard cap、停止规则和 materialization manifest，再一次性执行 60 问攻击语料。D4 bounded reimplementation 作为进入外部防御效果比较前的独立阻塞项，不应通过修改本轮官方工件产物来伪装解决。
