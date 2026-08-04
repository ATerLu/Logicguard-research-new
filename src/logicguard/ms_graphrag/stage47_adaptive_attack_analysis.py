"""Compatibility entry point for :mod:`logicguard.evaluation.adaptive_attack_analysis`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.evaluation.adaptive_attack_analysis")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
