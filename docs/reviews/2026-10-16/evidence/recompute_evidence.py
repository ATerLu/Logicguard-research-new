#!/usr/bin/env python3
"""Read-only recomputation of frozen Stage48 outcome and sample-unit counts."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path('/home/uisee/logicguard/Logicguard-research-new')
ROWS = ROOT / 'artifacts/results/stage48_e1_paired_defense_answer_rows.jsonl'
OUT = Path('/tmp/logicguard_review_20261016/recomputed_evidence.json')

rows = [json.loads(line) for line in ROWS.read_text().splitlines() if line.strip()]
by_method = defaultdict(list)
for row in rows:
    by_method[row['method']].append(row)
methods = []
for method, method_rows in sorted(by_method.items()):
    methods.append({
        'method': method,
        'row_count': len(method_rows),
        'unique_dataset_query_units': len({(r['dataset'], r['query_id']) for r in method_rows}),
        'attack_attempts': len({(r['dataset'], r['attack_family'], r['query_id']) for r in method_rows}),
        'targeted_success_count': sum(bool(r['attacked_targeted_success']) for r in method_rows),
        'attacked_correct_count': sum(bool(r['attacked_correct']) for r in method_rows),
        'clean_correct_count': sum(bool(r['clean_correct']) for r in method_rows),
        'attacked_abstain_count': sum(bool(r['attacked_abstained']) for r in method_rows),
        'clean_abstain_count': sum(bool(r['clean_abstained']) for r in method_rows),
        'clean_units_with_recovery': sum(r['clean_recovered_source_count'] > 0 for r in method_rows),
    })
regressions = []
for line_no, row in enumerate(rows, start=1):
    if row['method'] == 'stage38_second_hop_append_top14' and row['attacked_targeted_success']:
        regressions.append({'jsonl_line': line_no, **{k: row[k] for k in (
            'dataset', 'attack_family', 'query_id', 'gold_answer', 'malicious_answer',
            'attacked_generated_answer', 'clean_generated_answer'
        )}})
result = {
    'source': str(ROWS),
    'source_sha256': hashlib.sha256(ROWS.read_bytes()).hexdigest(),
    'row_count': len(rows),
    'unique_dataset_query_units_all_rows': len({(r['dataset'], r['query_id']) for r in rows}),
    'unique_attack_attempt_units_all_rows': len({(r['dataset'], r['attack_family'], r['query_id']) for r in rows}),
    'methods': methods,
    'stage45_targeted_success_regressions': regressions,
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
