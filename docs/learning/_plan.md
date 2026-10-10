# LogicGuard 学习手册实施计划

状态：正文与角色功能 SVG 已完成；已做源码事实交叉复核、本地链接检查及 SVG 结构检查。两组安全学习测试共 31 项通过。本文件记录导读的制作计划与验收，不替代项目事实源。

## Task 1：建立全局心智模型

- 读取 README、handoff、v1.2 protocol、methodology、codeNavigation。
- 画出三条代码线和端到端实验时序。
- 明确当前事实源与历史文档边界。

## Task 2：按数据流讲解核心代码

- 从 `NormalizedSample` 开始讲数据。
- 解释轻量图、攻击、风险恢复、官方 GraphRAG、回答审计。
- 用一个两跳问题示例解释 support hit、answer surface、chain complete。

## Task 3：讲清 benchmark 与研究状态

- 解释 A1–A4、S1/S2、D0–D7、T0/T1 和漏斗指标。
- 解释 dev60、RequestCostGuard、unknown 和固定分母。
- 区分 WP1 已完成、WP2 部分完成、WP3–WP5 待完成。

## Task 4：学习路线与验证

- 提供小白/后端/研究者三条阅读路径。
- 提供不调用 provider 的测试命令。
- 给出从读代码到能够改需求的练习和排错方法。

## 交付

正文：`logicguard-完整框架教程.md`。<br>
本手册现已归档到仓库 `docs/learning/`，作为项目学习材料；不改变源码运行逻辑。
