"""Build a content-addressed migration manifest for legacy Markdown reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _destination(name: str) -> tuple[str, str]:
    lowered = name.lower()
    if any(token in lowered for token in ("context", "seed", "preflight", "预检")):
        return "method", "docs/methodology.md"
    if any(token in lowered for token in ("cleanup", "inventory", "整理")):
        return "reproducibility", "docs/reproducibility.md"
    return "result", "docs/results.md"


def build_manifest(report_dir: Path, output_path: Path) -> int:
    """Write one deterministic CSV row per legacy report artifact."""

    rows: list[dict[str, object]] = []
    for path in sorted(report_dir.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file():
            continue
        content_type, destination = _destination(path.name)
        rows.append(
            {
                "legacy_path": path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "content_type": content_type,
                "consolidated_document": destination,
                "archive_member": f"reports/{path.name}",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=Path("outputs/reports"))
    parser.add_argument("--output", type=Path, default=Path("docs/report_manifest.csv"))
    args = parser.parse_args()
    count = build_manifest(args.report_dir, args.output)
    print(f"Wrote {count} report records to {args.output}")


if __name__ == "__main__":
    main()
