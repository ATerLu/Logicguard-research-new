"""Compatibility entry point for :mod:`logicguard.defense.source_enrichment`."""

from importlib import import_module
import sys

_implementation = import_module("logicguard.defense.source_enrichment")
if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
