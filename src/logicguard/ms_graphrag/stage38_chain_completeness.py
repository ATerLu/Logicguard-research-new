"""Compatibility entry point for :mod:`logicguard.defense.chain_completion`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.defense.chain_completion")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
