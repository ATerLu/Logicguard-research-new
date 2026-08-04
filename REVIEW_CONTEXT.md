# LogicGuard Web Review Context

## What this repository is

LogicGuard is a research prototype for defending GraphRAG-style multi-hop QA against logical corpus poisoning. The central problem is that simply removing suspicious retrieved evidence can suppress attacks but often leaves the model with too little evidence to answer. LogicGuard therefore uses a chain of source risk detection, trusted-reference recovery, candidate-source enrichment, and selective second-hop supplementation.

This is a curated mirror for code review and research guidance. The local source worktree has raw datasets and large GraphRAG artifacts; they are intentionally excluded here. Read `README.md`, `docs/项目总览与路线图.md`, `docs/新窗口交接文档_2026-07-01.md`, and the reports in `artifacts/reports/` before drawing conclusions.

## Current verified baseline: Stage47

Stage47 is the latest completed adaptive-attack evaluation. It applies three
label-blind attack families to clean official GraphRAG retrieval results and
then runs the frozen Stage43--45 defense and answer pipeline.

- Datasets: MuSiQue 20 queries and HotpotQA 5 transfer queries.
- Attack attempts: 75; generation-valid: 35; strict evaluation-valid: 21;
  actual malicious-answer prompt exposures: 19.
- Answer model: `qwen3.7-plus`, temperature 0, `evidence_compare` prompt,
  450 characters per source.
- Natural bridge is the clearest gap: MuSiQue Stage43 risk recall is 0 and
  targeted ASR remains 0.875; Stage44/45 reduce it only to 0.750.
- Low-entity-drift attacks confirm a detector blind spot, but the strict
  denominator is too small for a stable aggregate ASR estimate.
- Candidate-collision attacks are detected, but all 5 strict cases recover to
  the attacker-induced non-gold candidate. Answer-level ASR falls to 0, while
  recovery integrity still fails.

The Stage47 conclusion is bounded: it is a post-retrieval source perturbation
study. It does not test poisoned-corpus reindexing, graph extraction, embedding,
community formation, or original retrieval rank changes.

## Current research priority

The next planned stage is Stage48 full-corpus poisoning and reindex evaluation:

1. Add configuration-fingerprinted checkpoint/resume and per-case incremental
   answer persistence.
2. Freeze the successful Stage47 attacks and record clean/poisoned corpus hashes.
3. Build separate low-drift, candidate-collision, and natural-bridge corpus variants.
4. Reindex each variant with official GraphRAG and measure index, retrieval,
   ranking, truncation, and actual-prompt exposure before any answer calls.
5. Run the unchanged Stage43--45 baseline before implementing detector or
   recovery enhancements.

Every adaptive attack must be evaluated locally, must not use gold answers or changed-document labels as generation features, and must pass an actual-prompt poison-exposure preflight before answer-level attack success is reported.

## Suggested questions for ChatGPT web review

- "Read the Stage46 report and identify the strongest remaining threat-model assumptions."
- "Review the risk recovery detector for threshold-edge bypasses, without proposing changes that rely on gold labels at inference time."
- "Compare Stage44 and Stage45 and propose a non-oracle gate for second-hop supplementation."
- "Review the planned adaptive-attack protocol for leakage from offline evaluation labels."
- "Check whether the reported claims are supported by the tracked code, configs, tests, and artifacts."

## Artifact map

- `handoff.md`: authoritative current-state handoff and Stage48 guardrails.
- `artifacts/reports/Stage47_三类自适应攻击初步实验_中文报告.md`: main current result report.
- `artifacts/results/stage47_adaptive_attack_final_summary.csv`: strict final metrics.
- `artifacts/results/stage47_adaptive_attack_pairwise_summary.csv`: paired defense changes.
- `artifacts/results/stage47_adaptive_attack_examples.jsonl`: source and answer walkthroughs.
- `artifacts/attacks/`: frozen Stage47 attack records and no-oracle integrity rows.
- `docs/论文实验矩阵_阶段冻结版.md`: frozen experiment framing.
