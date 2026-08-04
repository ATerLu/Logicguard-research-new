"""Compatibility entry point for :mod:`logicguard.evaluation.llm_comparison`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.evaluation.llm_comparison")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
