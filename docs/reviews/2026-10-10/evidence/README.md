# 离线审查证据

对应审查基线：`1bad5928753a786261d98637094115334eba3fbf`。原始输出记录的是当日环境，不是本次归档重新运行全量测试的结果。

归档时对复现脚本应用项目格式化规则，并移除差异文件末尾的额外空行；不改变复现逻辑或所记录的资产差异。

- `repro_contracts.py`：使用 fake client 和内存数据，复现响应校验、可信池和同信息预算审计的已知缺陷。
- `repro_truncated_tail.py`：仅写自动清理的临时目录，复现残缺 JSONL 尾行在继续追加后的读取错误。
- `probe_output.txt`：上述问题及附加 inline fixture 的历史输出。`provider_calls_made` 是假客户端计数，不代表付费 API 请求。
- `pytest_short.txt`：历史全量测试短 traceback，包含缺外部资产、可选依赖及平台差异；本机路径只是历史环境记录。
- `test_side_effect.diff`：历史测试曾改写冻结资产的证据，该资产在审查后已恢复。**不要运行 `git apply` 应用此差异。**

从仓库根目录运行两个离线脚本：

```bash
uv run --frozen python docs/reviews/2026-10-10/evidence/repro_contracts.py
uv run --frozen python docs/reviews/2026-10-10/evidence/repro_truncated_tail.py
```

脚本不调用真实 provider，也不写冻结研究资产。首个脚本断言已知缺陷存在，因此未来修复后断言失败可能是预期现象；不要为了让历史复现继续通过而回退修复。全量 pytest 曾有写冻结资产的副作用，应使用隔离副本，不直接在研究工作区重跑。
