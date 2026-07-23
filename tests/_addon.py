"""
Loads modules from the add-on's `io` package for tests that run without Blender.

Two things block the obvious approaches. The package is named `io`, and the standard
library module of that name is already in sys.modules before any test starts, so no
sys.path ordering can win. And `io/__init__.py` imports modules that need bpy, so the
package cannot be executed outside Blender at all.

So mirror the package layout with a synthetic root and load single modules by path,
the same approach tests/texsearch.py uses for the utilities package.
"""

import os
import sys
import types
import importlib.util

_ROOT = "dzob_test_root"
_ADDON_DIR = os.path.join(os.getcwd(), "DZObjectBuilder")
_IO_DIR = os.path.join(_ADDON_DIR, "io")


def load_io(*names):
    if _ROOT not in sys.modules:
        root = types.ModuleType(_ROOT)
        root.__path__ = [_ADDON_DIR]
        root.addon_dir = _ADDON_DIR
        sys.modules[_ROOT] = root

        package = types.ModuleType(_ROOT + ".io")
        package.__path__ = [_IO_DIR]
        sys.modules[_ROOT + ".io"] = package

    loaded = []
    for name in names:
        full = "%s.io.%s" % (_ROOT, name)
        if full not in sys.modules:
            spec = importlib.util.spec_from_file_location(full, os.path.join(_IO_DIR, name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[full] = module
            spec.loader.exec_module(module)

        loaded.append(sys.modules[full])

    return loaded[0] if len(loaded) == 1 else tuple(loaded)
