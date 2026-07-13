# Stage28 risk non-oracle official sources recovery

## Purpose

Stage28 replaces the Stage25 risk oracle with a source risk detector that uses clean-candidate consistency rather than changed labels. Changed-support metadata is used only for offline evaluation.

## Detector

- Select a clean candidate by exact source title when available, otherwise by title/entity BM25.
- Compare capitalized entity-token drift between the current source and the clean candidate.
- Mark a source risky when title overlap and entity drift cross configured thresholds.

## Summary

| method | queries | gold recall | changed exposure | risk recall | risk precision | risk FP rate | avg filtered | avg recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full_query_guard | 5 | 0.9000 | 0.9000 | 0.9854 | 1.0000 | 0.0000 | 0.00 | 0.00 |
| risk_non_oracle_guarded_sources | 5 | 0.0000 | 0.0000 | 0.9854 | 1.0000 | 0.0000 | 23.40 | 0.00 |
| risk_non_oracle_title_entity_bm25 | 5 | 0.9000 | 0.0000 | 0.9854 | 1.0000 | 0.0000 | 0.00 | 23.40 |

## Artifacts

- context JSONL: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage28_poisoned5_risk_non_oracle_sources_contexts.jsonl`
- query metrics CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage28_poisoned5_risk_non_oracle_sources_metrics.csv`
- method summary CSV: `F:/LogicGuard_project/logicguard/outputs/ms_graphrag_query/stage28_poisoned5_risk_non_oracle_sources_summary.csv`
