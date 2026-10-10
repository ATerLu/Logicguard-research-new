# uisee-dev 调研资料导入记录（2026-09-12）

## 来源

- 仓库：`https://github.com/ATerLu/Logicguard-research-new.git`
- 分支：`uisee-dev`
- 拉取时 HEAD：`13aa86aea9e8dd7300cbf9bf93d4f88c41919369`
- 第一批调研提交：`de59ff9`（`docs: add LogicGuard paper reviews and experiment plan`）
- 第二批调研提交：`13aa86a`（`docs: add second LogicGuard paper review set`）

## 导入内容

- `papper/`：第一批 40 篇论文 PDF
- `papers_manifest.tsv`：第一批论文元数据清单
- `read_list.md`：第一批逐篇调研解读
- `papper2/`：第二批 40 篇论文 PDF
- `papers_manifest2.tsv`：第二批论文元数据清单
- `read_list2.md`：第二批逐篇调研解读
- `实验规划.md`：远端大规模对比实验规划 v1.0

## 同步边界

本次只导入远端新增的调研资料。没有用远端镜像中的 `handoff.md`、`docs/results.md`、`docs/methodology.md`、`docs/reproducibility.md` 或代码覆盖本地文件；`F:\LogicGuard_project\logicguard` 继续是唯一开发事实源。临时克隆目录只用于读取和逐文件哈希核验，不作为开发目录，也没有使用 `.logicguard_remote_backup`。

`实验规划.md` 是 2026-09-03 的调研规划材料。若其内容与本地主线的 `docs/thesisPlan.md` 或 `docs/comparativeExperimentPreregistration_v1.2.md` 冲突，以本地主线文档为准。
