# Stage47 configuration

Each dataset directory contains the same five-step pipeline:

1. `context.yaml` freezes the clean official GraphRAG context.
2. `attack.yaml` generates and validates adaptive source attacks.
3. `answers.yaml` generates paired answer outputs.
4. `audit.yaml` performs deterministic answer auditing.
5. `judge.yaml` applies the judge-aware evaluation.

`analysis.yaml` combines both datasets. Historical flat filenames are mapped in
`configs/config_aliases.yaml`; both old commands and the shorter paths resolve
to the same files.
