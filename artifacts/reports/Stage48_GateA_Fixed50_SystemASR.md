# Stage48 Gate A Fixed-50 System Targeted ASR

System-level targeted ASR uses every evaluation-valid attempted case in each ready cell; non-exposed cases remain failures in the denominator.

| Dataset | Attack | Prompt exposed | Targeted success | System ASR | Wilson 95% CI |
| --- | --- | ---: | ---: | ---: | ---: |
| musique | natural_bridge | 2/10 | 2/10 | 20.0% | [5.7%, 51.0%] |
| hotpotqa | natural_bridge | 2/10 | 2/10 | 20.0% | [5.7%, 51.0%] |
| pooled_ready_datasets | natural_bridge | 4/20 | 4/20 | 20.0% | [8.1%, 41.6%] |

Context requirement passed: False.
System ASR passing families: natural_bridge.
Gate A passed: False.

## Cost

Stage48 cumulative exact logged/catalog cost: CNY 3.576961.
Stage48 cumulative conservative upper bound: CNY 3.587267.
