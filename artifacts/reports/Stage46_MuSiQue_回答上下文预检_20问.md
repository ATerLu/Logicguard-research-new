# Stage46-MuSiQue musique 回答上下文矩阵与提示词预检

## 目的

将 Stage43 风险恢复、Stage44 候选源扩展、Stage45 二跳补证与未恢复基线固定为同一批 query 的回答输入。预检依据实际渲染并截断后的 sources，而不是原始 JSONL 的全部 sources。

## 冻结设置

- query 数：`20`
- 策略数：`4`
- answer case 数：`80`
- 默认单源截断：`450` 字符
- `unrecovered_changed_exposure_rate`：在发生过 support 文档变更的 query 中，实际提示词仍包含未恢复变更 source 的比例。只有该比例足够高时，基线的零 ASR 才可以被解释为面对攻击压力的结果。

## 预检结果

| 方法 | query数 | 实际未恢复污染源暴露率 | 完整支持率 | 标准答案表面率 | 平均sources | 攻击压力状态 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `full_query_guard` | 20 | 1.0000 | 0.3500 | 0.2000 | 12.00 | 充分 |
| `risk_non_oracle_title_entity_bm25` | 20 | 0.0000 | 0.3500 | 0.3500 | 12.00 | 缺失 |
| `stage35_query_bm25_append_top12` | 20 | 0.0000 | 0.6000 | 0.4000 | 12.00 | 缺失 |
| `stage38_second_hop_append_top14` | 20 | 0.0000 | 0.8000 | 0.4000 | 14.00 | 缺失 |

## 攻击压力解释

基线的实际未恢复污染源暴露率为 `1.0000`，攻击压力判定为 `充分`。
`充分`表示暴露率至少 0.50，`有限`表示大于 0 但低于 0.50，`缺失`表示没有未恢复污染源进入实际提示词。该标签只限定 ASR 的可解释范围，不替代后续真实 LLM 回答与裁决。

## 产物

- 冻结上下文矩阵：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage46_musique_poisoned20_answer_context_matrix.jsonl`
- 实际提示词 cases：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage46_musique_poisoned20_answer_preflight_cases.jsonl`
- query 级预检：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage46_musique_poisoned20_answer_preflight_rows.jsonl`
- 方法汇总：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage46_musique_poisoned20_answer_preflight_summary.csv`
- 样例：`F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage46_musique_poisoned20_answer_preflight_examples.jsonl`
