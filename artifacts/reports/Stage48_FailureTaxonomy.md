# Stage48 冻结失败分类审计

> 本报告只读取 fixed-50 inventory 与既有 full-corpus exposure；不读取回答结果，不补样，不产生 API 调用。

## 固定分母漏斗

| 数据集 | 攻击家族 | attempted | generation-valid | evaluation-valid | selected | index | retrieved | prompt-exposed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hotpotqa | candidate_collision | 50 | 29 | 6 | 0 | 0 | 0 | 0 |
| hotpotqa | low_drift | 50 | 22 | 19 | 10 | 10 | 5 | 0 |
| hotpotqa | natural_bridge | 50 | 18 | 17 | 10 | 10 | 7 | 2 |
| musique | candidate_collision | 50 | 26 | 6 | 0 | 0 | 0 | 0 |
| musique | low_drift | 50 | 13 | 13 | 10 | 10 | 5 | 3 |
| musique | natural_bridge | 50 | 21 | 20 | 10 | 10 | 3 | 2 |

## 互斥终止分类

| 数据集 | 攻击家族 | 阶段 | 分类 | 数量 | attempted 占比 |
| --- | --- | --- | --- | ---: | ---: |
| hotpotqa | candidate_collision | selection | `cell_below_reindex_minimum` | 6 | 12.0% |
| hotpotqa | candidate_collision | evaluation | `collision_candidate_is_gold_support` | 22 | 44.0% |
| hotpotqa | candidate_collision | generation | `collision_did_not_trigger_entity_drift` | 1 | 2.0% |
| hotpotqa | candidate_collision | generation | `generation_error` | 1 | 2.0% |
| hotpotqa | candidate_collision | evaluation | `malicious_target_matches_gold` | 1 | 2.0% |
| hotpotqa | candidate_collision | generation | `missing_malicious_answer` | 19 | 38.0% |
| hotpotqa | low_drift | generation | `attack_did_not_change_source` | 2 | 4.0% |
| hotpotqa | low_drift | generation | `entity_drift_not_below_frozen_threshold` | 11 | 22.0% |
| hotpotqa | low_drift | selection | `fixed_quota_not_selected` | 9 | 18.0% |
| hotpotqa | low_drift | generation | `generation_error` | 1 | 2.0% |
| hotpotqa | low_drift | retrieval | `indexed_not_retrieved` | 5 | 10.0% |
| hotpotqa | low_drift | evaluation | `malicious_target_matches_gold` | 3 | 6.0% |
| hotpotqa | low_drift | generation | `missing_malicious_answer` | 14 | 28.0% |
| hotpotqa | low_drift | prompt | `prompt_source_exposed_target_truncated` | 3 | 6.0% |
| hotpotqa | low_drift | prompt | `retrieved_beyond_prompt_source_limit` | 1 | 2.0% |
| hotpotqa | low_drift | prompt | `target_surface_without_attack_source` | 1 | 2.0% |
| hotpotqa | natural_bridge | selection | `fixed_quota_not_selected` | 7 | 14.0% |
| hotpotqa | natural_bridge | generation | `generation_error` | 1 | 2.0% |
| hotpotqa | natural_bridge | retrieval | `indexed_not_retrieved` | 3 | 6.0% |
| hotpotqa | natural_bridge | evaluation | `malicious_target_matches_gold` | 1 | 2.0% |
| hotpotqa | natural_bridge | generation | `missing_malicious_answer` | 31 | 62.0% |
| hotpotqa | natural_bridge | complete | `prompt_source_and_target_exposed` | 2 | 4.0% |
| hotpotqa | natural_bridge | prompt | `prompt_source_exposed_target_truncated` | 1 | 2.0% |
| hotpotqa | natural_bridge | prompt | `retrieved_beyond_prompt_source_limit` | 3 | 6.0% |
| hotpotqa | natural_bridge | prompt | `target_surface_without_attack_source` | 1 | 2.0% |
| musique | candidate_collision | selection | `cell_below_reindex_minimum` | 6 | 12.0% |
| musique | candidate_collision | evaluation | `collision_candidate_is_gold_support` | 19 | 38.0% |
| musique | candidate_collision | generation | `collision_did_not_trigger_entity_drift` | 1 | 2.0% |
| musique | candidate_collision | generation | `generation_error` | 2 | 4.0% |
| musique | candidate_collision | evaluation | `malicious_target_matches_gold` | 1 | 2.0% |
| musique | candidate_collision | generation | `missing_malicious_answer` | 21 | 42.0% |
| musique | low_drift | generation | `entity_drift_not_below_frozen_threshold` | 11 | 22.0% |
| musique | low_drift | selection | `fixed_quota_not_selected` | 3 | 6.0% |
| musique | low_drift | generation | `generation_error` | 2 | 4.0% |
| musique | low_drift | retrieval | `indexed_not_retrieved` | 5 | 10.0% |
| musique | low_drift | generation | `missing_malicious_answer` | 17 | 34.0% |
| musique | low_drift | complete | `prompt_source_and_target_exposed` | 3 | 6.0% |
| musique | low_drift | prompt | `prompt_source_exposed_target_truncated` | 2 | 4.0% |
| musique | low_drift | generation | `target_source_not_in_attacker_visible_context` | 7 | 14.0% |
| musique | natural_bridge | selection | `fixed_quota_not_selected` | 10 | 20.0% |
| musique | natural_bridge | generation | `generation_error` | 2 | 4.0% |
| musique | natural_bridge | retrieval | `indexed_not_retrieved` | 7 | 14.0% |
| musique | natural_bridge | evaluation | `malicious_target_matches_gold` | 1 | 2.0% |
| musique | natural_bridge | generation | `missing_malicious_answer` | 27 | 54.0% |
| musique | natural_bridge | complete | `prompt_source_and_target_exposed` | 2 | 4.0% |
| musique | natural_bridge | prompt | `retrieved_beyond_prompt_source_limit` | 1 | 2.0% |

## 解释边界

- `fixed_quota_not_selected` 是预注册固定配额造成的抽样状态，不是攻击失败。
- `cell_below_reindex_minimum` 表示该家族未达到 10 条 evaluation-valid 门槛，不得以小分母继续建索引。
- `prompt_source_exposed_target_truncated` 与 `retrieved_beyond_prompt_source_limit` 分别隔离字符截断和 top-k 选择故障。
- `target_surface_without_attack_source` 不算攻击 Prompt 暴露，避免把其他来源中的同名字符串误归因给攻击文档。
- 本分类不改变 Stage48 Gate A 已失败的冻结结论，也不授权重跑任何付费 namespace。
