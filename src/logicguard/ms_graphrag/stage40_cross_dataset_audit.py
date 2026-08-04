"""Compatibility entry point for :mod:`logicguard.evaluation.cross_dataset_audit`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.evaluation.cross_dataset_audit")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
