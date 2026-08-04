# LogicGuard Mirror Policy

This repository is a curated, one-way Git mirror of `../logicguard`.

## Authority

- `../logicguard` is the development source of truth.
- This directory exists for Git history, GitHub review, and ChatGPT web analysis.
- Do not edit mirrored project files here and then copy them back automatically.
- A review suggestion from GitHub or ChatGPT must be applied and tested in the source worktree first.

## Included

- Source code, configs, tests, scripts, tools, and lightweight library files.
- All project documents.
- All Markdown experiment reports under `outputs/reports`.
- Small Stage40--47 summaries and selected examples under `artifacts/results`.
- Frozen Stage47 attack records and integrity rows under `artifacts/attacks`.

## Excluded

- Raw datasets, processed datasets, GraphRAG workspaces, parquet indexes, full contexts, caches, virtual environments, and credentials.
- Large generated outputs that can be regenerated from tracked code/configs and documented inputs.

## Sync procedure

1. Work and test in `../logicguard`.
2. Run `./sync_from_logicguard.ps1` from this mirror.
3. Review `git diff --stat` and `git status` here.
4. Commit and push only a tested snapshot.

The sync script uses `/MIR` only inside explicitly whitelisted mirror subdirectories. It never deletes or writes files in the source worktree, and it never mirrors the root of this Git repository, so `.git` is preserved.
