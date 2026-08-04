"""Compatibility entry point for :mod:`logicguard.evaluation.answerability_ablation`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.evaluation.answerability_ablation")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
