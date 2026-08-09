"""Local fakes for CS interview unit tests.

The production Linux image uses infinity-sdk's native ``datrie`` dependency.
Python 3.13 has no Windows wheel for it, so the narrow Windows unit-test path
provides a no-I/O trie fake. Tests in this directory never exercise tokenizer
quality; Linux CI continues to use the real implementation.
"""

from __future__ import annotations

import string
import sys
import types
from pathlib import Path


# Importing a vertical service through ``api.apps`` otherwise executes the
# Quart application package initializer, which initializes Elasticsearch and
# other production connectors during test collection. Unit tests load the real
# service modules from this package path without booting the API process.
if "api.apps" not in sys.modules:
    apps_package = types.ModuleType("api.apps")
    apps_package.__path__ = [str(Path(__file__).resolve().parents[4] / "api" / "apps")]
    sys.modules["api.apps"] = apps_package


if sys.platform == "win32" and "datrie" not in sys.modules:
    module = types.ModuleType("datrie")

    class Trie(dict):
        def __init__(self, alphabet: str = string.printable):
            super().__init__()
            self.alphabet = alphabet

        @classmethod
        def load(cls, _path: str):
            return cls()

        def save(self, _path: str) -> None:
            return None

        def has_keys_with_prefix(self, prefix: str) -> bool:
            return any(str(key).startswith(prefix) for key in self)

    module.Trie = Trie
    sys.modules["datrie"] = module
