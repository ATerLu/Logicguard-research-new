from pathlib import Path
import tempfile

from logicguard.core.io import append_jsonl
from logicguard.core.run_state import load_checkpoint_rows


with tempfile.TemporaryDirectory(prefix="logicguard-tail-") as directory:
    path = Path(directory) / "checkpoint.jsonl"
    path.write_text(
        '{"run_fingerprint":"fp","case":"done"}\n{"run_fingerprint":"fp"',
        encoding="utf-8",
    )
    rows = load_checkpoint_rows(path, fingerprint="fp")
    print("rows_before_append", rows)
    append_jsonl(path, {"run_fingerprint": "fp", "case": "resumed"})
    print("raw_after_append", repr(path.read_text(encoding="utf-8")))
    try:
        print("rows_after_append", load_checkpoint_rows(path, fingerprint="fp"))
    except Exception as exc:
        print("reload_error", type(exc).__name__, str(exc))
