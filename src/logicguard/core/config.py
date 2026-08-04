"""Configuration and project-path helpers.

Experiment configs use paths relative to the repository root.  Locating that
root by counting parent directories made configs fragile when they were moved
into subdirectories, so all loaders should use :func:`find_project_root`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def find_project_root(start: Path, *, strict: bool = False) -> Path:
    """Return the nearest ancestor containing ``pyproject.toml``.

    ``start`` may name either a file or a directory.  The nearest marker wins,
    which also keeps this helper safe in nested checkouts.  Standalone configs
    without a project marker retain the legacy ``parents[1]`` behavior unless
    ``strict`` is true.
    """

    resolved = start.expanduser().resolve()
    current = resolved if resolved.is_dir() else resolved.parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    if strict:
        raise FileNotFoundError(f"Could not find pyproject.toml above {resolved}")
    return resolved.parents[1] if len(resolved.parents) > 1 else current


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from ``path`` with a useful type error."""

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(
            f"Expected a YAML mapping in {path}, got {type(payload).__name__}"
        )
    return payload


def resolve_config_path(path: Path) -> Path:
    """Resolve a config path, including entries in ``config_aliases.yaml``.

    The alias layer lets historical commands keep working after configuration
    files are grouped into concise experiment directories.
    """

    resolved = path.expanduser().resolve()
    if resolved.is_file():
        return resolved

    project_root = find_project_root(resolved)
    alias_file = project_root / "configs" / "config_aliases.yaml"
    if not alias_file.is_file():
        return resolved

    aliases = load_yaml(alias_file).get("aliases", {})
    if not isinstance(aliases, dict):
        raise TypeError(f"Expected 'aliases' to be a mapping in {alias_file}")

    try:
        relative = resolved.relative_to(project_root).as_posix()
    except ValueError:
        return resolved
    target = aliases.get(relative)
    if target is None:
        return resolved

    aliased = resolve_project_path(target, project_root=project_root)
    if not aliased.is_file():
        raise FileNotFoundError(
            f"Config alias {relative!r} points to missing file {aliased}"
        )
    return aliased


def resolve_project_path(raw: object, *, project_root: Path) -> Path:
    """Resolve an absolute or repository-relative path value."""

    candidate = Path(str(raw)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()
