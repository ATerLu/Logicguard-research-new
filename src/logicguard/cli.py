"""Stable command-line entry point for active LogicGuard workflows."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from logicguard.core.config import resolve_config_path

_COMMAND_MODULES = {
    "adaptive-attack": "logicguard.attack.adaptive",
    "adaptive-analysis": "logicguard.evaluation.adaptive_attack_analysis",
    "answer-preflight": "logicguard.evaluation.answer_preflight",
    "answer-generation": "logicguard.evaluation.answer_generation",
    "answer-audit": "logicguard.evaluation.answer_audit",
    "judge-audit": "logicguard.evaluation.judge_audit",
    "reindex-defense-matrix": "logicguard.evaluation.reindex_defense_matrix",
    "reindex-paired-analysis": "logicguard.evaluation.reindex_paired_analysis",
    "gate-a-expansion": "logicguard.evaluation.gate_a_expansion",
    "cross-dataset-analysis": "logicguard.evaluation.cross_dataset_analysis",
    "benchmark-readiness": "logicguard.benchmark.readiness",
    "benchmark-e1-preparation": "logicguard.benchmark.e1_preparation",
    "benchmark-attack-runner": "logicguard.benchmark.attack_runner",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logicguard", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser(
        "resolve-config", help="print the canonical path for a config or alias"
    )
    resolve_parser.add_argument("path", type=Path)

    run_parser = subparsers.add_parser("run", help="run an active experiment step")
    run_parser.add_argument("step", choices=sorted(_COMMAND_MODULES))
    run_parser.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse the stable CLI and dispatch to the selected workflow."""

    args = _build_parser().parse_args(argv)
    if args.command == "resolve-config":
        print(resolve_config_path(args.path))
        return

    module = importlib.import_module(_COMMAND_MODULES[args.step])
    config_path = resolve_config_path(args.config)
    previous_argv = sys.argv
    try:
        sys.argv = [f"logicguard run {args.step}", "--config", str(config_path)]
        module.main()
    finally:
        sys.argv = previous_argv


if __name__ == "__main__":
    main()
