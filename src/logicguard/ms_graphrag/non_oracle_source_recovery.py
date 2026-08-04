"""Compatibility entry point for :mod:`logicguard.defense.non_oracle_recovery`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.defense.non_oracle_recovery")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
