#!/usr/bin/env python3
"""Classify failures from the isolated pytest log without rerunning tests."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

BASE = Path('/tmp/logicguard_review_20261016')
ROOT = Path('/home/uisee/logicguard/Logicguard-research-new')
DEST = BASE / 'isolated_repo'
text = (BASE / 'pytest_full.txt').read_text()
matches = list(re.finditer(r'^_+ (.*?) _+$', text, re.MULTILINE))
failures = []
for i, match in enumerate(matches):
    end = matches[i + 1].start() if i + 1 < len(matches) else text.index('short test summary info')
    block = text[match.end():end]
    errors = re.findall(r'^E\s+.*', block, re.MULTILINE)
    if "Unable to find a usable engine" in block:
        category = 'missing_parquet_dependency'
    elif match.group(1) == 'test_cli_resolves_legacy_config_alias':
        category = 'windows_path_assertion_on_linux'
    elif 'FileNotFoundError' in block or 'input must be an existing project file' in block or match.group(1) == 'test_pinned_hog_grag_artifact_fails_closed_on_actual_core_sources':
        category = 'missing_external_dataset_or_vendor_assets'
    else:
        category = 'unclassified'
    failures.append({'test_name': match.group(1), 'category': category, 'errors': errors})
counts = {category: sum(f['category'] == category for f in failures) for category in sorted({f['category'] for f in failures})}
status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
changed = []
for raw in paths:
    if not raw or any(p in {'papers', '.git', '.venv'} for p in Path(raw).parts):
        continue
    a, b = ROOT / raw, DEST / raw
    if a.is_file() and b.is_file() and a.read_bytes() != b.read_bytes():
        changed.append({'file': raw, 'original_sha256': hashlib.sha256(a.read_bytes()).hexdigest(), 'after_test_snapshot_sha256': hashlib.sha256(b.read_bytes()).hexdigest()})
summary = re.search(r'(\d+) failed, (\d+) passed in ([\d.]+)s', text)
assert summary is not None
out = {
    'pytest_failed': int(summary.group(1)),
    'pytest_passed': int(summary.group(2)),
    'elapsed_seconds': float(summary.group(3)),
    'classified_failure_count': len(failures),
    'failure_categories': counts,
    'original_repository_git_status': status,
    'tracked_snapshot_files_modified_by_tests': changed,
    'failures': failures,
}
(BASE / 'test_failure_classification.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k,v in out.items() if k != 'failures'}, ensure_ascii=False, indent=2))
