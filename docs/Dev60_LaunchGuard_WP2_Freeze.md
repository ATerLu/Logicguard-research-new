# WP2 dev60 Launch Manifest 与 Request/Cost Guard 冻结报告

_冻结日期：2026-09-24；协议：comparison-v1.2；本轮为离线执行门，不调用 provider、不生成攻击、不建立索引。_

## Material passport

| 字段 | 内容 |
| --- | --- |
| 事实源 | `F:\LogicGuard_project\logicguard` |
| 配置 | `configs/benchmark/comparison_v1_2_dev60_launch.yaml` |
| 冻结入口 | `python -m logicguard.benchmark.dev60_launch` |
| 费用守卫 | `logicguard.benchmark.request_cost_guard.RequestCostGuard` |
| 主要产物 | `artifacts/benchmark/research_revision_v1_2/wp2/dev60_launch_v1/` |
| Launch fingerprint | `c8fa1ced0771501f707e50454c841c7fd82275c67788dcf83d9ae6a1f7a003e6` |
| 证据状态 | launch identity、固定分母、最坏请求成本和停止语义已冻结；paid runner 绑定与攻击效果尚未验证 |
| Provider 调用 / 新增费用 | 0 / ¥0 |

## 冻结结果

| 项目 | 冻结值 |
| --- | ---: |
| 数据集 | HotpotQA、MuSiQue、2WikiMultihopQA |
| development 问题 | 60；每数据集 20 |
| 攻击尝试 | 180；每个 dataset × attack 单元固定 20 |
| A1 请求槽 | 60 |
| A2 请求槽 | 60 |
| A3 请求槽 | 180 |
| 最大 provider 调用 | 300 |
| 最大输入 tokens | 1,530,000 |
| 最大输出 tokens | 702,720 |
| 最坏目录价预留 | ¥8.681760 |

攻击生成在两个后端之间共享同一冻结 attack seed；后端运行不会重新生成攻击。generation-invalid 仍保留在 fixed-attempted 分母，不能观察攻击成功后替换问题。A3 后两阶段绑定前一阶段 request slot，前序 schema 无效时只能以声明的原因跳过，不能继续调用或补样。

模型请求字符串冻结为 `qwen3.7-plus`，关闭 thinking，禁止 provider retry，使用 `max_completion_tokens`。百炼未暴露可固定的底层权重 revision，因此 manifest 明确记录 `provider_managed_alias_no_immutable_revision_exposed` 和观察日期；这是一项可复现性限制，不伪造模型 revision。

## 费用预留

| 攻击 | 请求槽 | 输入 cap | 输出 cap | 最坏费用 |
| --- | ---: | ---: | ---: | ---: |
| A1 PoisonedRAG | 60 | 360,000 | 96,000 | ¥1.488000 |
| A2 LogicPoison | 60 | 90,000 | 30,720 | ¥0.425760 |
| A3 GRAGPoison | 180 | 1,080,000 | 576,000 | ¥6.768000 |
| 合计 | 300 | 1,530,000 | 702,720 | ¥8.681760 |

该 hard cap 只覆盖 A1–A3 dev60 攻击生成请求，不覆盖 Microsoft GraphRAG/LightRAG 索引、检索、回答或裁判。后续费用不能借用本 cap 静默启动。

## Request/Cost Guard 语义

每次 provider 调用前，runner 必须先写入稳定 request slot、实际 Prompt fingerprint、输入/输出 token cap 和最坏费用预留。随后只允许一次 provider 调用，并用返回 usage 对账。

以下情况立即停止整个 namespace，且不自动重试：

- 硬中断后仍存在 `in_flight` 请求；
- provider error；
- prompt/completion usage 缺失或类型无效；
- reasoning tokens 非零；
- 实际 token 或目录价超过冻结上限；
- launch、request plan、Prompt、代码、语料或上游 commit 身份不一致。

schema-invalid 响应在 usage 已知时按实际费用记账，并保留为 generation-invalid。依赖该响应的 A3 后续槽只能标记为 `skipped`；守卫拒绝以“观察到攻击效果低”为理由跳过请求。

## 语料物化身份与上限

三个 clean corpus 的 SHA-256、文档数与正文 UTF-8 字节数已写入 launch manifest。A1 冻结为共同基准的每问题 1 文档，并同时披露上游原生 5 文档设置。A3 冻结 `N_alpha=10`、`N_beta=5`、每问题最多 30 文档、每文档 400 words、每数据集相对上限 10%。A2 冻结 `en_core_web_trf 3.8.0`、top ratio 0.05，并为每个数据集写入 concrete document/occurrence/byte fail-closed cap。

这些攻击的自然预算单位不同，正式报告必须分别列绝对量和相对语料比例，不能把 A1 文档数、A2 替换次数和 A3 文本出现次数混成统一攻击强度。

## 验收与当前边界

新增测试覆盖确定性重复冻结、固定分母、共享 seed、产物哈希、调用前预留、实际费用回收、in-flight/unknown fail-closed、provider error、reasoning/token 越界、Prompt 身份、A3 阶段依赖和禁止按结果跳过。

最终验收：专项测试 `8 passed`；全量回归 `348 passed`；Ruff 静态检查通过，`src/tests` 的 213 个文件格式检查通过。相同输入连续重放得到同一 launch fingerprint，并逐项重算比较攻击尝试、请求计划、摘要和完整 manifest；缺失、多余或被修改的冻结文件均拒绝复用。

当前 manifest 状态为 `FROZEN_OFFLINE_NO_PROVIDER_CALLS`，`paid_dispatch_allowed=false`。原因不是缺少付费授权，而是 A1/A2/A3 runner 尚未全部绑定到 exact launch fingerprint 与统一 guard。下一项工作是完成该绑定和纯 fixture 中断恢复测试；通过后才能开启 dev60 攻击生成与物化。
