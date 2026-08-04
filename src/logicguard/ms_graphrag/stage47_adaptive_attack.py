"""Compatibility entry point for :mod:`logicguard.attack.adaptive`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.attack.adaptive")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
