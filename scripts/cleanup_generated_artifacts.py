"""Safely inventory or remove regenerable LogicGuard cache directories."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _project_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError(f"Refusing cleanup without project marker at {root}")
    return root


def _graphrag_cache_dirs(root: Path) -> list[Path]:
    output_root = (root / "outputs" / "ms_graphrag").resolve()
    if not output_root.is_dir():
        return []
    targets: list[Path] = []
    for candidate in output_root.rglob("cache"):
        resolved = candidate.resolve()
        if not resolved.is_dir() or resolved.name != "cache":
            continue
        if not resolved.is_relative_to(output_root):
            raise RuntimeError(f"Cache target escaped output root: {resolved}")
        targets.append(resolved)
    return sorted(targets)


def _stats(paths: list[Path]) -> tuple[int, int]:
    files = 0
    size = 0
    for path in paths:
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                size += item.stat().st_size
    return files, size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="remove the allowlisted cache directories; otherwise only inventory",
    )
    args = parser.parse_args()

    targets = _graphrag_cache_dirs(_project_root())
    files, size = _stats(targets)
    print(
        f"GraphRAG cache directories={len(targets)} files={files} "
        f"bytes={size} mode={'apply' if args.apply else 'dry-run'}"
    )
    if not args.apply:
        return
    for target in targets:
        shutil.rmtree(target)
    print(f"Removed {len(targets)} verified cache directories")


if __name__ == "__main__":
    main()
