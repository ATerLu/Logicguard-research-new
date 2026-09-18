# LogicGuard Web Review Context

## Repository role

This repository is the curated GitHub handoff mirror of the active LogicGuard research worktree. The checked-out `uisee-dev` branch is intended to let another workstation resume development without treating excluded runtime data, indexes, virtual environments, or credentials as versioned source.

Read these files before reviewing or changing the project:

1. `handoff.md`
2. `WORKSTATION_HANDOFF.md`
3. `docs/thesisPlan.md`
4. `docs/results.md`
5. `docs/methodology.md`
6. `docs/reproducibility.md`
7. `docs/comparativeExperimentPreregistration_v1.2.md`

## Current verified status

- Stage48 Gate A is closed as failed: only natural bridge passed the family-level context/system gate.
- WP1 protocol correction and historical-use audit are complete.
- WP2 is partial: A2 local four-stage materialization, T0/T1 synthetic controls, A1/A3 asset and materialization anchors, real clean trace admission, and D3/D4 external-defense qualification have been audited.
- RAGDefender is eligible only as `RAGDefender_published_artifact_implementation`; its MiniLM path is order-sensitive and its published multi-hop implementation differs from the paper text.
- HoG-GRAG's fixed public artifact is paper-native unavailable because of a syntax error and missing prompts. This is not evidence that the defense is ineffective.
- D6, full dev60 A1/A2/A3 execution, real trusted-pool retrieval, a fresh confirmatory set, and formal external-defense ranking are not complete.

## Strongest current finding

Natural bridge poisoning survived full-corpus insertion, official Microsoft GraphRAG indexing, retrieval, prompt truncation, and answer generation on HotpotQA and MuSiQue, with pooled system targeted success `4/20=20%`. This does not make Gate A pass because only one attack family qualified.

The Stage43--45 defense chain remains a legacy internal baseline. Filtering alone removes poisoned exposure but damages answerability; trusted recovery and enrichment restore utility under a strong clean-reference assumption. Adaptive low-drift, candidate-collision, and no-counterpart natural-bridge attacks expose detector and recovery-integrity gaps.

## Next development task

Freeze the complete dev60 A1/A2/A3 request and materialization launch plan: model revisions, maximum calls/tokens/cost, unknown and in-flight accounting, stop rules, immutable corpus hashes, and fixed denominators. Do not select replacement questions after observing attack success.

## Artifact boundary

The repository tracks curated Stage40/46/47/48 results, frozen Stage47/48 attacks, Stage48 run manifests, and WP1/WP2 benchmark artifacts. Full datasets, GraphRAG/LightRAG indexes, caches, model snapshots, `.env` files, and full outputs are excluded. Their old-workstation hashes are recorded in `EXTERNAL_ASSETS_SHA256.tsv`.
