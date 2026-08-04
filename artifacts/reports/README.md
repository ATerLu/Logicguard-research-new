# Generated reports

The canonical experiment narrative is maintained in three documents:

- `docs/methodology.md` — design, stages, and experimental boundaries;
- `docs/results.md` — consolidated results and conclusions;
- `docs/reproducibility.md` — commands and environment checks.

New pipeline steps should emit CSV, JSONL, or logs here only when needed for
machine inspection. Add narrative findings to the canonical documents instead
of creating one Markdown report per substep.

The 97 pre-normalization report artifacts are recorded in
`docs/report_manifest.csv`. A verified local archive is stored at
`outputs/archive/legacy_reports_20260804.zip`; its digest is in
`docs/report_archive.sha256`, and the original files also remain in the remote
backup history.
