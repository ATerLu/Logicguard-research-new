# Stage48-E1 Paired Defense and Clean Control

## Pooled answer results

| method | n | source exposed | target exposed | targeted ASR / exposed | attacked acc. | clean acc. | delta | clean risk queries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `full_query_guard` | 14 | 9 | 7 | 0.7143 | 0.2143 | 0.2857 | -0.0714 | 10 |
| `risk_non_oracle_title_entity_bm25` | 14 | 8 | 7 | 0.4286 | 0.1429 | 0.1429 | 0.0000 | 10 |
| `stage35_query_bm25_append_top12` | 14 | 7 | 7 | 0.0000 | 0.3571 | 0.4286 | -0.0714 | 10 |
| `stage38_second_hop_append_top14` | 14 | 7 | 7 | 0.1429 | 0.3571 | 0.4286 | -0.0714 | 10 |

## Interpretation boundary

Targeted ASR is reported separately over all frozen attempts, exact-prompt source-exposed cases, and exact-prompt target-exposed cases. Clean utility uses the same query, attack-family batch, method, index scope and rendering policy. Transparent string classification is retained; no post-hoc LLM judge is introduced.

## Cost

- Exact logged paired increment: CNY 0.982251
- Increment including clean query-embedding upper bound: CNY 0.983147
