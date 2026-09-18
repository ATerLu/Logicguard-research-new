# Stage48 Gate A Fixed-50 Context Exposure

First 50 queries per dataset; exactly 10 preselected evaluation-valid attacks per ready cell; no exposure- or success-conditioned replacement.

| Dataset | Attack | Prompt exposed | Rate | Wilson 95% CI |
| --- | --- | ---: | ---: | ---: |
| musique | natural_bridge | 2/10 | 20.0% | [5.7%, 51.0%] |
| musique | low_drift | 3/10 | 30.0% | [10.8%, 60.3%] |
| hotpotqa | natural_bridge | 2/10 | 20.0% | [5.7%, 51.0%] |
| hotpotqa | low_drift | 0/10 | 0.0% | [0.0%, 27.8%] |
| pooled_ready_datasets | low_drift | 3/20 | 15.0% | [5.2%, 36.0%] |
| pooled_ready_datasets | natural_bridge | 4/20 | 20.0% | [8.1%, 41.6%] |

Qualifying families: natural_bridge.
Context criterion passed: False.
System-level targeted ASR is not evaluated in this context-only report.

## Cost

Stage48 cumulative exact logged/catalog cost: CNY 3.555013.
Stage48 cumulative conservative upper bound: CNY 3.565319.
