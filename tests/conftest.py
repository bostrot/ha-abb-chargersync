"""Register the integration package without importing Home Assistant.

The package __init__ needs homeassistant, which is not a test dependency. The
submodules under test (protocol, api) only need aiohttp and cryptography.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "custom_components" / "abb_chargersync"

for name, path in (("custom_components", PKG.parent), ("custom_components.abb_chargersync", PKG)):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
