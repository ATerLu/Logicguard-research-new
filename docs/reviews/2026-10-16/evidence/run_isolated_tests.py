#!/usr/bin/env python3
"""Create a tracked HEAD snapshot and run pytest with no inherited provider keys."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path('/home/uisee/logicguard/Logicguard-research-new')
BASE = Path('/tmp/logicguard_review_20261016')
DEST = BASE / 'isolated_repo'
PYTHON = ROOT / '.venv/bin/python'
DEST.mkdir(parents=True, exist_ok=True)
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
archive = subprocess.check_output(['git', 'archive', '--format=tar', 'HEAD'], cwd=ROOT)
count = 0
excluded = []
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tf:
    for member in tf:
        path = Path(member.name)
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError(f'Unsafe tracked path: {member.name}')
        if any(part in {'papers', '.git', '.venv'} for part in path.parts):
            excluded.append(member.name)
            continue
        target = DEST / path
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tf.extractfile(member)
            assert handle is not None
            target.write_bytes(handle.read())
            target.chmod(member.mode)
            count += 1
        else:
            raise RuntimeError(f'Unexpected tracked archive entry: {member.name}')

# A minimal environment deliberately inherits no provider keys, tokens, secrets,
# .env settings, or provider endpoints. No dependencies are installed.
env = {k: os.environ[k] for k in ['PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR'] if k in os.environ}
env['PYTHONPATH'] = str(DEST / 'src')
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PYTHONUNBUFFERED'] = '1'
probe = subprocess.run(
    [str(PYTHON), '-c', 'import logicguard,pathlib; p=pathlib.Path(logicguard.__file__).resolve(); print(p); assert str(p).startswith("/tmp/logicguard_review_20261016/isolated_repo/src/")'],
    cwd=DEST, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    check=True,
)
metadata = {
    'head': head,
    'original_repository': str(ROOT),
    'snapshot_repository': str(DEST),
    'tracked_files_copied': count,
    'excluded_entry_count': len(excluded),
    'python': str(PYTHON),
    'import_probe': probe.stdout.strip(),
    'environment_keys': sorted(env),
    'command': [str(PYTHON), '-m', 'pytest', '-q', '--tb=short'],
}
(BASE / 'test_run_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata, indent=2), flush=True)
with (BASE / 'pytest_full.txt').open('w') as log:
    log.write(json.dumps(metadata, indent=2) + '\n\n')
    log.flush()
    result = subprocess.run(metadata['command'], cwd=DEST, env=env, stdout=log, stderr=subprocess.STDOUT)
metadata['pytest_exit_code'] = result.returncode
(BASE / 'test_run_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
print('pytest_exit_code:', result.returncode, flush=True)
