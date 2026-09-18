# Stage48-GateA-fixed50-expansion

固定尝试预算：每数据集前 50 个 query；生成失败保留且不按成功条件追加调用。

| dataset | attack family | attempted | generation-valid | evaluation-valid | selected | cell ready |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| musique | natural_bridge | 50 | 21 | 20 | 10 | true |
| musique | low_drift | 50 | 13 | 13 | 10 | true |
| musique | candidate_collision | 50 | 26 | 6 | 0 | false |
| hotpotqa | natural_bridge | 50 | 18 | 17 | 10 | true |
| hotpotqa | low_drift | 50 | 22 | 19 | 10 | true |
| hotpotqa | candidate_collision | 50 | 29 | 6 | 0 | false |

只允许 `cell ready=true` 的格进入 10-sample full-corpus context-only reindex。
未达门的格记录为攻击生成/评测有效性瓶颈，不得继续生成到凑满成功样本。

攻击生成精确日志成本：¥2.169140。
含 clean query embedding 保守上界：¥2.175540。
