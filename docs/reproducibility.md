# LogicGuard 可复现实验命令清单

## WP2 dev60 launch 与 request/cost guard（2026-09-24）

以下命令只冻结或重验启动清单，不读取 API key、不调用 provider、不生成攻击：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.dev60_launch `
  --config configs\benchmark\comparison_v1_2_dev60_launch.yaml
.venv\Scripts\python.exe -m pytest tests\test_dev60_launch_guard.py -q
```

规范化产物位于 `artifacts/benchmark/research_revision_v1_2/wp2/dev60_launch_v1/`。相同输入重放只核验 launch fingerprint 和全部产物 hash；配置、协议、代码、clean corpus 或上游 commit 漂移时拒绝混入原 namespace。当前 `paid_dispatch_allowed=false`，因为 A1/A2/A3 paid runner 还未全部绑定 exact launch fingerprint 与统一 guard。该阶段 provider 调用 0、费用 ¥0；详见 [冻结报告](F:/LogicGuard_project/logicguard/docs/Dev60_LaunchGuard_WP2_Freeze.md)。

当前冻结 fingerprint 为 `c8fa1ced0771501f707e50454c841c7fd82275c67788dcf83d9ae6a1f7a003e6`。验收结果为专项 `8 passed`、全量 `348 passed`，Ruff 检查和 `src/tests` 的 213 文件格式门均通过。

## 📦 WP2 D3/D4 外部防御资格（2026-09-10）

D3 使用隔离的标准 Python 3.10 CPU 环境，避免项目 Anaconda 3.11 环境的 PyTorch DLL 冲突。环境路径已由 `.gitignore` 排除；模型 revision 和权重 SHA-256 已写入不可变结果。首次运行需要下载固定 90,868,373-byte MiniLM，以及 6,191,135,894-byte Stella 最小快照；重放强制 `local_files_only`。Stella 按模型快照自带版本记录固定 `sentence-transformers==3.0.1`、`transformers==4.42.3`。D4 审计只编译固定源码并检查提示词存在性，前置门失败时不读取 key、不调用 provider。

隔离环境的完整解析版本保存在 `tools/ragdefender/requirements-anchor.freeze.txt`；RAGDefender 本体使用项目内固定提交的 editable 安装。CPU PyTorch 须先从官方 CPU wheel index 安装，再按 freeze 文件安装其余依赖，避免解析器将 `transformers` 升到不兼容的 5.x。

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.external_defense_qualification `
  --config configs\benchmark\comparison_v1_2_external_defense_qualification_anchor.yaml
.venv\Scripts\python.exe -m pytest tests\test_external_defense_qualification.py -q
```

有效状态为 `D3_PASSED_D4_UPSTREAM_ARTIFACT_UNAVAILABLE`，产物位于 `artifacts/benchmark/research_revision_v1_2/wp2/d3_d4_external_defense_qualification_anchor_v5/`。同配置重放只核验输入和产物 hash，不重复模型推理。无后缀至 `_v4` 的 namespace 分别保留严格排列门、资格语义修正、不兼容依赖失败和 runner identity 补强过程；均不覆盖。v5 将配置、runner、上游源码与 fixture hash 全部纳入运行身份。完整边界见 [D3/D4 资格报告](F:/LogicGuard_project/logicguard/docs/D3_D4_ExternalDefense_WP2_Qualification.md)。

## WP2 T0/T1 共享可信证据控制层（2026-09-08）

以下命令只读取项目内合成 clean corpus 与规范化 retrieval fixture，不读取 API key、不连接真实 Microsoft GraphRAG/LightRAG，也不生成攻击：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.trusted_control_runner --config configs\benchmark\comparison_v1_2_trusted_controls_fixture.yaml
.venv\Scripts\python.exe -m pytest tests\test_trust_manifest.py tests\test_trusted_controls.py tests\test_trusted_control_runner.py tests\test_ms_graphrag_stage28_risk_non_oracle_recovery.py -q
.venv\Scripts\ruff.exe check src tests
.venv\Scripts\ruff.exe format --check src tests
```

规范化产物位于 `artifacts/benchmark/research_revision_v1_2/wp2/trusted_controls_synthetic_anchor_final/`。相同配置重放会校验运行身份和所有产物 hash；输入、配置或预算变化时拒绝混入该 namespace。验收输出为 32 条 context、16 条 audit、0 失败、0 provider 调用、费用 ¥0。该命令只复现工程合同，不复现攻击或防御效果；详见 [T0/T1 验收报告](F:/LogicGuard_project/logicguard/docs/TrustedControls_WP2_LocalVerification.md)。

## WP2 A2 本地四阶段验收（2026-09-08）

以下两个配置只运行合成 query 响应，不读取 API key。第二个使用已安装的真实 NER 模型；不生成三数据集真实攻击样本。隔离环境本轮新增 `PyYAML==6.0.3`，其他模型依赖保持原版本。

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.logicpoison_pipeline --config configs\benchmark\comparison_v1_2_logicpoison_fixture.yaml
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
tools\logicpoison\.venv\Scripts\python.exe -m logicguard.benchmark.logicpoison_pipeline --config configs\benchmark\comparison_v1_2_logicpoison_trf_anchor.yaml
.venv\Scripts\python.exe -m pytest tests\test_logicpoison_pipeline.py tests\test_research_audit.py tests\test_amendment_metrics.py tests\test_comparative_attack_runner.py -k 'not full_validation_dry_run' -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
```

两个锚点分别输出到 `artifacts/benchmark/research_revision_v1_2/wp2/logicpoison_synthetic_anchor/` 和 `logicpoison_trf_anchor/`；完成后相同命令核验身份/hash 并复用结果，不重新发请求。代码、输入、配置或记录的运行环境改变会拒绝续接，需使用新 namespace，不能覆盖旧 checkpoint。硬中断残留的 `run.lock` 必须先检查原进程与费用状态，不能自动抢锁。unknown usage/in-flight 请求保留预留费用且停止，不自动重试。

验收为 `44 passed, 1 deselected`、ruff 通过、195 文件格式通过。跳过会改写旧 namespace 的 dry-run 测试；未重跑 E0/E1 readiness 测试。当前 `generation_valid=false` 是合成模式的预期值，成功标志为 `CORPUS_MATERIALIZED` 与 `corpus_materialization_valid=true`。真实 provider 请求 0，新增费用 ¥0；详见 [验收报告](F:/LogicGuard_project/logicguard/docs/LogicPoison_WP2_LocalVerification.md)。

## 最新入口：WP1 研究审计与 v1.2（2026-09-06）

未来执行协议为 `docs/comparativeExperimentPreregistration_v1.2.md`，机器计划和人工源码保真度表为 `configs/benchmark/comparison_v1_2_protocol.yaml`、`comparison_v1_2_fidelity_review.yaml`。下文 v1.1 命令保留历史用途，可能重写原 readiness，不应为查看状态随意重跑。

本轮本地审计不调用 provider，不读取凭据，不生成攻击或索引；会读取历史产物以匹配 query ID/问题，但只输出路径、类别、hash 和匹配位置，不复制答案。旧 evaluator-only 文件只计算 hash；dev60 选择只读取 attacker-safe 输入。

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.research_audit --config configs\benchmark\comparison_v1_2_research_audit.yaml
.venv\Scripts\python.exe -m pytest tests\test_research_audit.py tests\test_amendment_metrics.py -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
```

输出限定为 `artifacts/benchmark/research_revision_v1_2/` 下五个派生 JSON/JSONL 文件；同一配置与历史输入的重跑会更新这些审计派生文件，不执行付费工作。`history_summary.json` 保存审计配置/实现和已审查源码 SHA-256，以及旧 v1.1 文档、机器表、readiness、split 的前后 hash；`history_files.jsonl` 保存扫描、排除和错误清单。证据分类使用文件名启发式，有记录不能推断人工看过或调参，缺记录不能认证独立性。

WP1 核验结果为 977 扫描、20 排除、0 解析错误、1,500 个问题有历史执行/分析记录；dev60 按原 development 内 stratum 轮转冻结。尚未实施完整 A2/D6，也未将新指标接入所有旧 runner；正式付费 qualification 需通过 v1.2 中的实现、预算与数据门。

本轮测试为新增审计/指标测试 `8 passed`，含临时目录端到端重跑一致性、标签不进入输出、历史文件 hash 保护和解析错误记录；`ruff check src tests` 通过，`ruff format --check src tests` 为 192 files already formatted。真实产物另核验 11 个受保护文件未变、dev60 每数据集 20 问、无非 development 行和额外标签字段。本轮没有重跑可能改写 v1.1 readiness 的旧全量测试，不能把这 8 项测试表述为全项目回归已通过。

> 规范化入口（2026-09-04）：本文是环境、命令和冻结审计的唯一维护入口。
> 旧配置路径由 `configs/config_aliases.yaml` 映射到新的分层路径。

基础开发环境使用 `uv sync --dev`；需要 dense retrieval、可视化或扩展研究
依赖时使用 `uv sync --dev --extra research`。Microsoft GraphRAG 继续使用
`tools/ms_graphrag/.venv` 隔离环境，避免与主项目依赖耦合。

## 0.0 Comparative Benchmark E0（2026-09-03）

E0-A/E0-B 已完成，v1.1 协议见 `docs/comparativeExperimentPreregistration_v1.1.md`。E1 的 execution adapter、生成成本控制和 1/10 文档索引计量已完成，但全规模索引 hard cap 与 BadRAG dense/payload 仍未冻结，因此 validation 尚未启动。E2 locked test 继续受 E1 门限制。v1.0 的 `docs/comparativeExperimentPreregistration.md` 与 `docs/对比实验预注册表.csv` 只保留历史，不再是执行协议。

复建 E0-A：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -m logicguard.benchmark.readiness `
  --config configs\benchmark\comparison_v1_1_e0.yaml
.venv\Scripts\python.exe -m pytest tests\test_comparative_benchmark_e0.py -q
```

LightRAG 使用隔离环境，固定为官方 v1.5.7 commit `28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`。只允许导入 smoke，不代表已运行 batch：

```powershell
uv venv tools\lightrag\.venv --python .venv\Scripts\python.exe
uv pip install --python tools\lightrag\.venv\Scripts\python.exe `
  --editable vendor\upstream\LightRAG
tools\lightrag\.venv\Scripts\python.exe -c `
  "from lightrag import LightRAG, QueryParam; print(QueryParam(mode='hybrid').mode)"
```

主要产物位于 `artifacts/benchmark/e0`，readiness 报告为 `artifacts/reports/ComparativeBenchmark_E0_Readiness.md`。命令可重复运行并原子覆盖同版本派生产物；不得手工修改 split。E0 的费用与调用均为 0。下一阶段需新建 E1 namespace；不得复用 E0 fixture 伪装攻击效果，也不得在 qualification 门前启动 E2。

## 0.1 Comparative Benchmark E1 preparation（2026-09-04）

以下命令只复算 attacker-safe input、各项冻结 pilot audit、BadRAG lexical smoke、成本表和 request plan，不发起新 provider 调用。为验证零调用，复算时应显式清空 API 环境变量：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
$env:DASHSCOPE_API_KEY=''
$env:OPENAI_API_KEY=''
$env:ALIYUN_API_KEY=''
.venv\Scripts\python.exe -m logicguard.cli run benchmark-e1-preparation `
  --config configs\benchmark\comparison_v1_1_e1_preparation.yaml
.venv\Scripts\python.exe -m logicguard.cli run benchmark-attack-runner `
  --config configs\benchmark\comparison_v1_1_attack_runner_dryrun.yaml
.venv\Scripts\python.exe -m pytest `
  tests\test_comparative_benchmark_e1_preparation.py `
  tests\test_comparative_attack_runner.py -q
```

预期为 18 cells、1,800 input rows、600 unique A1/A3 attempts、1,200 planned A1/A3 calls、300 planned A2 calls；audit 本身 0 provider calls。readiness 中的历史付费数为 102 次（6 次攻击生成、48 次索引 chat、48 次 embedding），不是本命令新产生的调用。主要产物位于 `artifacts/benchmark/e1_preparation`，汇总报告为 `artifacts/reports/ComparativeBenchmark_E1_Preparation.md`。

LogicPoison 使用独立 `tools/logicpoison/.venv`：Python 3.11.7、spaCy 3.8.14、CPU torch 2.5.1、OpenAI SDK 1.109.1、`spacy-curated-transformers 0.3.1` 与 `en_core_web_trf 3.8.0`。官方模型源 wheel SHA-256 为 `272a31e9d8530d1e075351d30a462d7e80e31da23574f1b274e200f3fff35bf5`；运行时已按包名加载模型并正确识别 `Barack Obama/PERSON` 与 `Paris/GPE`。机器记录见 `artifacts/benchmark/e1_preparation/comparison_v1_1_logicpoison_runtime_smoke.json`。该环境只证明依赖就绪，尚未运行 corpus NER 或 query API。

冻结的付费 development 产物不得重复执行。对应配置为 `comparison_v1_1_attack_runner_development_pilot.yaml`、`comparison_v1_1_logicpoison_development_pilot.yaml`、`comparison_v1_1_logicpoison_cost_control_pilot.yaml`，以及四个 `*_indexing_*pilot*.yaml`。索引产物与审计位于 `artifacts/benchmark/e1_preparation/indexing_pilots` 和 `comparison_v1_1_indexing_pilot_audit.json`。历史一次 LightRAG 初始化失败发生于 API 前、费用 ¥0；修复版和其余三次索引通过，不得为清理日志而重跑。

费用配置冻结 qwen3.7-plus 输入/输出 ¥2/¥8 每百万 tokens、text-embedding-v4 ¥0.5 每百万 tokens。攻击生成实际目录价 ¥0.079428；四次索引 chat 加本地估计 embedding token 的目录价为 ¥0.324525，合计 ¥0.403953。¥108.715720 只是非索引已知组件 cap/projection；当前 24-index 设计的 1/10 文档校准区间为 ¥2,958.622–¥4,322.297，`is_hard_cap=false`。全规模 indexing 和 BadRAG dense/payload 未封顶，不能据此直接启动 validation。

## 0. Stage48 E0/E1 当前接续点（2026-09-01）

E0 checkpoint/resume、E1 未防御 full-corpus 基线，以及未修改 Stage43/44/45 + clean full-corpus 配对均已完成。配对阶段完成 112/112 回答，当前没有需要恢复的后台进程。除离线重算外，不要重复索引或回答。

已完成配置如下；除审计复算或建立新命名空间外，不要重复索引：

- `configs/experiments/e1/musique_natural_bridge_dryrun5_full_corpus.yaml`
- `configs/experiments/e1/musique_low_drift_evalvalid5_full_corpus.yaml`
- `configs/experiments/e1/musique_candidate_collision_evalvalid2_full_corpus.yaml`
- `configs/experiments/e1/hotpotqa_natural_bridge_evalvalid2_full_corpus.yaml`

每个 variant 的命令模式如下，把 `<exposure-config>`、`<workspace>`、`<context-config>` 和 `<answer-config>` 替换为同前缀文件：

```powershell
cd F:\LogicGuard_project\logicguard

.venv\Scripts\python.exe -m logicguard.evaluation.reindex_exposure `
  --config <exposure-config> `
  --phase prepare

# settings 已冻结为 community reports omitted、entity_description only。
tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root <workspace>

.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config <context-config>

$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config <context-config>

.venv\Scripts\python.exe -m logicguard.evaluation.reindex_exposure `
  --config <exposure-config> `
  --phase audit

# 只调用 source 与 target 均进入冻结最终提示的 case。
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_answer_gate `
  --config <answer-config>

# 仅从已保存回答离线重算标签，不产生 API 调用。
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_answer_gate `
  --config <answer-config> --reclassify-existing
```

历史失效凭据的阻断记录仍可用下列命令复算，但不得覆盖当前 completed 状态：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_exposure `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus.yaml `
  --phase record-blocked
```

E1 的冻结 attack manifest、corpus hash、settings/prompts hash、GraphRAG 请求数、token 和回答成本清单均位于 `outputs/manifests/`。精确可归因的本轮目录价为 ¥0.227303；9 个短查询 embedding 另按约 ¥0.00045 保守封顶。任何费用换算都应保留 provider token 原始计数和价格快照；不能从 GraphRAG 日志中的 `cost_per_response: 0.0` 推断免费。

### 0.1 Stage48 clean/防御配对复现

配对使用两个 clean full-corpus workspace：

- `outputs/ms_graphrag/musique/stage48_clean_full_corpus`
- `outputs/ms_graphrag/hotpotqa/stage48_clean_full_corpus`

它们已完成且包含付费 embedding 结果，不应原地重跑。若必须在新 namespace 复现，先使用 `prepare_workspace --doc-scope all`，复制对应 E1 attack workspace 的冻结 `settings.yaml` / `prompts`，再执行：

```powershell
tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/musique/<new-clean-workspace> --method fast
tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/hotpotqa/<new-clean-workspace> --method fast
```

四组 clean context 配置后缀均为 `_clean_context.yaml`。每组先运行 seed planning，再在 GraphRAG 隔离环境中导出 official contexts：

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus_clean_context.yaml

$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus_clean_context.yaml
```

其余三个前缀为：

- `musique_low_drift_evalvalid5_full_corpus`
- `musique_candidate_collision_evalvalid2_full_corpus`
- `hotpotqa_natural_bridge_evalvalid2_full_corpus`

对 attacked 与 clean context 分别生成四列防御矩阵。配置后缀为 `_defense_matrix.yaml` 与 `_clean_defense_matrix.yaml`：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_defense_matrix `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus_defense_matrix.yaml
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_defense_matrix `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus_clean_defense_matrix.yaml
```

回答配置后缀为 `_defense_answers.yaml` 与 `_clean_defense_answers.yaml`。每个配置单独维护 checkpoint 和 fingerprint manifest；当前 8 个配置均已完成，重新运行只允许匹配 fingerprint 的无新增恢复：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs\experiments\e1\musique_natural_bridge_dryrun5_full_corpus_defense_answers.yaml
```

最终汇总完全离线，不增加 API 调用：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_paired_analysis `
  --config configs\experiments\e1\stage48_paired_defense_analysis.yaml
```

预期输出为 `stage48_paired_rows=56, answer_calls=112`。主要产物：

- `outputs/ms_graphrag_query/stage48_e1_paired_defense_answer_rows.jsonl`
- `outputs/ms_graphrag_query/stage48_e1_paired_defense_answer_summary.json`
- `outputs/manifests/stage48_e1_paired_defense_cost_ledger.json`

配对阶段精确日志成本为 ¥0.982251；clean context 的 14 次 query embedding 按每次最多 128 tokens 保守封顶 ¥0.000896，因此配对增量上界 ¥0.983147。Stage48 含前一轮 E1 的累计精确成本为 ¥1.209554，累计上界 ¥1.210900。

### 0.2 Stage48 Gate A fixed-50 扩样

Gate A 尝试预算固定为 MuSiQue 与 HotpotQA 各前 50 个 query；以下攻击扩展已经完成并产生付费结果，不应原地重跑：

```powershell
.venv\Scripts\python.exe -m logicguard.attack.adaptive `
  --config configs\experiments\e1\stage48_gate_a_musique_attack_expansion.yaml
.venv\Scripts\python.exe -m logicguard.attack.adaptive `
  --config configs\experiments\e1\stage48_gate_a_hotpotqa_attack_expansion.yaml
```

冻结合并、有效性清单、确定性选样和生成成本汇总可以离线复算：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.gate_a_expansion `
  --config configs\experiments\e1\stage48_gate_a_expansion.yaml
```

固定 50-query 清单显示四个单元达到 10 条 evaluation-valid：MuSiQue/HotpotQA 的 `natural_bridge` 与 `low_drift`。两个 `candidate_collision` 单元均只有 6 条，必须保留为未 ready，不得追加调用补足。四个 ready 单元分别使用以下 exposure 配置与同前缀 `_context.yaml`：

- `stage48_gate_a_musique_natural_bridge_evalvalid10_full_corpus.yaml`
- `stage48_gate_a_musique_low_drift_evalvalid10_full_corpus.yaml`
- `stage48_gate_a_hotpotqa_natural_bridge_evalvalid10_full_corpus.yaml`
- `stage48_gate_a_hotpotqa_low_drift_evalvalid10_full_corpus.yaml`

单元的执行顺序固定如下。已完成的 workspace 含付费 embedding，禁止原地重跑；若复现必须改用新 namespace 和新 manifest：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.reindex_exposure `
  --config <exposure-config> --phase prepare

tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root <workspace> --method fast

.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config <context-config>

$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config <context-config>

.venv\Scripts\python.exe -m logicguard.evaluation.reindex_exposure `
  --config <exposure-config> --phase audit
```

Context Gate 汇总完全离线，使用单元 `10/10` 与家族 pooled `20/20` attempted 分母，并生成 Wilson 95% 区间：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.gate_a_context_analysis `
  --config configs\experiments\e1\stage48_gate_a_context_analysis.yaml
```

只有 `stage48_gate_a_fixed50_context_summary.json` 中 `answer_stage_families` 列出的家族才允许运行同前缀 `_answers.yaml`。回答完成后执行：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.gate_a_answer_analysis `
  --config configs\experiments\e1\stage48_gate_a_answer_analysis.yaml
```

最终 system-level targeted ASR 使用全部 evaluation-valid attempted 分母，未检索、未暴露的 case 仍计为失败；禁止只按 prompt-exposed 分母宣告 Gate A 通过。

已完成结果为：natural bridge pooled Prompt 暴露与 system targeted ASR 均为 `4/20=20%`；low drift Prompt 暴露 `3/20=15%`；candidate collision 两个单元各只有 6 条 evaluation-valid。Gate A 因只有一个家族通过而判为未通过。主要汇总：

- `outputs/ms_graphrag_query/stage48_gate_a_fixed50_context_summary.json`
- `outputs/ms_graphrag_query/stage48_gate_a_fixed50_answer_summary.json`
- `outputs/manifests/stage48_gate_a_fixed50_answer_cost_ledger.json`

本轮 fixed-50 增量精确目录价为 ¥2.367407、保守上界 ¥2.376367；Stage48 累计精确 ¥3.576961、累计上界 ¥3.587267。MuSiQue 两个 index 日志各记录一次 provider 内部 retry、0 失败；HotpotQA 两个 index 为 0 retry、0 失败。HotpotQA context 的 tokenizer 远程握手失败后使用本地备份，两个导出均 exit 0。不得把内部 retry 隐去，也不得因它重新运行已完成 namespace。

### 0.3 Stage48 冻结失败分类

以下命令只复算 inventory 与失败分类，不调用 API、不重建索引、不读取回答结果：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.gate_a_expansion `
  --config configs\experiments\e1\stage48_gate_a_expansion.yaml

.venv\Scripts\python.exe -m logicguard.evaluation.stage48_failure_taxonomy `
  --config configs\experiments\e1\stage48_failure_taxonomy.yaml
```

第一条命令的确定性选择哈希必须与 `reindex_exposure` 同为 `fingerprint_json(query_id)`；测试 `test_gate_a_selection_uses_the_same_fingerprint_as_reindexing` 防止再次分叉。预期第二条命令输出 `stage48_failure_taxonomy_rows=300, paid_api_calls=0`。主要产物：

- `outputs/ms_graphrag_query/stage48_failure_taxonomy_rows.jsonl`
- `outputs/ms_graphrag_query/stage48_failure_taxonomy_summary.json`
- `outputs/ms_graphrag_query/stage48_failure_taxonomy_summary.csv`
- `outputs/reports/Stage48_FailureTaxonomy.md`

新的大规模效果实验尚未执行；文献/资产审计见 `docs/comparativeExperimentLiteratureAudit.md`。v1.0 预注册和机器表已暂停，v1.1 与 E0 已于 2026-09-03 冻结。当前只开放 E1 execution adapter、development smoke 与成本估算的无/低成本准备；正式 validation 调用和所有 E2 cell 仍受预注册门约束。

## 1. 使用规则

所有命令从 `F:\LogicGuard_project\logicguard` 执行。Stage19 冻结产物不应被覆盖；如果要重新做实验，应复制对应 YAML、改用新实验编号和新输出目录。API Key 只通过环境变量提供，文档和配置中不得出现真实值。

```powershell
cd F:\LogicGuard_project\logicguard
uv --version
uv sync --frozen
```

命令按成本分为：

- **L0**：测试、静态检查、冻结审计，不调用 API。
- **L1**：本地 CPU 检索、聚合与诊断，不调用 API。
- **L2**：回答模型与 Judge，会产生 API token 成本。
- **L3**：Microsoft GraphRAG 索引或 official query，时间和 API 成本最高。

## 2. L0：项目与冻结审计

```powershell
# 全部测试
.venv\Scripts\python.exe -m pytest -q

# 静态检查
.venv\Scripts\ruff.exe check .

# 严格重新生成注册表、哈希清单和冻结报告
.venv\Scripts\python.exe -m logicguard.reports.experiment_registry `
  --config configs/stage19_experiment_registry.yaml
```

预期：注册表命令输出 `experiments=21`、`artifacts=186`、`missing=0`。若出现缺失证据，严格模式会退出，不会生成一份假装完整的冻结报告。

## 3. L1：本地检索与防御

### 3.1 数据与轻量基线

```powershell
# LG-A01：三数据集标准化与验证
.venv\Scripts\python.exe -m logicguard.data.prepare `
  --config configs/data.yaml

# LG-B01：轻量 GraphRAG-style full-500
.venv\Scripts\python.exe -m logicguard.graph.run_baseline `
  --config configs/graphrag_baseline_full_500.yaml

# LG-B02：三数据集自建攻击总流程
.venv\Scripts\python.exe -m logicguard.experiments.run_multidataset `
  --config configs/multidataset_full_500.yaml

# LG-C01：三数据集阈值扫描
.venv\Scripts\python.exe -m logicguard.defense.run_threshold_scan `
  --config configs/logicguard_threshold_scan_full_500.yaml

# LG-C02：防御信号消融
.venv\Scripts\python.exe -m logicguard.defense.run_ablation `
  --config configs/logicguard_ablation_full_500.yaml
```

### 3.2 NaiveRAG BM25

```powershell
.venv\Scripts\python.exe -m logicguard.naive_rag.run_baseline `
  --config configs/naive_rag_bm25_2wiki_full_500.yaml

.venv\Scripts\python.exe -m logicguard.naive_rag.run_baseline `
  --config configs/naive_rag_bm25_hotpotqa_full_500.yaml

.venv\Scripts\python.exe -m logicguard.naive_rag.run_baseline `
  --config configs/naive_rag_bm25_musique_full_500.yaml
```

### 3.3 LogicPoison官方语料

```powershell
# LG-E02：clean/poisoned 对齐与改写统计
.venv\Scripts\python.exe -m logicguard.data.logicpoison_official `
  --config configs/logicpoison_official.yaml

# LG-E03：BM25 + graph surrogate 检索影响
.venv\Scripts\python.exe -m logicguard.experiments.run_logicpoison_retrieval `
  --config configs/logicpoison_retrieval_stage2.yaml

# LG-E04：检索层防御消融
.venv\Scripts\python.exe -m logicguard.defense.run_logicpoison_defense `
  --config configs/logicpoison_defense_stage3.yaml

# LG-F03 的本地 non-oracle recovery trace
.venv\Scripts\python.exe -m logicguard.defense.run_non_oracle_recovery `
  --config configs/logicpoison_recovery_stage8.yaml
```

### 3.4 从现有Judge结果重建汇总

以下命令只读取已有 JSONL，不调用 API：

```powershell
# LG-F01：BM25回答层聚合
.venv\Scripts\python.exe -m logicguard.llm.run_stage6_summary `
  --config configs/logicpoison_stage6_summary.yaml

# LG-F02：graph surrogate回答层聚合
.venv\Scripts\python.exe -m logicguard.llm.run_stage6_summary `
  --config configs/logicpoison_stage7_graph_summary.yaml

# LG-F03：合并基线与non-oracle recovered结果
.venv\Scripts\python.exe -m logicguard.llm.merge_stage8_recovery `
  --config configs/logicpoison_stage8_answer_merge.yaml
```

### 3.5 Microsoft GraphRAG已有结果诊断

```powershell
# Stage18 mixed-vs-independent 对比；不重新索引
.venv\Scripts\python.exe -m logicguard.ms_graphrag.independent_graphs compare `
  --mixed-recall outputs/ms_graphrag_query/stage16_5_broad_entities_recall.csv `
  --independent-recall outputs/ms_graphrag_query/stage18_5_independent_context_recall.csv `
  --mixed-entities outputs/ms_graphrag_query/stage17_5_broad_entities_entity_diagnostics.csv `
  --independent-entities outputs/ms_graphrag_query/stage18_5_independent_entity_diagnostics.csv `
  --csv outputs/ms_graphrag_query/stage18_independent_vs_mixed_broad_comparison.csv `
  --report outputs/reports/MicrosoftGraphRAG_Stage18_Independent_vs_MixedBroad_Report.md
```

## 4. L2：LLM回答与Judge

运行前只检查变量是否存在，不输出变量值：

```powershell
if (-not $env:DASHSCOPE_API_KEY) { throw "DASHSCOPE_API_KEY 未设置" }
if (-not $env:DASHSCOPE_BASE_URL) { throw "DASHSCOPE_BASE_URL 未设置" }
```

### 4.1 自建Natural BridgeV2

```powershell
.venv\Scripts\python.exe -m logicguard.llm.run_generation_pilot `
  --config configs/llm_generation_expanded_natural_bridge_v2_recovery_full_500.yaml
```

该配置包含 20 个 query、两个模型和 clean/poisoned/guarded/recovered 四种上下文；完整重跑约 320 次回答调用。

### 4.2 LogicPoison BM25回答层

每个数据集先生成答案，再调用 Judge：

```powershell
.venv\Scripts\python.exe -m logicguard.llm.run_logicpoison_answer_eval --config configs/logicpoison_answer_stage6_2wiki.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_logicpoison_answer_eval --config configs/logicpoison_answer_stage6_hotpotqa.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_logicpoison_answer_eval --config configs/logicpoison_answer_stage6_musique.yaml

.venv\Scripts\python.exe -m logicguard.llm.run_answer_judge --config configs/logicpoison_answer_judge_stage6_2wiki.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_answer_judge --config configs/logicpoison_answer_judge_stage6_hotpotqa.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_answer_judge --config configs/logicpoison_answer_judge_stage6_musique.yaml

.venv\Scripts\python.exe -m logicguard.llm.run_stage6_summary --config configs/logicpoison_stage6_summary.yaml
```

### 4.3 LogicPoison graph surrogate回答层

将上节配置替换为以下六个文件，最后运行 `logicpoison_stage7_graph_summary.yaml`：

| 步骤 | 2Wiki | HotpotQA | MuSiQue |
| --- | --- | --- | --- |
| 回答 | `logicpoison_answer_stage7_graph_2wiki.yaml` | `logicpoison_answer_stage7_graph_hotpotqa.yaml` | `logicpoison_answer_stage7_graph_musique.yaml` |
| Judge | `logicpoison_answer_judge_stage7_graph_2wiki.yaml` | `logicpoison_answer_judge_stage7_graph_hotpotqa.yaml` | `logicpoison_answer_judge_stage7_graph_musique.yaml` |

命令模板：

```powershell
.venv\Scripts\python.exe -m logicguard.llm.run_logicpoison_answer_eval --config configs/<回答配置>.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_answer_judge --config configs/<Judge配置>.yaml
.venv\Scripts\python.exe -m logicguard.llm.run_stage6_summary --config configs/logicpoison_stage7_graph_summary.yaml
```

### 4.4 Non-oracle Recovery回答层

Stage8 每个数据集只重新生成 recovered 条件，再与 Stage6 的 clean/poisoned/guarded 合并。配置对应关系：

| 步骤 | 2Wiki | HotpotQA | MuSiQue |
| --- | --- | --- | --- |
| 回答 | `logicpoison_answer_stage8_non_oracle_2wiki.yaml` | `logicpoison_answer_stage8_non_oracle_hotpotqa.yaml` | `logicpoison_answer_stage8_non_oracle_musique.yaml` |
| Judge | `logicpoison_answer_judge_stage8_non_oracle_2wiki.yaml` | `logicpoison_answer_judge_stage8_non_oracle_hotpotqa.yaml` | `logicpoison_answer_judge_stage8_non_oracle_musique.yaml` |

完成六个配置后运行：

```powershell
.venv\Scripts\python.exe -m logicguard.llm.merge_stage8_recovery `
  --config configs/logicpoison_stage8_answer_merge.yaml
```

## 5. L3：Microsoft GraphRAG

### 5.1 环境检查

```powershell
tools\ms_graphrag\.venv\Scripts\python.exe --version
tools\ms_graphrag\.venv\Scripts\graphrag.exe --help
```

主项目 `.venv` 负责 LogicGuard 适配代码；GraphRAG 索引和 official query 使用隔离环境。不要在两个环境之间交叉安装依赖。

### 5.2 已有五Query official pipeline

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.official_query_pipeline `
  --config configs/ms_graphrag_official_query_pipeline_stage14_5.yaml
```

该命令假设 clean/poisoned query-ready workspace 已存在，会重新导出 official local context并调用回答模型。它不负责从原始 corpus 重建索引。

### 5.3 Stage18 independent workspace准备

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.independent_graphs prepare `
  --dataset 2wikimultihopqa `
  --samples data/processed/2wikimultihopqa/stage14_local_defense_5.jsonl `
  --poisoned-corpus data/ms_graphrag_stage14_local_defense_5/2wikimultihopqa/poisoned/corpus.jsonl `
  --sample-output-root data/processed/2wikimultihopqa/stage18_independent_samples `
  --workspace-root outputs/ms_graphrag/2wikimultihopqa/stage18_independent_poisoned `
  --template-root outputs/ms_graphrag/template `
  --manifest outputs/ms_graphrag_query/stage18_independent_workspace_manifest.json `
  --max-queries 5
```

准备命令只建立 workspace，不执行索引。每个 manifest 中的 workspace 需要单独运行：

```powershell
tools\ms_graphrag\.venv\Scripts\graphrag.exe index --root <workspace路径>
```

Stage18 的三个历史 workspace 在 `create_community_reports` 阶段超时后使用了 local-only 降级。重新实验时必须预先选择并记录协议：

- **full workflow**：community report 完整生成，可做 local/global 对照。
- **local-only**：`community_prop=0`，不使用 community report，只评价 local context。

两种协议不能在主表中无标记混用。

### 5.4 Stage20 Query-layer LogicGuard

```powershell
# 1. 主环境生成不含gold字段的seed plan
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs/ms_graphrag_query_layer_stage20.yaml

# 2. GraphRAG隔离环境通过官方include/exclude entity接口导出context
$env:PYTHONPATH=(Resolve-Path 'src').Path
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs/ms_graphrag_query_layer_stage20.yaml

# 3. 主环境离线计算recall、exposure和entity hit
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_evaluation `
  --config configs/ms_graphrag_query_layer_stage20.yaml

# 4. 回答层poisoned/guarded/recovered确认，会调用LLM API
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_time_defense `
  --config configs/ms_graphrag_query_time_stage20_full_guard.yaml
```

Stage20的候选生成不得读取answer、support_doc_ids或support_docs。检索主报告为
`outputs/reports/MicrosoftGraphRAG_Stage20_综合实验分析报告.md`。

### 5.5 Stage21 中等规模共享索引诊断

该命令不调用外部LLM，也不重新索引GraphRAG；它读取已有50-query GraphRAG minimal indexed artifacts，并输出检索、干扰和Recovery指标。

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.stage21_medium_diagnostics `
  --config configs/ms_graphrag_stage21_medium_diagnostics.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage21_medium_evidence.jsonl`
- `outputs/ms_graphrag_query/stage21_medium_metrics.csv`
- `outputs/ms_graphrag_query/stage21_medium_summary.csv`
- `outputs/reports/MicrosoftGraphRAG_Stage21_中等规模查询诊断报告.md`

### 5.6 Stage23 official sources级Recovery

该命令不调用外部LLM，也不重新索引GraphRAG；它读取 Stage22 已导出的 official `context_data.sources`，对 source 行执行 changed 标注、guard 过滤和 clean-reference doc_id recovery。

```powershell
.venv\Scripts\python.exe -m logicguard.defense.oracle_recovery `
  --config configs/ms_graphrag_stage23_sources_recovery_poisoned5.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage23_poisoned5_sources_recovery_contexts.jsonl`
- `outputs/ms_graphrag_query/stage23_poisoned5_sources_recovery_metrics.csv`
- `outputs/ms_graphrag_query/stage23_poisoned5_sources_recovery_summary.csv`
- `outputs/reports/Stage23_官方GraphRAG_Sources级Recovery_5Query实验报告.md`

当前 5-query 结果：`recovered_sources_by_doc_id` 保持 `gold recall=0.9000`，同时将未恢复 `changed exposure` 从 `0.9000` 降到 `0.0000`。该结果属于 oracle clean-reference 上界，不等同于无干净库部署。

### 5.7 Stage24 official sources级Recovery扩展到20/50 Query

Stage24 不调用回答模型，不重新索引 GraphRAG。先用 query-layer seeding 与 official context builder 导出 `full_query_guard` sources，再运行 sources-level recovery。

20-query：

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs/ms_graphrag_query_layer_stage24_poisoned20.yaml

$env:PYTHONPATH=(Resolve-Path 'src').Path
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs/ms_graphrag_query_layer_stage24_poisoned20.yaml

.venv\Scripts\python.exe -m logicguard.defense.oracle_recovery `
  --config configs/ms_graphrag_stage24_sources_recovery_poisoned20.yaml
```

50-query：

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs/ms_graphrag_query_layer_stage24_poisoned50.yaml

$env:PYTHONPATH=(Resolve-Path 'src').Path
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs/ms_graphrag_query_layer_stage24_poisoned50.yaml

.venv\Scripts\python.exe -m logicguard.defense.oracle_recovery `
  --config configs/ms_graphrag_stage24_sources_recovery_poisoned50.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage24_poisoned20_sources_recovery_summary.csv`
- `outputs/ms_graphrag_query/stage24_poisoned50_sources_recovery_summary.csv`
- `outputs/reports/Stage24_官方GraphRAG_Sources级Recovery_20Query实验报告.md`
- `outputs/reports/Stage24_官方GraphRAG_Sources级Recovery_50Query实验报告.md`
- `outputs/reports/Stage24_官方GraphRAG_Sources级Recovery_20_50Query综合报告.md`

当前 50-query 结果：`recovered_sources_by_doc_id` 保持 `gold recall=0.7850`，同时将未恢复 `changed exposure` 从 `0.7833` 降到 `0.0000`。

### 5.8 Stage25 non-oracle official sources级Recovery

Stage25 不调用回答模型，不重新索引 GraphRAG。它读取 Stage24 已导出的 `full_query_guard` official sources，并在 `risk_oracle + recovery_non_oracle` 设置下运行三种非 oracle 候选排序策略。

20-query：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.non_oracle_recovery `
  --config configs/ms_graphrag_stage25_non_oracle_sources_poisoned20.yaml
```

50-query：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.non_oracle_recovery `
  --config configs/ms_graphrag_stage25_non_oracle_sources_poisoned50.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage25_poisoned20_non_oracle_sources_summary.csv`
- `outputs/ms_graphrag_query/stage25_poisoned50_non_oracle_sources_summary.csv`
- `outputs/reports/Stage25_官方GraphRAG_NonOracleSourcesRecovery_20Query实验报告.md`
- `outputs/reports/Stage25_官方GraphRAG_NonOracleSourcesRecovery_50Query实验报告.md`
- `outputs/reports/Stage25_官方GraphRAG_NonOracleSourcesRecovery_20_50Query综合报告.md`

当前 50-query 结果：`non_oracle_title_entity_bm25` 达到 `gold recall=0.5450`，`changed exposure=0.0000`，明显高于 `guarded_sources` 的 `gold recall=0.0400`，但仍低于 oracle `recovered_sources_by_doc_id=0.7850`。

### 5.9 Stage26 official sources answer-level proxy verification

Stage26 不调用外部 LLM。它读取 Stage25 contexts，用 answer-surface proxy 评价 `correct / partial / incorrect / abstained / attack_success_proxy`，用于在真实 LLM answer-level 实验前冻结字段和样本。

5-query smoke：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_proxy `
  --config configs/ms_graphrag_stage26_answer_proxy_poisoned5.yaml
```

20-query：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_proxy `
  --config configs/ms_graphrag_stage26_answer_proxy_poisoned20.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage26_poisoned5_answer_proxy_summary.csv`
- `outputs/ms_graphrag_query/stage26_poisoned20_answer_proxy_summary.csv`
- `outputs/reports/Stage26_官方GraphRAG_AnswerProxy_5QuerySmoke报告.md`
- `outputs/reports/Stage26_官方GraphRAG_AnswerProxy_20Query实验报告.md`
- `outputs/reports/Stage26_官方GraphRAG_AnswerProxy_5_20Query综合报告.md`

当前 20-query 结果：`non_oracle_title_entity_bm25` 达到 `correct_rate=0.4500`、`attack_success_proxy=0.0000`，高于 `guarded_sources` 的 `correct_rate=0.2000`，但低于 oracle `recovered_sources_by_doc_id=0.8000`。

### 5.10 Stage27 official sources LLM answer-level verification

Stage27 会调用外部 LLM API。它读取 Stage25 contexts，生成真实回答，并评价 `correct / partial / incorrect / abstained / attack_success`。API key 只从环境变量读取，不写入配置或日志。

5-query smoke：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage27_answer_llm_poisoned5.yaml
```

20-query formal：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage27_answer_llm_poisoned20.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage27_poisoned5_answer_llm_summary.csv`
- `outputs/ms_graphrag_query/stage27_poisoned20_answer_llm_summary.csv`
- `outputs/reports/Stage27_OfficialGraphRAG_LLMAnswer_5QuerySmoke.md`
- `outputs/reports/Stage27_OfficialGraphRAG_LLMAnswer_20QueryFormal.md`
- `outputs/reports/Stage27_OfficialGraphRAG_LLMAnswer_5_20Query_Summary.md`

当前 20-query 结果：`full_query_guard` 的真实回答层 `attack_success_rate=0.2500`；`recovered_sources_by_doc_id` 与 `non_oracle_title_entity_bm25` 均为 `0.0000`。但 `non_oracle_title_entity_bm25` 的 `utility_rate=0.0500`，说明下一步需要提升 recovery 后可答性并补充 answer judge。

### 5.11 Stage28 risk non-oracle + recovery non-oracle

Stage28 的 source-level 步骤不调用外部 LLM。它读取 Stage24 `full_query_guard` contexts 和 trusted clean candidate pool，用 clean-candidate consistency detector 替换 `changed_support_doc_ids` risk oracle。

source-level 5-query smoke：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.risk_aware_recovery `
  --config configs/ms_graphrag_stage28_risk_non_oracle_sources_poisoned5.yaml
```

source-level 20-query formal：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.risk_aware_recovery `
  --config configs/ms_graphrag_stage28_risk_non_oracle_sources_poisoned20.yaml
```

answer proxy：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_proxy `
  --config configs/ms_graphrag_stage28_answer_proxy_poisoned5.yaml

.venv\Scripts\python.exe -m logicguard.evaluation.answer_proxy `
  --config configs/ms_graphrag_stage28_answer_proxy_poisoned20.yaml
```

真实 LLM 回答层：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage28_answer_llm_poisoned5.yaml

.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage28_answer_llm_poisoned20.yaml
```

主要产物：

- `outputs/ms_graphrag_query/stage28_poisoned20_risk_non_oracle_sources_summary.csv`
- `outputs/ms_graphrag_query/stage28_poisoned20_answer_proxy_summary.csv`
- `outputs/ms_graphrag_query/stage28_poisoned20_answer_llm_summary.csv`
- `outputs/reports/Stage28_RiskNonOracle_5_20Query_Summary.md`

当前 20-query 结果：source-level `risk_non_oracle_title_entity_bm25` 保持标准答案证据召回（`gold recall`）为 `0.7750`，将污染暴露率（`changed exposure`）降到 `0.0000`；真实 LLM 回答层下攻击成功率（`attack_success_rate`）为 `0.0000`、效用率（`utility_rate`）为 `0.1500`。

## 6. 结果核验

重跑后至少检查：

1. 输出 JSONL/CSV 行数与配置中的 query、模型和 variant 数量一致。
2. 报告中的分母不是 API 成功调用数的隐式子集；失败调用必须单列。
3. clean、poisoned、guarded、recovered 使用相同 query 集。
4. official GraphRAG 报告同时给出 support recall、changed exposure 和答案指标。
5. 新结果登记新 `LG-*` 编号，更新 registry 后重新生成 SHA-256 清单。

### 5.12 Stage29 回答层审计

Stage29 不重新调用外部 LLM，只复用 Stage28 已保存的真实 LLM 回答 case/results，对答案做离线归一化审计、错误归因和代表样例导出。

20-query formal：
```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answer_audit `
  --config configs/ms_graphrag_stage29_answer_audit_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_results.jsonl`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_summary.csv`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_breakdown.csv`
- `outputs/ms_graphrag_query/stage29_poisoned20_answer_audit_examples.jsonl`
- `outputs/reports/Stage29_AnswerAudit_20QueryFormal.md`

当前 20-query 结果：`risk_non_oracle_title_entity_bm25` 的 Stage29 效用率（`utility_rate`）为 `0.2000`、攻击成功率（`attack_success_rate`）为 `0.0000`；`full_query_guard` 的攻击成功率为 `0.1500`；`risk_non_oracle_guarded_sources` 的拒答率（`abstain_rate`）为 `1.0000`。

### 5.13 Stage30 项目整理与报告整合

Stage30 不调用外部 LLM，也不改变任何实验算法。它只整理报告入口、标注可归档产物、修复历史语法错误并清理可自动再生成的缓存。

主要产物：
- `outputs/reports/Stage30_项目整理与报告整合.md`
- `outputs/reports/stage30_report_inventory.csv`
- `outputs/reports/stage30_cleanup_manifest.csv`
- `outputs/reports/实验结果总报告.md`

验证命令：

```powershell
.venv\Scripts\python.exe -m ruff check src\logicguard\graph\baseline.py src\logicguard\ms_graphrag\stage29_answer_audit.py tests\test_graphrag_baseline.py tests\test_ms_graphrag_stage29_answer_audit.py
.venv\Scripts\python.exe -m pytest tests\test_graphrag_baseline.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage28_risk_non_oracle_recovery.py -q
.venv\Scripts\python.exe -m pytest -q
```

整理结论：Stage30 后优先阅读总报告和 Stage30 索引；Stage24-28 的 smoke/formal 单项报告保留为历史审计证据，不再作为默认阅读入口。

### 5.14 Stage31 回答可用性消融

Stage31 不调用外部 LLM，只复用 Stage28 的 `risk_non_oracle_title_entity_bm25` recovered official GraphRAG sources。它离线比较 source ordering、top-k 和 prompt budget 对 answerability proxy 的影响。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.answerability_ablation `
  --config configs/ms_graphrag_stage31_answerability_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_rows.jsonl`
- `outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_summary.csv`
- `outputs/ms_graphrag_query/stage31_poisoned20_answerability_ablation_examples.jsonl`
- `outputs/reports/Stage31_AnswerabilityAblation_20Query.md`

当前 20-query 结果：
- Stage28 默认近似设置 `official_order + top-8 + stage28` 的 clean answerable rate 为 `0.5500`。
- 最佳非 oracle 设置 `title_query_overlap + top-8 + compact` 的 clean answerable rate 为 `0.6000`，support hit 为 `1.0000`，unsafe context 为 `0.0000`。
- oracle 诊断上界 `oracle_answer_surface_first` 达到 `0.7500`，说明仍有约 25% query 不是单靠排序和 prompt budget 能解决。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage31_answerability_ablation.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage31_answerability_ablation.py tests\test_ms_graphrag_stage31_answerability_ablation.py
```

### 5.15 Stage32 真实回答对照验证

Stage32 调用真实 LLM，复用 Stage28 的 `risk_non_oracle_title_entity_bm25` recovered official GraphRAG sources，对比 Stage28 默认渲染与 Stage31 推荐的 `title_query_overlap` 渲染。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.llm_comparison `
  --config configs/ms_graphrag_stage32_llm_comparison_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_cases.jsonl`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_results.jsonl`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_summary.csv`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_pairwise.csv`
- `outputs/ms_graphrag_query/stage32_poisoned20_llm_comparison_examples.jsonl`
- `outputs/reports/Stage32_LLMComparison_20Query.md`

当前 20-query 结果：
- `stage28_default` 的 `correct_rate=0.1500`、`utility_rate=0.1500`、`abstain_rate=0.7500`、`attack_success_rate=0.0000`。
- `stage31_title_query_overlap` 的 `correct_rate=0.2500`、`utility_rate=0.2500`、`abstain_rate=0.6500`、`attack_success_rate=0.0000`。
- pairwise：utility delta 为 `+0.1000`，candidate 改善 `2/20`、退化 `0/20`、持平 `18/20`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage32_llm_comparison.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage32_llm_comparison.py tests\test_ms_graphrag_stage32_llm_comparison.py
```

### 5.16 Stage33 Title-Overlap 正式回答管线

Stage33 调用真实 LLM，把 Stage32 验证有效的 `title_query_overlap + top-8 + 450 chars/source` 固化到正式 `answer_level_llm_verification` 管线。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
# 1. 真实 LLM answer generation
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage33_answer_llm_ordered_poisoned20.yaml

# 2. 复用 Stage29 审计逻辑
.venv\Scripts\python.exe -m logicguard.evaluation.answer_audit `
  --config configs/ms_graphrag_stage33_answer_audit_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_llm_cases.jsonl`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_llm_results.jsonl`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_llm_summary.csv`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_audit_summary.csv`
- `outputs/ms_graphrag_query/stage33_poisoned20_answer_audit_breakdown.csv`
- `outputs/reports/Stage33_TitleOverlapPipeline_20Query.md`
- `outputs/reports/Stage33_AnswerAudit_TitleOverlap_20Query.md`

当前 20-query 结果：
- 原始真实 LLM：`correct_rate=0.2500`、`utility_rate=0.2500`、`abstain_rate=0.6500`、`attack_success_rate=0.0000`。
- 审计后：`stage29_correct_rate=0.3000`、`stage29_utility_rate=0.3000`、`stage29_attack_success_rate=0.0000`。
- 失败归因：`abstain_without_gold_answer_surface=8/20`、`abstain_despite_gold_answer_surface=5/20`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage32_llm_comparison.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\answer_level_llm_verification.py tests\test_ms_graphrag_stage27_answer_llm_verification.py
```

### 5.17 Stage34 回答裁判增强审计

Stage34 复用 Stage33 审计结果，只对本地归一化后仍为 `incorrect` 的非拒答样本调用 LLM judge。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.judge_audit `
  --config configs/ms_graphrag_stage34_answer_judge_audit_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_results.jsonl`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_summary.csv`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_breakdown.csv`
- `outputs/ms_graphrag_query/stage34_poisoned20_answer_judge_examples.jsonl`
- `outputs/reports/Stage34_AnswerJudgeAudit_20Query.md`

当前 20-query 结果：
- judge call rate 为 `0.0500`，20 个 query 中仅 1 个需要语义裁判。
- Stage33 本地审计 `utility_rate=0.3000`；Stage34 judge-aware `final_utility_rate=0.3500`。
- `final_incorrect_rate=0.0000`，`final_attack_success_rate=0.0000`。
- 主要剩余瓶颈仍是拒答：`abstain_without_gold_answer_surface=8/20`，`abstain_despite_gold_answer_surface=5/20`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage34_answer_judge_audit.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage34_answer_judge_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py
```

### 5.18 Stage35 候选源扩展诊断

Stage35 不调用外部 LLM。它复用 Stage28/33 recovered official GraphRAG sources、Stage34 judge-aware 审计结果和 clean reference candidate pool，离线评估 source enrichment 对 `abstain_without_gold_answer_surface` 的改善。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.source_enrichment `
  --config configs/ms_graphrag_stage35_source_enrichment_poisoned20.yaml
```

主要产物：
- `outputs/ms_graphrag_query/stage35_poisoned20_query_bm25_append_top12_contexts.jsonl`
- `outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_rows.jsonl`
- `outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_summary.csv`
- `outputs/ms_graphrag_query/stage35_poisoned20_source_enrichment_examples.jsonl`
- `outputs/reports/Stage35_SourceEnrichment_20Query.md`

当前 20-query 结果：
- Stage33 top-8 baseline：`support_answer_surface_rate=0.5500`，`clean_answerable_rate=0.6000`。
- `query_bm25_append + top-12`：`support_answer_surface_rate=0.7500`，`clean_answerable_rate=0.8000`，`full_support_hit_rate=0.8000`，`unsafe_context_rate=0.0000`。
- 目标失败类 `abstain_without_gold_answer_surface=8/20` 中，`target_failure_support_gain_rate=0.5000`。
- oracle support append 上界：`support_answer_surface_rate=0.8500`，`clean_answerable_rate=0.9000`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage35_source_enrichment.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage35_source_enrichment.py tests\test_ms_graphrag_stage35_source_enrichment.py
```

### 5.19 Stage36 Enriched Contexts 真实 LLM 复验

Stage36 调用真实 LLM。它复用 Stage35 生成的 `query_bm25_append + top-12` enriched contexts，先生成答案，再运行 Stage29 本地审计，最后运行 Stage34 judge-aware 审计。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
# 1. 真实 LLM answer generation
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage36_answer_llm_enriched_poisoned20.yaml

# 2. Stage29 本地审计
.venv\Scripts\python.exe -m logicguard.evaluation.answer_audit `
  --config configs/ms_graphrag_stage36_answer_audit_enriched_poisoned20.yaml

# 3. Stage34 judge-aware 审计
.venv\Scripts\python.exe -m logicguard.evaluation.judge_audit `
  --config configs/ms_graphrag_stage36_answer_judge_audit_enriched_poisoned20.yaml
```

主要产物：
- `outputs/reports/Stage36_EnrichedContextLLM_20Query.md`
- `outputs/reports/Stage36_AnswerLLM_Enriched_20Query.md`
- `outputs/reports/Stage36_AnswerAudit_Enriched_20Query.md`
- `outputs/reports/Stage36_AnswerJudgeAudit_Enriched_20Query.md`
- `outputs/ms_graphrag_query/stage36_poisoned20_answer_llm_results.jsonl`
- `outputs/ms_graphrag_query/stage36_poisoned20_answer_audit_results.jsonl`
- `outputs/ms_graphrag_query/stage36_poisoned20_answer_judge_results.jsonl`
- `outputs/ms_graphrag_query/stage36_poisoned20_answer_judge_summary.csv`

当前 20-query 结果：
- raw LLM：`utility_rate=0.7500`，`abstain_rate=0.1500`，`attack_success_rate=0.0000`。
- Stage29 audit：`stage29_utility_rate=0.8000`，`stage29_incorrect_rate=0.0500`。
- judge-aware final：`final_utility_rate=0.8500`，`final_incorrect_rate=0.0000`，`final_attack_success_rate=0.0000`。
- 相比 Stage34 judge-aware final utility `0.3500`，Stage36 提升到 `0.8500`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\answer_level_llm_verification.py src\logicguard\ms_graphrag\stage29_answer_audit.py src\logicguard\ms_graphrag\stage34_answer_judge_audit.py tests\test_ms_graphrag_stage29_answer_audit.py
```

### 5.20 Stage37 Evidence Prompt 复验

Stage37 复用 Stage35 的 `query_bm25_append + top-12` enriched contexts，但在 answer generation 中启用 `prompt_policy=evidence_compare`。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
# 1. evidence prompt 真实 LLM answer generation
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage37_answer_llm_evidence_prompt_poisoned20.yaml

# 2. Stage29 本地审计
.venv\Scripts\python.exe -m logicguard.evaluation.answer_audit `
  --config configs/ms_graphrag_stage37_answer_audit_evidence_prompt_poisoned20.yaml

# 3. Stage34 judge-aware 审计
.venv\Scripts\python.exe -m logicguard.evaluation.judge_audit `
  --config configs/ms_graphrag_stage37_answer_judge_audit_evidence_prompt_poisoned20.yaml
```

主要产物：
- `outputs/reports/Stage37_EvidencePrompt_20Query_中文综合报告.md`
- `outputs/reports/Stage37_AnswerLLM_EvidencePrompt_20Query.md`
- `outputs/reports/Stage37_AnswerAudit_EvidencePrompt_20Query.md`
- `outputs/reports/Stage37_AnswerJudgeAudit_EvidencePrompt_20Query.md`
- `outputs/ms_graphrag_query/stage37_poisoned20_answer_llm_results.jsonl`
- `outputs/ms_graphrag_query/stage37_poisoned20_answer_audit_results.jsonl`
- `outputs/ms_graphrag_query/stage37_poisoned20_answer_judge_results.jsonl`
- `outputs/ms_graphrag_query/stage37_poisoned20_answer_judge_summary.csv`

当前 20-query 结果：
- raw LLM：`utility_rate=0.7000`，`abstain_rate=0.1500`，`attack_success_rate=0.0000`。
- Stage29 audit：`stage29_utility_rate=0.8000`，`stage29_incorrect_rate=0.0500`。
- judge-aware final：`final_utility_rate=0.8500`，`final_incorrect_rate=0.0000`，`final_attack_success_rate=0.0000`。
- 与 Stage36 final utility `0.8500` 持平，说明下一步重点应转向 chain-completeness 与 second-hop evidence 补全。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_llm_generation.py tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\llm\context.py src\logicguard\ms_graphrag\answer_level_llm_verification.py src\logicguard\ms_graphrag\stage29_answer_audit.py src\logicguard\ms_graphrag\stage34_answer_judge_audit.py tests\test_llm_generation.py tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py
```

### 5.21 Stage38 链路完整性与二跳补证诊断

Stage38 不调用外部 LLM。它复用 Stage35 的 `query_bm25_append + top-12` contexts、Stage37 judge-aware 结果和 clean reference candidate pool，离线诊断 answer surface 与 full support chain 的差异，并生成 `stage38_second_hop_append_top14` targeted contexts。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.defense.chain_completion `
  --config configs/ms_graphrag_stage38_chain_completeness_poisoned20.yaml
```

主要产物：
- `outputs/reports/Stage38_ChainCompleteness_SecondHop_20Query.md`
- `outputs/ms_graphrag_query/stage38_poisoned20_chain_completeness_rows.jsonl`
- `outputs/ms_graphrag_query/stage38_poisoned20_chain_completeness_summary.csv`
- `outputs/ms_graphrag_query/stage38_poisoned20_second_hop_append_top14_contexts.jsonl`
- `outputs/ms_graphrag_query/stage38_poisoned20_chain_completeness_examples.jsonl`

当前 20-query 结果：
- 基线：`full_support_hit_rate=0.8000`，`chain_complete_rate=0.8000`，`answer_surface_rate=0.8000`。
- Stage38 targeted append：`targeted_full_support_hit_rate=1.0000`，`targeted_chain_complete_rate=1.0000`，`full-support gain=0.2000`。
- 4 个缺失 support 均补入 targeted context：`4684`、`1440`、`551`、`2762`。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage38_chain_completeness.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage38_chain_completeness.py tests\test_ms_graphrag_stage38_chain_completeness.py
```

### 5.22 Stage39 二跳补证真实回答复验

Stage39 调用真实 LLM。它复用 Stage38 生成的 `stage38_second_hop_append_top14` targeted contexts，先生成答案，再运行 Stage29 本地审计和 Stage34 judge-aware 审计。运行前需要确保环境变量 `DASHSCOPE_API_KEY` 和 `DASHSCOPE_BASE_URL` 已设置。

运行命令：

```powershell
# 1. Stage38 targeted contexts 真实 LLM answer generation
.venv\Scripts\python.exe -m logicguard.evaluation.answer_generation `
  --config configs/ms_graphrag_stage39_answer_llm_second_hop_poisoned20.yaml

# 2. Stage29 本地审计
.venv\Scripts\python.exe -m logicguard.evaluation.answer_audit `
  --config configs/ms_graphrag_stage39_answer_audit_second_hop_poisoned20.yaml

# 3. Stage34 judge-aware 审计
.venv\Scripts\python.exe -m logicguard.evaluation.judge_audit `
  --config configs/ms_graphrag_stage39_answer_judge_audit_second_hop_poisoned20.yaml
```

主要产物：
- `outputs/reports/Stage39_SecondHopAnswer_20Query_中文综合报告.md`
- `outputs/reports/Stage39_AnswerLLM_SecondHop_20Query.md`
- `outputs/reports/Stage39_AnswerAudit_SecondHop_20Query.md`
- `outputs/reports/Stage39_AnswerJudgeAudit_SecondHop_20Query.md`
- `outputs/ms_graphrag_query/stage39_poisoned20_answer_llm_results.jsonl`
- `outputs/ms_graphrag_query/stage39_poisoned20_answer_audit_results.jsonl`
- `outputs/ms_graphrag_query/stage39_poisoned20_answer_judge_results.jsonl`
- `outputs/ms_graphrag_query/stage39_poisoned20_answer_judge_summary.csv`

当前 20-query 结果：
- raw LLM：`utility_rate=0.8000`，`abstain_rate=0.0500`，`attack_success_rate=0.0000`。
- Stage29 audit：`stage29_utility_rate=0.9000`，`stage29_incorrect_rate=0.0500`。
- judge-aware final：`final_correct_rate=0.9000`，`final_partial_rate=0.0500`，`final_utility_rate=0.9500`，`final_attack_success_rate=0.0000`。
- 与 Stage37 final utility `0.8500` 相比提升 `+0.1000`；2 条从拒答变正确，0 条退化。

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage27_answer_llm_verification.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\answer_level_llm_verification.py src\logicguard\ms_graphrag\stage29_answer_audit.py src\logicguard\ms_graphrag\stage34_answer_judge_audit.py tests\test_ms_graphrag_stage29_answer_audit.py tests\test_ms_graphrag_stage34_answer_judge_audit.py
```

### 5.23 Stage40 跨数据集 official GraphRAG readiness 审计

Stage40 不调用 GraphRAG 和 LLM，只检查 2WikiMultihopQA、HotpotQA、MuSiQue 是否具备进入 official GraphRAG source recovery、chain completeness 和 answer-level 复验的前置资产。

运行命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.cross_dataset_audit `
  --config configs/ms_graphrag_stage40_cross_dataset_audit.yaml
```

主要产物：
- `outputs/reports/Stage40_CrossDatasetReadiness_OfficialGraphRAG.md`
- `outputs/ms_graphrag_query/stage40_cross_dataset_readiness_summary.csv`
- `outputs/ms_graphrag_query/stage40_cross_dataset_asset_rows.jsonl`
- `outputs/ms_graphrag_query/stage40_cross_dataset_gap_actions.jsonl`

当前审计结果：
- `2wikimultihopqa`：Stage28/35/38/39 相关 official GraphRAG 资产均 ready。
- `hotpotqa`：processed samples、corpus、query integrity ready，但 clean/poisoned official GraphRAG workspaces missing。
- `musique`：processed samples、corpus、query integrity ready，但 clean/poisoned official GraphRAG workspaces missing。
- 因此 Stage40 只产生 readiness/gap 结论，不能报告 HotpotQA/MuSiQue 的 utility 或 attack success。

HotpotQA/MuSiQue 的下一步补齐命令可从以下文件读取：

```powershell
Get-Content outputs\ms_graphrag_query\stage40_cross_dataset_gap_actions.jsonl
```

验证命令：

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage40_cross_dataset_audit.py -q
.venv\Scripts\python.exe -m ruff check src\logicguard\ms_graphrag\stage40_cross_dataset_audit.py tests\test_ms_graphrag_stage40_cross_dataset_audit.py
```

### 5.24 Stage41 HotpotQA/MuSiQue official GraphRAG 索引与 baseline/broad context 补齐

Stage41 补齐 Stage40 发现的 HotpotQA/MuSiQue official GraphRAG 索引缺口，并导出 5-query baseline/broad contexts。GraphRAG 相关命令使用隔离环境 `tools\ms_graphrag\.venv`，运行前需要设置 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`。

1. 准备 workspace input：

```powershell
.venv\Scripts\python.exe -m logicguard.ms_graphrag.prepare_workspace `
  --dataset hotpotqa `
  --sample-path data/processed/hotpotqa/debug_50.jsonl `
  --corpus-path data/logicpoison_official/clean/hotpotqa/corpus.jsonl `
  --workspace-root outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready `
  --doc-scope sample_support

.venv\Scripts\python.exe -m logicguard.ms_graphrag.prepare_workspace `
  --dataset hotpotqa `
  --sample-path data/processed/hotpotqa/debug_50.jsonl `
  --corpus-path data/logicpoison_official/poisoned/hotpotqa/corpus.jsonl `
  --workspace-root outputs/ms_graphrag/hotpotqa/stage40_debug50_poisoned_query_ready `
  --doc-scope sample_support

.venv\Scripts\python.exe -m logicguard.ms_graphrag.prepare_workspace `
  --dataset musique `
  --sample-path data/processed/musique/debug_50.jsonl `
  --corpus-path data/logicpoison_official/clean/musique/corpus.jsonl `
  --workspace-root outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready `
  --doc-scope sample_support

.venv\Scripts\python.exe -m logicguard.ms_graphrag.prepare_workspace `
  --dataset musique `
  --sample-path data/processed/musique/debug_50.jsonl `
  --corpus-path data/logicpoison_official/poisoned/musique/corpus.jsonl `
  --workspace-root outputs/ms_graphrag/musique/stage40_debug50_poisoned_query_ready `
  --doc-scope sample_support
```

2. 复用 2Wiki Stage10 的 `settings.yaml` 与 `prompts` 后执行索引：

```powershell
tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready `
  --method fast

tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/hotpotqa/stage40_debug50_poisoned_query_ready `
  --method fast

tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready `
  --method fast

tools\ms_graphrag\.venv\Scripts\python.exe -m graphrag index `
  --root outputs/ms_graphrag/musique/stage40_debug50_poisoned_query_ready `
  --method fast
```

3. 导出 5-query baseline/broad contexts：

```powershell
$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.official_local_context `
  --config configs/ms_graphrag_stage40_hotpotqa_official_local_baseline.yaml
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.official_local_context `
  --config configs/ms_graphrag_stage40_hotpotqa_official_local_broad.yaml
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.official_local_context `
  --config configs/ms_graphrag_stage40_musique_official_local_baseline.yaml
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.official_local_context `
  --config configs/ms_graphrag_stage40_musique_official_local_broad.yaml
```

主要产物：
- `outputs/reports/Stage41_CrossDatasetGraphRAGIndexAndContext_中文报告.md`
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/hotpotqa/stage40_debug50_poisoned_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_clean_query_ready`
- `outputs/ms_graphrag/musique/stage40_debug50_poisoned_query_ready`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned5_broad_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_official_local_context.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned5_broad_context.jsonl`

当前结果：
- HotpotQA clean/poisoned 已完成 100 docs 索引；community reports 为 `32/23`。
- MuSiQue clean/poisoned 已完成 117 docs 索引；community reports 为 `25/24`。
- Stage40 readiness 复查后，HotpotQA/MuSiQue 下一阻断项为 `run_query_guard_context_export`。

验证命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.cross_dataset_audit `
  --config configs/ms_graphrag_stage40_cross_dataset_audit.yaml
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_stage40_cross_dataset_audit.py -q
```

### 5.25 Stage42 HotpotQA/MuSiQue query-guard source context 导出

Stage42 为 HotpotQA/MuSiQue 生成 20-query `full_query_guard` official source contexts。`query_layer_context` 依赖 GraphRAG 包，需要使用 `tools\ms_graphrag\.venv` 并设置 `PYTHONPATH=src`；`query_layer_seeding` 和 `query_layer_evaluation` 使用主 `.venv`。

运行命令：

```powershell
# HotpotQA
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs/ms_graphrag_stage40_hotpotqa.yaml
$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs/ms_graphrag_stage40_hotpotqa.yaml
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_evaluation `
  --config configs/ms_graphrag_stage40_hotpotqa.yaml

# MuSiQue
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_seeding `
  --config configs/ms_graphrag_stage40_musique.yaml
$env:PYTHONPATH='src'
tools\ms_graphrag\.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_context `
  --config configs/ms_graphrag_stage40_musique.yaml
.venv\Scripts\python.exe -m logicguard.ms_graphrag.query_layer_evaluation `
  --config configs/ms_graphrag_stage40_musique.yaml
```

主要产物：
- `outputs/reports/Stage42_CrossDatasetQueryGuardContext_中文报告.md`
- `configs/ms_graphrag_stage40_hotpotqa.yaml`
- `configs/ms_graphrag_stage40_musique.yaml`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_seed_plan.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_seed_plan.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_contexts_full_query_guard.jsonl`
- `outputs/ms_graphrag_query/stage40_hotpotqa_poisoned20_query_guard_summary.csv`
- `outputs/ms_graphrag_query/stage40_musique_poisoned20_query_guard_summary.csv`

当前结果：
- HotpotQA `full_query_guard`：`gold_support_recall=0.8750`，`changed_exposure=0.8750`，`context_recall_failure_count=2`。
- MuSiQue `full_query_guard`：`gold_support_recall=0.7375`，`changed_exposure=0.7375`，`context_recall_failure_count=0`。
- Stage40 readiness 复查后，HotpotQA/MuSiQue 下一阻断项为 `run_stage28_risk_non_oracle_recovery`。

验证命令：

```powershell
.venv\Scripts\python.exe -m logicguard.evaluation.cross_dataset_audit `
  --config configs/ms_graphrag_stage40_cross_dataset_audit.yaml
.venv\Scripts\python.exe -m pytest tests\test_ms_graphrag_query_layer_seeding.py tests\test_ms_graphrag_query_layer_context.py tests\test_ms_graphrag_query_layer_evaluation.py -q
```

## WP2 A1/A3 机制预算与后端 trace 资格锚点（2026-09-08）

以下命令只读取项目内冻结的上游资产、历史 Microsoft GraphRAG clean trace、clean corpus 和 LightRAG schema fixture，不生成攻击、不索引、不调用 provider：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
uv run python -m logicguard.benchmark.wp2_qualification_runner `
  --config configs\benchmark\comparison_v1_2_a1_a3_trace_qualification.yaml
uv run pytest tests\test_attack_qualification.py `
  tests\test_backend_trace_adapters.py `
  tests\test_wp2_qualification_runner.py -q
```

预期状态为 `LOCAL_QUALIFICATION_PASSED_WITH_DECLARED_BOUNDARIES`：A1 为 100 records/500 texts；A3 为 74 records、1,555 raw texts、1,461 selected occurrences、1,341 unique selected texts；Microsoft GraphRAG 为 50 rows/1,870 exact clean sources；LightRAG 为 1 个 2-hit fixture 且 `real_trace_rows=0`。产物位于 `artifacts/benchmark/research_revision_v1_2/wp2/a1_a3_backend_trace_qualification_anchor/`。重放会校验配置、五个输入和所有派生产物 hash；输入或配置改变时拒绝混入该 namespace。provider 调用 0，费用 ¥0。

## 🔄 WP2 common-dev 物化与真实 LightRAG trace（2026-09-10）

物化器只复用已经冻结的两个 generation-valid pilot，不生成新攻击、不读取 API key：

```powershell
cd F:\LogicGuard_project\logicguard
$env:PYTHONPATH='src'
uv run python -m logicguard.benchmark.attack_corpus_materializer `
  --config configs\benchmark\comparison_v1_2_a1_a3_common_dev_materialization_anchor.yaml
```

真实 LightRAG trace 使用隔离环境和已有十文档索引的副本。该 namespace 已完成，禁止为了重看结果而重跑付费命令：

```powershell
$env:PYTHONPATH='src'
tools\lightrag\.venv\Scripts\python.exe -m logicguard.benchmark.lightrag_trace_capture `
  --config configs\benchmark\comparison_v1_2_lightrag_real_trace_anchor.yaml
```

冻结结果为 hybrid 1 query/6 chunks、1 次 LLM、1 次 embedding、666/37 chat tokens、33 embedding tokens，目录价 ¥0.001644；thinking/retry=0，原索引 hash 未变化。输出位于 `artifacts/benchmark/research_revision_v1_2/wp2/lightrag_real_trace_anchor/`。

以下合同命令为纯本地运行，可重复执行时校验不可变 namespace：

```powershell
uv run python -m logicguard.benchmark.real_trace_contract_runner `
  --config configs\benchmark\comparison_v1_2_real_trace_contract_anchor.yaml
uv run pytest tests\test_attack_corpus_materializer.py `
  tests\test_real_trace_contract_runner.py `
  tests\test_backend_trace_adapters.py -q
```

预期为双后端 2 条真实 trace、48 个 exact clean hits、4 条 T0/T1 context、2 条 audit、0 失败。该运行固定为 0% trusted coverage，只验证 native trace 可以进入统一合同；不能把它复述为真实可信池检索或防御效果。
