# LogicGuard Mirror Policy

This repository is a curated, one-way Git mirror of the sibling `logicguard` development worktree.

## Authority

- On the source workstation, `../logicguard` is the development source of truth.
- On a new workstation, a verified clone of `uisee-dev` becomes that workstation's development source of truth.
- Never develop in `.logicguard_remote_backup` or a temporary clone.
- Do not copy mirror changes back automatically; review, test, and deliberately apply them.

## Included

- Source code, configs, tests, scripts, lightweight tools, and library files.
- Research documents, handoff instructions, paper manifests, and reading notes.
- Curated Markdown reports and Stage40/46/47/48 result artifacts.
- Frozen Stage47/48 attack records and Stage48 cost/run manifests.
- WP1/WP2 benchmark protocol, split, qualification, and reproducibility artifacts.
- A SHA-256 inventory of excluded data files.

## Excluded

- Credentials and `.env` files.
- Virtual environments, caches, temporary directories, and nested `.git` metadata.
- Raw/processed datasets and complete clean/poisoned corpus copies.
- GraphRAG/LightRAG workspaces, indexes, model snapshots, and full generated outputs.
- External upstream repositories; use the pinned revisions documented by the project.

## Sync procedure

1. Work and test in `../logicguard`.
2. Run `./sync_from_logicguard.ps1 -DryRun` from this mirror.
3. Run `./sync_from_logicguard.ps1`.
4. Review `git diff --stat`, `git status`, large-file output, and secret-scan output.
5. Run tests and static checks in the mirror or verified source environment.
6. Commit and push normally to `uisee-dev`; never force-push or use `git push --mirror` for routine handoff.

The sync script writes only inside its own mirror root and excludes nested `.git`, environments, caches, and temporary directories.
