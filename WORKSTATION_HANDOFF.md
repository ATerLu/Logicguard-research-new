# LogicGuard 工作站迁移与接手续作说明

更新日期：2026-09-18
GitHub：`https://github.com/ATerLu/Logicguard-research-new`
工作分支：`uisee-dev`

## 1. 克隆

```powershell
git clone --branch uisee-dev --single-branch `
  https://github.com/ATerLu/Logicguard-research-new.git logicguard
cd logicguard
```

克隆后的目录是新工作站的开发事实源。不要把 `.logicguard_remote_backup`、旧镜像目录或临时 clone 当作开发目录。

## 2. 首次阅读顺序

1. `handoff.md`
2. `docs/thesisPlan.md`
3. `docs/results.md`
4. `docs/methodology.md`
5. `docs/reproducibility.md`
6. `docs/comparativeExperimentPreregistration_v1.2.md`
7. `docs/D3_D4_ExternalDefense_WP2_Qualification.md`
8. `docs/A1_A3_BackendTrace_WP2_Qualification.md`

## 3. Python 环境

安装与 `.python-version` 相符的 Python 后，优先使用锁文件恢复：

```powershell
uv sync --frozen
```

项目还使用隔离的 Microsoft GraphRAG、LightRAG、LogicPoison 和 RAGDefender 运行环境。它们的具体版本、命令和模型 revision 以 `docs/reproducibility.md` 为准；不要把旧机器的 `.venv` 直接复制到新机器。

## 4. 未进入 Git 的外部资产

Git 仓库有意不包含：

- API key、`.env` 和用户级环境变量；
- 原始及处理数据；
- 全量 clean/poisoned corpus 副本；
- Microsoft GraphRAG/LightRAG 工作区、索引和缓存；
- Hugging Face 模型快照；
- 全量 `outputs/` 中间产物；
- 上游仓库自己的 `.git` 元数据。

旧机器数据文件的相对路径、字节数和 SHA-256 位于 `EXTERNAL_ASSETS_SHA256.tsv`。恢复文件后必须按该清单核验；如果没有相同哈希，应视为新的数据版本或新实验 namespace，不能静默续跑旧实验。

先恢复固定版本的上游仓库：

```powershell
.\scripts\bootstrap_upstreams.ps1
```

再将旧机器 `data/` 下的外部资产复制到同一相对路径，并核验：

```powershell
.\scripts\verify_external_assets.ps1
```

仅查看仍缺哪些资产而不让脚本失败，可使用 `-AllowMissing`。这两个脚本都不会写入或传输任何 API key；上游恢复脚本也不会覆盖已经存在但版本不符的 checkout。

必要环境变量只在新机器本地设置，不得写入仓库：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL`

## 5. Git 中已经保留的关键研究资产

- Stage40/46/47 的精选结果与案例；
- Stage47 和 Stage48 的冻结攻击记录与完整性记录；
- Stage48 fixed-50 inventory、失败 taxonomy、暴露/回答汇总与费用清单；
- WP1 v1.2 审计、dev60 清单、split、指标测试产物；
- WP2 A1/A2/A3、T0/T1、双后端 trace、RAGDefender/HoG-GRAG 资格产物；
- 两批论文调研、论文 manifest 和比较实验规划。

这些资产用于继续研究和复核，不代表所有攻击或防御已经完成正式效果比较。

## 6. 首次质量门

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\ruff.exe format --check src tests scripts
```

若依赖或外部模型尚未恢复，先记录缺失项，不要修改测试来绕过失败。

## 7. 当前续作点

Stage48 已以 Gate A 失败关闭；WP1 已完成，WP2 部分完成。下一项开发任务是冻结并执行完整 dev60 的 A1/A2/A3 请求和 materialization 启动清单，包括：

- 模型 revision；
- 最大调用数、token 与费用 hard cap；
- unknown/in-flight 计账；
- 停止规则；
- clean/poisoned corpus hash；
- 不因攻击成败替换问题的固定分母。

随后才进入真实 trusted-pool retrieval、D6 development 和外部防御效果比较。D4 HoG-GRAG 仍需作者修正版或单独预注册 bounded reimplementation，不能把当前公开工件失败写成方法无效。
