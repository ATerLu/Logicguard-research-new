# LogicGuard Web Review Context

## What this repository is

LogicGuard is a research prototype for defending GraphRAG-style multi-hop QA against logical corpus poisoning. The central problem is that simply removing suspicious retrieved evidence can suppress attacks but often leaves the model with too little evidence to answer. LogicGuard therefore uses a chain of source risk detection, trusted-reference recovery, candidate-source enrichment, and selective second-hop supplementation.

This is a curated mirror for code review and research guidance. The local source worktree has raw datasets and large GraphRAG artifacts; they are intentionally excluded here. Read `README.md`, `docs/项目总览与路线图.md`, `docs/新窗口交接文档_2026-07-01.md`, and the reports in `artifacts/reports/` before drawing conclusions.

## Current verified baseline: Stage46

Stage46 is the latest frozen cross-dataset real-LLM answer evaluation.

- Datasets: HotpotQA and MuSiQue, 20 LogicPoison queries each.
- Answer model: `qwen3.7-plus`, temperature 0, `evidence_compare` prompt, 450 characters per source.
- Compared contexts: un-recovered `full_query_guard`, Stage43 risk recovery, Stage44 top-12 enrichment, Stage45 top-14 second-hop supplementation.
- The prompt preflight verified real attack pressure: un-recovered changed-source exposure is 0.85 on HotpotQA and 1.00 on MuSiQue.
- Un-recovered baseline final attack-success rate is 0.45 on HotpotQA and 0.10 on MuSiQue.
- All three defense contexts have final attack-success rate 0 on both datasets.
- Stage44 is the current default security-utility balance: final utility 0.85 on HotpotQA and 0.40 on MuSiQue.
- Stage45 adds no utility on HotpotQA but raises MuSiQue utility from 0.40 to 0.45, so it should be chain-diagnostic gated rather than unconditional.

The Stage46 conclusion is bounded: it is based on 20 queries per dataset, one answer model, and a trusted clean/reference candidate pool. It is not a production no-clean guarantee.

## Current research priority

The next planned stage is adaptive-attack evaluation against the frozen Stage46 defense:

1. Low-entity-drift factual rewrites that target the detector threshold.
2. Candidate collisions that cause recovery to choose an unsuitable clean candidate.
3. Evidence-fragmentation attacks across multiple sources.
4. Natural bridge injection with no corresponding trusted clean candidate.

Every adaptive attack must be evaluated locally, must not use gold answers or changed-document labels as generation features, and must pass an actual-prompt poison-exposure preflight before answer-level attack success is reported.

## Suggested questions for ChatGPT web review

- "Read the Stage46 report and identify the strongest remaining threat-model assumptions."
- "Review the risk recovery detector for threshold-edge bypasses, without proposing changes that rely on gold labels at inference time."
- "Compare Stage44 and Stage45 and propose a non-oracle gate for second-hop supplementation."
- "Review the planned adaptive-attack protocol for leakage from offline evaluation labels."
- "Check whether the reported claims are supported by the tracked code, configs, tests, and artifacts."

## Artifact map

- `artifacts/reports/Stage46_跨数据集真实LLM回答验证_中文报告.md`: main current result report.
- `artifacts/results/stage46_cross_dataset_answer_final_summary.csv`: judge-aware final metrics.
- `artifacts/results/stage46_cross_dataset_answer_pairwise_summary.csv`: same-query baseline versus defense comparison.
- `artifacts/results/stage46_cross_dataset_answer_paired_examples.jsonl`: source and answer walkthroughs.
- `docs/论文实验矩阵_阶段冻结版.md`: frozen experiment framing.
